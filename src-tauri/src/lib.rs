use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;
use tauri::Manager;
mod wsl;
mod deployment;
mod process_stream;
mod image_export;
#[cfg(test)]
use wsl::decode_output as decode_command_output;

const WORKER_BASE_URL: &str = "http://127.0.0.1:48173/v1";

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DiagnosticItem {
    id: &'static str,
    label: &'static str,
    status: &'static str,
    detail: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    detail_values: Option<Value>,
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

#[tauri::command]
async fn list_wsl_distributions() -> Result<wsl::Inventory, String> {
    tauri::async_runtime::spawn_blocking(wsl::inventory).await.map_err(|error| error.to_string())?
}

async fn worker_healthy() -> Result<String, String> {
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|error| error.to_string())?;
    let response = client
        .get(format!("{WORKER_BASE_URL}/health"))
        .send()
        .await
        .map_err(|error| error.to_string())?;
    let payload: Value = response.error_for_status().map_err(|error| error.to_string())?.json().await.map_err(|error| error.to_string())?;
    if payload.get("status").and_then(Value::as_str) != Some("healthy") || payload.get("runner").and_then(Value::as_str).is_none() {
        return Err("Port 48173 did not return a CTXBench health response.".into());
    }
    payload.get("version").and_then(Value::as_str).map(str::to_owned)
        .ok_or_else(|| "The worker health response has no version.".into())
}

fn diagnose_wsl(
    distribution: Option<&str>,
    inventory: Result<wsl::Inventory, String>,
    output: impl Fn(&str, &[&str]) -> Result<String, String>,
) -> Vec<DiagnosticItem> {
    let items = inventory
        .as_ref()
        .map(|value| value.distributions.as_slice())
        .unwrap_or(&[]);
    let selected = wsl::selected_distribution(items, distribution);
    let installed = selected
        .as_ref()
        .and_then(|name| items.iter().find(|item| item.name == *name));
    let wsl_check = match (&inventory, installed, &selected) {
        (Err(error), _, _) => DiagnosticItem {
            id: "wsl",
            label: "WSL 2",
            status: "warning",
            detail: "Could not read WSL versions: {error}".into(),
            detail_values: Some(serde_json::json!({"error": error})),
            fix: Some(
                "Refresh the distribution list or enter a name manually. Check wsl --list --verbose in PowerShell.",
            ),
        },
        (_, Some(item), _) => DiagnosticItem {
            id: "wsl",
            label: "WSL 2",
            status: if item.version == 2 {
                "healthy"
            } else {
                "missing"
            },
            detail: "{distribution} · WSL {version}".into(),
            detail_values: Some(
                serde_json::json!({"distribution": item.name, "version": item.version}),
            ),
            fix: if item.version == 2 {
                None
            } else {
                Some("Select a WSL 2 distribution. The selected distribution uses WSL 1.")
            },
        },
        (_, None, Some(name)) => DiagnosticItem {
            id: "wsl",
            label: "WSL 2",
            status: "missing",
            detail: "Distribution {distribution} is not in the installed WSL list.".into(),
            detail_values: Some(serde_json::json!({"distribution": name})),
            fix: Some(
                "Choose an installed distribution or check the exact name in PowerShell with wsl --list --verbose.",
            ),
        },
        (_, None, None) => DiagnosticItem {
            id: "wsl",
            label: "WSL 2",
            status: "missing",
            detail: "No usable WSL distribution selected.".into(),
            detail_values: None,
            fix: Some(
                "Choose an installed distribution or install a WSL 2 distribution, then refresh the list.",
            ),
        },
    };
    let (os, docker) = match selected.as_deref() {
        Some(name) if installed.is_some() || inventory.is_err() => {
            let os = output(name, &["cat", "/etc/os-release"]);
            let docker = if os.is_ok() {
                output(
                    name,
                    &["docker", "version", "--format", "{{.Server.Version}}"],
                )
            } else {
                Err(
                    "The selected distribution could not be started; Docker was not checked."
                        .into(),
                )
            };
            (os, docker)
        }
        _ => (
            Err("Select an installed WSL distribution first.".into()),
            Err("Select an installed WSL distribution first.".into()),
        ),
    };
    vec![
        wsl_check,
        DiagnosticItem {
            id: "distribution",
            label: "Distribution",
            status: if os.is_ok() { "healthy" } else { "missing" },
            detail: "{distribution} · {result}".into(),
            detail_values: Some(
                serde_json::json!({"distribution": selected.as_deref().unwrap_or("WSL"), "result": os.unwrap_or_else(|error| error)}),
            ),
            fix: None,
        },
        DiagnosticItem {
            id: "docker",
            label: "Docker Engine",
            status: if docker.is_ok() { "healthy" } else { "missing" },
            detail: if docker.is_ok() {
                "Docker Engine {result} inside {distribution}"
            } else {
                "Docker check failed in {distribution}: {result}"
            }
            .into(),
            fix: if docker.is_ok() {
                None
            } else {
                Some("Install Docker Engine inside WSL and start the daemon.")
            },
            detail_values: Some(
                serde_json::json!({"distribution": selected.as_deref().unwrap_or("WSL"), "result": docker.unwrap_or_else(|error| error)}),
            ),
        },
    ]
}

#[tauri::command]
async fn diagnose_environment(_app: tauri::AppHandle, distribution: Option<String>) -> Vec<DiagnosticItem> {
    let mut diagnostics = tauri::async_runtime::spawn_blocking(move || {
        diagnose_wsl(distribution.as_deref(), wsl::inventory(), wsl::output)
    }).await.unwrap_or_else(|error| vec![DiagnosticItem {
        id: "wsl", label: "WSL 2", status: "warning", detail: "Could not read WSL versions: {error}".into(),
        detail_values: Some(serde_json::json!({"error": error.to_string()})), fix: None,
    }]);
    let worker = worker_healthy().await;
    let runtime = if worker.is_ok() { worker_request("GET".into(), "/runtime".into(), None).await } else { Err("Worker storage is unavailable.".into()) };
    let storage = runtime.and_then(|value| value.get("dataDirectory").and_then(Value::as_str).map(str::to_owned).ok_or_else(|| "Worker storage is unavailable.".to_string()));
    let worker_ok = worker.is_ok();
    let storage_ok = storage.is_ok();

    diagnostics.extend([
        DiagnosticItem {
            id: "worker",
            label: "CTXBench worker",
            status: if worker_ok { "healthy" } else { "missing" },
            detail: if worker_ok { "Worker {result} · 127.0.0.1:48173" } else { "Worker health check failed: {result}" }.into(),
            detail_values: Some(serde_json::json!({"result": worker.unwrap_or_else(|error| deployment::redact(&error, &[]))})),
            fix: if worker_ok {
                None
            } else {
                Some("Docker being ready does not mean the worker is installed. Check deployment files and images below, start the worker, then retry diagnostics.")
            },
        },
        DiagnosticItem {
            id: "storage",
            label: "Artifact store",
            status: if storage_ok { "healthy" } else { "warning" },
            detail: storage
                .map(|path| format!("WSL: {path}"))
                .unwrap_or_else(|_| "Application data directory is unavailable.".into()),
            detail_values: None,
            fix: None,
        },
    ]);
    diagnostics
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
    let client = reqwest::Client::builder().no_proxy().timeout(Duration::from_secs(300)).build().map_err(|error| error.to_string())?;
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

fn deployment_root(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    Ok(if cfg!(debug_assertions) {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
    } else { app.path().resource_dir().map_err(|error| error.to_string())?.join("deployment") })
}

#[tauri::command]
async fn get_deployment_info(app: tauri::AppHandle, distribution: String) -> Result<deployment::DeploymentInfo, String> {
    let root = deployment_root(&app)?;
    let distribution = distribution.trim().to_string();
    if distribution.is_empty() { return Err("Select an installed WSL distribution first.".into()); }
    tauri::async_runtime::spawn_blocking(move || deployment::inspect(&root, &distribution)).await.map_err(|error| error.to_string())
}

#[tauri::command]
async fn select_offline_bundle() -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(|| {
        rfd::FileDialog::new().add_filter("CTXBench offline images ZIP / legacy manifest", &["zip", "json"])
            .pick_file().map(|path| path.display().to_string())
    }).await.map_err(|error| error.to_string())
}

#[tauri::command]
async fn import_offline_images(app: tauri::AppHandle, distribution: String, package_path: String, on_progress: tauri::ipc::Channel<process_stream::BuildProgress>) -> Result<deployment::ActionResult, String> {
    let root = deployment_root(&app)?;
    let distribution = distribution.trim().to_string();
    if distribution.is_empty() { return Err("Select an installed WSL distribution first.".into()); }
    let version = app.package_info().version.to_string();
    tauri::async_runtime::spawn_blocking(move || deployment::import_images(&root, &distribution, std::path::Path::new(&package_path), &version, |event| { let _ = on_progress.send(event); }))
        .await.map_err(|_| "Offline import connection lost; check Docker before retrying.".to_string())
}

#[tauri::command]
async fn list_local_images(app: tauri::AppHandle, distribution: String) -> Result<image_export::ImageInventory, String> {
    let root = deployment_root(&app)?;
    let distribution = distribution.trim().to_string();
    if distribution.is_empty() { return Err("Select an installed WSL distribution first.".into()); }
    tauri::async_runtime::spawn_blocking(move || image_export::list_images(&root, &distribution)).await.map_err(|_| "Could not list local Docker images.".to_string())
}

#[tauri::command]
async fn select_image_export_path(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let name = format!("ctxbench-images-v{}-custom-{}.zip", app.package_info().version, &uuid::Uuid::new_v4().simple().to_string()[..8]);
    tauri::async_runtime::spawn_blocking(move || rfd::FileDialog::new().add_filter("CTXBench image ZIP", &["zip"])
        .set_file_name(name).save_file().map(|path| path.display().to_string()))
        .await.map_err(|_| "Could not open the file picker. Retry in the desktop application.".to_string())
}

#[tauri::command]
async fn export_offline_images(app: tauri::AppHandle, distribution: String, package_path: String, images: Vec<image_export::ImageSelection>, on_progress: tauri::ipc::Channel<process_stream::BuildProgress>) -> Result<deployment::ActionResult, String> {
    let root = deployment_root(&app)?;
    let distribution = distribution.trim().to_string();
    if distribution.is_empty() { return Err("Select an installed WSL distribution first.".into()); }
    let version = app.package_info().version.to_string();
    tauri::async_runtime::spawn_blocking(move || image_export::export_images(&root, &distribution, std::path::Path::new(&package_path), &version, &images, |event| { let _ = on_progress.send(event); }))
        .await.map_err(|_| "Image export connection lost. Check the output before retrying.".to_string())
}

#[tauri::command]
async fn worker_control(app: tauri::AppHandle, webview: tauri::Webview, action: String, distribution: String, on_progress: Option<tauri::ipc::JavaScriptChannelId>) -> Result<deployment::ActionResult, String> {
    let root = deployment_root(&app)?;
    let distribution = distribution.trim().to_string();
    if distribution.is_empty() { return Err("Select an installed WSL distribution first.".into()); }
    let starting = action == "start";
    let on_progress = on_progress.map(|id| id.channel_on::<_, process_stream::BuildProgress>(webview));
    let mut result = tauri::async_runtime::spawn_blocking(move || deployment::control(&root, &distribution, &action, |event| {
        // Navigating away or losing a listener must not cancel Docker's build.
        if let Some(channel) = &on_progress { let _ = channel.send(event); }
    })).await.map_err(|error| error.to_string())?;
    if result.ok && starting {
        let mut error = String::new();
        for _ in 0..6 {
            match worker_healthy().await {
                Ok(_) => return Ok(result),
                Err(failure) => error = failure,
            }
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
        result.ok = false;
        result.code = "worker_health".into();
        result.detail = deployment::redact(&error, &[]);
    }
    Ok(result)
}

#[tauri::command]
async fn create_experiment(request: CreateExperimentRequest) -> Result<Value, String> {
    let client = reqwest::Client::builder()
        .no_proxy()
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
        // Links are handled explicitly in React so failures are visible to the user.
        .plugin(tauri_plugin_opener::Builder::new().open_js_links_on_click(false).build())
        .invoke_handler(tauri::generate_handler![
            bootstrap,
            diagnose_environment,
            list_wsl_distributions,
            get_deployment_info,
            create_experiment
            ,worker_request, save_export, worker_control, select_offline_bundle, import_offline_images,
            list_local_images, select_image_export_path, export_offline_images
        ])
        .run(tauri::generate_context!())
        .expect("error while running CTXBench Desktop");
}

#[cfg(test)]
mod tests {
    use super::{decode_command_output, diagnose_wsl, wsl};

    fn inventory() -> Result<wsl::Inventory, String> {
        let distributions = wsl::parse_distributions("NAME STATE VERSION\n* Ubuntu-24.04 Stopped 2\n  Legacy Running 1").unwrap();
        Ok(wsl::Inventory { distributions, default_distribution: Some("Ubuntu-24.04".into()) })
    }

    #[test]
    fn diagnoses_actual_version_without_querying_kernel_name() {
        let checks = diagnose_wsl(None, inventory(), |name, args| {
            assert_eq!(name, "Ubuntu-24.04");
            match args[0] {
                "cat" => Ok("Company Linux".into()),
                "docker" => Ok("28.0.0".into()),
                _ => panic!("Unexpected diagnostic command"),
            }
        });
        assert!(checks.iter().all(|check| check.status == "healthy"));
        assert_eq!(checks[0].detail_values.as_ref().unwrap()["version"], 2);
        let legacy = diagnose_wsl(Some("Legacy"), inventory(), |_, _| Ok("ok".into()));
        assert_eq!(legacy[0].status, "missing");
        assert!(legacy[0].fix.unwrap().contains("WSL 1"));
    }

    #[test]
    fn distinguishes_missing_distribution_startup_failure_and_unknown_version() {
        let missing = diagnose_wsl(Some("Ubuntu"), inventory(), |_, _| panic!("Must not launch a missing distribution"));
        assert_eq!(missing[0].status, "missing");
        assert!(missing[0].detail.contains("not in the installed"));
        let stopped = diagnose_wsl(None, inventory(), |_, args| {
            assert_eq!(args[0], "cat"); // Do not repeat a failed cold start for Docker.
            Err("Company policy blocked startup".into())
        });
        assert_eq!(stopped[0].status, "healthy"); // Installed WSL 2, but cannot start it.
        assert_eq!(stopped[1].status, "missing");
        assert_eq!(stopped[1].detail_values.as_ref().unwrap()["result"], "Company policy blocked startup");
        let unknown = diagnose_wsl(Some("Custom"), Err("Enumeration timed out".into()), |name, _| {
            assert_eq!(name, "Custom");
            Ok("available".into())
        });
        assert_eq!(unknown[0].status, "warning");
        assert_eq!(unknown[1].status, "healthy");
        assert_eq!(unknown[2].status, "healthy");
    }

    #[test]
    fn decodes_utf16_wsl_output() {
        let bytes: Vec<u8> = "Ubuntu\r\n"
            .encode_utf16()
            .flat_map(u16::to_le_bytes)
            .collect();
        assert_eq!(decode_command_output(&bytes), "Ubuntu");
    }
}
