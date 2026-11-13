//! Requests waiting for a reply, keyed by JSON-RPC id.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard};

use serde_json::Value;
use tokio::sync::oneshot;

use crate::error::UiError;

pub type Outcome = Result<Value, UiError>;

#[derive(Debug, Default)]
pub struct PendingRequests {
    next_id: AtomicU64,
    waiting: Mutex<HashMap<u64, oneshot::Sender<Outcome>>>,
    /// Set once the sidecar is gone, so a request registered afterwards fails at once.
    closed: Mutex<Option<UiError>>,
}

impl PendingRequests {
    pub fn new() -> Self {
        Self::default()
    }

    /// Allocates an id and returns it with the receiver its reply will arrive on.
    /// Fails if the sidecar has already gone away.
    pub fn register(&self) -> Result<(u64, oneshot::Receiver<Outcome>), UiError> {
        // Hold the `closed` lock while inserting so `fail_all` cannot slip in between.
        let closed = lock(&self.closed);
        if let Some(error) = closed.as_ref() {
            return Err(error.clone());
        }
        let id = self.next_id.fetch_add(1, Ordering::Relaxed) + 1;
        let (sender, receiver) = oneshot::channel();
        lock(&self.waiting).insert(id, sender);
        Ok((id, receiver))
    }

    /// Delivers a reply. Returns false if no request with this id is waiting (for example
    /// because it already timed out).
    pub fn complete(&self, id: u64, outcome: Outcome) -> bool {
        match lock(&self.waiting).remove(&id) {
            // The receiver may have been dropped (timeout); that is not an error.
            Some(sender) => sender.send(outcome).is_ok(),
            None => false,
        }
    }

    /// Forgets a request, for example after a timeout or a failed write.
    pub fn cancel(&self, id: u64) {
        lock(&self.waiting).remove(&id);
    }

    /// Fails every waiting request with `error` and refuses new ones from now on.
    pub fn fail_all(&self, error: UiError) {
        let mut closed = lock(&self.closed);
        let drained: Vec<_> = lock(&self.waiting).drain().collect();
        for (_, sender) in drained {
            let _ignored_if_receiver_gone = sender.send(Err(error.clone()));
        }
        *closed = Some(error);
    }

    pub fn len(&self) -> usize {
        lock(&self.waiting).len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

/// Locks a mutex, recovering from poisoning: the maps stay consistent even if a holder panicked,
/// because every operation on them is a single insert or remove.
fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn ids_are_unique_and_start_at_one() {
        let pending = PendingRequests::new();
        let (a, _ra) = pending.register().unwrap();
        let (b, _rb) = pending.register().unwrap();
        assert_eq!((a, b), (1, 2));
        assert_eq!(pending.len(), 2);
    }

    #[test]
    fn complete_delivers_to_the_matching_receiver() {
        let pending = PendingRequests::new();
        let (a, mut ra) = pending.register().unwrap();
        let (b, mut rb) = pending.register().unwrap();

        assert!(pending.complete(b, Ok(json!({"b": true}))));
        assert!(pending.complete(a, Err(UiError::sidecar_not_running())));

        assert_eq!(rb.try_recv().unwrap(), Ok(json!({"b": true})));
        assert_eq!(
            ra.try_recv().unwrap().unwrap_err().code,
            "SIDECAR_NOT_RUNNING"
        );
        assert!(pending.is_empty());
    }

    #[test]
    fn unknown_or_cancelled_ids_are_ignored() {
        let pending = PendingRequests::new();
        assert!(!pending.complete(99, Ok(Value::Null)));
        let (id, _rx) = pending.register().unwrap();
        pending.cancel(id);
        assert!(!pending.complete(id, Ok(Value::Null)));
    }

    #[test]
    fn dropped_receiver_does_not_panic() {
        let pending = PendingRequests::new();
        let (id, rx) = pending.register().unwrap();
        drop(rx);
        assert!(!pending.complete(id, Ok(Value::Null)));
    }

    #[test]
    fn fail_all_fails_every_request_and_closes() {
        let pending = PendingRequests::new();
        let (_, mut r1) = pending.register().unwrap();
        let (_, mut r2) = pending.register().unwrap();

        pending.fail_all(UiError::sidecar_exited(None));

        assert_eq!(r1.try_recv().unwrap().unwrap_err().code, "SIDECAR_EXITED");
        assert_eq!(r2.try_recv().unwrap().unwrap_err().code, "SIDECAR_EXITED");
        assert!(pending.is_empty());
        assert_eq!(pending.register().unwrap_err().code, "SIDECAR_EXITED");
    }
}
