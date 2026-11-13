//! Shared test helpers: a sink that records every event, and a polling helper.

// Each test file compiles this module separately and uses only part of it.
#![allow(dead_code, clippy::unwrap_used)]

use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use openlocate_sidecar_host::EventSink;
use serde_json::Value;

#[derive(Debug, Clone, PartialEq)]
pub enum Event {
    Notification(String, Value),
    Exited(Option<i32>),
    Warning(String),
}

#[derive(Default, Clone)]
pub struct RecordingSink(Arc<Mutex<Vec<Event>>>);

impl RecordingSink {
    pub fn events(&self) -> Vec<Event> {
        self.0.lock().unwrap().clone()
    }

    pub fn exits(&self) -> Vec<Option<i32>> {
        self.events()
            .into_iter()
            .filter_map(|e| match e {
                Event::Exited(code) => Some(code),
                _ => None,
            })
            .collect()
    }
}

impl EventSink for RecordingSink {
    fn notification(&self, method: String, params: Value) {
        self.0
            .lock()
            .unwrap()
            .push(Event::Notification(method, params));
    }
    fn exited(&self, code: Option<i32>) {
        self.0.lock().unwrap().push(Event::Exited(code));
    }
    fn warning(&self, message: String) {
        self.0.lock().unwrap().push(Event::Warning(message));
    }
}

/// Polls `condition` for up to five seconds.
pub fn eventually(condition: impl Fn() -> bool) -> bool {
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if condition() {
            return true;
        }
        thread::sleep(Duration::from_millis(20));
    }
    condition()
}
