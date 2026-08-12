use std::ffi::OsString;
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Mutex, mpsc};
use std::thread;
use std::time::{Duration, Instant};

use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use rand::TryRngCore;
use rand::rngs::OsRng;
use serde::Serialize;
use thiserror::Error;

use crate::handshake::{HandshakeError, ReadyMessage};

const READY_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(6);

#[derive(Debug, Error)]
pub enum RuntimeError {
    #[error("failed to prepare local runtime storage: {0}")]
    PrepareStorage(#[source] std::io::Error),
    #[error("failed to generate the local session token")]
    GenerateToken,
    #[error("failed to start the local runtime: {0}")]
    Spawn(#[source] std::io::Error),
    #[error("local runtime stdout was not available")]
    MissingStdout,
    #[error("local runtime did not become ready within 30 seconds")]
    ReadyTimeout,
    #[error("local runtime closed stdout before sending its ready message")]
    ReadyChannelClosed,
    #[error("failed to read the local runtime ready message: {0}")]
    ReadReady(String),
    #[error("invalid local runtime ready message: {0}")]
    InvalidReady(#[from] HandshakeError),
    #[error("local runtime state lock is unavailable")]
    StateLock,
    #[error("local runtime is not online")]
    NotOnline,
}

#[derive(Clone, Debug, Serialize)]
pub struct RuntimeConnection {
    pub base_url: String,
    pub protocol_version: u16,
    pub session_token: String,
}

#[derive(Clone, Debug)]
enum RuntimeStatus {
    Starting,
    Online(RuntimeConnection),
    Offline,
}

#[derive(Debug)]
struct RuntimeInner {
    status: RuntimeStatus,
    child: Option<Child>,
}

#[derive(Debug)]
pub struct RuntimeManager {
    inner: Mutex<RuntimeInner>,
    project_root: PathBuf,
    state_dir: PathBuf,
}

impl RuntimeManager {
    pub fn new() -> Self {
        let project_root = project_root();
        Self {
            inner: Mutex::new(RuntimeInner {
                status: RuntimeStatus::Starting,
                child: None,
            }),
            state_dir: project_root.join(".astraquant"),
            project_root,
        }
    }

    pub fn start(&self) -> Result<RuntimeConnection, RuntimeError> {
        let mut inner = self.inner.lock().map_err(|_| RuntimeError::StateLock)?;
        inner.status = RuntimeStatus::Starting;

        match self.launch() {
            Ok((child, connection)) => {
                inner.child = Some(child);
                inner.status = RuntimeStatus::Online(connection.clone());
                Ok(connection)
            }
            Err(error) => {
                inner.child = None;
                inner.status = RuntimeStatus::Offline;
                Err(error)
            }
        }
    }

    pub fn connection(&self) -> Result<RuntimeConnection, RuntimeError> {
        let inner = self.inner.lock().map_err(|_| RuntimeError::StateLock)?;
        match &inner.status {
            RuntimeStatus::Online(connection) => Ok(connection.clone()),
            RuntimeStatus::Starting | RuntimeStatus::Offline => Err(RuntimeError::NotOnline),
        }
    }

    pub fn log_dir(&self) -> PathBuf {
        self.state_dir.join("logs")
    }

    pub fn shutdown(&self) {
        let Ok(mut inner) = self.inner.lock() else {
            return;
        };
        let Some(mut child) = inner.child.take() else {
            inner.status = RuntimeStatus::Offline;
            return;
        };

        if let RuntimeStatus::Online(connection) = &inner.status {
            let _ = reqwest::blocking::Client::builder()
                .no_proxy()
                .timeout(Duration::from_secs(2))
                .build()
                .and_then(|client| {
                    client
                        .post(format!("{}/internal/shutdown", connection.base_url))
                        .bearer_auth(&connection.session_token)
                        .send()
                });
        }

        let deadline = Instant::now() + SHUTDOWN_TIMEOUT;
        while Instant::now() < deadline {
            match child.try_wait() {
                Ok(Some(_)) => {
                    inner.status = RuntimeStatus::Offline;
                    return;
                }
                Ok(None) => thread::sleep(Duration::from_millis(50)),
                Err(_) => break,
            }
        }
        let _ = child.kill();
        let _ = child.wait();
        inner.status = RuntimeStatus::Offline;
    }

    fn launch(&self) -> Result<(Child, RuntimeConnection), RuntimeError> {
        let log_dir = self.log_dir();
        fs::create_dir_all(&log_dir).map_err(RuntimeError::PrepareStorage)?;
        let session_token = generate_session_token()?;
        let mut command = runtime_command(&self.project_root);
        let mut child = command
            .current_dir(&self.project_root)
            .env("ASTRAQUANT_SESSION_TOKEN", &session_token)
            .env("ASTRAQUANT_STATE_DIR", &self.state_dir)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(RuntimeError::Spawn)?;
        let pid = child.id();

        if let Some(stderr) = child.stderr.take() {
            let log_path = log_dir.join("desktop-runtime.stderr.log");
            thread::spawn(move || {
                let Ok(mut log_file) = OpenOptions::new().create(true).append(true).open(log_path)
                else {
                    return;
                };
                let mut reader = BufReader::new(stderr);
                let _ = std::io::copy(&mut reader, &mut log_file);
            });
        }

        let stdout = match child.stdout.take() {
            Some(stdout) => stdout,
            None => {
                stop_child(&mut child);
                return Err(RuntimeError::MissingStdout);
            }
        };
        let (sender, receiver) = mpsc::sync_channel(1);
        thread::spawn(move || {
            let result = BufReader::new(stdout)
                .lines()
                .next()
                .ok_or(RuntimeError::ReadyChannelClosed)
                .and_then(|line| line.map_err(|error| RuntimeError::ReadReady(error.to_string())));
            let _ = sender.send(result);
        });

        let ready_line = match receiver.recv_timeout(READY_TIMEOUT) {
            Ok(Ok(line)) => line,
            Ok(Err(error)) => {
                stop_child(&mut child);
                return Err(error);
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {
                stop_child(&mut child);
                return Err(RuntimeError::ReadyTimeout);
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                stop_child(&mut child);
                return Err(RuntimeError::ReadyChannelClosed);
            }
        };
        let ready = match ReadyMessage::parse_and_validate(&ready_line, pid) {
            Ok(ready) => ready,
            Err(error) => {
                stop_child(&mut child);
                return Err(RuntimeError::InvalidReady(error));
            }
        };
        let connection = RuntimeConnection {
            base_url: ready.base_url(),
            protocol_version: ready.protocol_version,
            session_token,
        };
        Ok((child, connection))
    }
}

impl Default for RuntimeManager {
    fn default() -> Self {
        Self::new()
    }
}

fn project_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("src-tauri must live under apps/desktop")
        .to_path_buf()
}

fn workspace_python_source_paths(project_root: &Path) -> Vec<PathBuf> {
    let Ok(entries) = fs::read_dir(project_root.join("packages")) else {
        return Vec::new();
    };
    let mut paths = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path().join("src"))
        .filter(|path| path.is_dir())
        .collect::<Vec<_>>();
    paths.sort();
    paths.dedup();
    paths
}

struct RuntimeLaunchSpec {
    program: PathBuf,
    arguments: Vec<String>,
    environment: Vec<(String, OsString)>,
}

fn runtime_launch_spec(project_root: &Path) -> RuntimeLaunchSpec {
    if let Some(executable) = std::env::var_os("ASTRAQUANT_API_EXECUTABLE") {
        return RuntimeLaunchSpec {
            program: PathBuf::from(executable),
            arguments: vec!["serve".into()],
            environment: Vec::new(),
        };
    }

    let virtual_environment = project_root.join(".venv");
    let managed_python = if cfg!(windows) {
        windows_base_python(&virtual_environment)
    } else {
        Some(project_root.join(".venv").join("bin").join("python"))
    };
    if let Some(managed_python) = managed_python.filter(|path| path.is_file()) {
        let mut environment = Vec::new();
        if cfg!(windows) {
            let mut search_paths = vec![virtual_environment.join("Lib").join("site-packages")];
            search_paths.extend(workspace_python_source_paths(project_root));
            if let Ok(python_path) = std::env::join_paths(search_paths) {
                environment.push(("PYTHONPATH".into(), python_path));
            }
            environment.push((
                "VIRTUAL_ENV".into(),
                virtual_environment.as_os_str().to_owned(),
            ));
            environment.push(("PYTHONNOUSERSITE".into(), "1".into()));
        }
        return RuntimeLaunchSpec {
            program: managed_python,
            arguments: vec!["-m".into(), "astraquant_api.cli".into(), "serve".into()],
            environment,
        };
    }

    RuntimeLaunchSpec {
        program: PathBuf::from(
            std::env::var_os("ASTRAQUANT_UV_EXECUTABLE").unwrap_or_else(|| "uv".into()),
        ),
        arguments: vec![
            "run".into(),
            "python".into(),
            "-m".into(),
            "astraquant_api.cli".into(),
            "serve".into(),
        ],
        environment: Vec::new(),
    }
}

fn runtime_command(project_root: &Path) -> Command {
    let spec = runtime_launch_spec(project_root);
    let mut command = Command::new(spec.program);
    command.args(spec.arguments);
    command.envs(spec.environment);
    command
}

fn windows_base_python(virtual_environment: &Path) -> Option<PathBuf> {
    let configuration = fs::read_to_string(virtual_environment.join("pyvenv.cfg")).ok()?;
    let home = configuration.lines().find_map(|line| {
        let (key, value) = line.split_once('=')?;
        (key.trim() == "home").then(|| value.trim())
    })?;
    Some(PathBuf::from(home).join("python.exe"))
}

fn generate_session_token() -> Result<String, RuntimeError> {
    let mut bytes = [0_u8; 32];
    OsRng
        .try_fill_bytes(&mut bytes)
        .map_err(|_| RuntimeError::GenerateToken)?;
    Ok(URL_SAFE_NO_PAD.encode(bytes))
}

fn stop_child(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::TempDir;

    use super::{generate_session_token, runtime_launch_spec, workspace_python_source_paths};

    fn managed_project_root() -> TempDir {
        let project_root = tempfile::tempdir().expect("temporary project root must be created");
        let virtual_environment = project_root.path().join(".venv");

        if cfg!(windows) {
            let python_home = project_root.path().join("python-home");
            fs::create_dir_all(&python_home).expect("fake Python home must be created");
            fs::write(python_home.join("python.exe"), b"")
                .expect("fake Windows Python executable must be created");
            fs::create_dir_all(&virtual_environment)
                .expect("fake virtual environment must be created");
            fs::write(
                virtual_environment.join("pyvenv.cfg"),
                format!("home = {}\n", python_home.display()),
            )
            .expect("fake pyvenv.cfg must be created");
        } else {
            let executable = virtual_environment.join("bin").join("python");
            fs::create_dir_all(executable.parent().expect("executable must have a parent"))
                .expect("fake virtual environment must be created");
            fs::write(executable, b"").expect("fake Python executable must be created");
        }

        project_root
    }

    #[test]
    fn generates_a_url_safe_256_bit_session_token() {
        let token = generate_session_token().unwrap();
        assert_eq!(token.len(), 43);
        assert!(
            token
                .chars()
                .all(|character| character.is_ascii_alphanumeric()
                    || character == '-'
                    || character == '_')
        );
    }

    #[test]
    fn launches_the_managed_python_process_directly() {
        let project_root = managed_project_root();
        let spec = runtime_launch_spec(project_root.path());
        assert!(spec.program.ends_with(if cfg!(windows) {
            "python.exe"
        } else {
            "python"
        }));
        assert_eq!(spec.arguments, ["-m", "astraquant_api.cli", "serve"]);
    }

    #[test]
    fn windows_runtime_exposes_every_workspace_python_package() {
        if !cfg!(windows) {
            return;
        }
        let project_root = managed_project_root();
        for package in ["api", "data", "domain", "paper", "quant"] {
            fs::create_dir_all(
                project_root
                    .path()
                    .join("packages")
                    .join(package)
                    .join("src"),
            )
            .expect("workspace package source must be created");
        }
        let spec = runtime_launch_spec(project_root.path());
        let python_path = spec
            .environment
            .iter()
            .find(|(name, _)| name == "PYTHONPATH")
            .map(|(_, value)| value.to_string_lossy())
            .expect("Windows managed runtime must define PYTHONPATH");

        assert!(python_path.contains("packages\\api\\src"));
        assert!(python_path.contains("packages\\data\\src"));
        assert!(python_path.contains("packages\\domain\\src"));
        assert!(python_path.contains("packages\\paper\\src"));
        assert!(python_path.contains("packages\\quant\\src"));
    }

    #[test]
    fn windows_runtime_discovers_new_workspace_python_packages() {
        let project_root = tempfile::tempdir().expect("temporary project root must be created");
        for package in ["api", "execution", "research"] {
            fs::create_dir_all(
                project_root
                    .path()
                    .join("packages")
                    .join(package)
                    .join("src"),
            )
            .expect("workspace package source must be created");
        }
        fs::create_dir_all(project_root.path().join("packages").join("without-src"))
            .expect("non-package directory must be created");

        let paths = workspace_python_source_paths(project_root.path());

        assert_eq!(
            paths,
            ["api", "execution", "research"].map(|package| project_root
                .path()
                .join("packages")
                .join(package)
                .join("src"))
        );
    }
}
