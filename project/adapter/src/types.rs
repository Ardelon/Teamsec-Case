use serde_json::json;
use std::collections::HashMap;
use thiserror::Error;

#[derive(Debug, Clone)]
pub struct ErrorLog {
    pub row_number: u32,
    pub field: String,
    pub error_type: String,
    pub message: String,
}

#[derive(Debug, Clone)]
pub struct PipelineMetrics {
    pub total_credits_ingested: u64,
    pub total_payments_ingested: u64,
}

#[derive(Debug, Clone)]
pub struct PipelineResult {
    pub success: bool,
    pub job_id: String,
    pub processed_rows_count: u64,
    pub execution_duration_seconds: f64,
    pub metrics: PipelineMetrics,
    pub error_logs: Vec<ErrorLog>,
}

#[derive(Debug, Clone)]
pub struct ParsedCredit {
    pub loan_account_number: String,
    pub customer_id: String,
    pub customer_type: String,
    pub loan_status_code: String,
    pub days_past_due: Option<i32>,
    pub final_maturity_date: Option<String>,
    pub total_installment_count: Option<i32>,
    pub outstanding_installment_count: Option<i32>,
    pub paid_installment_count: Option<i32>,
    pub first_payment_date: Option<String>,
    pub original_loan_amount: Option<String>,
    pub outstanding_principal_balance: Option<String>,
    pub nominal_interest_rate: Option<String>,
    pub total_interest_amount: Option<String>,
    pub kkdf_rate: Option<String>,
    pub kkdf_amount: Option<String>,
    pub bsmv_rate: Option<String>,
    pub bsmv_amount: Option<String>,
    pub grace_period_months: Option<i32>,
    pub installment_frequency: Option<i32>,
    pub loan_start_date: Option<String>,
    pub loan_closing_date: Option<String>,
    pub internal_rating: Option<i32>,
    pub external_rating: Option<i32>,
    pub retail_specific_attributes: serde_json::Value,
    pub commercial_specific_attributes: serde_json::Value,
}

#[derive(Debug, Clone)]
pub struct ParsedPayment {
    pub loan_account_number: String,
    pub installment_number: i32,
    pub actual_payment_date: Option<String>,
    pub scheduled_payment_date: Option<String>,
    pub installment_amount: Option<String>,
    pub principal_component: Option<String>,
    pub interest_component: Option<String>,
    pub kkdf_component: Option<String>,
    pub bsmv_component: Option<String>,
    pub installment_status: String,
    pub remaining_principal: Option<String>,
    pub remaining_interest: Option<String>,
    pub remaining_kkdf: Option<String>,
    pub remaining_bsmv: Option<String>,
}

#[derive(Debug, Error)]
pub enum PipelineError {
    #[error("HTTP error: {0}")]
    Http(String),
    #[error("CSV parse error: {0}")]
    Parse(String),
    #[error("Database error: {0}")]
    Database(String),
}

pub fn build_retail_attributes(row: &HashMap<String, String>) -> serde_json::Value {
    json!({
        "insurance_included": row.get("insurance_included").cloned().unwrap_or_default(),
        "customer_district_code": row.get("customer_district_code").cloned().unwrap_or_default(),
        "customer_province_code": row
            .get("customer_region_code")
            .or_else(|| row.get("customer_province_code"))
            .cloned()
            .unwrap_or_default(),
    })
}

pub fn build_commercial_attributes(row: &HashMap<String, String>) -> serde_json::Value {
    json!({
        "loan_product_type": parse_optional_int(row.get("loan_product_type")),
        "loan_status_flag": row.get("loan_status_flag").cloned().unwrap_or_default(),
        "customer_region_code": row.get("customer_region_code").cloned().unwrap_or_default(),
        "sector_code": parse_optional_int(row.get("sector_code")),
        "internal_credit_rating": parse_optional_int(row.get("internal_credit_rating")),
        "default_probability": parse_optional_decimal_f64(row.get("default_probability")),
        "risk_class": parse_optional_int(row.get("risk_class")),
        "customer_segment": parse_optional_int(row.get("customer_segment")),
    })
}

fn parse_optional_int(value: Option<&String>) -> Option<i32> {
    value.and_then(|v| v.trim().parse().ok())
}

fn parse_optional_decimal_f64(value: Option<&String>) -> Option<f64> {
    value.and_then(|v| {
        let normalized = v.trim().replace(',', ".");
        normalized.parse().ok()
    })
}
