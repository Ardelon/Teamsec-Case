use crate::db::{open_database_client, SnapshotWriter};
use crate::parser::{parse_date, parse_decimal, parse_int};
use crate::profiler::WelfordProfiler;
use crate::stream::JsonRowStream;
use crate::types::{
    build_commercial_attributes, build_retail_attributes, ErrorLog, ParsedCredit, ParsedPayment,
    PipelineMetrics, PipelineResult,
};
use pyo3::prelude::*;
use reqwest::Client;
use std::collections::HashSet;
use std::collections::HashMap;
use std::time::Instant;

pub type ProgressCallback = Option<PyObject>;

pub struct ProgressState<'a> {
    pub callback: &'a ProgressCallback,
    pub total_rows: u64,
    pub processed_rows: u64,
    pub errors: &'a [ErrorLog],
}

impl<'a> ProgressState<'a> {
    pub fn emit(&self, py: Python, processed_rows: u64, progress_percentage: u8) -> PyResult<()> {
        if let Some(callback) = self.callback {
            // Cap payload size — cloning all errors into Python every tick dominated runtime.
            const MAX_PROGRESS_ERRORS: usize = 50;
            let start = self.errors.len().saturating_sub(MAX_PROGRESS_ERRORS);
            let errors: Vec<(u32, String, String, String)> = self.errors[start..]
                .iter()
                .map(|e| {
                    (
                        e.row_number,
                        e.field.clone(),
                        e.error_type.clone(),
                        e.message.clone(),
                    )
                })
                .collect();
            callback.call1(py, (processed_rows, progress_percentage, errors))?;
        }
        Ok(())
    }
}

fn credit_phase_progress(row_number: u32) -> u8 {
    let rows = row_number as u64;
    (5 + (rows.saturating_mul(35) / rows.saturating_add(10_000)).min(39)) as u8
}

fn payment_phase_progress(payment_row: u32, credit_count: u64) -> u8 {
    let payments = payment_row as u64;
    let credits = credit_count.max(1);
    (40 + (payments.saturating_mul(50) / payments.saturating_add(credits)).min(50)) as u8
}

fn collect_date(
    row_errors: &mut Vec<ErrorLog>,
    value: Option<&str>,
    field: &str,
    row_number: u32,
) -> Option<String> {
    match parse_date(value, field, row_number) {
        Ok(v) => v,
        Err(err) => {
            row_errors.push(err);
            None
        }
    }
}

fn collect_decimal(
    row_errors: &mut Vec<ErrorLog>,
    value: Option<&str>,
    field: &str,
    row_number: u32,
) -> Option<String> {
    match parse_decimal(value, field, row_number) {
        Ok(v) => v,
        Err(err) => {
            row_errors.push(err);
            None
        }
    }
}

fn parse_credit_row(
    row: &HashMap<String, String>,
    row_number: u32,
    loan_type: &str,
    row_errors: &mut Vec<ErrorLog>,
) -> Option<ParsedCredit> {
    let account = row.get("loan_account_number").map(|s| s.trim().to_string()).unwrap_or_default();
    if account.is_empty() {
        row_errors.push(ErrorLog {
            row_number,
            field: "loan_account_number".to_string(),
            error_type: "VALIDATION_ERROR".to_string(),
            message: "Missing loan_account_number".to_string(),
        });
        return None;
    }

    let loan_type_upper = loan_type.to_uppercase();
    let (retail_attrs, commercial_attrs) = if loan_type_upper == "RETAIL" {
        (build_retail_attributes(row), serde_json::json!({}))
    } else {
        (serde_json::json!({}), build_commercial_attributes(row))
    };

    Some(ParsedCredit {
        loan_account_number: account,
        customer_id: row.get("customer_id").cloned().unwrap_or_default(),
        customer_type: row.get("customer_type").cloned().unwrap_or_default(),
        loan_status_code: row.get("loan_status_code").cloned().unwrap_or_default(),
        days_past_due: parse_int(row.get("days_past_due").map(|s| s.as_str())),
        final_maturity_date: collect_date(row_errors, row.get("final_maturity_date").map(|s| s.as_str()), "final_maturity_date", row_number),
        total_installment_count: parse_int(row.get("total_installment_count").map(|s| s.as_str())),
        outstanding_installment_count: parse_int(row.get("outstanding_installment_count").map(|s| s.as_str())),
        paid_installment_count: parse_int(row.get("paid_installment_count").map(|s| s.as_str())),
        first_payment_date: collect_date(row_errors, row.get("first_payment_date").map(|s| s.as_str()), "first_payment_date", row_number),
        original_loan_amount: collect_decimal(row_errors, row.get("original_loan_amount").map(|s| s.as_str()), "original_loan_amount", row_number),
        outstanding_principal_balance: collect_decimal(row_errors, row.get("outstanding_principal_balance").map(|s| s.as_str()), "outstanding_principal_balance", row_number),
        nominal_interest_rate: collect_decimal(row_errors, row.get("nominal_interest_rate").map(|s| s.as_str()), "nominal_interest_rate", row_number),
        total_interest_amount: collect_decimal(row_errors, row.get("total_interest_amount").map(|s| s.as_str()), "total_interest_amount", row_number),
        kkdf_rate: collect_decimal(row_errors, row.get("kkdf_rate").map(|s| s.as_str()), "kkdf_rate", row_number),
        kkdf_amount: collect_decimal(row_errors, row.get("kkdf_amount").map(|s| s.as_str()), "kkdf_amount", row_number),
        bsmv_rate: collect_decimal(row_errors, row.get("bsmv_rate").map(|s| s.as_str()), "bsmv_rate", row_number),
        bsmv_amount: collect_decimal(row_errors, row.get("bsmv_amount").map(|s| s.as_str()), "bsmv_amount", row_number),
        grace_period_months: parse_int(row.get("grace_period_months").map(|s| s.as_str())),
        installment_frequency: parse_int(row.get("installment_frequency").map(|s| s.as_str())),
        loan_start_date: collect_date(row_errors, row.get("loan_start_date").map(|s| s.as_str()), "loan_start_date", row_number),
        loan_closing_date: collect_date(row_errors, row.get("loan_closing_date").map(|s| s.as_str()), "loan_closing_date", row_number),
        internal_rating: parse_int(row.get("internal_rating").map(|s| s.as_str())),
        external_rating: parse_int(row.get("external_rating").map(|s| s.as_str())),
        retail_specific_attributes: retail_attrs,
        commercial_specific_attributes: commercial_attrs,
    })
}

fn parse_payment_row(
    row: &HashMap<String, String>,
    row_number: u32,
    known_accounts: &HashSet<String>,
    row_errors: &mut Vec<ErrorLog>,
) -> Option<ParsedPayment> {
    let account = row.get("loan_account_number").map(|s| s.trim().to_string()).unwrap_or_default();
    if account.is_empty() {
        row_errors.push(ErrorLog {
            row_number,
            field: "loan_account_number".to_string(),
            error_type: "VALIDATION_ERROR".to_string(),
            message: "Missing loan_account_number".to_string(),
        });
        return None;
    }

    if !known_accounts.contains(&account) {
        row_errors.push(ErrorLog {
            row_number,
            field: "loan_account_number".to_string(),
            error_type: "VALIDATION_ERROR".to_string(),
            message: format!("Unknown loan_account_number {account}"),
        });
        return None;
    }

    Some(ParsedPayment {
        loan_account_number: account,
        installment_number: parse_int(row.get("installment_number").map(|s| s.as_str())).unwrap_or(0),
        actual_payment_date: collect_date(row_errors, row.get("actual_payment_date").map(|s| s.as_str()), "actual_payment_date", row_number),
        scheduled_payment_date: collect_date(row_errors, row.get("scheduled_payment_date").map(|s| s.as_str()), "scheduled_payment_date", row_number),
        installment_amount: collect_decimal(row_errors, row.get("installment_amount").map(|s| s.as_str()), "installment_amount", row_number),
        principal_component: collect_decimal(row_errors, row.get("principal_component").map(|s| s.as_str()), "principal_component", row_number),
        interest_component: collect_decimal(row_errors, row.get("interest_component").map(|s| s.as_str()), "interest_component", row_number),
        kkdf_component: collect_decimal(row_errors, row.get("kkdf_component").map(|s| s.as_str()), "kkdf_component", row_number),
        bsmv_component: collect_decimal(row_errors, row.get("bsmv_component").map(|s| s.as_str()), "bsmv_component", row_number),
        installment_status: row.get("installment_status").cloned().unwrap_or_default(),
        remaining_principal: collect_decimal(row_errors, row.get("remaining_principal").map(|s| s.as_str()), "remaining_principal", row_number),
        remaining_interest: collect_decimal(row_errors, row.get("remaining_interest").map(|s| s.as_str()), "remaining_interest", row_number),
        remaining_kkdf: collect_decimal(row_errors, row.get("remaining_kkdf").map(|s| s.as_str()), "remaining_kkdf", row_number),
        remaining_bsmv: collect_decimal(row_errors, row.get("remaining_bsmv").map(|s| s.as_str()), "remaining_bsmv", row_number),
    })
}

pub async fn run_pipeline(
    py: Python<'_>,
    job_id: String,
    tenant_id: String,
    loan_type: String,
    bank_credits_url: String,
    bank_payments_url: String,
    database_url: String,
    on_progress: ProgressCallback,
) -> PyResult<PipelineResult> {
    let started = Instant::now();
    let http_client = Client::new();
    let loan_type_upper = loan_type.to_uppercase();
    let mut error_logs = Vec::new();
    let mut profiler = WelfordProfiler::new();
    let mut known_accounts = HashSet::new();
    let mut processed_rows = 0u64;

    let (mut db_client, _connection_task) = open_database_client(&database_url)
        .await
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    let mut writer = SnapshotWriter::begin(&mut db_client, &tenant_id, &loan_type_upper)
        .await
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    let mut credit_stream = JsonRowStream::open(&http_client, &bank_credits_url)
        .await
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    while let Some(row) = credit_stream
        .next_row()
        .await
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?
    {
        let row_number = credit_stream.row_number();
        if let Some(credit) = parse_credit_row(&row, row_number, &loan_type, &mut error_logs) {
            if let Some(amount) = credit
                .original_loan_amount
                .as_ref()
                .and_then(|v| v.parse::<f64>().ok())
            {
                profiler.observe(Some(amount));
            } else {
                profiler.observe(None);
            }
            known_accounts.insert(credit.loan_account_number.clone());
            writer
                .push_credit(credit)
                .await
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        }

        processed_rows += 1;
        if row_number % 2_000 == 0 {
            let state = ProgressState {
                callback: &on_progress,
                total_rows: processed_rows,
                processed_rows,
                errors: &error_logs,
            };
            state.emit(py, processed_rows, credit_phase_progress(row_number))?;
        }
    }

    writer
        .flush_credits()
        .await
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    let credit_count = writer.credits_ingested();
    {
        let state = ProgressState {
            callback: &on_progress,
            total_rows: processed_rows,
            processed_rows,
            errors: &error_logs,
        };
        state.emit(py, processed_rows, 40)?;
    }

    let mut payment_stream = JsonRowStream::open(&http_client, &bank_payments_url)
        .await
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    while let Some(row) = payment_stream
        .next_row()
        .await
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?
    {
        let row_number = payment_stream.row_number();
        if let Some(payment) = parse_payment_row(&row, row_number, &known_accounts, &mut error_logs) {
            writer
                .push_payment(payment)
                .await
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        }

        processed_rows += 1;
        if row_number % 2_000 == 0 {
            let state = ProgressState {
                callback: &on_progress,
                total_rows: processed_rows,
                processed_rows,
                errors: &error_logs,
            };
            state.emit(
                py,
                processed_rows,
                payment_phase_progress(row_number, credit_count),
            )?;
        }
    }

    {
        let state = ProgressState {
            callback: &on_progress,
            total_rows: processed_rows,
            processed_rows,
            errors: &error_logs,
        };
        state.emit(py, processed_rows, 95)?;
    }

    let persist_result = writer.commit().await;
    let mut success = persist_result.is_ok();
    let payments_ingested = persist_result.as_ref().copied().unwrap_or(0);

    if let Err(err) = persist_result {
        success = false;
        error_logs.push(ErrorLog {
            row_number: 0,
            field: "pipeline".to_string(),
            error_type: "PIPELINE_ERROR".to_string(),
            message: err.to_string(),
        });
    }

    let metrics = PipelineMetrics {
        total_credits_ingested: credit_count,
        total_payments_ingested: payments_ingested,
    };

    Ok(PipelineResult {
        success,
        job_id,
        processed_rows_count: processed_rows,
        execution_duration_seconds: started.elapsed().as_secs_f64(),
        metrics,
        error_logs,
    })
}
