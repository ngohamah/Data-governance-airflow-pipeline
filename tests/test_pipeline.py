import pandas as pd
import pytest

from src.pipeline import render_execution_report, run_pipeline


@pytest.fixture
def raw_csv(tmp_path):
    df = pd.DataFrame(
        {
            "customer_id": ["1", "2", "3"],
            "first_name": ["john", "mary", "alex"],
            "last_name": ["doe", "smith", "lee"],
            "email": ["john@x.com", "mary@x.com", "alex@x.com"],
            "phone": ["(555) 123-4567", "555-234-5678", "555-345-6789"],
            "date_of_birth": ["1990-01-01", "03/15/1985", "1995-06-15"],
            "address": ["123 Main St, Springfield", "456 Oak Ave, Metropolis", "789 Pine Rd Town"],
            "income": ["50000", "60000", "75000"],
            "account_status": ["active", "inactive", "suspended"],
            "created_date": ["2020-01-01", "2019-06-15", "2021-03-10"],
        }
    )
    path = tmp_path / "customers_raw.csv"
    df.to_csv(path, index=False)
    return path


def test_run_pipeline_success_produces_all_deliverables(tmp_path, raw_csv):
    report = run_pipeline(
        raw_path=raw_csv,
        quality_report_path=tmp_path / "data_quality_report.txt",
        plots_dir=tmp_path / "plots",
        pii_report_path=tmp_path / "pii_detection_report.txt",
        validation_report_path=tmp_path / "validation_results.txt",
        cleaned_csv_path=tmp_path / "customers_cleaned.csv",
        cleaning_log_path=tmp_path / "cleaning_log.txt",
        masked_csv_path=tmp_path / "customers_masked.csv",
        masked_sample_path=tmp_path / "masked_sample.txt",
        execution_report_path=tmp_path / "pipeline_execution_report.txt",
    )

    assert report.overall_status == "SUCCESS"
    assert [s.name for s in report.stages] == [
        "sense_raw_data",
        "profile_quality",
        "detect_pii",
        "validate_raw",
        "clean_and_revalidate",
        "mask_pii",
    ]
    assert all(s.status == "SUCCESS" for s in report.stages)

    for path in [
        tmp_path / "data_quality_report.txt",
        tmp_path / "pii_detection_report.txt",
        tmp_path / "validation_results.txt",
        tmp_path / "cleaning_log.txt",
        tmp_path / "customers_cleaned.csv",
        tmp_path / "masked_sample.txt",
        tmp_path / "customers_masked.csv",
        tmp_path / "pipeline_execution_report.txt",
    ]:
        assert path.exists(), f"expected {path} to exist"


def test_run_pipeline_raises_and_reports_on_missing_input(tmp_path):
    missing = tmp_path / "does_not_exist.csv"
    execution_report_path = tmp_path / "pipeline_execution_report.txt"

    with pytest.raises(FileNotFoundError):
        run_pipeline(raw_path=missing, execution_report_path=execution_report_path)

    assert execution_report_path.exists()
    text = execution_report_path.read_text()
    assert "FAILED" in text
    assert "sense_raw_data" in text


def test_render_execution_report_smoke():
    from src.pipeline import PipelineExecutionReport, StageResult

    stage = StageResult(name="stage_a", status="SUCCESS", duration_seconds=1.23, details={"x": 1})
    report = PipelineExecutionReport(
        stages=[stage],
        total_duration_seconds=1.23,
        overall_status="SUCCESS",
    )
    text = render_execution_report(report)
    assert "PIPELINE EXECUTION REPORT" in text
    assert "stage_a" in text
    assert "x: 1" in text
