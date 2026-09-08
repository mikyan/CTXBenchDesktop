use crate::process_stream::{self, BuildProgress};
use crate::wsl;
use regex::Regex;
use serde::Serialize;
use serde_json::Value;
use std::path::Path;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

pub(crate) static MUTATION: Mutex<()> = Mutex::new(());

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ActionResult {
    pub ok: bool,
    pub code: String,
    pub detail: String,
    pub command: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct SetupCheck {
    pub id: &'static str,
    pub ok: bool,
    pub detail: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DeploymentInfo {
    pub distribution: String,
    pub compose_path: String,
    pub wsl_compose_path: Option<String>,
    pub data_directory: Option<String>,
    pub checks: Vec<SetupCheck>,
    pub missing_images: Vec<String>,
    pub containers: Vec<String>,
    pub active_containers: Vec<ActiveContainer>,
    pub activity_error: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ActiveContainer {
    pub id: String,
    pub name: String,
    pub status: String,
    pub role: &'static str,
}

// Query only running containers and explicitly selected fields, never Env, commands or arbitrary labels.
const ACTIVITY_FILTERS: [(&str, &str); 3] = [
    ("io.ctxbench.run", "agent"),
    ("io.ctxbench.evaluator", "grader"),
    ("com.docker.compose.service=ctxbench-worker", "worker"),
];

fn read_activity(
    mut run: impl FnMut(&[&str]) -> Result<String, String>,
    secrets: &[String],
) -> Result<Vec<ActiveContainer>, String> {
    let mut containers = Vec::<ActiveContainer>::new();
    for (filter, role) in ACTIVITY_FILTERS {
        let text = run(&[
            "docker",
            "ps",
            "--filter",
            &format!("label={filter}"),
            "--format",
            r#"{"id":{{json .ID}},"name":{{json .Names}},"status":{{json .Status}}}"#,
        ])?;
        for line in text.lines().filter(|line| !line.trim().is_empty()) {
            let row: Value = serde_json::from_str(line)
                .map_err(|_| "Docker returned invalid container activity JSON.".to_string())?;
            let field = |key: &str| {
                row[key]
                    .as_str()
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| {
                        "Docker returned incomplete container activity JSON.".to_string()
                    })
            };
            let id = field("id")?;
            if !containers.iter().any(|item| item.id == id) {
                containers.push(ActiveContainer {
                    id: id.into(),
                    name: redact(field("name")?, secrets),
                    status: redact(field("status")?, secrets),
                    role,
                });
            }
        }
    }
    Ok(containers)
}

fn activity_guard(
    action: &str,
    run: impl FnMut(&[&str]) -> Result<String, String>,
    secrets: &[String],
) -> Result<(), ActionResult> {
    let containers = read_activity(run, secrets).map_err(|detail| ActionResult {
        ok: false,
        code: classify_error(&detail, "activity_unknown"),
        detail: redact(&detail, secrets),
        command: None,
    })?;
    let blockers: Vec<_> = containers
        .iter()
        .filter(|item| matches!(action, "import" | "build") || item.role != "worker")
        .collect();
    if blockers.is_empty() {
        return Ok(());
    }
    Err(ActionResult {
        ok: false,
        code: if blockers.iter().any(|item| item.role != "worker") {
            "active_runs"
        } else {
            "worker_running"
        }
        .into(),
        detail: blockers
            .iter()
            .map(|item| {
                format!(
                    "{} · {} · {} · {}",
                    item.id, item.name, item.role, item.status
                )
            })
            .collect::<Vec<_>>()
            .join("\n"),
        command: None,
    })
}

pub fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}

pub fn compose_args(path: &str, action: &str) -> Result<Vec<String>, String> {
    let tail: &[&str] = match action {
        // Starting must never unexpectedly build images or require the Internet.
        "start" => &[
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "ctxbench-worker",
        ],
        "stop" => &["stop", "ctxbench-worker"],
        "build" => &["--progress", "plain", "--profile", "build-only", "build"],
        "logs" => &[
            "logs",
            "--no-color",
            "--tail",
            "80",
            "ctxbench-worker",
            "ctxbench-egress-proxy",
        ],
        _ => return Err("Unsupported infrastructure action.".into()),
    };
    Ok([
        vec!["docker".into(), "compose".into(), "-f".into(), path.into()],
        tail.iter().map(|item| item.to_string()).collect(),
    ]
    .concat())
}

pub fn classify_error(detail: &str, fallback: &str) -> String {
    let value = detail.to_lowercase();
    let code = if value.contains("permission denied")
        || value.contains("access is denied")
        || value.contains("权限")
    {
        "permission"
    } else if value.contains("address already in use")
        || value.contains("port is already allocated")
        || value.contains("ports are not available")
    {
        "port_in_use"
    } else if value.contains("bind source path does not exist")
        || value.contains("invalid mount config")
        || value.contains("mounts denied")
    {
        "data_directory"
    } else if value.contains("no such image")
        || value.contains("pull access denied")
        || value.contains("pull policy")
        || value.contains("image is required")
    {
        "images"
    } else if value.contains("cannot connect to the docker daemon")
        || value.contains("is the docker daemon running")
    {
        "docker"
    } else if value.contains("no space left") || value.contains("not enough space") {
        "disk_space"
    } else if value.contains("no such host")
        || value.contains("certificate")
        || value.contains("network is unreachable")
        || value.contains("connection refused")
        || ((value.contains("registry")
            || value.contains("load metadata")
            || value.contains("failed to fetch"))
            && (value.contains("deadline exceeded")
                || value.contains("timeout")
                || value.contains("timed out")))
    {
        "network"
    } else if value.contains("timed out")
        || value.contains("timeout")
        || value.contains("deadline exceeded")
    {
        "timeout"
    } else {
        fallback
    };
    code.into()
}

// Docker/build logs can contain provider credentials or authenticated registry URLs.
// Redact before returning to the WebView or copy/export UI; never serialize config Env.
pub fn redact(detail: &str, secrets: &[String]) -> String {
    static ANSI: OnceLock<Regex> = OnceLock::new();
    let mut clean = ANSI
        .get_or_init(|| Regex::new(r"\x1b\[[0-9;]*[a-zA-Z]").unwrap())
        .replace_all(detail, "")
        .into_owned();
    let mut secrets = secrets.to_vec();
    secrets.sort_by_key(|value| std::cmp::Reverse(value.len()));
    for secret in secrets.iter().filter(|value| !value.is_empty()) {
        clean = clean.replace(secret, "[REDACTED]");
    }
    static RULES: OnceLock<Vec<(Regex, &'static str)>> = OnceLock::new();
    for (pattern, replacement) in RULES.get_or_init(|| [
        (r"(?i)(https?://)[^\s/@]+(?::[^\s/@]*)?@", "${1}[REDACTED]@"),
        (
            r"(?i)([?&](?:api[_-]?key|token|secret|password|access_token)=)[^&\s]+",
            "${1}[REDACTED]",
        ),
        (
            r#"(?im)((?:^|[\s{,])["'$]?[\w.-]*(?:api[_-]?key|token|secret|password|passwd|authorization|credential)[\w.-]*["']?\s*[:=]\s*)[^\r\n]+"#,
            "${1}[REDACTED]",
        ),
        (r"(?i)(bearer\s+)[a-z0-9._~+/-]+=*", "${1}[REDACTED]"),
        (
            r"\b(?:sk-[A-Za-z0-9_-]{8,}|tp-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,})\b",
            "[REDACTED]",
        ),
    ].into_iter().map(|(pattern, replacement)| (Regex::new(pattern).expect("static redaction expression"), replacement)).collect()) {
        clean = pattern.replace_all(&clean, *replacement)
            .into_owned();
    }
    let limit = 24_000;
    if clean.chars().count() > limit {
        clean = clean.chars().take(limit).collect::<String>() + "\n[Output truncated]";
    }
    clean
}

pub(crate) fn secret_values(root: &Path) -> Vec<String> {
    let sensitive = |key: &str| {
        let key = key.to_ascii_uppercase();
        [
            "KEY",
            "TOKEN",
            "SECRET",
            "PASSWORD",
            "PASSWD",
            "CREDENTIAL",
            "AUTH",
        ]
        .iter()
        .any(|part| key.contains(part))
    };
    let mut values: Vec<_> = std::env::vars()
        .filter(|(key, _)| sensitive(key))
        .map(|(_, value)| value)
        .collect();
    // Only the deployment's dotenv files; no browsing of unrelated credential stores.
    for path in [root.join(".env"), root.join("docker/.env")] {
        if let Ok(text) = std::fs::read_to_string(path) {
            for line in text
                .lines()
                .filter(|line| !line.trim_start().starts_with('#'))
            {
                if let Some((key, value)) = line.split_once('=') {
                    if sensitive(key) {
                        values.push(value.trim().trim_matches(['\'', '"']).to_string());
                    }
                }
            }
        }
    }
    values
}

fn checked_path(root: &Path, distribution: &str) -> Result<String, ActionResult> {
    let path = root.join("docker/compose.yaml");
    let fail = |code: &str, detail: String| ActionResult {
        ok: false,
        code: code.into(),
        detail: redact(&detail, &secret_values(root)),
        command: None,
    };
    if !path.is_file() {
        return Err(fail("compose_file", path.display().to_string()));
    }
    let translated = wsl::output(
        distribution,
        &["wslpath", "-a", &path.display().to_string()],
    )
    .map_err(|error| fail("wsl_path", error))?;
    if !translated.starts_with('/') || translated.contains(['\n', '\r']) {
        return Err(fail("wsl_path", translated));
    }
    wsl::output(distribution, &["test", "-f", &translated])
        .map_err(|error| fail("wsl_path", format!("{translated}\n{error}")))?;
    Ok(translated)
}

pub fn inspect(root: &Path, distribution: &str) -> DeploymentInfo {
    let secrets = secret_values(root);
    let mut info = DeploymentInfo {
        distribution: distribution.into(),
        compose_path: root.join("docker/compose.yaml").display().to_string(),
        wsl_compose_path: None,
        data_directory: None,
        checks: vec![],
        missing_images: vec![],
        containers: vec![],
        active_containers: vec![],
        activity_error: Some("Container activity has not been checked.".into()),
    };
    let path = match checked_path(root, distribution) {
        Ok(path) => path,
        Err(failure) => {
            info.checks.push(SetupCheck {
                id: if failure.code == "wsl_path" {
                    "wsl_path"
                } else {
                    "compose_file"
                },
                ok: false,
                detail: failure.detail,
            });
            return info;
        }
    };
    info.wsl_compose_path = Some(path.clone());
    info.checks.push(SetupCheck {
        id: "compose_file",
        ok: true,
        detail: path.clone(),
    });
    let version = wsl::output(distribution, &["docker", "compose", "version", "--short"]);
    info.checks.push(SetupCheck {
        id: "compose",
        ok: version.is_ok(),
        detail: redact(version.as_ref().unwrap_or_else(|error| error), &secrets),
    });
    if version.is_err() {
        return info;
    }
    if let Err(error) = wsl::output(
        distribution,
        &["docker", "version", "--format", "{{.Server.Version}}"],
    ) {
        info.checks.push(SetupCheck {
            id: "docker",
            ok: false,
            detail: redact(&error, &secrets),
        });
        return info;
    }
    match read_activity(|args| wsl::output(distribution, args), &secrets) {
        Ok(containers) => {
            info.active_containers = containers;
            info.activity_error = None;
        }
        Err(error) => info.activity_error = Some(redact(&error, &secrets)),
    }
    // Full config stays in memory. Only image names and the data mount escape this function.
    let config = wsl::output(
        distribution,
        &[
            "docker",
            "compose",
            "-f",
            &path,
            "--profile",
            "build-only",
            "config",
            "--format",
            "json",
        ],
    )
    .and_then(|text| {
        serde_json::from_str::<Value>(&text)
            .map_err(|_| "Docker Compose returned invalid configuration JSON.".to_string())
    });
    let config = match config {
        Ok(config) => config,
        Err(error) => {
            info.checks.push(SetupCheck {
                id: "compose_config",
                ok: false,
                detail: redact(&error, &secrets),
            });
            return info;
        }
    };
    for role in [
        "ctxbench-worker",
        "ctxbench-egress-proxy",
        "agent-pi-image",
        "official-harness-image",
    ] {
        if let Some(image) = config["services"][role]["image"].as_str() {
            if wsl::output(
                distribution,
                &["docker", "image", "inspect", image, "--format", "{{.Id}}"],
            )
            .is_err()
            {
                info.missing_images.push(redact(image, &secrets));
            }
        } else {
            info.missing_images.push(role.into());
        }
    }
    info.checks.push(SetupCheck {
        id: "images",
        ok: info.missing_images.is_empty(),
        detail: info.missing_images.join("\n"),
    });
    if let Some(volumes) = config["services"]["ctxbench-worker"]["volumes"].as_array() {
        if let Some(source) = volumes
            .iter()
            .find(|item| item["target"] == "/var/lib/ctxbench")
            .and_then(|item| item["source"].as_str())
        {
            info.data_directory = Some(source.into());
            info.checks.push(SetupCheck {
                id: "data_directory",
                ok: wsl::output(distribution, &["test", "-d", source]).is_ok(),
                detail: source.into(),
            });
        }
    }
    let states = wsl::output(
        distribution,
        &[
            "docker", "compose", "-f", &path, "ps", "-a", "--format", "json",
        ],
    );
    if let Ok(states) = states {
        // Compose versions emit either a JSON array or JSON Lines.
        let rows = serde_json::from_str::<Vec<Value>>(&states).unwrap_or_else(|_| {
            states
                .lines()
                .filter_map(|line| serde_json::from_str::<Value>(line).ok())
                .collect()
        });
        info.containers = rows
            .iter()
            .map(|row| {
                redact(
                    &format!(
                        "{} · {} · {}",
                        row["Service"].as_str().unwrap_or("?"),
                        row["State"].as_str().unwrap_or("?"),
                        row["Status"].as_str().unwrap_or("?")
                    ),
                    &secrets,
                )
            })
            .collect();
    }
    info
}

pub fn control(
    root: &Path,
    distribution: &str,
    action: &str,
    mut progress: impl FnMut(BuildProgress),
) -> ActionResult {
    // Validate the operation before any process can be launched.
    if let Err(detail) = compose_args("", action) {
        return ActionResult {
            ok: false,
            code: "action".into(),
            detail,
            command: None,
        };
    }
    let _guard = if action == "logs" {
        None
    } else {
        match MUTATION.try_lock() {
            Ok(guard) => Some(guard),
            Err(_) => {
                return ActionResult {
                    ok: false,
                    code: "busy".into(),
                    detail: "Another infrastructure action is still running.".into(),
                    command: None,
                };
            }
        }
    };
    let started = Instant::now();
    if action == "build" {
        progress(BuildProgress {
            phase: "checking",
            lines: vec![],
            elapsed_ms: 0,
            last_output_ms: None,
        });
    }
    let path = match checked_path(root, distribution) {
        Ok(path) => path,
        Err(error) => return error,
    };
    let args = compose_args(&path, action).unwrap();
    let command = args
        .iter()
        .map(|value| shell_quote(value))
        .collect::<Vec<_>>()
        .join(" ");
    let secrets = secret_values(root);
    if let Err(error) = wsl::output(distribution, &["docker", "compose", "version", "--short"]) {
        return ActionResult {
            ok: false,
            code: classify_error(&error, "compose"),
            detail: redact(&error, &secrets),
            command: Some(command),
        };
    }
    if action != "logs" {
        if let Err(result) =
            activity_guard(action, |args| wsl::output(distribution, args), &secrets)
        {
            return result;
        }
    }
    let args: Vec<&str> = args.iter().map(String::as_str).collect();
    let timeout = Duration::from_secs(if action == "build" { 3600 } else { 120 });
    let output = if action == "build" {
        let mut process = std::process::Command::new("wsl.exe");
        process
            .args(["--distribution", distribution, "--exec"])
            .args(&args);
        process_stream::run(
            &mut process,
            timeout,
            started,
            |line| redact(line, &secrets),
            &mut progress,
        )
    } else {
        wsl::output_with_timeout(distribution, &args, timeout)
    };
    match output {
        Ok(output) => ActionResult {
            ok: true,
            code: action.into(),
            detail: redact(&output, &secrets),
            command: Some(command),
        },
        Err(error) => ActionResult {
            ok: false,
            code: classify_error(&error, "action"),
            detail: redact(&error, &secrets),
            command: Some(command),
        },
    }
}

pub fn offline_import_args(tool: &str, package: &str, version: &str) -> Vec<String> {
    [
        "python3",
        "-I",
        "-u",
        tool,
        "import",
        package,
        "--expected-version",
        version,
        "--progress-json",
        "--require-stopped",
    ]
    .iter()
    .map(|value| value.to_string())
    .collect()
}

fn offline_error_code(detail: &str) -> String {
    // Helper errors share a "bundle" prefix; preserve actionable OS/Docker failures.
    let infrastructure = classify_error(detail, "action");
    if detail.contains("Version mismatch") {
        "bundle_version".into()
    } else if detail.contains("Active CTXBench containers") {
        "worker_running".into()
    } else if detail.contains("Linux amd64 Docker daemon") {
        "offline_platform".into()
    } else if infrastructure != "action" {
        infrastructure
    } else if [
        "ZIP",
        "checksum",
        "SHA-256",
        "bundle",
        "Bundle",
        "manifest",
        "Manifest",
        "archive part",
    ]
    .iter()
    .any(|part| detail.contains(part))
    {
        "bundle_invalid".into()
    } else {
        classify_error(detail, "action")
    }
}

pub fn import_images(
    root: &Path,
    distribution: &str,
    package: &Path,
    version: &str,
    mut progress: impl FnMut(BuildProgress),
) -> ActionResult {
    let secrets = secret_values(root);
    let fail = |code: &str, detail: String| ActionResult {
        ok: false,
        code: code.into(),
        detail: redact(&detail, &secrets),
        command: None,
    };
    let _guard = match MUTATION.try_lock() {
        Ok(guard) => guard,
        Err(_) => {
            return fail(
                "busy",
                "Another infrastructure action is still running.".into(),
            );
        }
    };
    let started = Instant::now();
    progress(BuildProgress {
        phase: "checking",
        lines: vec![],
        elapsed_ms: 0,
        last_output_ms: None,
    });
    if !package.is_absolute()
        || !package.is_file()
        || !(package
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("zip"))
            || package
                .file_name()
                .is_some_and(|name| name == "ctxbench-images-manifest.json"))
    {
        return fail(
            "bundle_invalid",
            "Select an offline images ZIP or the legacy ctxbench-images-manifest.json file.".into(),
        );
    }
    // Only our installed importer is executed; scripts inside a user-supplied ZIP are data.
    let tool = root.join("scripts/images-release.py");
    if !tool.is_file() {
        return fail("offline_tool", tool.display().to_string());
    }
    if let Err(error) = wsl::output(
        distribution,
        &[
            "python3",
            "-I",
            "-c",
            "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ required'",
        ],
    ) {
        return fail("python", error);
    }
    let translate = |path: &Path| -> Result<String, String> {
        let translated = wsl::output(
            distribution,
            &["wslpath", "-a", &path.display().to_string()],
        )?;
        if !translated.starts_with('/') || translated.contains(['\r', '\n']) {
            return Err("WSL returned an invalid file path.".into());
        }
        wsl::output(distribution, &["test", "-r", &translated])?;
        Ok(translated)
    };
    let tool = match translate(&tool) {
        Ok(path) => path,
        Err(error) => return fail("wsl_path", error),
    };
    let package = match translate(package) {
        Ok(path) => path,
        Err(error) => return fail("wsl_path", error),
    };
    // Fail before hashing a large ZIP, then the trusted importer checks again immediately before loading.
    if let Err(result) = activity_guard("import", |args| wsl::output(distribution, args), &secrets)
    {
        return result;
    }
    let args = offline_import_args(&tool, &package, version);
    let mut process = std::process::Command::new("wsl.exe");
    process
        .args(["--distribution", distribution, "--exec"])
        .args(&args);
    match process_stream::run(
        &mut process,
        Duration::from_secs(3600),
        started,
        |line| redact(line, &secrets),
        &mut progress,
    ) {
        Ok(detail) => ActionResult {
            ok: true,
            code: "images_import".into(),
            detail,
            command: None,
        },
        Err(detail) => fail(&offline_error_code(&detail), detail),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn activity_fixture(args: &[&str], active_filter: &str) -> Result<String, String> {
        assert_eq!(&args[..3], &["docker", "ps", "--filter"]);
        assert!(!args.contains(&"-a"));
        assert!(!args.last().unwrap().contains("Command"));
        Ok(if args[3] == format!("label={active_filter}") {
            r#"{"id":"abc123","name":"test-container","status":"Up 1 minute"}"#.into()
        } else {
            String::new()
        })
    }

    #[test]
    fn mutations_guard_workers_agents_and_graders_without_touching_containers() {
        for action in ["import", "build", "start", "stop"] {
            for (filter, role) in ACTIVITY_FILTERS {
                let result = activity_guard(action, |args| activity_fixture(args, filter), &[]);
                let should_block = role != "worker" || matches!(action, "import" | "build");
                assert_eq!(result.is_err(), should_block, "{action}: {role}");
                if let Err(error) = result {
                    assert_eq!(
                        error.code,
                        if role == "worker" {
                            "worker_running"
                        } else {
                            "active_runs"
                        }
                    );
                    assert!(error.detail.contains("test-container"));
                }
            }
            assert!(
                activity_guard(action, |args| activity_fixture(args, "unrelated"), &[]).is_ok()
            );
        }
        assert_eq!(
            compose_args("/test/compose.yaml", "stop").unwrap(),
            [
                "docker",
                "compose",
                "-f",
                "/test/compose.yaml",
                "stop",
                "ctxbench-worker"
            ]
        );
    }

    #[test]
    fn unknown_activity_fails_closed_and_diagnostic_fields_are_allowlisted() {
        for output in ["not json", "{}", r#"{"id":"a","name":"b"}"#] {
            assert_eq!(
                activity_guard("stop", |_| Ok(output.into()), &[])
                    .unwrap_err()
                    .code,
                "activity_unknown"
            );
        }
        assert_eq!(
            activity_guard("import", |_| Err("permission denied".into()), &[])
                .unwrap_err()
                .code,
            "permission"
        );
        let containers = read_activity(|_| Ok(r#"{"id":"abc","name":"OPENAI_API_KEY=hidden","status":"Up","Env":["PRIVATE=hidden"],"Command":"secret command"}"#.into()), &[]).unwrap();
        assert_eq!(containers.len(), 1); // Multiple matching labels do not duplicate a container.
        let data = serde_json::to_string(&containers).unwrap();
        assert!(!data.contains("hidden"));
        assert!(!data.contains("Env"));
        assert!(!data.contains("secret command"));
    }

    #[test]
    fn offline_import_uses_only_installed_tool_and_literal_arguments() {
        let args = offline_import_args(
            "/mnt/c/Program Files/CTXBench/scripts/images-release.py",
            "/mnt/d/离线 包/pkg';echo.zip",
            "0.1.2",
        );
        assert_eq!(&args[..3], ["python3", "-I", "-u"]);
        assert_eq!(args[5], "/mnt/d/离线 包/pkg';echo.zip");
        assert!(args.contains(&"--require-stopped".into()));
        assert!(args.contains(&"--expected-version".into()));
        assert!(
            !args
                .iter()
                .any(|value| value == "bash" || value.ends_with("ctxbench-images.py"))
        );
        assert_eq!(
            offline_error_code("Version mismatch: package v0.1.0"),
            "bundle_version"
        );
        assert_eq!(
            offline_error_code("Active CTXBench containers detected"),
            "worker_running"
        );
        assert_eq!(offline_error_code("SHA-256 mismatch"), "bundle_invalid");
        assert_eq!(
            offline_error_code("Image bundle error: permission denied"),
            "permission"
        );
        assert_eq!(
            offline_error_code("Image bundle error: no space left on device"),
            "disk_space"
        );
        assert_eq!(
            offline_error_code("Image bundle error: operation timed out"),
            "timeout"
        );
    }

    #[test]
    fn startup_is_offline_and_preserves_absolute_paths() {
        let args = compose_args(
            "/mnt/c/Program Files/CTXBench/deployment/docker/compose.yaml",
            "start",
        )
        .unwrap();
        assert_eq!(
            args[3],
            "/mnt/c/Program Files/CTXBench/deployment/docker/compose.yaml"
        );
        assert!(args.contains(&"--no-build".into()));
        assert!(args.windows(2).any(|pair| pair == ["--pull", "never"]));
        assert!(!args.contains(&"--build".into()));
        assert!(compose_args("/compose.yaml", "prune").is_err());
        assert!(
            compose_args("/compose.yaml", "build")
                .unwrap()
                .windows(2)
                .any(|pair| pair == ["--progress", "plain"])
        );
        assert_eq!(shell_quote("one'two"), "'one'\"'\"'two'");
    }

    #[test]
    fn classifies_actionable_docker_failures() {
        for (message, code) in [
            (
                "bind source path does not exist: /var/lib/ctxbench",
                "data_directory",
            ),
            ("No such image: ctxbench/worker:0.1.0", "images"),
            (
                "Bind for 127.0.0.1:48173 failed: port is already allocated",
                "port_in_use",
            ),
            (
                "permission denied while trying to connect to Docker",
                "permission",
            ),
            ("Cannot connect to the Docker daemon", "docker"),
            ("no space left on device", "disk_space"),
            (
                "load metadata: registry-1.docker.io: context deadline exceeded",
                "network",
            ),
            ("context deadline exceeded", "timeout"),
            ("something else", "action"),
        ] {
            assert_eq!(classify_error(message, "action"), code);
        }
    }

    #[test]
    fn offline_errors_preserve_recovery_categories() {
        for (message, code) in [
            (
                "Image bundle error: This bundle requires a Linux amd64 Docker daemon (the selected WSL distribution).",
                "offline_platform",
            ),
            (
                "Image bundle error: Active CTXBench containers detected.",
                "worker_running",
            ),
            ("Image bundle error: Version mismatch", "bundle_version"),
            ("Image bundle error: no space left on device", "disk_space"),
            ("Image bundle error: SHA-256 mismatch", "bundle_invalid"),
        ] {
            assert_eq!(offline_error_code(message), code);
        }
    }

    #[test]
    fn redacts_secrets_before_details_can_leave_native_code() {
        let input = "plain top-secret-value\nOPENAI_API_KEY=abc123\nAuthorization: Bearer abc.def.ghi\nhttps://user:pass@registry.example/image\nhttps://api.example?token=abcd&ok=1\nsk-abcdefghijk\ntp-abcdefghijk\n";
        let clean = redact(input, &["top-secret-value".into()]);
        for secret in [
            "top-secret-value",
            "abc123",
            "abc.def.ghi",
            "user:pass",
            "token=abcd",
            "sk-abcdefghijk",
            "tp-abcdefghijk",
        ] {
            assert!(!clean.contains(secret), "{secret}");
        }
        assert!(clean.contains("registry.example"));
        assert!(clean.contains("ok=1"));
        assert!(redact(&"a".repeat(30_000), &[]).ends_with("[Output truncated]"));
        assert_eq!(
            redact("test-\x1b[31msecret", &["test-secret".into()]),
            "[REDACTED]"
        );
    }

    #[test]
    fn missing_bundle_has_a_specific_error_without_launching_wsl() {
        let root = std::env::temp_dir().join(format!("ctxbench-missing-{}", uuid::Uuid::new_v4()));
        let result = control(&root, "Ubuntu-24.04", "start", |_| {});
        assert!(!result.ok);
        assert_eq!(result.code, "compose_file");
        assert!(
            result.detail.ends_with("docker\\compose.yaml")
                || result.detail.ends_with("docker/compose.yaml")
        );
    }

    #[test]
    #[ignore = "read-only deployment inspection requires WSL and Docker on the host"]
    fn inspect_installed_deployment() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
        let info = inspect(root, "Ubuntu");
        assert!(
            info.checks
                .iter()
                .any(|check| check.id == "compose_file" && check.ok)
        );
        assert!(
            info.checks
                .iter()
                .any(|check| check.id == "compose" && check.ok)
        );
        println!("{}", serde_json::to_string(&info).unwrap());
    }

    #[test]
    #[cfg(windows)]
    #[ignore = "requires Ubuntu WSL Python/Docker; rejects active containers or a corrupt ZIP without mutation"]
    fn real_offline_import_preflight_through_wsl() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
        let activity = activity_guard(
            "import",
            |args| wsl::output("Ubuntu", args),
            &secret_values(root),
        );
        let folder =
            std::env::temp_dir().join(format!("ctxbench 离线 test {}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&folder).unwrap();
        let package = folder.join("invalid package.zip");
        std::fs::write(&package, b"This is not an archive").unwrap();
        let mut events = Vec::new();
        let result = import_images(root, "Ubuntu", &package, "0.1.2", |event| {
            events.push(event)
        });
        // Only this test's two explicit temporary paths are removed.
        std::fs::remove_file(package).unwrap();
        std::fs::remove_dir(folder).unwrap();
        assert!(!result.ok, "{result:?}");
        assert!(events.iter().any(|event| event.phase == "checking"));
        if let Err(blocker) = activity {
            assert_eq!(result.code, blocker.code, "{result:?}");
            assert!(
                matches!(result.code.as_str(), "worker_running" | "active_runs"),
                "{result:?}"
            );
        } else {
            assert_eq!(result.code, "bundle_invalid", "{result:?}");
            assert!(result.detail.contains("not a zip file"), "{result:?}");
        }
    }

    #[test]
    #[cfg(windows)]
    #[ignore = "requires Ubuntu WSL Docker and local ctxbench/worker:0.1.0; builds only isolated test images"]
    fn real_docker_build_streams_success_cache_and_failure() {
        let distro = "Ubuntu";
        wsl::output(
            distro,
            &[
                "docker",
                "image",
                "inspect",
                "ctxbench/worker:0.1.0",
                "--format",
                "{{.Id}}",
            ],
        )
        .expect("Requires an already-installed local worker image; this test never pulls it.");
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/build-progress");
        let path = checked_path(&root, distro).unwrap();
        let project = format!("ctxbench-progress-test-{}", uuid::Uuid::new_v4().simple());
        let image = format!("{project}-success");
        let mut runs = Vec::new();
        for (service, cache) in [("success", false), ("success", true), ("failure", false)] {
            let mut args = compose_args(&path, "build").unwrap();
            args.splice(2..2, ["-p".into(), project.clone()]);
            if !cache {
                args.push("--no-cache".into());
            }
            args.push(service.into());
            let mut command = std::process::Command::new("wsl.exe");
            command
                .args(["--distribution", distro, "--exec"])
                .args(args);
            let started = Instant::now();
            let mut events = Vec::new();
            let result = process_stream::run(
                &mut command,
                Duration::from_secs(90),
                started,
                |line| redact(line, &[]),
                &mut |event| events.push((Instant::now(), event)),
            );
            runs.push((service, cache, result, events, Instant::now()));
        }
        // Remove only this run's unique image tag, never production tags or build caches.
        let cleanup = wsl::output(distro, &["docker", "image", "rm", &image]);
        for (service, cache, result, events, finished) in runs {
            assert_eq!(result.is_ok(), service == "success", "{result:?}");
            let lines: Vec<_> = events
                .iter()
                .flat_map(|(_, event)| event.lines.iter())
                .collect();
            assert!(lines.iter().any(|line| line.starts_with('#')));
            if cache {
                assert!(lines.iter().any(|line| line.contains("CACHED")));
            } else {
                let marker = if service == "success" {
                    "progress-test: first output"
                } else {
                    "progress-test: failure started"
                };
                let first = events
                    .iter()
                    .find(|(_, event)| event.lines.iter().any(|line| line.contains(marker)))
                    .unwrap();
                assert!(
                    finished.duration_since(first.0) > Duration::from_secs(1),
                    "Output must arrive during the build, not at completion"
                );
            }
            if service == "failure" {
                assert!(result.unwrap_err().contains("expected failure"));
            }
            println!(
                "{service} (cache={cache}): {} live batches, {} log lines",
                events.len(),
                lines.len()
            );
        }
        cleanup.expect("Could not remove the unique integration-test image tag");
    }
}
