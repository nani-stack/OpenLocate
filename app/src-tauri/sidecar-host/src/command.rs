//! Deciding which program runs the sidecar. Pure: the caller reads the environment and the
//! build profile and passes them in.

use std::ffi::OsString;
use std::path::{Path, PathBuf};

use crate::error::UiError;

/// Environment variable naming a Python interpreter to run `-m openlocate` with.
pub const PYTHON_ENV: &str = "OPENLOCATE_SIDECAR_PYTHON";
/// Environment variable naming the device backend, forwarded as `--backend`.
pub const BACKEND_ENV: &str = "OPENLOCATE_BACKEND";

const MAX_BACKEND_LEN: usize = 32;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SidecarCommand {
    pub program: PathBuf,
    pub args: Vec<String>,
    /// Extra environment variables for the child.
    pub env: Vec<(String, String)>,
}

/// Everything `resolve_command` needs to know about the outside world.
#[derive(Debug, Clone, Default)]
pub struct ResolveInputs {
    /// Value of `OPENLOCATE_SIDECAR_PYTHON`, if set.
    pub python_override: Option<OsString>,
    /// Value of `OPENLOCATE_BACKEND`, if set.
    pub backend: Option<OsString>,
    /// The development virtualenv's interpreter; `Some` only in debug builds.
    pub dev_python: Option<PathBuf>,
    /// The standalone helper shipped inside the installed app, if the app knows where its
    /// resources are.
    pub bundled: Option<PathBuf>,
}

/// Folder inside the app's resources that holds the standalone helper, and its file name.
pub const BUNDLED_DIR: &str = "sidecar";
pub const BUNDLED_NAME: &str = "openlocate-sidecar";

/// Where the standalone helper sits, given the app's resource directory.
pub fn bundled_sidecar(resource_dir: &Path, windows: bool) -> PathBuf {
    let name = if windows {
        format!("{BUNDLED_NAME}.exe")
    } else {
        BUNDLED_NAME.to_owned()
    };
    resource_dir.join(BUNDLED_DIR).join(name)
}

/// The interpreter inside `<repo>/sidecar/.venv`, given the Tauri crate's manifest directory
/// (`<repo>/app/src-tauri`).
pub fn dev_venv_python(manifest_dir: &Path, windows: bool) -> PathBuf {
    let repo = manifest_dir.join("..").join("..");
    let venv = repo.join("sidecar").join(".venv");
    if windows {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

/// Resolves the sidecar command, in order: the `OPENLOCATE_SIDECAR_PYTHON` override, the
/// development virtualenv (debug builds), then the standalone helper shipped with the app.
/// `exists` is used to report a missing virtualenv or helper clearly.
pub fn resolve_command(
    inputs: &ResolveInputs,
    exists: impl Fn(&Path) -> bool,
) -> Result<SidecarCommand, UiError> {
    let (program, standalone) = resolve_program(inputs, exists)?;
    // A Python interpreter is told which module to run; the standalone helper is the module.
    let mut args = if standalone {
        Vec::new()
    } else {
        vec!["-m".to_owned(), "openlocate".to_owned()]
    };
    if let Some(backend) = parse_backend(inputs.backend.as_ref())? {
        args.push("--backend".to_owned());
        args.push(backend);
    }
    Ok(SidecarCommand {
        program,
        args,
        // Unbuffered so replies are not held back; UTF-8 mode because the protocol is UTF-8
        // and Python on Windows otherwise uses the locale code page for pipes.
        env: vec![
            ("PYTHONUNBUFFERED".to_owned(), "1".to_owned()),
            ("PYTHONUTF8".to_owned(), "1".to_owned()),
        ],
    })
}

/// The program to run, and whether it is the standalone helper (true) or a Python
/// interpreter (false).
fn resolve_program(
    inputs: &ResolveInputs,
    exists: impl Fn(&Path) -> bool,
) -> Result<(PathBuf, bool), UiError> {
    if let Some(python) = inputs.python_override.as_ref().filter(|p| !p.is_empty()) {
        return Ok((PathBuf::from(python), false));
    }
    let Some(dev_python) = inputs.dev_python.as_ref() else {
        return match inputs.bundled.as_ref() {
            Some(bundled) if exists(bundled) => Ok((bundled.clone(), true)),
            missing => Err(UiError::new(
                "SIDECAR_NOT_BUNDLED",
                "A part of OpenLocate is missing: the bundled sidecar was not found.",
                "Install OpenLocate again from the original download. If an antivirus program \
                 removed the file, restore it or allow OpenLocate, then install again.",
                missing.map(|path| path.display().to_string()),
            )),
        };
    };
    if !exists(dev_python) {
        return Err(UiError::new(
            "SIDECAR_VENV_MISSING",
            "The sidecar's development virtualenv was not found.",
            &format!(
                "Create it as described in sidecar/README.md, or set {PYTHON_ENV} to a Python \
                 interpreter that has the openlocate package installed. Then press Restart."
            ),
            Some(dev_python.display().to_string()),
        ));
    }
    Ok((dev_python.clone(), false))
}

/// Accepts short lowercase names such as `mock` or `ios`; the sidecar validates the value
/// itself, this only keeps junk out of the command line. Empty means "not set".
fn parse_backend(raw: Option<&OsString>) -> Result<Option<String>, UiError> {
    let Some(raw) = raw.filter(|value| !value.is_empty()) else {
        return Ok(None);
    };
    let valid = raw.to_str().filter(|value| {
        value.len() <= MAX_BACKEND_LEN
            && value
                .chars()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
    });
    match valid {
        Some(value) => Ok(Some(value.to_owned())),
        None => Err(UiError::new(
            "INVALID_CONFIG",
            &format!("{BACKEND_ENV} has an invalid value."),
            &format!("Set {BACKEND_ENV} to a backend name such as `mock`, or unset it."),
            Some(raw.to_string_lossy().into_owned()),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn venv() -> PathBuf {
        dev_venv_python(
            Path::new("repo").join("app").join("src-tauri").as_path(),
            false,
        )
    }

    #[test]
    fn dev_venv_path_per_os() {
        let manifest = Path::new("r").join("app").join("src-tauri");
        let unix = dev_venv_python(&manifest, false);
        let windows = dev_venv_python(&manifest, true);
        let tail = |p: &Path| {
            p.components()
                .rev()
                .take(4)
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect::<Vec<_>>()
        };
        assert_eq!(tail(&unix), ["python", "bin", ".venv", "sidecar"]);
        assert_eq!(
            tail(&windows),
            ["python.exe", "Scripts", ".venv", "sidecar"]
        );
        assert!(unix.starts_with(manifest.join("..").join("..")));
    }

    #[test]
    fn override_wins_and_is_not_checked_for_existence() {
        let inputs = ResolveInputs {
            python_override: Some("/opt/py/python3".into()),
            backend: None,
            dev_python: Some(venv()),
            bundled: None,
        };
        let command = resolve_command(&inputs, |_| false).unwrap();
        assert_eq!(command.program, PathBuf::from("/opt/py/python3"));
        assert_eq!(command.args, ["-m", "openlocate"]);
    }

    #[test]
    fn empty_override_is_ignored() {
        let inputs = ResolveInputs {
            python_override: Some(OsString::new()),
            backend: None,
            dev_python: Some(venv()),
            bundled: None,
        };
        assert_eq!(resolve_command(&inputs, |_| true).unwrap().program, venv());
    }

    #[test]
    fn debug_build_uses_the_venv() {
        let inputs = ResolveInputs {
            dev_python: Some(venv()),
            ..ResolveInputs::default()
        };
        let command = resolve_command(&inputs, |p| p == venv()).unwrap();
        assert_eq!(command.program, venv());
        assert!(command
            .env
            .contains(&("PYTHONUTF8".to_owned(), "1".to_owned())));
    }

    #[test]
    fn missing_venv_is_a_clear_error() {
        let inputs = ResolveInputs {
            dev_python: Some(venv()),
            ..ResolveInputs::default()
        };
        let err = resolve_command(&inputs, |_| false).unwrap_err();
        assert_eq!(err.code, "SIDECAR_VENV_MISSING");
        assert!(err.fix.contains(PYTHON_ENV));
        assert_eq!(err.detail, Some(venv().display().to_string()));
    }

    #[test]
    fn release_build_runs_the_bundled_helper_directly() {
        let bundled = bundled_sidecar(Path::new("res"), true);
        assert!(bundled.ends_with(Path::new("sidecar").join("openlocate-sidecar.exe")));
        assert!(bundled_sidecar(Path::new("res"), false).ends_with("openlocate-sidecar"));
        let inputs = ResolveInputs {
            bundled: Some(bundled.clone()),
            backend: Some("mock".into()),
            ..ResolveInputs::default()
        };
        let command = resolve_command(&inputs, |p| p == bundled).unwrap();
        assert_eq!(command.program, bundled);
        assert_eq!(command.args, ["--backend", "mock"]);
    }

    #[test]
    fn release_build_without_the_helper_says_to_reinstall() {
        let err = resolve_command(&ResolveInputs::default(), |_| true).unwrap_err();
        assert_eq!(err.code, "SIDECAR_NOT_BUNDLED");
        assert!(err.message.contains("bundled sidecar"));
        assert_eq!(err.detail, None);

        let inputs = ResolveInputs {
            bundled: Some(PathBuf::from("res/sidecar/openlocate-sidecar")),
            ..ResolveInputs::default()
        };
        let err = resolve_command(&inputs, |_| false).unwrap_err();
        assert_eq!(err.code, "SIDECAR_NOT_BUNDLED");
        assert!(err.fix.contains("Install OpenLocate again"));
        assert!(err.detail.is_some_and(|d| d.contains("openlocate-sidecar")));
    }

    #[test]
    fn debug_build_prefers_the_venv_over_the_bundled_helper() {
        let inputs = ResolveInputs {
            dev_python: Some(venv()),
            bundled: Some(PathBuf::from("res/sidecar/openlocate-sidecar")),
            ..ResolveInputs::default()
        };
        let command = resolve_command(&inputs, |_| true).unwrap();
        assert_eq!(command.program, venv());
        assert_eq!(command.args, ["-m", "openlocate"]);
    }

    #[test]
    fn backend_is_appended() {
        let inputs = ResolveInputs {
            python_override: Some("python".into()),
            backend: Some("mock".into()),
            dev_python: None,
            bundled: None,
        };
        let command = resolve_command(&inputs, |_| true).unwrap();
        assert_eq!(command.args, ["-m", "openlocate", "--backend", "mock"]);
    }

    #[test]
    fn empty_backend_is_ignored_and_junk_is_rejected() {
        let mut inputs = ResolveInputs {
            python_override: Some("python".into()),
            backend: Some(OsString::new()),
            dev_python: None,
            bundled: None,
        };
        assert_eq!(resolve_command(&inputs, |_| true).unwrap().args.len(), 2);
        for junk in [
            "Mock",
            "mock --log-dir /tmp",
            "a;b",
            &"x".repeat(MAX_BACKEND_LEN + 1),
        ] {
            inputs.backend = Some(junk.into());
            let err = resolve_command(&inputs, |_| true).unwrap_err();
            assert_eq!(err.code, "INVALID_CONFIG", "{junk:?}");
        }
    }
}
