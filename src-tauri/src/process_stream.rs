//! Bounded, line-framed process output. Raw bytes never cross the IPC boundary.
use serde::Serialize;
use std::collections::VecDeque;
use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::mpsc::{SyncSender, sync_channel};
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BuildProgress {
    pub phase: &'static str,
    pub lines: Vec<String>,
    pub elapsed_ms: u64,
    pub last_output_ms: Option<u64>,
}

#[derive(Default)]
struct Lines {
    bytes: Vec<u8>,
    omitted: bool,
}

impl Lines {
    fn push(&mut self, bytes: &[u8], emit: &mut impl FnMut(String)) {
        for &byte in bytes {
            if matches!(byte, b'\n' | b'\r') {
                self.finish(emit);
            } else if !self.omitted {
                if self.bytes.len() == 65_536 {
                    // Never emit a prefix of an oversized line: it may split a secret.
                    self.bytes.clear();
                    self.omitted = true;
                } else {
                    self.bytes.push(byte);
                }
            }
        }
    }

    fn finish(&mut self, emit: &mut impl FnMut(String)) {
        if self.omitted {
            emit("[Long output line omitted]".into());
        } else if !self.bytes.is_empty() {
            emit(String::from_utf8_lossy(&self.bytes).into_owned());
        }
        self.bytes.clear();
        self.omitted = false;
    }
}

enum Output {
    Bytes(usize, Vec<u8>),
    End(usize, bool),
}

fn reader(mut pipe: impl Read + Send + 'static, stream: usize, sender: SyncSender<Output>) {
    std::thread::spawn(move || {
        let mut buffer = [0; 4096];
        loop {
            match pipe.read(&mut buffer) {
                Ok(0) => {
                    let _ = sender.send(Output::End(stream, false));
                    break;
                }
                Ok(count) => {
                    if sender
                        .send(Output::Bytes(stream, buffer[..count].to_vec()))
                        .is_err()
                    {
                        break;
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(_) => {
                    let _ = sender.send(Output::End(stream, true));
                    break;
                }
            }
        }
    });
}

pub fn run(
    command: &mut Command,
    timeout: Duration,
    started: Instant,
    sanitize: impl Fn(&str) -> String,
    progress: &mut impl FnMut(BuildProgress),
) -> Result<String, String> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW, including streamed builds.
    }
    let mut child = command
        .spawn()
        .map_err(|error| sanitize(&format!("Could not start build process: {error}")))?;
    let (sender, receiver) = sync_channel(32);
    reader(child.stdout.take().unwrap(), 0, sender.clone());
    reader(child.stderr.take().unwrap(), 1, sender);
    let deadline = Instant::now() + timeout;
    let mut streams = [Lines::default(), Lines::default()];
    let mut ended = [false, false];
    let mut read_failed = false;
    let mut status = None;
    let mut last_output_ms = None;
    let mut last_sent = Instant::now();
    let mut batch = Vec::new();
    let mut tail = VecDeque::<String>::new();
    let mut tail_bytes = 0;
    let mut failure = None;
    loop {
        // Check time even under continuous output, not just when a pipe is idle.
        if Instant::now() >= deadline {
            failure = Some(format!(
                "Build command timed out after {} seconds. Docker may still be working; inspect it before retrying.",
                timeout.as_secs()
            ));
            break;
        }
        if status.is_none() {
            match child.try_wait() {
                Ok(value) => status = value,
                Err(_) => {
                    failure = Some("Could not wait for build process.".into());
                    break;
                }
            }
        }
        let mut emit = |line: String| {
            let clean = sanitize(&line);
            tail_bytes += clean.len();
            tail.push_back(clean.clone());
            while tail.len() > 500 || (tail_bytes > 24_000 && tail.len() > 1) {
                tail_bytes -= tail.pop_front().unwrap().len();
            }
            batch.push(clean);
        };
        match receiver.recv_timeout(Duration::from_millis(50)) {
            Ok(Output::Bytes(index, bytes)) => {
                last_output_ms = Some(started.elapsed().as_millis() as u64);
                streams[index].push(&bytes, &mut emit);
            }
            Ok(Output::End(index, failed)) => {
                read_failed |= failed;
                ended[index] = true;
                streams[index].finish(&mut emit);
            }
            Err(_) => {}
        }
        let finished = status.is_some() && ended.iter().all(|value| *value);
        if finished || batch.len() >= 128 || last_sent.elapsed() >= Duration::from_millis(250) {
            progress(BuildProgress {
                phase: "building",
                lines: std::mem::take(&mut batch),
                elapsed_ms: started.elapsed().as_millis() as u64,
                last_output_ms,
            });
            last_sent = Instant::now();
        }
        if finished {
            break;
        }
    }
    if failure.is_some() {
        let _ = child.kill();
        let _ = child.wait();
        // Do not wait forever for pipes held by grandchildren, or publish partial secrets.
    }
    if !batch.is_empty() {
        progress(BuildProgress {
            phase: "building",
            lines: batch,
            elapsed_ms: started.elapsed().as_millis() as u64,
            last_output_ms,
        });
    }
    let detail = tail.into_iter().collect::<Vec<_>>().join("\n");
    if let Some(error) = failure {
        Err(format!("{detail}\n{error}"))
    } else if read_failed {
        Err(format!(
            "{detail}\nCould not read build output; completion could not be verified."
        ))
    } else if status.unwrap().success() {
        Ok(detail)
    } else {
        Err(format!(
            "{detail}\nBuild process failed ({}).",
            status.unwrap()
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frames_utf8_and_secrets_across_chunks_and_bounds_long_lines() {
        let mut lines = Lines::default();
        let mut result = Vec::new();
        let mut emit = |line: String| {
            result.push(crate::deployment::redact(
                &line,
                &["test-secret-value".into()],
            ))
        };
        for byte in "安装 test-secret-value\r\n#1 DONE\nlast".as_bytes() {
            lines.push(&[*byte], &mut emit);
        }
        lines.finish(&mut emit);
        lines.push(&vec![b'x'; 100_000], &mut emit);
        lines.push(b"\n", &mut emit);
        assert_eq!(
            result,
            [
                "安装 [REDACTED]",
                "#1 DONE",
                "last",
                "[Long output line omitted]"
            ]
        );
    }

    #[cfg(windows)]
    fn shell(script: &str) -> Command {
        let mut command = Command::new("powershell.exe");
        command.args(["-NoProfile", "-NonInteractive", "-Command", script]);
        command
    }

    #[test]
    #[cfg(windows)]
    fn streams_both_pipes_before_exit_and_keeps_failure_tail() {
        let started = Instant::now();
        let mut events = Vec::new();
        let result = run(
            &mut shell(
                "[Console]::Out.WriteLine('#1 RUN install'); [Console]::Error.WriteLine('token=test-only-credential'); Start-Sleep -Milliseconds 900; [Console]::Error.Write('last failure'); exit 7",
            ),
            Duration::from_secs(15),
            started,
            |line| crate::deployment::redact(line, &[]),
            &mut |event| events.push((Instant::now(), event)),
        );
        let finished = Instant::now();
        let detail = result.unwrap_err();
        assert!(detail.contains("last failure"));
        assert!(!detail.contains("test-only-credential"));
        let first = events
            .iter()
            .find(|(_, event)| event.lines.iter().any(|line| line.contains("RUN install")))
            .unwrap();
        assert!(finished.duration_since(first.0) >= Duration::from_millis(400));
        assert!(
            events
                .iter()
                .any(|(_, event)| event.lines.is_empty() && event.last_output_ms.is_some())
        );
    }

    #[test]
    #[cfg(windows)]
    fn timeout_is_bounded_and_does_not_claim_docker_cancellation() {
        let started = Instant::now();
        let mut events = Vec::new();
        let result = run(
            &mut shell("Start-Sleep -Seconds 30"),
            Duration::from_millis(600),
            started,
            str::to_string,
            &mut |event| events.push(event),
        );
        assert!(result.unwrap_err().contains("Docker may still be working"));
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(!events.is_empty());
    }
}
