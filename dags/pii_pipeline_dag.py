"""Airflow DAG: orchestrates the customers_raw.csv pipeline.

One task per pipeline stage, each calling its underlying src module function
directly (not going through src.pipeline.run_pipeline()) so every stage gets
its own retry, log stream, and status in the Airflow UI. Task dependencies
follow the real data dependencies rather than an arbitrary chain, so four
stages fan out in parallel once the raw file is sensed:

                          +-> profile_quality --------+
                          |-> detect_pii --------------|
    sense_raw_data -------+-> validate_raw ------------+-> write_pipeline_summary
                          +-> clean_and_revalidate -> mask_pii -+

profile_quality/detect_pii/validate_raw/clean_and_revalidate all only read
the raw CSV and each write to a distinct output file, so running them
concurrently (which LocalExecutor will do) is safe. mask_pii genuinely
depends on clean_and_revalidate's cleaned CSV; write_pipeline_summary
depends on every stage having finished.

src/pipeline.py's run_pipeline() is unchanged and still the way to run the
whole thing as one script (`python -m src.pipeline`), independent of
Airflow. write_pipeline_summary reuses its StageResult/PipelineExecutionReport
dataclasses and render_execution_report() purely for the report text format,
so both entry points produce the same pipeline_execution_report.txt shape.

Trade-off vs. the single-task design this replaces: if any stage before
write_pipeline_summary fails, that task (whose trigger rule is the default
"all_success") never runs, so no pipeline_execution_report.txt is written for
a failed DAG run — failure visibility instead comes from Airflow's own UI,
per-task logs, and the retry/failure email below. `python -m src.pipeline`
still always writes a partial report, even on failure, since it's not bound
by Airflow's task trigger rules.

Retry policy (user-requested): 3 retries, 5 minutes apart, then an email to
ADMIN_EMAIL. ADMIN_EMAIL and SMTP settings come from environment variables
(see .env.example) — real values live only in the untracked .env.
"""

from __future__ import annotations

import os
import time
from datetime import timedelta

import pendulum
from airflow.decorators import dag, task
from airflow.exceptions import AirflowException

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")

default_args = {
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "email_on_retry": False,
    "email_on_failure": True,
    "email": [ADMIN_EMAIL],
}


@dag(
    dag_id="pii_detection_pipeline",
    description="Profile, detect PII in, validate, clean, and mask customers_raw.csv",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    default_args=default_args,
    tags=["pii", "data-quality"],
)
def pii_detection_pipeline():
    @task
    def sense_raw_data() -> dict:
        from src.config import RAW_CSV_PATH

        start = time.monotonic()
        if not RAW_CSV_PATH.exists():
            raise AirflowException(
                f"customers_raw.csv not found at {RAW_CSV_PATH}. Generate it with "
                "`python -m src.data_generator` before this DAG can run."
            )
        import pandas as pd

        row_count = len(pd.read_csv(RAW_CSV_PATH, dtype=str, keep_default_na=False))
        return {
            "duration_seconds": round(time.monotonic() - start, 3),
            "raw_path": str(RAW_CSV_PATH),
            "details": {"row_count": row_count},
        }

    @task
    def profile_quality(sense_result: dict) -> dict:
        from pathlib import Path

        from src.quality_analysis import run_quality_analysis

        start = time.monotonic()
        report = run_quality_analysis(Path(sense_result["raw_path"]))
        return {
            "duration_seconds": round(time.monotonic() - start, 3),
            "details": {
                "row_count": report.row_count,
                "duplicate_id_rows": report.uniqueness["duplicate_id_row_count"],
                "invalid_account_status_rows": report.categorical_validity["invalid_row_count"],
            },
        }

    @task
    def detect_pii(sense_result: dict) -> dict:
        from pathlib import Path

        from src.pii_detection import run_pii_detection

        start = time.monotonic()
        report = run_pii_detection(Path(sense_result["raw_path"]))
        return {
            "duration_seconds": round(time.monotonic() - start, 3),
            "details": {
                "full_identity_profile_rows": report.breach_risk["full_profile_record_count"],
            },
        }

    @task
    def validate_raw(sense_result: dict) -> dict:
        from pathlib import Path

        from src.validator import run_validation

        start = time.monotonic()
        result = run_validation(
            Path(sense_result["raw_path"]), title="VALIDATION RESULTS (raw data)"
        )
        return {
            "duration_seconds": round(time.monotonic() - start, 3),
            "details": {
                "invalid_row_count": result.invalid_row_count,
                "row_count": result.row_count,
            },
        }

    @task
    def clean_and_revalidate(sense_result: dict) -> dict:
        from pathlib import Path

        from src.cleaning import run_cleaning
        from src.config import CLEANED_CSV_PATH

        start = time.monotonic()
        cleaned_df, post_validation = run_cleaning(Path(sense_result["raw_path"]))
        return {
            "duration_seconds": round(time.monotonic() - start, 3),
            "cleaned_csv_path": str(CLEANED_CSV_PATH),
            "details": {
                "rows_out": len(cleaned_df),
                "post_clean_invalid_row_count": post_validation.invalid_row_count,
            },
        }

    @task
    def mask_pii(clean_result: dict) -> dict:
        from pathlib import Path

        from src.masking import run_masking

        start = time.monotonic()
        masked_df = run_masking(Path(clean_result["cleaned_csv_path"]))
        return {
            "duration_seconds": round(time.monotonic() - start, 3),
            "details": {"rows_masked": len(masked_df)},
        }

    @task
    def write_pipeline_summary(
        sense_result: dict,
        profile_result: dict,
        pii_result: dict,
        validate_result: dict,
        clean_result: dict,
        mask_result: dict,
    ) -> dict:
        from src.config import PIPELINE_EXECUTION_REPORT_PATH
        from src.pipeline import (
            PipelineExecutionReport,
            StageResult,
            render_execution_report,
        )

        named_results = [
            ("sense_raw_data", sense_result),
            ("profile_quality", profile_result),
            ("detect_pii", pii_result),
            ("validate_raw", validate_result),
            ("clean_and_revalidate", clean_result),
            ("mask_pii", mask_result),
        ]
        stages = [
            StageResult(
                name=name,
                status="SUCCESS",
                duration_seconds=result["duration_seconds"],
                details=result.get("details", {}),
            )
            for name, result in named_results
        ]
        total_duration = round(sum(s.duration_seconds for s in stages), 3)
        report = PipelineExecutionReport(
            stages=stages, total_duration_seconds=total_duration, overall_status="SUCCESS"
        )

        PIPELINE_EXECUTION_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        PIPELINE_EXECUTION_REPORT_PATH.write_text(render_execution_report(report), encoding="utf-8")
        return {"overall_status": "SUCCESS", "total_duration_seconds": total_duration}

    sensed = sense_raw_data()
    profiled = profile_quality(sensed)
    detected = detect_pii(sensed)
    validated = validate_raw(sensed)
    cleaned = clean_and_revalidate(sensed)
    masked = mask_pii(cleaned)
    write_pipeline_summary(sensed, profiled, detected, validated, cleaned, masked)


pii_detection_pipeline()
