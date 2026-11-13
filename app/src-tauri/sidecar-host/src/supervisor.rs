//! Owns the sidecar child process: spawning, the stdin writer, the stdout reader, request
//! timeouts, restart and shutdown. Events go to an `EventSink`, so this runs (and is tested)
//! without Tauri; the app plugs in a sink that emits Tauri events.

use std::io::{BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;
use tokio::sync::oneshot;

use crate::command::SidecarCommand;
use crate::error::UiError;
use crate::pending::{Outcome, PendingRequests};
use crate::reader::{read_lines, ReaderEnd};
use crate::request::encode_request;

const EXIT_POLL_INTERVAL: Duration = Duration::from_millis(50);

/// Where the supervisor reports what the sidecar does.
pub trait EventSink: Send + Sync + 'static {
    /// A notification line arrived.
    fn notification(&self, method: String, params: Value);
    /// The current child exited on its own (not through `restart` or `shutdown`).
    fn exited(&self, code: Option<i32>);
    /// Something worth a log line that is not an error for any caller.
    fn warning(&self, message: String);
}

/// How a child process ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExitOutcome {
    /// It exited by itself (within the grace period, when one applied).
    Exited { code: Option<i32> },
    /// It had to be killed.
    Killed { code: Option<i32> },
}

impl ExitOutcome {
    /// The exit code, if the OS reported one (there is none after a kill by signal).
    pub fn code(self) -> Option<i32> {
        match self {
            Self::Exited { code } | Self::Killed { code } => code,
        }
    }
}

/// Produces the command to run; called on every start so environment changes apply on restart.
pub type CommandResolver = Box<dyn Fn() -> Result<SidecarCommand, UiError> + Send + Sync>;

#[derive(Debug, Clone, Copy)]
pub struct Timing {
    /// A request with no reply within this time fails with `TIMEOUT`.
    pub request_timeout: Duration,
    /// How long a child may take to exit after its stdin closes before it is killed.
    pub shutdown_grace: Duration,
}

impl Default for Timing {
    fn default() -> Self {
        Self {
            request_timeout: Duration::from_secs(30),
            shutdown_grace: Duration::from_secs(2),
        }
    }
}

/// A live child process.
struct Running {
    generation: u64,
    child: Arc<Mutex<Child>>,
    /// Lines for the writer thread. Dropping it closes the child's stdin.
    writer: mpsc::Sender<String>,
    pending: Arc<PendingRequests>,
}

enum State {
    Running(Running),
    /// Not running; the error explains why and is returned to callers.
    Stopped(UiError),
}

struct Inner {
    sink: Box<dyn EventSink>,
    resolve: CommandResolver,
    timing: Timing,
    inherit_stderr: bool,
    state: Mutex<State>,
    next_generation: AtomicU64,
}

/// Cheap to clone; all clones control the same child.
#[derive(Clone)]
pub struct Supervisor {
    inner: Arc<Inner>,
}

impl Supervisor {
    /// `inherit_stderr` passes the child's stderr through (useful in development); otherwise it
    /// is discarded, since the sidecar writes its own log file.
    pub fn new(
        sink: Box<dyn EventSink>,
        resolve: CommandResolver,
        timing: Timing,
        inherit_stderr: bool,
    ) -> Self {
        Self {
            inner: Arc::new(Inner {
                sink,
                resolve,
                timing,
                inherit_stderr,
                state: Mutex::new(State::Stopped(UiError::sidecar_not_running())),
                next_generation: AtomicU64::new(0),
            }),
        }
    }

    pub fn is_running(&self) -> bool {
        matches!(*lock(&self.inner.state), State::Running(_))
    }

    /// Starts the sidecar unless it is already running. On failure the error is also kept and
    /// returned by later calls, so the UI's first request explains what went wrong.
    pub fn start(&self) -> Result<(), UiError> {
        let mut state = lock(&self.inner.state);
        if matches!(*state, State::Running(_)) {
            return Ok(());
        }
        match spawn(&self.inner) {
            Ok(running) => {
                *state = State::Running(running);
                Ok(())
            }
            Err(err) => {
                *state = State::Stopped(err.clone());
                Err(err)
            }
        }
    }

    /// Kills the current child (if any) and starts a new one. Blocks while the old one is reaped.
    pub fn restart(&self) -> Result<(), UiError> {
        if let Some(old) = self.take_running() {
            drop(old.writer);
            kill_and_reap(&old.child, self.inner.sink.as_ref());
        }
        self.start()
    }

    /// Closes the child's stdin and gives it the shutdown grace period to exit before killing it.
    /// Blocks for at most that long. Returns how the child ended, or `None` if none was running.
    pub fn shutdown(&self) -> Option<ExitOutcome> {
        let old = self.take_running()?;
        drop(old.writer);
        Some(wait_or_kill(
            &old.child,
            self.inner.timing.shutdown_grace,
            self.inner.sink.as_ref(),
        ))
    }

    /// Sends one request and waits for its reply, at most the request timeout.
    pub async fn call(&self, method: &str, params: Option<Value>) -> Result<Value, UiError> {
        let sent = self.send(method, params)?;
        let timeout = self.inner.timing.request_timeout;
        match tokio::time::timeout(timeout, sent.receiver).await {
            Ok(Ok(outcome)) => outcome,
            // The reply channel closed without a reply; only happens if the table was dropped.
            Ok(Err(_closed)) => Err(UiError::sidecar_exited(None)),
            Err(_elapsed) => {
                sent.pending.cancel(sent.id);
                Err(UiError::timeout(method, timeout))
            }
        }
    }

    fn send(&self, method: &str, params: Option<Value>) -> Result<Sent, UiError> {
        let state = lock(&self.inner.state);
        let running = match &*state {
            State::Running(running) => running,
            State::Stopped(err) => return Err(err.clone()),
        };
        let (id, receiver) = running.pending.register()?;
        let line =
            encode_request(id, method, params).inspect_err(|_| running.pending.cancel(id))?;
        if running.writer.send(line).is_err() {
            running.pending.cancel(id);
            return Err(UiError::write_failed(
                "the sidecar's stdin is closed".to_owned(),
            ));
        }
        Ok(Sent {
            id,
            receiver,
            pending: Arc::clone(&running.pending),
        })
    }

    fn take_running(&self) -> Option<Running> {
        let mut state = lock(&self.inner.state);
        match std::mem::replace(&mut *state, State::Stopped(UiError::sidecar_not_running())) {
            State::Running(running) => Some(running),
            stopped @ State::Stopped(_) => {
                *state = stopped;
                None
            }
        }
    }
}

struct Sent {
    id: u64,
    receiver: oneshot::Receiver<Outcome>,
    pending: Arc<PendingRequests>,
}

fn spawn(inner: &Arc<Inner>) -> Result<Running, UiError> {
    let command = (inner.resolve)()?;
    let program = command.program.display().to_string();
    let mut child = build_command(&command, inner.inherit_stderr)
        .spawn()
        .map_err(|err| UiError::start_failed(&program, err.to_string()))?;

    let (Some(stdin), Some(stdout)) = (child.stdin.take(), child.stdout.take()) else {
        let _already_exited = child.kill();
        let _reaped = child.wait();
        return Err(UiError::start_failed(
            &program,
            "stdin or stdout was not piped".to_owned(),
        ));
    };

    let generation = inner.next_generation.fetch_add(1, Ordering::Relaxed) + 1;
    let child = Arc::new(Mutex::new(child));
    let pending = Arc::new(PendingRequests::new());
    let (writer, lines) = mpsc::channel();

    let started = start_threads(inner, generation, stdin, stdout, &child, &pending, lines);
    if let Err(err) = started {
        kill_and_reap(&child, inner.sink.as_ref());
        return Err(UiError::start_failed(
            &program,
            format!("could not start a thread: {err}"),
        ));
    }

    Ok(Running {
        generation,
        child,
        writer,
        pending,
    })
}

fn start_threads(
    inner: &Arc<Inner>,
    generation: u64,
    stdin: ChildStdin,
    stdout: ChildStdout,
    child: &Arc<Mutex<Child>>,
    pending: &Arc<PendingRequests>,
    lines: mpsc::Receiver<String>,
) -> std::io::Result<()> {
    let writer_inner = Arc::clone(inner);
    thread::Builder::new()
        .name("sidecar-writer".to_owned())
        .spawn(move || write_lines(stdin, &lines, writer_inner.sink.as_ref()))?;

    let (inner, child, pending) = (Arc::clone(inner), Arc::clone(child), Arc::clone(pending));
    thread::Builder::new()
        .name("sidecar-reader".to_owned())
        .spawn(move || read_until_exit(&inner, generation, stdout, &child, &pending))?;
    Ok(())
}

fn build_command(spec: &SidecarCommand, inherit_stderr: bool) -> Command {
    let mut command = Command::new(&spec.program);
    command
        .args(&spec.args)
        .envs(spec.env.iter().map(|(key, value)| (key, value)))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(if inherit_stderr {
            Stdio::inherit()
        } else {
            Stdio::null()
        });
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // Keeps a console window from flashing up when the GUI app starts the sidecar.
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

/// Writer thread: one whole line per request, so lines never interleave. Ends (closing stdin)
/// when every sender is dropped or a write fails.
fn write_lines(mut stdin: ChildStdin, lines: &mpsc::Receiver<String>, sink: &dyn EventSink) {
    for line in lines {
        if let Err(err) = stdin
            .write_all(line.as_bytes())
            .and_then(|()| stdin.flush())
        {
            // The reader sees EOF as well and fails the pending requests.
            sink.warning(format!("Writing to the sidecar failed: {err}"));
            return;
        }
    }
}

/// Reader thread: forwards replies and notifications until stdout closes, then fails what is
/// still pending and, if this child is still the current one, reports the exit.
fn read_until_exit(
    inner: &Inner,
    generation: u64,
    stdout: ChildStdout,
    child: &Mutex<Child>,
    pending: &PendingRequests,
) {
    let sink = inner.sink.as_ref();
    let end = read_lines(
        BufReader::new(stdout),
        pending,
        |method, params| sink.notification(method, params),
        |warning| sink.warning(warning),
    );
    let reason = match end {
        ReaderEnd::Eof => "The sidecar closed its output.".to_owned(),
        ReaderEnd::Error(err) => format!("Reading the sidecar's output failed: {err}"),
    };
    pending.fail_all(UiError::sidecar_exited(Some(reason.clone())));

    let code = wait_or_kill(child, inner.timing.shutdown_grace, sink).code();

    // Hold the state lock while reporting, so a concurrent restart cannot be overtaken by a
    // stale exit event from the child it replaced.
    let mut state = lock(&inner.state);
    let is_current = matches!(&*state, State::Running(r) if r.generation == generation);
    if is_current {
        let detail = match code {
            Some(code) => format!("{reason} Exit code {code}."),
            None => reason,
        };
        *state = State::Stopped(UiError::sidecar_exited(Some(detail)));
        sink.exited(code);
    }
}

/// Waits up to `grace` for the child to exit, then kills it.
fn wait_or_kill(child: &Mutex<Child>, grace: Duration, sink: &dyn EventSink) -> ExitOutcome {
    let deadline = Instant::now() + grace;
    loop {
        // Bind first: a guard in the `match` scrutinee would stay locked through the arms,
        // and `kill_and_reap` locks again.
        let status = lock(child).try_wait();
        match status {
            Ok(Some(status)) => {
                return ExitOutcome::Exited {
                    code: status.code(),
                }
            }
            Ok(None) if Instant::now() < deadline => {}
            Ok(None) => {
                return ExitOutcome::Killed {
                    code: kill_and_reap(child, sink),
                }
            }
            Err(err) => {
                sink.warning(format!("Could not check the sidecar's status: {err}"));
                return ExitOutcome::Killed {
                    code: kill_and_reap(child, sink),
                };
            }
        }
        thread::sleep(EXIT_POLL_INTERVAL);
    }
}

fn kill_and_reap(child: &Mutex<Child>, sink: &dyn EventSink) -> Option<i32> {
    let mut child = lock(child);
    // Killing a process that already exited is not an error worth reporting.
    let _already_exited = child.kill();
    match child.wait() {
        Ok(status) => status.code(),
        Err(err) => {
            sink.warning(format!("Could not reap the sidecar: {err}"));
            None
        }
    }
}

/// Locks a mutex, recovering from poisoning: no code here panics while holding a lock, and the
/// guarded values stay valid either way.
fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}
