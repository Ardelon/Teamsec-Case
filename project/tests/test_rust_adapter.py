def test_execute_etl_pipeline_import():
    import adapter_core

    result = adapter_core.execute_etl_pipeline("job-1", "tenant_alpha", "mortgage")
    assert "Successfully initialized Rust ETL channel" in result
    assert "job-1" in result
    assert "tenant_alpha" in result
