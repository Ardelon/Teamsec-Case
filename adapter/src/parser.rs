use crate::types::ErrorLog;
use chrono::NaiveDate;
use regex::Regex;
use rust_decimal::Decimal;
use std::str::FromStr;
use std::sync::OnceLock;

fn date_formats() -> &'static [(Regex, &'static str)] {
    static FORMATS: OnceLock<Vec<(Regex, &'static str)>> = OnceLock::new();
    FORMATS.get_or_init(|| {
        vec![
            (Regex::new(r"^\d{8}$").expect("valid date regex"), "%Y%m%d"),
            (
                Regex::new(r"^\d{4}-\d{2}-\d{2}$").expect("valid date regex"),
                "%Y-%m-%d",
            ),
            (
                Regex::new(r"^\d{2}\.\d{2}\.\d{4}$").expect("valid date regex"),
                "%d.%m.%Y",
            ),
        ]
    })
}

pub fn parse_date(value: Option<&str>, field: &str, row_number: u32) -> Result<Option<String>, ErrorLog> {
    let raw = match value.map(str::trim).filter(|v| !v.is_empty()) {
        Some(v) => v,
        None => return Ok(None),
    };

    for (re, fmt) in date_formats() {
        if re.is_match(raw) {
            if let Ok(parsed) = NaiveDate::parse_from_str(raw, fmt) {
                return Ok(Some(parsed.format("%Y-%m-%d").to_string()));
            }
        }
    }

    Err(ErrorLog {
        row_number,
        field: field.to_string(),
        error_type: "INVALID_DATE_FORMAT".to_string(),
        message: format!(
            "Value '{raw}' could not be resolved to a standardized format."
        ),
    })
}

pub fn parse_decimal(
    value: Option<&str>,
    field: &str,
    row_number: u32,
) -> Result<Option<String>, ErrorLog> {
    let raw = match value.map(str::trim).filter(|v| !v.is_empty()) {
        Some(v) => v,
        None => return Ok(None),
    };

    let normalized = raw.replace(',', ".");
    match Decimal::from_str(&normalized) {
        Ok(_) => Ok(Some(normalized)),
        Err(_) => Err(ErrorLog {
            row_number,
            field: field.to_string(),
            error_type: "INVALID_NUMERIC".to_string(),
            message: "Unable to convert string raw item into exact decimal parameters.".to_string(),
        }),
    }
}

pub fn parse_int(value: Option<&str>) -> Option<i32> {
    value
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .and_then(|v| v.parse().ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_yyyymmdd() {
        let result = parse_date(Some("20250901"), "final_maturity_date", 1).unwrap();
        assert_eq!(result, Some("2025-09-01".to_string()));
    }

    #[test]
    fn parses_iso_date() {
        let result = parse_date(Some("2025-09-02"), "scheduled_payment_date", 1).unwrap();
        assert_eq!(result, Some("2025-09-02".to_string()));
    }

    #[test]
    fn parses_european_date() {
        let result = parse_date(Some("15.01.2024"), "loan_start_date", 1).unwrap();
        assert_eq!(result, Some("2024-01-15".to_string()));
    }

    #[test]
    fn rejects_invalid_date() {
        let err = parse_date(Some("35.01.2024"), "final_maturity_date", 14).unwrap_err();
        assert_eq!(err.error_type, "INVALID_DATE_FORMAT");
    }

    #[test]
    fn parses_decimal() {
        let result = parse_decimal(Some("1234,56"), "kkdf_component", 1).unwrap();
        assert_eq!(result, Some("1234.56".to_string()));
    }

    #[test]
    fn rejects_invalid_decimal() {
        let err = parse_decimal(Some("not-a-number"), "kkdf_component", 45).unwrap_err();
        assert_eq!(err.error_type, "INVALID_NUMERIC");
    }
}
