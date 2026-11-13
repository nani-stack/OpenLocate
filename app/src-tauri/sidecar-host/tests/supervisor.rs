//! Runs the supervisor against a real child process (the `fake-sidecar` test binary).

// Test code: a panic is the right reaction to an unexpected error.
#![allow(clippy::unwrap_used)]

mod common;

use std::path::PathBuf;
use std::thread;
use std::time::{Duration, Instant};

use common::{eventually, Event, RecordingSink};

use openlocate_sidecar_host::{ExitOutcome, SidecarCommand, Supervisor, Timing, UiError};
use serde_json::json;

const FAST: Timing = Timing {
    request_timeout: Duration::from_millis(300),
    shutdown_grace: Duration::from_millis(300),
};

fn fake_command() -> SidecarCommand {
    SidecarCommand {
        program: PathBuf::from(env!("CARGO_BIN_EXE_fake-sidecar")),
        args: vec![
            "-m".into(),
            "openlocate".into(),
            "--backend".into(),
            "mock".into(),
        ],
        env: vec![("PYTHONUTF8".into(), "1".into())],
    }
}

fn supervisor_with(timing: Timing) -> (Supervisor, RecordingSink) {
    let sink = RecordingSink::default();
    let supervisor = Supervisor::new(
        Box::new(sink.clone()),
        Box::new(|| Ok(fake_command())),
        timing,
        false,
    );
    (supervisor, sink)
}

fn started(timing: Timing) -> (Supervisor, RecordingSink) {
    let (supervisor, sink) = supervisor_with(timing);
    supervisor.start().unwrap();
    (supervisor, sink)
}

#[tokio::test]
async fn call_before_start_reports_not_running() {
    let (supervisor, _) = supervisor_with(FAST);
    let err = supervisor.call("echo", None).await.unwrap_err();
    assert_eq!(err.code, "SIDECAR_NOT_RUNNING");
}

#[tokio::test]
async fn round_trip_with_command_args_and_env() {
    let (supervisor, _) = started(Timing::default());
    assert_eq!(
        supervisor.call("echo", Some(json!({"a": 1}))).await,
        Ok(json!({"a": 1}))
    );
    assert_eq!(
        supervisor.call("args", None).await,
        Ok(json!(["-m", "openlocate", "--backend", "mock"]))
    );
    assert_eq!(supervisor.call("env", None).await, Ok(json!("1")));
    supervisor.shutdown();
}

#[tokio::test]
async fn concurrent_calls_get_their_own_replies() {
    let (supervisor, _) = started(Timing::default());
    let calls = (0..20).map(|i| {
        let supervisor = supervisor.clone();
        async move { supervisor.call("echo", Some(json!({"i": i}))).await }
    });
    let results = futures_join_all(calls).await;
    for (i, result) in results.into_iter().enumerate() {
        assert_eq!(result, Ok(json!({"i": i})));
    }
    supervisor.shutdown();
}

/// A minimal join_all so the tests need no extra crate.
async fn futures_join_all<F: std::future::Future + Send + 'static>(
    futures: impl Iterator<Item = F>,
) -> Vec<F::Output>
where
    F::Output: Send + 'static,
{
    let handles: Vec<_> = futures.map(tokio::spawn).collect();
    let mut outputs = Vec::new();
    for handle in handles {
        outputs.push(handle.await.unwrap());
    }
    outputs
}

#[tokio::test]
async fn sidecar_errors_are_mapped() {
    let (supervisor, _) = started(Timing::default());
    let err = supervisor.call("fail", None).await.unwrap_err();
    assert_eq!(
        err,
        UiError::new(
            "NOT_CONNECTED",
            "No iPhone is connected.",
            "Connect an iPhone first.",
            None
        )
    );
    let err = supervisor.call("no.such.method", None).await.unwrap_err();
    assert_eq!(err.code, "INTERNAL");
    supervisor.shutdown();
}

#[tokio::test]
async fn invalid_requests_never_reach_the_sidecar() {
    let (supervisor, _) = started(Timing::default());
    let err = supervisor.call("bad method", None).await.unwrap_err();
    assert_eq!(err.code, "INVALID_PARAMS");
    let err = supervisor.call("echo", Some(json!(5))).await.unwrap_err();
    assert_eq!(err.code, "INVALID_PARAMS");
    assert_eq!(supervisor.call("echo", None).await, Ok(json!({})));
    supervisor.shutdown();
}

#[tokio::test]
async fn notifications_and_bad_lines_go_to_the_sink() {
    let (supervisor, sink) = started(Timing::default());
    supervisor
        .call("notify", Some(json!({"n": 1})))
        .await
        .unwrap();
    supervisor.call("garbage", None).await.unwrap();

    let events = sink.events();
    assert!(events.contains(&Event::Notification("test.note".into(), json!({"n": 1}))));
    assert!(events
        .iter()
        .any(|e| matches!(e, Event::Warning(w) if w.contains("invalid JSON"))));
    supervisor.shutdown();
}

#[tokio::test]
async fn a_request_without_reply_times_out_and_the_next_one_works() {
    let (supervisor, _) = started(FAST);
    let err = supervisor.call("silent", None).await.unwrap_err();
    assert_eq!(err.code, "TIMEOUT");
    assert!(err.detail.unwrap().contains("silent"));
    assert_eq!(supervisor.call("echo", None).await, Ok(json!({})));
    supervisor.shutdown();
}

#[tokio::test]
async fn child_exit_fails_pending_requests_and_is_reported() {
    let (supervisor, sink) = started(Timing::default());
    let pending = {
        let supervisor = supervisor.clone();
        tokio::spawn(async move { supervisor.call("silent", None).await })
    };
    // Give the silent request time to be written before the child exits.
    tokio::time::sleep(Duration::from_millis(100)).await;
    let err = supervisor
        .call("exit", Some(json!({"code": 3})))
        .await
        .unwrap_err();
    assert_eq!(err.code, "SIDECAR_EXITED");
    assert_eq!(pending.await.unwrap().unwrap_err().code, "SIDECAR_EXITED");

    assert!(eventually(|| sink.exits() == vec![Some(3)]));
    assert!(!supervisor.is_running());
    let err = supervisor.call("echo", None).await.unwrap_err();
    assert_eq!(err.code, "SIDECAR_EXITED");
    assert!(err.detail.unwrap().contains("Exit code 3"));
}

#[tokio::test]
async fn restart_replaces_the_child_without_a_stale_exit_event() {
    let (supervisor, sink) = started(Timing::default());
    let pending = {
        let supervisor = supervisor.clone();
        tokio::spawn(async move { supervisor.call("silent", None).await })
    };
    tokio::time::sleep(Duration::from_millis(100)).await;

    supervisor.restart().unwrap();

    assert_eq!(pending.await.unwrap().unwrap_err().code, "SIDECAR_EXITED");
    assert_eq!(supervisor.call("echo", None).await, Ok(json!({})));
    // Give the old reader thread time to finish; it must not report an exit.
    thread::sleep(Duration::from_millis(300));
    assert!(sink.exits().is_empty());
    supervisor.shutdown();
}

#[tokio::test]
async fn restart_after_an_exit_starts_again() {
    let (supervisor, sink) = started(Timing::default());
    let _ = supervisor.call("exit", Some(json!({"code": 0}))).await;
    assert!(eventually(|| !supervisor.is_running()));
    supervisor.restart().unwrap();
    assert_eq!(supervisor.call("echo", None).await, Ok(json!({})));
    assert_eq!(sink.exits(), vec![Some(0)]);
    supervisor.shutdown();
}

#[tokio::test]
async fn shutdown_closes_stdin_and_the_child_exits() {
    let (supervisor, sink) = started(Timing::default());
    supervisor.call("echo", None).await.unwrap();
    let begun = Instant::now();
    assert_eq!(
        supervisor.shutdown(),
        Some(ExitOutcome::Exited { code: Some(0) })
    );
    assert!(begun.elapsed() < Duration::from_secs(2));
    assert!(!supervisor.is_running());
    assert_eq!(
        supervisor.call("echo", None).await.unwrap_err().code,
        "SIDECAR_NOT_RUNNING"
    );
    thread::sleep(Duration::from_millis(200));
    assert!(sink.exits().is_empty());
}

#[tokio::test]
async fn shutdown_kills_a_child_that_ignores_stdin_closing() {
    let (supervisor, _) = started(FAST);
    supervisor.call("linger", None).await.unwrap();
    let begun = Instant::now();
    let outcome = supervisor.shutdown();
    assert!(
        matches!(outcome, Some(ExitOutcome::Killed { .. })),
        "{outcome:?}"
    );
    // Grace is 300 ms; the child would otherwise sleep for 60 s.
    assert!(begun.elapsed() < Duration::from_secs(5));
}

#[tokio::test]
async fn resolver_errors_are_kept_and_returned() {
    let sink = RecordingSink::default();
    let supervisor = Supervisor::new(
        Box::new(sink),
        Box::new(|| Err(UiError::new("SIDECAR_VENV_MISSING", "m", "f", None))),
        FAST,
        false,
    );
    assert_eq!(supervisor.start().unwrap_err().code, "SIDECAR_VENV_MISSING");
    assert_eq!(
        supervisor.call("echo", None).await.unwrap_err().code,
        "SIDECAR_VENV_MISSING"
    );
}

#[tokio::test]
async fn a_missing_program_is_a_start_failure() {
    let sink = RecordingSink::default();
    let supervisor = Supervisor::new(
        Box::new(sink),
        Box::new(|| {
            Ok(SidecarCommand {
                program: PathBuf::from("this-program-does-not-exist-openlocate"),
                args: vec![],
                env: vec![],
            })
        }),
        FAST,
        false,
    );
    let err = supervisor.start().unwrap_err();
    assert_eq!(err.code, "SIDECAR_START_FAILED");
    assert!(err.detail.unwrap().contains("this-program-does-not-exist"));
}
