//! Explicit acceptance probe: never open a browser during ordinary CI/test runs.
#[test]
#[cfg(windows)]
#[ignore = "Opens the release page in the system browser; run explicitly on an interactive Windows desktop"]
fn opens_release_downloads_in_default_browser() {
    let capability: serde_json::Value = serde_json::from_str(include_str!("../capabilities/default.json")).unwrap();
    let opener = capability["permissions"].as_array().unwrap().iter()
        .find(|permission| permission["identifier"] == "opener:allow-open-url").unwrap();
    let url = "https://github.com/mikyan/CTXBenchDesktop/releases";
    assert!(opener["allow"].as_array().unwrap().iter().any(|entry| entry["url"] == url));
    tauri_plugin_opener::open_url(url, None::<&str>).expect("Windows could not open the default browser");
}
