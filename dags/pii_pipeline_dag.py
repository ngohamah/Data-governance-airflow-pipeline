"""Airflow DAG: orchestrates the customers_raw.csv pipeline (src/pipeline.py).

Two tasks: sense_raw_data (waits for the user to have generated the raw CSV),
then run_full_pipeline (calls src.pipeline.run_pipeline(), unchanged). See
implementationmap.md section 5 for why this isn't one task per brief part.

Retry policy (user-requested): 3 retries, 5 minutes apart, then an email to
ADMIN_EMAIL. ADMIN_EMAIL and SMTP settings come from environment variables
(see .env.example) — real values live only in the untracked .env.
"""

from __future__ import annotations

import os
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
    def sense_raw_data() -> str:
        from src.config import RAW_CSV_PATH

        if not RAW_CSV_PATH.exists():
            raise AirflowException(
                f"customers_raw.csv not found at {RAW_CSV_PATH}. Generate it with "
                "`python -m src.data_generator` before this DAG can run."
            )
        return str(RAW_CSV_PATH)

    @task
    def run_full_pipeline(raw_path: str) -> dict:
        from pathlib import Path

        from src.pipeline import run_pipeline

        report = run_pipeline(raw_path=Path(raw_path))
        return {
            "overall_status": report.overall_status,
            "total_duration_seconds": report.total_duration_seconds,
        }

    run_full_pipeline(sense_raw_data())


pii_detection_pipeline()
