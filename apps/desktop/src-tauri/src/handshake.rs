use serde::Deserialize;
use thiserror::Error;

const SUPPORTED_PROTOCOL_VERSION: u16 = 1;

#[derive(Debug, Error, PartialEq)]
pub enum HandshakeError {
    #[error("invalid ready message JSON")]
    InvalidJson,
    #[error("unexpected ready message type")]
    InvalidType,
    #[error("unsupported protocol version {0}")]
    UnsupportedProtocol(u16),
    #[error("runtime must bind to the IPv4 loopback address")]
    InvalidHost,
    #[error("runtime returned an invalid port")]
    InvalidPort,
    #[error("runtime pid mismatch: expected {expected}, got {actual}")]
    PidMismatch { expected: u32, actual: u32 },
}

#[derive(Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ReadyMessage {
    #[serde(rename = "type")]
    kind: String,
    pub protocol_version: u16,
    host: String,
    port: u16,
    pid: u32,
}

impl ReadyMessage {
    pub fn parse_and_validate(input: &str, expected_pid: u32) -> Result<Self, HandshakeError> {
        let message: Self = serde_json::from_str(input).map_err(|_| HandshakeError::InvalidJson)?;
        if message.kind != "ready" {
            return Err(HandshakeError::InvalidType);
        }
        if message.protocol_version != SUPPORTED_PROTOCOL_VERSION {
            return Err(HandshakeError::UnsupportedProtocol(
                message.protocol_version,
            ));
        }
        if message.host != "127.0.0.1" {
            return Err(HandshakeError::InvalidHost);
        }
        if message.port == 0 {
            return Err(HandshakeError::InvalidPort);
        }
        if message.pid != expected_pid {
            return Err(HandshakeError::PidMismatch {
                expected: expected_pid,
                actual: message.pid,
            });
        }
        Ok(message)
    }

    pub fn base_url(&self) -> String {
        format!("http://{}:{}", self.host, self.port)
    }
}

#[cfg(test)]
mod tests {
    use super::{HandshakeError, ReadyMessage};

    #[test]
    fn parses_valid_ready_message() {
        let message =
            r#"{"type":"ready","protocol_version":1,"host":"127.0.0.1","port":43127,"pid":12040}"#;
        let parsed = ReadyMessage::parse_and_validate(message, 12040).unwrap();
        assert_eq!(parsed.base_url(), "http://127.0.0.1:43127");
    }

    #[test]
    fn rejects_non_loopback_host() {
        let message =
            r#"{"type":"ready","protocol_version":1,"host":"0.0.0.0","port":43127,"pid":12040}"#;
        assert!(matches!(
            ReadyMessage::parse_and_validate(message, 12040),
            Err(HandshakeError::InvalidHost)
        ));
    }

    #[test]
    fn rejects_wrong_protocol_or_pid() {
        let protocol =
            r#"{"type":"ready","protocol_version":2,"host":"127.0.0.1","port":43127,"pid":12040}"#;
        let pid =
            r#"{"type":"ready","protocol_version":1,"host":"127.0.0.1","port":43127,"pid":99}"#;
        assert!(matches!(
            ReadyMessage::parse_and_validate(protocol, 12040),
            Err(HandshakeError::UnsupportedProtocol(2))
        ));
        assert!(matches!(
            ReadyMessage::parse_and_validate(pid, 12040),
            Err(HandshakeError::PidMismatch { .. })
        ));
    }
}
