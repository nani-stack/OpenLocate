//! OpenLocate's Rust shell: a pipe between the webview and the Python sidecar.

mod sidecar;

use openlocate_sidecar_host::{ExitOutcome, Supervisor, UiError};
use serde_json::Value;
use tauri::webview::{PermissionKind, PermissionResponse};
use tauri::{Manager, RunEvent, State};

/// Forwards one JSON-RPC call to the sidecar. `Ok` is the JSON-RPC `result`; `Err` is
/// `{code, message, fix, detail}`.
#[tauri::command]
async fn rpc(
    supervisor: State<'_, Supervisor>,
    method: String,
    params: Option<Value>,
) -> Result<Value, Value> {
    supervisor
        .call(&method, params)
        .await
        .map_err(|err| err.to_value())
}

/// Kills the sidecar (if running) and starts a new one.
#[tauri::command]
async fn sidecar_restart(supervisor: State<'_, Supervisor>) -> Result<(), Value> {
    let supervisor = supervisor.inner().clone();
    // Restarting waits for the old process to be reaped; keep that off the async workers.
    match tauri::async_runtime::spawn_blocking(move || supervisor.restart()).await {
        Ok(result) => result.map_err(|err| err.to_value()),
        Err(err) => Err(UiError::new(
            "INTERNAL",
            "Restarting the sidecar failed unexpectedly.",
            "Close and reopen OpenLocate.",
            Some(err.to_string()),
        )
        .to_value()),
    }
}

pub fn run() -> Result<(), tauri::Error> {
    let app = tauri::Builder::default()
        // The map opens at this computer's position, so the app's own pages may ask the
        // operating system for it (the system's location setting still decides). Nothing
        // else is granted: no camera, microphone, notifications, clipboard or file access.
        .on_permission_request(|_, kind| match kind {
            PermissionKind::Geolocation => PermissionResponse::Allow,
            _ => PermissionResponse::Deny,
        })
        .setup(|app| {
            let supervisor = sidecar::supervisor(app.handle().clone());
            // A failed start is remembered by the supervisor, so the UI's first call reports
            // it with a fix. The window still opens.
            if let Err(err) = supervisor.start() {
                eprintln!("[openlocate] the sidecar did not start: {}", err.message);
            }
            app.manage(supervisor);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![rpc, sidecar_restart])
        .build(tauri::generate_context!())?;

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(supervisor) = handle.try_state::<Supervisor>() {
                // Closes the sidecar's stdin and kills it if it has not exited within 2 s.
                if let Some(ExitOutcome::Killed { .. }) = supervisor.shutdown() {
                    eprintln!("[openlocate] the sidecar did not exit in time and was killed");
                }
            }
        }
    });
    Ok(())
}
