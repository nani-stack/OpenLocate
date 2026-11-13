//! The error object the UI receives for every failed call: `{code, message, fix, detail}`.

use std::time::Duration;

use serde_json::Value;

const RESTART_FIX: &str =
    "Press Restart in the header. If it keeps happening, report it and attach the log file.";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UiError {
    pub code: String,
    pub message: String,
    pub fix: String,
    pub detail: Option<String>,
}

impl UiError {
    pub fn new(code: &str, message: &str, fix: &str, detail: Option<String>) -> Self {
        Self {
            code: code.to_owned(),
            message: message.to_owned(),
            fix: fix.to_owned(),
            detail,
        }
    }

    /// Converts the JSON-RPC `error` member of a response into a `UiError`.
    ///
    /// The sidecar puts `{code, message, fix, detail}` in `error.data`; that is used when it is
    /// well formed. Otherwise (for example a protocol error such as `-32601`) an `INTERNAL`
    /// error is built from the JSON-RPC code and message.
    pub fn from_rpc_error(error: &Value) -> Self {
        if let Some(data) = error.get("data").and_then(Self::from_data) {
            return data;
        }
        let rpc_code = error.get("code").and_then(Value::as_i64);
        let rpc_message = error.get("message").and_then(Value::as_str);
        let detail = match (rpc_code, rpc_message) {
            (Some(code), Some(message)) => format!("JSON-RPC error {code}: {message}"),
            (Some(code), None) => format!("JSON-RPC error {code}"),
            (None, Some(message)) => message.to_owned(),
            (None, None) => format!("Malformed JSON-RPC error: {error}"),
        };
        Self::new(
            "INTERNAL",
            "The sidecar reported an internal error.",
            RESTART_FIX,
            Some(detail),
        )
    }

    fn from_data(data: &Value) -> Option<Self> {
        let text = |key: &str| data.get(key).and_then(Value::as_str).map(str::to_owned);
        let (code, message, fix) = (text("code")?, text("message")?, text("fix")?);
        if code.is_empty() || message.is_empty() {
            return None;
        }
        Some(Self {
            code,
            message,
            fix,
            detail: text("detail"),
        })
    }

    /// No reply arrived in time.
    pub fn timeout(method: &str, after: Duration) -> Self {
        Self::new(
            "TIMEOUT",
            "The sidecar did not answer in time.",
            RESTART_FIX,
            Some(format!("No reply to `{method}` within {after:?}.")),
        )
    }

    /// The sidecar process exited (or closed stdout) before replying.
    pub fn sidecar_exited(detail: Option<String>) -> Self {
        Self::new(
            "SIDECAR_EXITED",
            "The sidecar stopped before it could answer.",
            RESTART_FIX,
            detail,
        )
    }

    /// There is no running sidecar to send a request to.
    pub fn sidecar_not_running() -> Self {
        Self::new(
            "SIDECAR_NOT_RUNNING",
            "The sidecar is not running.",
            RESTART_FIX,
            None,
        )
    }

    /// Writing a request to the sidecar's stdin failed.
    pub fn write_failed(detail: String) -> Self {
        Self::new(
            "SIDECAR_WRITE_FAILED",
            "The request could not be sent to the sidecar.",
            RESTART_FIX,
            Some(detail),
        )
    }

    /// The child process could not be spawned.
    pub fn start_failed(program: &str, detail: String) -> Self {
        Self::new(
            "SIDECAR_START_FAILED",
            "The sidecar could not be started.",
            "Check that the Python interpreter exists and has the openlocate package installed \
             (see sidecar/README.md), then press Restart.",
            Some(format!("{program}: {detail}")),
        )
    }

    /// The UI sent a request that cannot be forwarded.
    pub fn invalid_request(detail: String) -> Self {
        Self::new(
            "INVALID_PARAMS",
            "The app sent an invalid request to the sidecar.",
            "This is a bug in the app. Please report it.",
            Some(detail),
        )
    }

    pub fn to_value(&self) -> Value {
        serde_json::json!({
            "code": self.code,
            "message": self.message,
            "fix": self.fix,
            "detail": self.detail,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn uses_error_data_when_present() {
        let error = json!({
            "code": -32000,
            "message": "Developer Mode is turned off on the iPhone.",
            "data": {
                "code": "DEVELOPER_MODE_OFF",
                "message": "Developer Mode is turned off on the iPhone.",
                "fix": "Turn it on.",
                "detail": null
            }
        });
        let mapped = UiError::from_rpc_error(&error);
        assert_eq!(
            mapped,
            UiError::new(
                "DEVELOPER_MODE_OFF",
                "Developer Mode is turned off on the iPhone.",
                "Turn it on.",
                None
            )
        );
    }

    #[test]
    fn keeps_detail_from_data() {
        let error = json!({"code": -32000, "message": "x", "data": {
            "code": "NOT_CONNECTED", "message": "m", "fix": "f", "detail": "more"}});
        assert_eq!(
            UiError::from_rpc_error(&error).detail.as_deref(),
            Some("more")
        );
    }

    #[test]
    fn builds_internal_error_without_data() {
        let error = json!({"code": -32601, "message": "Method not found"});
        let mapped = UiError::from_rpc_error(&error);
        assert_eq!(mapped.code, "INTERNAL");
        assert!(!mapped.message.is_empty());
        assert!(!mapped.fix.is_empty());
        assert_eq!(
            mapped.detail.as_deref(),
            Some("JSON-RPC error -32601: Method not found")
        );
    }

    #[test]
    fn ignores_malformed_data() {
        let error = json!({"code": -32603, "message": "boom", "data": {"code": 5}});
        assert_eq!(UiError::from_rpc_error(&error).code, "INTERNAL");
        let error = json!("just a string");
        let mapped = UiError::from_rpc_error(&error);
        assert_eq!(mapped.code, "INTERNAL");
        assert!(mapped.detail.is_some());
    }

    #[test]
    fn serialises_with_all_four_fields() {
        let value = UiError::timeout("app.info", Duration::from_secs(30)).to_value();
        assert_eq!(value["code"], "TIMEOUT");
        assert!(value["message"].is_string());
        assert!(value["fix"].is_string());
        assert_eq!(value["detail"], "No reply to `app.info` within 30s.");
        assert!(UiError::sidecar_not_running().to_value()["detail"].is_null());
    }
}
