//! Classification of one line read from the sidecar's stdout.

use serde_json::{Map, Value};

use crate::error::UiError;

/// What a line from the sidecar turned out to be.
#[derive(Debug, Clone, PartialEq)]
pub enum Incoming {
    /// A reply to one of our requests. `outcome` is the `result`, or the mapped `error`.
    Response {
        id: u64,
        outcome: Result<Value, UiError>,
    },
    /// A notification (a message with `method` and no `id`).
    Notification { method: String, params: Value },
    /// Anything else. The reason is meant for a log warning; the line is otherwise ignored.
    Unrecognised { reason: String },
}

/// Classifies one line of sidecar output. Never panics.
pub fn classify_line(line: &str) -> Incoming {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return unrecognised("empty line");
    }
    let value: Value = match serde_json::from_str(trimmed) {
        Ok(value) => value,
        Err(err) => return unrecognised(&format!("invalid JSON ({err})")),
    };
    let Value::Object(object) = value else {
        return unrecognised("JSON value is not an object");
    };
    classify_object(object)
}

fn classify_object(mut object: Map<String, Value>) -> Incoming {
    let id = object.remove("id");
    let result = object.remove("result");
    let error = object.remove("error");

    match (id, result, error) {
        (None, None, None) => classify_notification(object),
        (None, _, _) => unrecognised("response without an id"),
        (Some(_), None, None) => unrecognised("message has an id but no result or error"),
        (Some(id), result, error) => classify_response(&id, result, error),
    }
}

fn classify_response(id: &Value, result: Option<Value>, error: Option<Value>) -> Incoming {
    let Some(id) = id.as_u64() else {
        return unrecognised(&format!("response id {id} is not one of ours"));
    };
    let outcome = match (result, error) {
        (_, Some(error)) => Err(UiError::from_rpc_error(&error)),
        (Some(result), None) => Ok(result),
        (None, None) => return unrecognised("response without result or error"),
    };
    Incoming::Response { id, outcome }
}

fn classify_notification(mut object: Map<String, Value>) -> Incoming {
    match object.remove("method") {
        Some(Value::String(method)) if !method.is_empty() => Incoming::Notification {
            method,
            params: object.remove("params").unwrap_or(Value::Null),
        },
        Some(_) => unrecognised("notification method is not a non-empty string"),
        None => unrecognised("message has neither an id nor a method"),
    }
}

fn unrecognised(reason: &str) -> Incoming {
    Incoming::Unrecognised {
        reason: reason.to_owned(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn is_unrecognised(line: &str) -> bool {
        matches!(classify_line(line), Incoming::Unrecognised { .. })
    }

    #[test]
    fn success_response() {
        let line = r#"{"jsonrpc":"2.0","id":7,"result":{"version":"0.1.0"}}"#;
        assert_eq!(
            classify_line(line),
            Incoming::Response {
                id: 7,
                outcome: Ok(json!({"version": "0.1.0"}))
            }
        );
    }

    #[test]
    fn null_result_is_still_a_success() {
        let line = r#"{"jsonrpc":"2.0","id":1,"result":null}"#;
        assert_eq!(
            classify_line(line),
            Incoming::Response {
                id: 1,
                outcome: Ok(Value::Null)
            }
        );
    }

    #[test]
    fn error_response_maps_error_data() {
        let line = r#"{"jsonrpc":"2.0","id":3,"error":{"code":-32000,"message":"x",
            "data":{"code":"NOT_CONNECTED","message":"No iPhone.","fix":"Connect one.","detail":null}}}"#
            .replace('\n', "");
        match classify_line(&line) {
            Incoming::Response {
                id: 3,
                outcome: Err(err),
            } => {
                assert_eq!(err.code, "NOT_CONNECTED");
                assert_eq!(err.fix, "Connect one.");
            }
            other => panic!("unexpected {other:?}"),
        }
    }

    #[test]
    fn notification_with_and_without_params() {
        let line = r#"{"jsonrpc":"2.0","method":"location.updated","params":{"lat":1,"lon":2,"source":"teleport"}}"#;
        assert_eq!(
            classify_line(line),
            Incoming::Notification {
                method: "location.updated".into(),
                params: json!({"lat": 1, "lon": 2, "source": "teleport"})
            }
        );
        assert_eq!(
            classify_line(r#"{"jsonrpc":"2.0","method":"ping"}"#),
            Incoming::Notification {
                method: "ping".into(),
                params: Value::Null
            }
        );
    }

    #[test]
    fn tolerates_surrounding_whitespace_and_crlf() {
        assert!(matches!(
            classify_line("  {\"id\":2,\"result\":{}}\r"),
            Incoming::Response { id: 2, .. }
        ));
    }

    #[test]
    fn rejects_everything_else_without_panicking() {
        for line in [
            "",
            "   ",
            "not json",
            "{\"id\":1,\"result\":",
            "[1,2,3]",
            "42",
            "null",
            r#"{"jsonrpc":"2.0"}"#,
            r#"{"id":1}"#,
            r#"{"id":"abc","result":{}}"#,
            r#"{"id":-1,"result":{}}"#,
            r#"{"id":1.5,"result":{}}"#,
            r#"{"id":null,"error":{"code":-32700,"message":"Parse error"}}"#,
            r#"{"result":{}}"#,
            r#"{"method":5}"#,
            r#"{"method":""}"#,
            r#"{"id":4,"method":"server.request"}"#,
        ] {
            assert!(is_unrecognised(line), "expected unrecognised: {line:?}");
        }
    }
}
