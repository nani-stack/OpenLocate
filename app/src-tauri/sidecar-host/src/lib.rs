//! The sidecar host for OpenLocate, without any Tauri dependency, so it can be built and tested
//! on any machine (including hosts without the WebView development packages).
//!
//! `Supervisor` runs the child process and talks JSON-RPC over its stdio. The Tauri crate
//! (`src-tauri/src/sidecar.rs`) only decides which command to run and turns `EventSink` calls
//! into Tauri events.

pub mod command;
pub mod error;
pub mod line;
pub mod pending;
pub mod reader;
pub mod request;
pub mod supervisor;

pub use command::{resolve_command, ResolveInputs, SidecarCommand};
pub use error::UiError;
pub use line::{classify_line, Incoming};
pub use pending::{Outcome, PendingRequests};
pub use reader::{read_lines, ReaderEnd};
pub use request::encode_request;
pub use supervisor::{CommandResolver, EventSink, ExitOutcome, Supervisor, Timing};
