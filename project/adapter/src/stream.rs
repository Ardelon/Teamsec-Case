use crate::types::PipelineError;
use bytes::Bytes;
use futures_util::{Stream, StreamExt};
use reqwest::Client;
use serde_json::Value;
use std::collections::HashMap;
use std::pin::Pin;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};
use tokio_util::io::StreamReader;

type ByteStream = Pin<Box<dyn Stream<Item = Result<Bytes, std::io::Error>> + Send>>;
type JsonByteReader = BufReader<StreamReader<ByteStream, Bytes>>;

fn map_reqwest_io_error(error: reqwest::Error) -> std::io::Error {
    std::io::Error::new(std::io::ErrorKind::Other, error)
}

fn value_to_string(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::Bool(flag) => flag.to_string(),
        Value::Number(number) => number.to_string(),
        Value::String(text) => text.clone(),
        other => other.to_string(),
    }
}

fn object_to_row(value: Value) -> Result<HashMap<String, String>, PipelineError> {
    let object = value
        .as_object()
        .ok_or_else(|| PipelineError::Parse("expected JSON object row".to_string()))?;

    Ok(object
        .iter()
        .map(|(key, value)| (key.clone(), value_to_string(value)))
        .collect())
}

pub struct JsonRowStream {
    reader: JsonByteReader,
    buffer: Vec<u8>,
    started: bool,
    finished: bool,
    row_number: u32,
}

impl JsonRowStream {
    pub async fn open(client: &Client, url: &str) -> Result<Self, PipelineError> {
        let response = client
            .get(url)
            .send()
            .await
            .map_err(|e| PipelineError::Http(e.to_string()))?;

        let status = response.status();
        if !status.is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "<failed to read response body>".to_string());
            return Err(PipelineError::Http(format!(
                "HTTP {status} from {url}: {body}"
            )));
        }

        let byte_stream: ByteStream = Box::pin(
            response
                .bytes_stream()
                .map(|chunk| chunk.map_err(map_reqwest_io_error)),
        );
        let reader = BufReader::new(StreamReader::new(byte_stream));

        Ok(Self {
            reader,
            buffer: Vec::new(),
            started: false,
            finished: false,
            row_number: 0,
        })
    }

    pub async fn next_row(&mut self) -> Result<Option<HashMap<String, String>>, PipelineError> {
        if self.finished {
            return Ok(None);
        }

        if !self.started {
            self.skip_until(b'[')
                .await
                .map_err(|e| PipelineError::Http(e.to_string()))?;
            self.started = true;
        }

        loop {
            self.skip_whitespace_and_commas()
                .await
                .map_err(|e| PipelineError::Http(e.to_string()))?;

            let next = self
                .peek_byte()
                .await
                .map_err(|e| PipelineError::Http(e.to_string()))?;

            match next {
                None => {
                    self.finished = true;
                    return Ok(None);
                }
                Some(b']') => {
                    let _ = self
                        .reader
                        .read_u8()
                        .await
                        .map_err(|e| PipelineError::Http(e.to_string()))?;
                    self.finished = true;
                    return Ok(None);
                }
                Some(b'{') => {
                    let object_bytes = self
                        .read_json_object()
                        .await
                        .map_err(|e| PipelineError::Parse(e.to_string()))?;
                    let value: Value = serde_json::from_slice(&object_bytes)
                        .map_err(|e| PipelineError::Parse(e.to_string()))?;
                    self.row_number += 1;
                    return Ok(Some(object_to_row(value)?));
                }
                Some(other) => {
                    return Err(PipelineError::Parse(format!(
                        "unexpected JSON array token: {}",
                        other as char
                    )));
                }
            }
        }
    }

    pub fn row_number(&self) -> u32 {
        self.row_number
    }

    async fn peek_byte(&mut self) -> Result<Option<u8>, std::io::Error> {
        let buf = self.reader.fill_buf().await?;
        Ok(buf.first().copied())
    }

    async fn skip_until(&mut self, target: u8) -> Result<(), std::io::Error> {
        loop {
            let buf = self.reader.fill_buf().await?;
            if buf.is_empty() {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::UnexpectedEof,
                    "unexpected end of JSON stream",
                ));
            }
            if let Some(index) = buf.iter().position(|byte| *byte == target) {
                self.reader.consume(index + 1);
                return Ok(());
            }
            let len = buf.len();
            self.reader.consume(len);
        }
    }

    async fn skip_whitespace_and_commas(&mut self) -> Result<(), std::io::Error> {
        loop {
            let buf = self.reader.fill_buf().await?;
            if buf.is_empty() {
                return Ok(());
            }
            let mut consume = 0usize;
            for byte in buf {
                if byte.is_ascii_whitespace() || *byte == b',' {
                    consume += 1;
                } else {
                    break;
                }
            }
            if consume == 0 {
                return Ok(());
            }
            self.reader.consume(consume);
        }
    }

    async fn read_json_object(&mut self) -> Result<Vec<u8>, std::io::Error> {
        self.buffer.clear();
        let mut depth = 0i32;
        let mut in_string = false;
        let mut escape = false;

        loop {
            let byte = self.reader.read_u8().await?;
            self.buffer.push(byte);

            if in_string {
                if escape {
                    escape = false;
                } else if byte == b'\\' {
                    escape = true;
                } else if byte == b'"' {
                    in_string = false;
                }
                continue;
            }

            match byte {
                b'"' => in_string = true,
                b'{' => depth += 1,
                b'}' => {
                    depth -= 1;
                    if depth == 0 {
                        return Ok(self.buffer.clone());
                    }
                }
                _ => {}
            }
        }
    }
}
