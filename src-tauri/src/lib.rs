use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::process::Command;
use std::time::Duration;
use tauri::Manager;

const WORKER_BASE_URL: &str = "http://127.0.0.1:48173/v1";

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DiagnosticItem {
    id: &'static str,
    label: &'static str,
    status: &'static str,
    detail: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    fix: Option<&'static str>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct CreateExperimentRequest {
    name: String,
    benchmark: String,
    dataset: String,
    arms: Vec<String>,
    repeats: u32,
    task_ids: Vec<String>,
    model: Value,
    profiles: Value,
    agent_image: String,
    resources: Value,
    seed: u64,
}

fn decode_command_output(bytes: &[u8]) -> String {
    if bytes
        .iter()
        .skip(1)
        .step_by(2)
        .filter(|byte| **byte == 0)
        .count()
        > bytes.len() / 8
    {
        let units: Vec<u16> = bytes
            .chunks_exact(2)
            .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
            .collect();
        String::from_utf16_lossy(&units)
            .trim_matches('\0')
            .trim()
            .to_string()
    } else {
        String::from_utf8_lossy(bytes).trim().to_string()
    }
}

fn wsl_output(distribution: &str, args: &[&str]) -> Result<String, String> {
    use std::os::windows::process::CommandExt;
    use std::process::Stdio;
    let mut child = Command::new("wsl.exe").args(["-d", distribution, "--"]).args(args)
        .creation_flags(0x08000000).stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn().map_err(|error| error.to_string())?;
    let deadline = std::time::Instant::now() + Duration::from_secs(15);
    while child.try_wait().map_err(|error| error.to_string())?.is_none() {
        if std::time::Instant::now() > deadline { let _ = child.kill(); let _ = child.wait(); return Err("WSL diagnostic timed out.".into()); }
        std::thread::sleep(Duration::from_millis(50));
    }
    let output = child.wait_with_output().map_err(|error| error.to_string())?;
    if output.status.success() {
        Ok(decode_command_output(&output.stdout))
    } else {
        Err(decode_command_output(&output.stderr))
    }
}

async fn worker_healthy() -> Result<String, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|error| error.to_string())?;
    let response = client
        .get(format!("{WORKER_BASE_URL}/health"))
        .send()
        .await
        .map_err(|error| error.to_string())?;
    let payload: Value = response.error_for_status().map_err(|error| error.to_string())?.json().await.map_err(|error| error.to_string())?;
    Ok(payload
        .get("version")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string())
}

#[tauri::command]
async fn diagnose_environment(_app: tauri::AppHandle, distribution: Option<String>) -> Vec<DiagnosticItem> {
    let distro = distribution.unwrap_or_else(|| "Ubuntu".into());
    let selected = distro.clone();
    let (wsl, distribution, docker) = tauri::async_runtime::spawn_blocking(move || (
        wsl_output(&selected, &["uname", "-r"]),
        wsl_output(&selected, &["cat", "/etc/os-release"]),
        wsl_output(&selected, &["docker", "version", "--format", "{{.Server.Version}}"]),
    )).await.unwrap_or_else(|_| (Err("WSL check failed.".into()), Err("Distribution check failed.".into()), Err("Docker check failed.".into())));
    let worker = worker_healthy().await;
    let runtime = if worker.is_ok() { worker_request("GET".into(), "/runtime".into(), None).await } else { Err("Worker storage is unavailable.".into()) };
    let storage = runtime.and_then(|value| value.get("dataDirectory").and_then(Value::as_str).map(str::to_owned).ok_or_else(|| "Worker storage is unavailable.".to_string()));
    let wsl_ok = wsl.as_ref().map(|kernel| kernel.to_lowercase().contains("wsl2")).unwrap_or(false);
    let distribution_ok = distribution.is_ok();
    let docker_ok = docker.is_ok();
    let worker_ok = worker.is_ok();
    let storage_ok = storage.is_ok();

    vec![
        DiagnosticItem {
            id: "wsl",
            label: "WSL 2",
            status: if wsl_ok { "healthy" } else { "missing" },
            detail: wsl
                .map(|kernel| format!("{distro} · kernel {kernel}"))
                .unwrap_or_else(|_| "WSL2 Ubuntu is unavailable.".into()),
            fix: if wsl_ok {
                None
            } else {
                Some(
                    "Install WSL2 and an Ubuntu distribution, then restart if Windows requests it.",
                )
            },
        },
        DiagnosticItem {
            id: "distribution",
            label: "Distribution",
            status: if distribution_ok {
                "healthy"
            } else {
                "missing"
            },
            detail: distribution
                .unwrap_or_else(|_| "The Ubuntu distribution could not be opened.".into()),
            fix: None,
        },
        DiagnosticItem {
            id: "docker",
            label: "Docker Engine",
            status: if docker_ok { "healthy" } else { "missing" },
            detail: docker
                .map(|version| format!("Docker Engine {version} inside WSL"))
                .unwrap_or_else(|_| {
                    "Docker is not installed or its daemon is stopped in Ubuntu.".into()
                }),
            fix: if docker_ok {
                None
            } else {
                Some("Install Docker Engine inside WSL and start the daemon.")
            },
        },
        DiagnosticItem {
            id: "worker",
            label: "CTXBench worker",
            status: if worker_ok { "healthy" } else { "missing" },
            detail: worker
                .map(|version| format!("Worker {version} · 127.0.0.1:48173"))
                .unwrap_or_else(|_| "No worker is listening on 127.0.0.1:48173.".into()),
            fix: if worker_ok {
                None
            } else {
                Some("Build and start ctxbench-worker with the supplied Docker Compose file.")
            },
        },
        DiagnosticItem {
            id: "storage",
            label: "Artifact store",
            status: if storage_ok { "healthy" } else { "warning" },
            detail: storage
                .map(|path| format!("WSL: {path}"))
                .unwrap_or_else(|_| "Application data directory is unavailable.".into()),
            fix: None,
        },
    ]
}

#[tauri::command]
async fn bootstrap(app: tauri::AppHandle) -> Result<Value, String> {
    let diagnostics = diagnose_environment(app, None).await;
    let mut snapshot = worker_request("GET".into(), "/snapshot".into(), None).await?;
    snapshot["diagnostics"] = serde_json::to_value(diagnostics).map_err(|error| error.to_string())?;
    Ok(snapshot)
}

#[tauri::command]
async fn worker_request(method: String, path: String, body: Option<Value>) -> Result<Value, String> {
    if !path.starts_with('/') || path.contains("..") || path.contains('\\') || path.starts_with("//") {
        return Err("Invalid worker route.".into());
    }
    let method = match method.as_str() {
        "GET" => reqwest::Method::GET,
        "POST" => reqwest::Method::POST,
        _ => return Err("Unsupported worker method.".into()),
    };
    let client = reqwest::Client::builder().timeout(Duration::from_secs(300)).build().map_err(|error| error.to_string())?;
    let mut request = client.request(method, format!("{WORKER_BASE_URL}{path}"));
    if let Some(body) = body { request = request.json(&body); }
    let response = request.send().await.map_err(|_| "The WSL worker is unavailable. Start it from Infrastructure and retry.".to_string())?;
    let status = response.status();
    let payload: Value = response.json().await.map_err(|_| "Worker returned an invalid response.".to_string())?;
    if status.is_success() { Ok(payload) } else { Err(payload.get("detail").map(|detail| detail.as_str().map(str::to_owned).unwrap_or_else(|| detail.to_string())).unwrap_or_else(|| format!("Worker error: {status}"))) }
}

#[tauri::command]
async fn save_export(filename: String, content: String) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        if let Some(path) = rfd::FileDialog::new().set_file_name(&filename).save_file() {
            std::fs::write(&path, content).map_err(|error| error.to_string())?;
            Ok(Some(path.display().to_string()))
        } else { Ok(None) }
    }).await.map_err(|error| error.to_string())?
}

#[tauri::command]
async fn worker_control(app: tauri::AppHandle, action: String, distribution: String) -> Result<String, String> {
    let deployment = if cfg!(debug_assertions) {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
    } else { app.path().resource_dir().map_err(|error| error.to_string())?.join("deployment") };
    tauri::async_runtime::spawn_blocking(move || {
        use std::os::windows::process::CommandExt;
        let translated = Command::new("wsl.exe").args(["-d", &distribution, "--", "wslpath", "-a", &deployment.display().to_string()]).creation_flags(0x08000000).output().map_err(|error| error.to_string())?;
        if !translated.status.success() { return Err(decode_command_output(&translated.stderr)); }
        let root = decode_command_output(&translated.stdout);
        let mut command = Command::new("wsl.exe");
        command.args(["-d", &distribution, "--", "docker", "compose", "-f", &format!("{root}/docker/compose.yaml")]);
        match action.as_str() {
            "start" => { command.args(["up", "-d", "ctxbench-worker"]); },
            "stop" => { command.args(["stop", "ctxbench-worker"]); },
            "build" => { command.args(["--profile", "build-only", "build"]); },
            _ => return Err("Unsupported infrastructure action.".into()),
        }
        let output = command.creation_flags(0x08000000).output().map_err(|error| error.to_string())?;
        if output.status.success() { Ok("Worker action completed.".into()) } else { Err("Worker action failed. Check Docker and the packaged deployment prerequisites.".into()) }
    }).await.map_err(|error| error.to_string())?
}

#[tauri::command]
async fn create_experiment(request: CreateExperimentRequest) -> Result<Value, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|error| error.to_string())?;
    let response = client
        .post(format!("{WORKER_BASE_URL}/experiments"))
        .json(&request)
        .send()
        .await
        .map_err(|_| {
            "The WSL worker is unavailable. Start it from Infrastructure and retry.".to_string()
        })?;
    let status = response.status();
    let payload: Value = response.json().await.map_err(|error| error.to_string())?;
    if status.is_success() {
        Ok(payload)
    } else {
        Err(payload
            .get("detail")
            .and_then(Value::as_str)
            .unwrap_or("Worker rejected the experiment.")
            .to_string())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            bootstrap,
            diagnose_environment,
            create_experiment
            ,worker_request, save_export, worker_control
        ])
        .run(tauri::generate_context!())
        .expect("error while running CTXBench Desktop");
}

#[cfg(test)]
mod tests {
    use super::decode_command_output;

    #[test]
    fn decodes_utf16_wsl_output() {
        let bytes: Vec<u8> = "Ubuntu\r\n"
            .encode_utf16()
            .flat_map(u16::to_le_bytes)
            .collect();
        assert_eq!(decode_command_output(&bytes), "Ubuntu");
    }
}
