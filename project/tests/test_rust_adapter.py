def test_execute_etl_pipeline_signature():
    import adapter_core

    assert hasattr(adapter_core, "execute_etl_pipeline")
    assert hasattr(adapter_core, "PyPipelineResult")
