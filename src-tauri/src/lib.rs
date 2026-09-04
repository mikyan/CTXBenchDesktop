use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
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

fn wsl_output(script: &str) -> Result<String, String> {
    let output = Command::new("wsl.exe")
        .args(["-d", "Ubuntu", "--", "sh", "-lc", script])
        .output()
        .map_err(|error| error.to_string())?;
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
    let payload: Value = response.json().await.map_err(|error| error.to_string())?;
    Ok(payload
        .get("version")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string())
}

#[tauri::command]
async fn diagnose_environment(app: tauri::AppHandle) -> Vec<DiagnosticItem> {
    let wsl = wsl_output("uname -r");
    let distribution = wsl_output("printf 'Ubuntu · WSL 2'");
    let docker = wsl_output("docker version --format '{{.Server.Version}}' 2>/dev/null");
    let worker = worker_healthy().await;
    let storage = app.path().app_data_dir();
    let wsl_ok = wsl.is_ok();
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
                .map(|kernel| format!("Ubuntu · kernel {kernel}"))
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
                .map(|path| path.display().to_string())
                .unwrap_or_else(|_| "Application data directory is unavailable.".into()),
            fix: None,
        },
    ]
}

#[tauri::command]
async fn bootstrap(app: tauri::AppHandle) -> Result<Value, String> {
    let diagnostics = diagnose_environment(app).await;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|error| error.to_string())?;
    let experiments = match client
        .get(format!("{WORKER_BASE_URL}/experiments"))
        .send()
        .await
    {
        Ok(response) if response.status().is_success() => {
            response.json::<Value>().await.unwrap_or_else(|_| json!([]))
        }
        _ => json!([]),
    };

    Ok(json!({
        "metrics": {
            "totalRuns": 0, "passRate": 0.0, "knowledgeLift": 0.0,
            "passPatchViolationRate": 0.0, "avgCostUsd": 0.0,
            "pairedWins": 0, "pairedLosses": 0, "pairedTies": 0,
            "dsr": 0.0, "dvr": 0.0, "dnr": 0.0
        },
        "armMetrics": [],
        "experiments": experiments,
        "runs": [],
        "artifacts": [],
        "constraints": [],
        "diagnostics": diagnostics,
        "activity": [],
        "runtime": "desktop"
    }))
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
