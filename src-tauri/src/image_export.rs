use crate::deployment::{self, ActionResult, MUTATION};
use crate::process_stream::{self, BuildProgress};
use crate::wsl;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::sync::OnceLock;
use std::time::{Duration, Instant};

const ROLES: [&str; 4] = [
    "ctxbench-worker",
    "ctxbench-egress-proxy",
    "agent-pi-image",
    "official-harness-image",
];

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ImageSelection {
    pub role: String,
    pub reference: String,
}

#[derive(Serialize)]
pub struct ImageInventory {
    pub images: Vec<String>,
    pub error: Option<ActionResult>,
}

fn valid_reference(reference: &str) -> bool {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN
        .get_or_init(|| Regex::new(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}$").unwrap())
        .is_match(reference)
}

pub fn export_args(
    tool: &str,
    root: &str,
    output: &str,
    version: &str,
    images: &[ImageSelection],
) -> Result<Vec<String>, String> {
    if images.len() != 4
        || ROLES
            .iter()
            .any(|role| images.iter().filter(|image| image.role == *role).count() != 1)
        || images
            .iter()
            .any(|image| !valid_reference(&image.reference))
    {
        return Err("Invalid export image selection; provide one local image reference for each application role.".into());
    }
    let mut args: Vec<String> = [
        "python3",
        "-I",
        "-u",
        tool,
        "export-local",
        "--root",
        root,
        "--output",
        output,
        "--version",
        version,
        "--progress-json",
    ]
    .iter()
    .map(|value| value.to_string())
    .collect();
    for image in images {
        args.extend([
            "--image".into(),
            format!("{}={}", image.role, image.reference),
        ]);
    }
    Ok(args)
}

fn export_error(detail: &str) -> String {
    if detail.contains("Image credentials detected") {
        "export_credentials".into()
    } else if detail.contains("Export destination already exists") {
        "export_exists".into()
    } else if detail.contains("Invalid export path") {
        "export_path".into()
    } else if detail.contains("Image platform mismatch") {
        "export_platform".into()
    } else if detail.contains("Invalid export image selection") {
        "export_selection".into()
    } else {
        deployment::classify_error(detail, "action")
    }
}

pub fn list_images(root: &Path, distribution: &str) -> ImageInventory {
    let secrets = deployment::secret_values(root);
    match wsl::output(
        distribution,
        &[
            "docker",
            "image",
            "ls",
            "--format",
            "{{.Repository}}:{{.Tag}}",
        ],
    ) {
        Ok(output) => {
            let mut images: Vec<String> = output
                .lines()
                .filter(|line| {
                    valid_reference(line)
                        && !line.contains(":local-export-")
                        && deployment::redact(line, &secrets) == *line
                })
                .map(str::to_string)
                .collect();
            images.sort();
            images.dedup();
            images.truncate(2000);
            ImageInventory {
                images,
                error: None,
            }
        }
        Err(error) => ImageInventory {
            images: vec![],
            error: Some(ActionResult {
                ok: false,
                code: deployment::classify_error(&error, "docker"),
                detail: deployment::redact(&error, &secrets),
                command: None,
            }),
        },
    }
}

pub fn export_images(
    root: &Path,
    distribution: &str,
    output: &Path,
    version: &str,
    images: &[ImageSelection],
    mut progress: impl FnMut(BuildProgress),
) -> ActionResult {
    let secrets = deployment::secret_values(root);
    let fail = |code: &str, detail: String| ActionResult {
        ok: false,
        code: code.into(),
        detail: deployment::redact(&detail, &secrets),
        command: None,
    };
    let _guard = match MUTATION.try_lock() {
        Ok(guard) => guard,
        Err(_) => {
            return fail(
                "action",
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
    if let Err(error) = export_args("", "", "", version, images) {
        return fail("export_selection", error);
    }
    if !output.is_absolute()
        || !output
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("zip"))
        || !output.parent().is_some_and(Path::is_dir)
    {
        return fail(
            "export_path",
            "Choose a new ZIP path in an existing directory.".into(),
        );
    }
    if output.exists() {
        return fail(
            "export_exists",
            "Existing files are never overwritten.".into(),
        );
    }
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
        let value = wsl::output(
            distribution,
            &["wslpath", "-a", &path.display().to_string()],
        )?;
        if !value.starts_with('/') || value.contains(['\r', '\n']) {
            return Err("WSL returned an invalid path.".into());
        }
        Ok(value)
    };
    let paths = [tool.as_path(), root, output];
    let translated: Vec<String> = match paths.into_iter().map(translate).collect::<Result<_, _>>() {
        Ok(paths) => paths,
        Err(error) => return fail("export_path", error),
    };
    let args = export_args(
        &translated[0],
        &translated[1],
        &translated[2],
        version,
        images,
    )
    .unwrap();
    let mut process = std::process::Command::new("wsl.exe");
    process
        .args(["--distribution", distribution, "--exec"])
        .args(args);
    match process_stream::run(
        &mut process,
        Duration::from_secs(3600),
        started,
        |line| deployment::redact(line, &secrets),
        &mut progress,
    ) {
        Ok(detail) => ActionResult {
            ok: true,
            code: "images_export".into(),
            detail,
            command: None,
        },
        Err(detail) => fail(&export_error(&detail), detail),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore = "read-only WSL Docker export preflight; rejects a unique missing image without tagging or exporting"]
    fn real_wsl_export_preflight_and_local_inventory() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
        let temporary =
            std::env::temp_dir().join(format!("ctxbench-export-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&temporary).unwrap();
        let output = temporary.join("离线 包';literal.zip");
        let missing = format!("ctxbench/export-missing:{}", uuid::Uuid::new_v4());
        let images: Vec<_> = ROLES
            .iter()
            .map(|role| ImageSelection {
                role: role.to_string(),
                reference: missing.clone(),
            })
            .collect();
        let mut events = vec![];
        let result = export_images(root, "Ubuntu", &output, "0.1.3", &images, |event| {
            events.push(event)
        });
        assert!(!output.exists());
        // This test only created this empty, uniquely named directory.
        std::fs::remove_dir(&temporary).unwrap();
        assert!(!result.ok);
        assert_eq!(result.code, "images", "{}", result.detail);
        assert!(events.iter().any(|event| {
            event
                .lines
                .iter()
                .any(|line| line.starts_with("CTXBENCH_EXPORT_PROGRESS "))
        }));
        let inventory = list_images(root, "Ubuntu");
        assert!(inventory.error.is_none());
        assert!(
            inventory
                .images
                .iter()
                .all(|reference| valid_reference(reference))
        );
    }

    #[test]
    fn export_preserves_literal_paths_and_rejects_arguments_outside_the_four_roles() {
        let mut images: Vec<_> = ROLES
            .iter()
            .map(|role| ImageSelection {
                role: role.to_string(),
                reference: "registry.internal:5000/team/pi:custom".into(),
            })
            .collect();
        let args = export_args(
            "/mnt/c/Program Files/tool.py",
            "/mnt/c/app",
            "/mnt/d/离线 包/test';x.zip",
            "0.1.3",
            &images,
        )
        .unwrap();
        assert_eq!(args[8], "/mnt/d/离线 包/test';x.zip");
        assert_eq!(args.iter().filter(|arg| *arg == "--image").count(), 4);
        assert!(
            !args
                .iter()
                .any(|arg| arg == "bash" || arg == "commit" || arg == "build")
        );
        images[0].reference = "--help".into();
        assert!(export_args("", "", "", "", &images).is_err());
        images[0].reference = "x;touch /tmp/file".into();
        assert!(export_args("", "", "", "", &images).is_err());
        images[0] = images[1].clone();
        assert!(export_args("", "", "", "", &images).is_err());
        assert_eq!(
            export_error("Image credentials detected"),
            "export_credentials"
        );
        assert_eq!(
            export_error("Export destination already exists"),
            "export_exists"
        );
        assert_eq!(
            export_error("Image bundle error: no space left on device"),
            "disk_space"
        );
    }
}
