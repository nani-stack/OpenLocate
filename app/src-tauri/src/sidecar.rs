//! Tauri glue for the sidecar: which command to run, and turning supervisor events into
//! Tauri events. The process handling itself is `openlocate_sidecar_host::Supervisor`, which
//! does not depend on Tauri so it can be tested anywhere.

use std::path::Path;

use openlocate_sidecar_host::command::{dev_venv_python, BACKEND_ENV, PYTHON_ENV};
use openlocate_sidecar_host::{
    resolve_command, EventSink, ResolveInputs, SidecarCommand, Supervisor, Timing, UiError,
};
use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter};

pub const NOTIFICATION_EVENT: &str = "sidecar://notification";
pub const EXIT_EVENT: &str = "sidecar://exit";

#[derive(Clone, Serialize)]
struct NotificationPayload {
    method: String,
    params: Value,
}

#[derive(Clone, Serialize)]
struct ExitPayload {
    code: Option<i32>,
}

struct TauriSink {
    app: AppHandle,
}

impl TauriSink {
    fn emit<P: Serialize + Clone>(&self, event: &str, payload: P) {
        if let Err(err) = self.app.emit(event, payload) {
            eprintln!("[openlocate] could not emit {event}: {err}");
        }
    }
}

impl EventSink for TauriSink {
    fn notification(&self, method: String, params: Value) {
        self.emit(NOTIFICATION_EVENT, NotificationPayload { method, params });
    }

    fn exited(&self, code: Option<i32>) {
        self.emit(EXIT_EVENT, ExitPayload { code });
    }

    fn warning(&self, message: String) {
        eprintln!("[openlocate] {message}");
    }
}

/// Builds the supervisor for this app. It is not started yet.
pub fn supervisor(app: AppHandle) -> Supervisor {
    Supervisor::new(
        Box::new(TauriSink { app }),
        Box::new(resolve),
        Timing::default(),
        // The sidecar logs to its own file; its stderr is only useful while developing.
        cfg!(debug_assertions),
    )
}

fn resolve() -> Result<SidecarCommand, UiError> {
    // The development virtualenv is located from this crate's source directory, so it only
    // makes sense in debug builds run from a checkout.
    let dev_python = cfg!(debug_assertions)
        .then(|| dev_venv_python(Path::new(env!("CARGO_MANIFEST_DIR")), cfg!(windows)));
    let inputs = ResolveInputs {
        python_override: std::env::var_os(PYTHON_ENV),
        backend: std::env::var_os(BACKEND_ENV),
        dev_python,
    };
    resolve_command(&inputs, Path::exists)
}
