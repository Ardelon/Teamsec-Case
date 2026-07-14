mod db;
mod parser;
mod pipeline;
mod stream;
mod types;

use pipeline::run_pipeline;
use pyo3::prelude::*;
use types::{ErrorLog, PipelineMetrics, PipelineResult};

#[pyclass]
#[derive(Clone)]
struct PyErrorLog {
    #[pyo3(get)]
    row_number: u32,
    #[pyo3(get)]
    field: String,
    #[pyo3(get)]
    error_type: String,
    #[pyo3(get)]
    message: String,
}

impl From<ErrorLog> for PyErrorLog {
    fn from(value: ErrorLog) -> Self {
        Self {
            row_number: value.row_number,
            field: value.field,
            error_type: value.error_type,
            message: value.message,
        }
    }
}

#[pyclass]
#[derive(Clone)]
struct PyPipelineMetrics {
    #[pyo3(get)]
    total_credits_ingested: u64,
    #[pyo3(get)]
    total_payments_ingested: u64,
}

impl From<PipelineMetrics> for PyPipelineMetrics {
    fn from(value: PipelineMetrics) -> Self {
        Self {
            total_credits_ingested: value.total_credits_ingested,
            total_payments_ingested: value.total_payments_ingested,
        }
    }
}

#[pyclass]
#[derive(Clone)]
struct PyPipelineResult {
    #[pyo3(get)]
    success: bool,
    #[pyo3(get)]
    cancelled: bool,
    #[pyo3(get)]
    job_id: String,
    #[pyo3(get)]
    processed_rows_count: u64,
    #[pyo3(get)]
    execution_duration_seconds: f64,
    #[pyo3(get)]
    metrics: PyPipelineMetrics,
    #[pyo3(get)]
    error_logs: Vec<PyErrorLog>,
}

impl From<PipelineResult> for PyPipelineResult {
    fn from(value: PipelineResult) -> Self {
        Self {
            success: value.success,
            cancelled: value.cancelled,
            job_id: value.job_id,
            processed_rows_count: value.processed_rows_count,
            execution_duration_seconds: value.execution_duration_seconds,
            metrics: value.metrics.into(),
            error_logs: value.error_logs.into_iter().map(Into::into).collect(),
        }
    }
}

#[pyfunction]
fn execute_etl_pipeline(
    py: Python<'_>,
    job_id: String,
    tenant_id: String,
    loan_type: String,
    bank_credits_url: String,
    bank_payments_url: String,
    database_url: String,
    on_progress: Option<PyObject>,
) -> PyResult<PyPipelineResult> {
    let runtime = tokio::runtime::Runtime::new()
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    let result = py.allow_threads(|| {
        runtime.block_on(run_pipeline(
            job_id,
            tenant_id,
            loan_type,
            bank_credits_url,
            bank_payments_url,
            database_url,
            on_progress,
        ))
    })?;

    Ok(result.into())
}

#[pymodule]
fn adapter_core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyErrorLog>()?;
    m.add_class::<PyPipelineMetrics>()?;
    m.add_class::<PyPipelineResult>()?;
    m.add_function(wrap_pyfunction!(execute_etl_pipeline, m)?)?;
    Ok(())
}
