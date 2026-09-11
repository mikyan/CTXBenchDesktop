use serde_json::Value;
use std::time::Duration;

const MAX_BYTES: usize = 32 * 1024 * 1024;

fn validate(filename: &str, bytes: &[u8], benchmark: &str) -> Result<(), String> {
    if bytes.is_empty() || bytes.len() > MAX_BYTES {
        return Err("Choose a nonempty dataset file no larger than 32 MiB.".into());
    }
    if filename.is_empty()
        || filename.len() > 1024
        || filename.contains(['/', '\\', '\0', '\r', '\n'])
    {
        return Err("Choose a local dataset file, not a directory or server path.".into());
    }
    if !["ctxbench", "swebench", "custom"].contains(&benchmark) {
        return Err("Select the matching dataset source.".into());
    }
    Ok(())
}

#[tauri::command]
pub async fn preview_dataset_file(
    filename: String,
    bytes: Vec<u8>,
    name: String,
    benchmark: String,
) -> Result<Value, String> {
    validate(&filename, &bytes, &benchmark)?;
    // Fixed loopback destination; never forward dataset contents through proxies or redirects.
    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(660))
        .build()
        .map_err(|_| "Could not connect to the local evaluation service.".to_string())?;
    let mut url = reqwest::Url::parse(&format!(
        "{}/datasets/files/preview",
        crate::worker_connection::current()?.base_url
    ))
    .unwrap();
    url.query_pairs_mut().extend_pairs([
        ("filename", filename),
        ("name", name),
        ("benchmark", benchmark),
    ]);
    let response = client
        .post(url)
        .header("Content-Type", "application/octet-stream")
        .body(bytes)
        .send()
        .await
        .map_err(|_| {
            "Could not connect to the local evaluation service. Start it in Settings and retry."
                .to_string()
        })?;
    if matches!(response.status().as_u16(), 404 | 405) {
        return Err("Local file import requires the matching new evaluation service image. Update it in Settings; no manual file copy is needed.".into());
    }
    let status = response.status();
    let payload: Value = response
        .json()
        .await
        .map_err(|_| "The local evaluation service returned an invalid response.".to_string())?;
    if status.is_success() {
        Ok(payload)
    } else {
        Err(payload["detail"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| {
                "Dataset file check failed. Check the file and local evaluation service.".into()
            }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_only_bounded_bytes_and_display_filenames() {
        assert!(validate("中文 data.parquet", b"PAR1", "ctxbench").is_ok());
        for path in [
            "../data.parquet",
            "C:\\data.parquet",
            "/root/file.json",
            "x\nfile.json",
        ] {
            assert!(validate(path, b"data", "ctxbench").is_err());
        }
        assert!(validate("data.json", &[], "ctxbench").is_err());
        assert!(validate("data.json", b"[]", "unknown").is_err());
    }
}
