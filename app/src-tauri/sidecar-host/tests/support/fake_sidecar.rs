//! A stand-in for the Python sidecar, used only by `tests/supervisor.rs`. It speaks
//! newline-delimited JSON-RPC on stdio and has a few methods that trigger specific behaviour.

use std::io::{self, BufRead, Write};
use std::time::Duration;

use serde_json::{json, Value};

fn main() {
    let stdin = io::stdin();
    let mut linger_after_eof = false;
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let Ok(request) = serde_json::from_str::<Value>(&line) else {
            continue;
        };
        let id = request.get("id").cloned().unwrap_or(Value::Null);
        let params = request.get("params").cloned().unwrap_or(json!({}));
        match request.get("method").and_then(Value::as_str).unwrap_or("") {
            "echo" => reply(&id, params),
            "args" => reply(&id, json!(std::env::args().skip(1).collect::<Vec<_>>())),
            "env" => reply(&id, json!(std::env::var("PYTHONUTF8").ok())),
            "notify" => {
                send(&json!({"jsonrpc": "2.0", "method": "test.note", "params": params}));
                reply(&id, json!({}));
            }
            "garbage" => {
                send_raw("this is not json");
                reply(&id, json!({}));
            }
            "fail" => send(&json!({"jsonrpc": "2.0", "id": id, "error": {
                "code": -32000,
                "message": "No iPhone is connected.",
                "data": {"code": "NOT_CONNECTED", "message": "No iPhone is connected.",
                         "fix": "Connect an iPhone first.", "detail": null}
            }})),
            "silent" => {}
            "linger" => {
                linger_after_eof = true;
                reply(&id, json!({}));
            }
            "exit" => {
                let code = params.get("code").and_then(Value::as_i64).unwrap_or(0);
                std::process::exit(i32::try_from(code).unwrap_or(1));
            }
            _ => send(&json!({"jsonrpc": "2.0", "id": id,
                              "error": {"code": -32601, "message": "Method not found"}})),
        }
    }
    if linger_after_eof {
        std::thread::sleep(Duration::from_secs(60));
    }
}

fn reply(id: &Value, result: Value) {
    send(&json!({"jsonrpc": "2.0", "id": id, "result": result}));
}

fn send(message: &Value) {
    send_raw(&message.to_string());
}

fn send_raw(line: &str) {
    let mut stdout = io::stdout().lock();
    let _ = writeln!(stdout, "{line}");
    let _ = stdout.flush();
}
