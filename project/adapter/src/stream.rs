use crate::types::PipelineError;
use reqwest::Client;
use std::collections::HashMap;

pub async fn fetch_csv_rows(client: &Client, url: &str) -> Result<Vec<HashMap<String, String>>, PipelineError> {
    let response = client
        .get(url)
        .send()
        .await
        .map_err(|e| PipelineError::Http(e.to_string()))?;

    let status = response.status();
    let body = response
        .bytes()
        .await
        .map_err(|e| PipelineError::Http(e.to_string()))?;

    if !status.is_success() {
        let body_text = String::from_utf8_lossy(&body);
        return Err(PipelineError::Http(format!(
            "HTTP {status} from {url}: {body_text}"
        )));
    }

    let mut reader = csv::ReaderBuilder::new()
        .delimiter(b';')
        .flexible(true)
        .from_reader(body.as_ref());

    let headers = reader
        .headers()
        .map_err(|e| PipelineError::Parse(e.to_string()))?
        .iter()
        .map(|h| h.to_string())
        .collect::<Vec<_>>();

    let mut rows = Vec::new();
    for record in reader.records() {
        let record = record.map_err(|e| PipelineError::Parse(e.to_string()))?;
        let mut row = HashMap::new();
        for (header, value) in headers.iter().zip(record.iter()) {
            row.insert(header.clone(), value.to_string());
        }
        rows.push(row);
    }

    Ok(rows)
}
