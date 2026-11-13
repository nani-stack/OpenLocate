//! The loop that reads the sidecar's stdout. Generic over the reader so it can be tested with
//! in-memory input.

use std::io::{BufRead, ErrorKind};

use serde_json::Value;

use crate::line::{classify_line, Incoming};
use crate::pending::PendingRequests;

/// Why the read loop stopped.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReaderEnd {
    /// stdout was closed (normally because the sidecar exited).
    Eof,
    /// Reading failed with an I/O error.
    Error(String),
}

/// Reads lines until EOF or an I/O error, completing pending requests and forwarding
/// notifications. Bad lines are reported through `on_warning` and skipped. The caller decides
/// what to do with the requests still pending when this returns.
pub fn read_lines<R, N, W>(
    reader: R,
    pending: &PendingRequests,
    mut on_notification: N,
    mut on_warning: W,
) -> ReaderEnd
where
    R: BufRead,
    N: FnMut(String, Value),
    W: FnMut(String),
{
    for line in reader.lines() {
        let line = match line {
            Ok(line) => line,
            // The bad bytes have been consumed; the next line may be fine.
            Err(err) if err.kind() == ErrorKind::InvalidData => {
                on_warning(format!("Ignoring sidecar output that is not UTF-8: {err}"));
                continue;
            }
            Err(err) => return ReaderEnd::Error(err.to_string()),
        };
        match classify_line(&line) {
            Incoming::Response { id, outcome } => {
                if !pending.complete(id, outcome) {
                    on_warning(format!(
                        "Ignoring reply to request {id}: nothing is waiting for it (it may have timed out)"
                    ));
                }
            }
            Incoming::Notification { method, params } => on_notification(method, params),
            Incoming::Unrecognised { reason } => {
                on_warning(format!("Ignoring unrecognised sidecar output: {reason}"));
            }
        }
    }
    ReaderEnd::Eof
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::io::Cursor;

    #[test]
    fn routes_replies_notifications_and_warnings() {
        let pending = PendingRequests::new();
        let (id, mut rx) = pending.register().unwrap();
        let input = format!(
            "{{\"jsonrpc\":\"2.0\",\"method\":\"playback.state\",\"params\":{{\"state\":\"PLAYING\"}}}}\n\
             garbage\n\
             {{\"jsonrpc\":\"2.0\",\"id\":{id},\"result\":{{\"ok\":true}}}}\n\
             {{\"jsonrpc\":\"2.0\",\"id\":555,\"result\":{{}}}}\n"
        );
        let mut notifications = Vec::new();
        let mut warnings = Vec::new();

        let end = read_lines(
            Cursor::new(input),
            &pending,
            |method, params| notifications.push((method, params)),
            |warning| warnings.push(warning),
        );

        assert_eq!(end, ReaderEnd::Eof);
        assert_eq!(rx.try_recv().unwrap(), Ok(json!({"ok": true})));
        assert_eq!(
            notifications,
            vec![("playback.state".to_owned(), json!({"state": "PLAYING"}))]
        );
        assert_eq!(warnings.len(), 2, "{warnings:?}");
    }

    #[test]
    fn skips_invalid_utf8_and_keeps_reading() {
        let pending = PendingRequests::new();
        let mut input: Vec<u8> = vec![0xff, 0xfe, b'\n'];
        input.extend_from_slice(b"{\"method\":\"log.error\",\"params\":{}}\n");
        let mut notifications = 0;
        let mut warnings = 0;

        let end = read_lines(
            Cursor::new(input),
            &pending,
            |_, _| notifications += 1,
            |_| warnings += 1,
        );

        assert_eq!(end, ReaderEnd::Eof);
        assert_eq!((notifications, warnings), (1, 1));
    }

    #[test]
    fn last_line_without_newline_is_still_read() {
        let pending = PendingRequests::new();
        let (id, mut rx) = pending.register().unwrap();
        let input = format!("{{\"id\":{id},\"result\":1}}");
        read_lines(Cursor::new(input), &pending, |_, _| {}, |_| {});
        assert_eq!(rx.try_recv().unwrap(), Ok(json!(1)));
    }

    struct FailingReader;

    impl std::io::Read for FailingReader {
        fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
            Err(std::io::Error::new(ErrorKind::BrokenPipe, "pipe broke"))
        }
    }

    #[test]
    fn io_error_ends_the_loop() {
        let pending = PendingRequests::new();
        let end = read_lines(
            std::io::BufReader::new(FailingReader),
            &pending,
            |_, _| {},
            |_| {},
        );
        assert_eq!(end, ReaderEnd::Error("pipe broke".into()));
    }
}
