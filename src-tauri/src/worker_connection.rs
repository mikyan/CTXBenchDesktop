//! One immutable, loopback-only destination for every desktop service request.
use serde::Serialize;
use std::sync::OnceLock;

const DEFAULT_PORT: u16 = 48173;
const INVALID_PORT: &str = "CTXBENCH_DEBUG_WORKER_PORT must be an integer between 1 and 65535. No service request was sent.";
const PRODUCTION_PORT: &str = "Debug isolation cannot use the production service port 48173. Choose another local port; no service request was sent.";
pub const ISOLATED_CONTROL_ERROR: &str = "Production environment controls are disabled in isolated acceptance mode. Ask the test coordinator to manage the isolated service.";

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Connection {
    pub base_url: String,
    pub isolated: bool,
}

fn resolve(debug: bool, value: Option<&str>) -> Result<Connection, String> {
    let override_port = if debug { value } else { None };
    let port = match override_port {
        Some(value) => {
            if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
                return Err(INVALID_PORT.into());
            }
            value.parse::<u16>().ok().filter(|port| *port > 0).ok_or(INVALID_PORT)?
        }
        None => DEFAULT_PORT,
    };
    if override_port.is_some() && port == DEFAULT_PORT {
        return Err(PRODUCTION_PORT.into());
    }
    Ok(Connection { base_url: format!("http://127.0.0.1:{port}/v1"), isolated: override_port.is_some() })
}

pub fn current() -> Result<&'static Connection, String> {
    static CONNECTION: OnceLock<Result<Connection, String>> = OnceLock::new();
    CONNECTION.get_or_init(|| {
        #[cfg(debug_assertions)]
        {
            let value = std::env::var_os("CTXBENCH_DEBUG_WORKER_PORT");
            let text = value.as_ref().map(|value| value.to_str().ok_or(INVALID_PORT)).transpose()?;
            resolve(true, text)
        }
        #[cfg(not(debug_assertions))]
        { resolve(false, None) }
    }).as_ref().map_err(Clone::clone)
}

pub fn require_production_controls() -> Result<(), String> {
    if current()?.isolated { Err(ISOLATED_CONTROL_ERROR.into()) } else { Ok(()) }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn debug_override_is_only_a_port_on_loopback() {
        for port in ["1", "48174", "65535"] {
            let connection = resolve(true, Some(port)).unwrap();
            assert_eq!(connection.base_url, format!("http://127.0.0.1:{port}/v1"));
            assert!(connection.isolated);
        }
        assert!(!resolve(true, None).unwrap().isolated);
    }
    #[test]
    fn invalid_override_fails_closed_without_default_fallback() {
        for value in ["", "0", "65536", "-1", "+48174", "48174 ", " 48174", "48174\n", "http://localhost:48174", "example.com", "48174/path", "１２３", "99999999999999999999"] {
            assert_eq!(resolve(true, Some(value)).unwrap_err(), INVALID_PORT);
        }
    }
    #[test]
    fn release_ignores_every_override_even_invalid_ones() {
        for value in [None, Some("48174"), Some("https://example.com"), Some("")] {
            let connection = resolve(false, value).unwrap();
            assert_eq!(connection.base_url, "http://127.0.0.1:48173/v1");
            assert!(!connection.isolated);
        }
    }
    #[test]
    fn isolation_cannot_mislabel_the_production_service() {
        for value in ["48173", "048173", "00048173"] {
            assert_eq!(resolve(true, Some(value)).unwrap_err(), PRODUCTION_PORT);
        }
        assert!(!resolve(true, None).unwrap().isolated);
        assert!(!resolve(false, Some("48173")).unwrap().isolated);
    }
}
