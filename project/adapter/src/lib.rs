use pyo3::prelude::*;

#[pyfunction]
fn execute_etl_pipeline(job_id: String, tenant_id: String, loan_type: String) -> PyResult<String> {
    Ok(format!("Successfully initialized Rust ETL channel for Job: {}, Tenant: {}, Type: {}", job_id, tenant_id, loan_type))
}

#[pymodule]
fn adapter_core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(execute_etl_pipeline, m)?)?;
    Ok(())
}
