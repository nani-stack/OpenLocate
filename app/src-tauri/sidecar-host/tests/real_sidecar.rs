//! Drives the supervisor against the real Python sidecar (mock backend), using the development
//! virtualenv at `<repo>/sidecar/.venv`. Without that virtualenv the test prints why it was
//! skipped and passes, so hosts that only build the app are not blocked.

// Test code: a panic is the right reaction to an unexpected error.
#![allow(clippy::unwrap_used)]

mod common;

use std::path::{Path, PathBuf};
use std::time::Duration;

use common::{eventually, Event, RecordingSink};
use openlocate_sidecar_host::command::dev_venv_python;
use openlocate_sidecar_host::{resolve_command, ExitOutcome, ResolveInputs, Supervisor, Timing};
use serde_json::json;

/// `<repo>/sidecar/.venv/.../python`, located from this crate (`<repo>/app/src-tauri/sidecar-host`).
fn venv_python() -> PathBuf {
    let tauri_crate = Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
    dev_venv_python(&tauri_crate, cfg!(windows))
}

/// A fresh log directory under the system temp dir, removed when dropped.
struct TempLogDir(PathBuf);

impl TempLogDir {
    fn new() -> Self {
        let dir = std::env::temp_dir().join(format!(
            "openlocate-sidecar-host-test-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        Self(dir)
    }
}

impl Drop for TempLogDir {
    fn drop(&mut self) {
        let _best_effort = std::fs::remove_dir_all(&self.0);
    }
}

#[tokio::test]
async fn real_sidecar_with_mock_backend() {
    let python = venv_python();
    if !python.exists() {
        println!("skipped: sidecar venv not found at {}", python.display());
        return;
    }
    let log_dir = TempLogDir::new();

    // Same resolution path as the app, then point the logs at the temp dir.
    let inputs = ResolveInputs {
        python_override: None,
        backend: Some("mock".into()),
        dev_python: Some(python),
    };
    let mut command = resolve_command(&inputs, Path::exists).unwrap();
    command.args.push("--log-dir".into());
    command.args.push(log_dir.0.display().to_string());
    assert_eq!(command.args[..4], ["-m", "openlocate", "--backend", "mock"]);
    // Leave the sidecar checkout untouched: no __pycache__ writes from this test.
    command
        .env
        .push(("PYTHONDONTWRITEBYTECODE".into(), "1".into()));

    let sink = RecordingSink::default();
    let supervisor = Supervisor::new(
        Box::new(sink.clone()),
        Box::new(move || Ok(command.clone())),
        Timing::default(),
        false,
    );
    supervisor.start().unwrap();

    let info = supervisor.call("app.info", None).await.unwrap();
    assert_eq!(info["backend"], "mock");

    let device = supervisor
        .call("device.connect", Some(json!({"id": "MOCK-0001"})))
        .await
        .unwrap();
    assert_eq!(device["state"], "ready");

    let result = supervisor
        .call("location.set", Some(json!({"lat": 48.8584, "lon": 2.2945})))
        .await
        .unwrap();
    assert_eq!(result, json!({}));
    let teleported = Event::Notification(
        "location.updated".into(),
        json!({"lat": 48.8584, "lon": 2.2945, "source": "teleport"}),
    );
    assert!(
        eventually(|| sink.events().contains(&teleported)),
        "no teleport notification; events: {:?}",
        sink.events()
    );

    let err = supervisor
        .call("location.set", Some(json!({"lat": 123, "lon": 0})))
        .await
        .unwrap_err();
    assert_eq!(err.code, "INVALID_PARAMS");
    assert!(!err.fix.is_empty());

    let outcome = supervisor.shutdown();
    assert_eq!(outcome, Some(ExitOutcome::Exited { code: Some(0) }));
    assert!(!supervisor.is_running());
    // The process was replaced deliberately, so no exit event is expected.
    std::thread::sleep(Duration::from_millis(100));
    assert!(sink.exits().is_empty());
    // stdout must carry protocol messages only: any other line would have produced a warning.
    let warnings: Vec<_> = sink
        .events()
        .into_iter()
        .filter(|e| matches!(e, Event::Warning(_)))
        .collect();
    assert!(warnings.is_empty(), "{warnings:?}");
}
