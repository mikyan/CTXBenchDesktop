use serde::Serialize;
use std::io::Read;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Distribution {
    pub name: String,
    pub state: String,
    pub version: u8,
    pub is_default: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Inventory {
    pub distributions: Vec<Distribution>,
    pub default_distribution: Option<String>,
}

pub fn decode_output(bytes: &[u8]) -> String {
    let utf16 = bytes.starts_with(&[0xff, 0xfe])
        || bytes
            .iter()
            .skip(1)
            .step_by(2)
            .filter(|byte| **byte == 0)
            .count()
            > bytes.len() / 8;
    let text = if utf16 {
        let units: Vec<u16> = bytes
            .chunks_exact(2)
            .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
            .collect();
        String::from_utf16_lossy(&units)
    } else {
        String::from_utf8_lossy(bytes).into_owned()
    };
    text.trim_matches(['\u{feff}', '\0']).trim().to_string()
}

// Parse from the right: names may contain spaces, and column headings/states
// are localized by Windows. Never infer WSL version from the kernel name.
pub fn parse_distributions(text: &str) -> Result<Vec<Distribution>, String> {
    let mut distributions = Vec::new();
    for (index, line) in text
        .trim_start_matches('\u{feff}')
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .enumerate()
    {
        let is_default = line.starts_with('*');
        let row = line.trim_start_matches('*').trim();
        let parsed = row
            .rsplit_once(char::is_whitespace)
            .and_then(|(prefix, version)| {
                let version = version
                    .parse::<u8>()
                    .ok()
                    .filter(|value| matches!(value, 1 | 2))?;
                let (name, state) = prefix.trim_end().rsplit_once(char::is_whitespace)?;
                let name = name.trim();
                if name.is_empty() || state.is_empty() {
                    return None;
                }
                Some(Distribution {
                    name: name.into(),
                    state: state.into(),
                    version,
                    is_default,
                })
            });
        if let Some(distribution) = parsed {
            distributions.push(distribution);
        } else if index != 0 || is_default {
            return Err(format!(
                "Could not parse wsl --list --verbose output:\n{text}"
            ));
        }
    }
    if distributions.is_empty() && !text.trim().is_empty() {
        return Err(format!(
            "No distribution versions found in wsl --list --verbose output:\n{text}"
        ));
    }
    Ok(distributions)
}

pub fn preferred_distribution(distributions: &[Distribution]) -> Option<&Distribution> {
    let candidates: Vec<_> = distributions
        .iter()
        .filter(|item| !item.name.to_ascii_lowercase().starts_with("docker-desktop"))
        .collect();
    candidates
        .iter()
        .copied()
        .find(|item| item.is_default && item.version == 2)
        .or_else(|| candidates.iter().copied().find(|item| item.version == 2))
        .or_else(|| candidates.iter().copied().find(|item| item.is_default))
        .or_else(|| candidates.first().copied())
}

pub fn selected_distribution(
    distributions: &[Distribution],
    requested: Option<&str>,
) -> Option<String> {
    match requested.map(str::trim).filter(|name| !name.is_empty()) {
        Some(name) => Some(
            distributions
                .iter()
                .find(|item| item.name.eq_ignore_ascii_case(name))
                .map(|item| item.name.as_str())
                .unwrap_or(name)
                .to_string(),
        ),
        None => preferred_distribution(distributions).map(|item| item.name.clone()),
    }
}

fn failure_output(stdout: &[u8], stderr: &[u8], status: &str) -> String {
    let stdout = decode_output(stdout);
    let stderr = decode_output(stderr);
    let detail = [stdout.as_str(), stderr.as_str()]
        .into_iter()
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("\n");
    if detail.is_empty() {
        format!("wsl.exe failed ({status}).")
    } else {
        detail
    }
}

fn run(args: &[&str], timeout: Duration) -> Result<String, String> {
    let mut command = Command::new("wsl.exe");
    command
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("Could not start wsl.exe: {error}"))?;
    // Drain both pipes while the process runs so verbose errors cannot deadlock it.
    let read_pipe = |mut pipe: Box<dyn Read + Send>| {
        std::thread::spawn(move || {
            let mut bytes = Vec::new();
            pipe.read_to_end(&mut bytes).map(|_| bytes)
        })
    };
    let stdout = read_pipe(Box::new(child.stdout.take().unwrap()));
    let stderr = read_pipe(Box::new(child.stderr.take().unwrap()));
    let deadline = Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(50)),
            result => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(match result {
                    Err(error) => format!("Could not wait for wsl.exe: {error}"),
                    _ => format!(
                        "wsl.exe {} timed out after {} seconds.",
                        args.join(" "),
                        timeout.as_secs()
                    ),
                });
            }
        }
    };
    let stdout = stdout
        .join()
        .map_err(|_| "Could not read WSL stdout.".to_string())?
        .map_err(|error| error.to_string())?;
    let stderr = stderr
        .join()
        .map_err(|_| "Could not read WSL stderr.".to_string())?
        .map_err(|error| error.to_string())?;
    if status.success() {
        Ok(decode_output(&stdout))
    } else {
        Err(failure_output(&stdout, &stderr, &status.to_string()))
    }
}

pub fn inventory() -> Result<Inventory, String> {
    let output = run(&["--list", "--verbose"], Duration::from_secs(30))?;
    let distributions = parse_distributions(&output)?;
    let default_distribution = preferred_distribution(&distributions).map(|item| item.name.clone());
    Ok(Inventory {
        distributions,
        default_distribution,
    })
}

pub fn output(distribution: &str, args: &[&str]) -> Result<String, String> {
    output_with_timeout(distribution, args, Duration::from_secs(60))
}

pub fn output_with_timeout(
    distribution: &str,
    args: &[&str],
    timeout: Duration,
) -> Result<String, String> {
    let mut arguments = vec!["--distribution", distribution, "--exec"];
    arguments.extend_from_slice(args);
    run(&arguments, timeout)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_localized_utf16_and_default_marker() {
        let bytes: Vec<_> = "\u{feff}  名称              状态       版本\r\n* Ubuntu-24.04      已停止     2\r\n  Debian            正在运行   1\r\n\0"
            .encode_utf16().flat_map(u16::to_le_bytes).collect();
        let items = parse_distributions(&decode_output(&bytes)).unwrap();
        assert_eq!(
            items[0],
            Distribution {
                name: "Ubuntu-24.04".into(),
                state: "已停止".into(),
                version: 2,
                is_default: true
            }
        );
        assert_eq!(items[1].version, 1);
        assert!(!items[1].is_default);
        assert_eq!(
            selected_distribution(&items, Some(" ubuntu-24.04 ")).as_deref(),
            Some("Ubuntu-24.04")
        );
    }

    #[test]
    fn parses_english_names_with_spaces_and_no_default() {
        let items = parse_distributions(
            "NAME STATE VERSION\n  Company Linux    Stopped    2\n  Ubuntu\tRunning\t1",
        )
        .unwrap();
        assert_eq!(items[0].name, "Company Linux");
        assert_eq!(items[1].state, "Running");
        assert_eq!(
            preferred_distribution(&items).unwrap().name,
            "Company Linux"
        );
    }

    #[test]
    fn prefers_user_wsl2_over_default_wsl1_or_docker_internal_distros() {
        let items = parse_distributions("NAME STATE VERSION\n* Legacy Stopped 1\n  docker-desktop Running 2\n  Ubuntu-24.04 Stopped 2").unwrap();
        assert_eq!(
            selected_distribution(&items, None).as_deref(),
            Some("Ubuntu-24.04")
        );
        assert_eq!(
            selected_distribution(&items, Some("Legacy")).as_deref(),
            Some("Legacy")
        );
        // Do not silently redirect an explicitly configured runtime to a different one.
        assert_eq!(
            selected_distribution(&items, Some("Company-WSL")).as_deref(),
            Some("Company-WSL")
        );
        assert!(preferred_distribution(&items[1..2]).is_none());
        assert_eq!(preferred_distribution(&items[..1]).unwrap().version, 1);
    }

    #[test]
    fn prefers_default_wsl2_and_rejects_unrecognized_output() {
        let items =
            parse_distributions("NAME STATE VERSION\n  Ubuntu Running 2\n* Debian Stopped 2")
                .unwrap();
        assert_eq!(preferred_distribution(&items).unwrap().name, "Debian");
        assert_eq!(parse_distributions("").unwrap(), vec![]);
        assert!(
            parse_distributions("Windows Subsystem for Linux has no installed distributions.")
                .is_err()
        );
        assert!(parse_distributions("NAME STATE VERSION\n* Ubuntu Stopped unknown").is_err());
        assert!(
            parse_distributions("NAME STATE VERSION\n  Ubuntu Running 2\n  Broken output").is_err()
        );
    }

    #[test]
    fn preserves_stdout_only_errors_and_decodes_utf8() {
        assert_eq!(
            failure_output(b"Distro not found", b"", "1"),
            "Distro not found"
        );
        assert_eq!(
            failure_output(b"Failure", b"Details", "1"),
            "Failure\nDetails"
        );
        assert!(failure_output(b"", b"", "1").contains('1'));
        assert_eq!(decode_output("\u{feff}错误信息\r\n".as_bytes()), "错误信息");
    }

    // Explicit, read-only integration check; ordinary CI does not require WSL.
    #[test]
    #[ignore = "requires WSL installed on the Windows host"]
    fn installed_wsl_inventory() {
        let inventory = inventory().expect("WSL enumeration failed");
        assert!(!inventory.distributions.is_empty());
        println!("{}", serde_json::to_string(&inventory).unwrap());
    }
}
