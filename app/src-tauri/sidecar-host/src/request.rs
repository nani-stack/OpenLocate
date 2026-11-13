//! Encoding of outgoing JSON-RPC requests. The method and params come from the webview, so
//! they are checked before anything is written to the sidecar.

use serde_json::{json, Value};

use crate::error::UiError;

const MAX_METHOD_LEN: usize = 64;

/// Builds one newline-terminated JSON-RPC 2.0 request line.
///
/// `params` must be an object or an array (the JSON-RPC rule); `None` and JSON `null` both
/// mean "no params" and the member is left out.
pub fn encode_request(id: u64, method: &str, params: Option<Value>) -> Result<String, UiError> {
    validate_method(method)?;
    let mut request = json!({"jsonrpc": "2.0", "id": id, "method": method});
    match params {
        None | Some(Value::Null) => {}
        Some(params @ (Value::Object(_) | Value::Array(_))) => {
            request["params"] = params;
        }
        Some(other) => {
            return Err(UiError::invalid_request(format!(
                "params for `{method}` must be an object or an array, got {}",
                json_type(&other)
            )))
        }
    }
    // Serialising a `Value` cannot fail, and serde_json never emits raw newlines, so the
    // request is always exactly one line.
    Ok(format!("{request}\n"))
}

fn validate_method(method: &str) -> Result<(), UiError> {
    let well_formed = !method.is_empty()
        && method.len() <= MAX_METHOD_LEN
        && method
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_');
    if well_formed {
        Ok(())
    } else {
        Err(UiError::invalid_request(format!(
            "method name {method:?} is not valid (letters, digits, '.' and '_' only, at most {MAX_METHOD_LEN} characters)"
        )))
    }
}

fn json_type(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "a boolean",
        Value::Number(_) => "a number",
        Value::String(_) => "a string",
        Value::Array(_) => "an array",
        Value::Object(_) => "an object",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(line: &str) -> Value {
        assert!(line.ends_with('\n'));
        assert_eq!(line.matches('\n').count(), 1);
        serde_json::from_str(line).unwrap()
    }

    #[test]
    fn request_without_params() {
        let line = encode_request(1, "app.info", None).unwrap();
        assert_eq!(
            parse(&line),
            json!({"jsonrpc": "2.0", "id": 1, "method": "app.info"})
        );
        let line = encode_request(2, "app.info", Some(Value::Null)).unwrap();
        assert!(parse(&line).get("params").is_none());
    }

    #[test]
    fn request_with_params_containing_newlines_stays_one_line() {
        let params = json!({"id": "line1\nline2"});
        let line = encode_request(9, "device.connect", Some(params.clone())).unwrap();
        assert_eq!(parse(&line)["params"], params);
    }

    #[test]
    fn rejects_scalar_params() {
        let err = encode_request(1, "location.set", Some(json!(5))).unwrap_err();
        assert_eq!(err.code, "INVALID_PARAMS");
    }

    #[test]
    fn rejects_bad_method_names() {
        let too_long = "a".repeat(MAX_METHOD_LEN + 1);
        for method in ["", "app info", "app.info\n", "évènement", too_long.as_str()] {
            assert!(encode_request(1, method, None).is_err(), "{method:?}");
        }
    }
}
