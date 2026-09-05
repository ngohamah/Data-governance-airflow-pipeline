"""Part 6: End-to-End Pipeline.

Orchestrates Parts 1-5 as a single run: sense raw data -> profile quality ->
detect PII -> validate raw -> clean (+ re-validate) -> mask -> report.

Each stage is timed and wrapped in error handling; a failure halts the
pipeline (no stage runs on top of a bad prior result) but the execution
report is still written for whatever stages completed, and the original
exception propagates so a caller (e.g. Airflow) sees the failure and can
retry. This module is import-only with no Airflow dependency, so the same
functions run identically standalone or as Airflow tasks.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.cleaning import run_cleaning
from src.config import (
    CLEANED_CSV_PATH,
    CLEANING_LOG_PATH,
    DATA_QUALITY_REPORT_PATH,
    MASKED_CSV_PATH,
    MASKED_SAMPLE_PATH,
    PII_DETECTION_REPORT_PATH,
    PIPELINE_EXECUTION_REPORT_PATH,
    PLOTS_DIR,
    RAW_CSV_PATH,
    VALIDATION_RESULTS_PATH,
)
from src.logging_config import get_logger
from src.masking import run_masking
from src.pii_detection import run_pii_detection
from src.quality_analysis import run_quality_analysis
from src.validator import run_validation

logger = get_logger(__name__)


@dataclass
class StageResult:
    name: str
    status: str  # "SUCCESS" or "FAILED"
    duration_seconds: float
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class PipelineExecutionReport:
    stages: list[StageResult]
    total_duration_seconds: float
    overall_status: str


def _sense_raw_data(path: Path) -> int:
    if not path.exists():
        raise FileNotFoundError(
            f"Raw data file not found at {path}. This pipeline does not generate "
            "customers_raw.csv itself — run `python -m src.data_generator` first."
        )
    return len(pd.read_csv(path, dtype=str, keep_default_na=False))


def _run(stages: list[StageResult], name: str, fn) -> Any:
    """Execute one stage, time it, and record a StageResult. Re-raises on failure
    after recording it, so run_pipeline can still write a partial report."""
    logger.info("Starting pipeline stage: %s", name)
    start = time.monotonic()
    try:
        result = fn()
    except Exception:
        duration = round(time.monotonic() - start, 3)
        logger.exception("Pipeline stage '%s' failed", name)
        stages.append(
            StageResult(
                name=name,
                status="FAILED",
                duration_seconds=duration,
                error=traceback.format_exc(limit=3),
            )
        )
        raise
    duration = round(time.monotonic() - start, 3)
    stages.append(StageResult(name=name, status="SUCCESS", duration_seconds=duration))
    logger.info("Completed pipeline stage: %s (%.2fs)", name, duration)
    return result


def render_execution_report(report: PipelineExecutionReport) -> str:
    lines: list[str] = []
    lines.append("PIPELINE EXECUTION REPORT")
    lines.append("=" * 60)
    lines.append(f"Overall status: {report.overall_status}")
    lines.append(f"Total duration: {report.total_duration_seconds}s")
    lines.append("")

    for stage in report.stages:
        lines.append(f"[{stage.status}] {stage.name}  ({stage.duration_seconds}s)")
        for key, value in stage.details.items():
            lines.append(f"    {key}: {value}")
        if stage.error:
            lines.append(f"    ERROR: {stage.error.strip().splitlines()[-1]}")
        lines.append("")

    return "\n".join(lines)


def run_pipeline(
    raw_path: Path = RAW_CSV_PATH,
    quality_report_path: Path = DATA_QUALITY_REPORT_PATH,
    plots_dir: Path = PLOTS_DIR,
    pii_report_path: Path = PII_DETECTION_REPORT_PATH,
    validation_report_path: Path = VALIDATION_RESULTS_PATH,
    cleaned_csv_path: Path = CLEANED_CSV_PATH,
    cleaning_log_path: Path = CLEANING_LOG_PATH,
    masked_csv_path: Path = MASKED_CSV_PATH,
    masked_sample_path: Path = MASKED_SAMPLE_PATH,
    execution_report_path: Path = PIPELINE_EXECUTION_REPORT_PATH,
) -> PipelineExecutionReport:
    stages: list[StageResult] = []
    overall_start = time.monotonic()
    failure: Exception | None = None

    try:
        row_count = _run(stages, "sense_raw_data", lambda: _sense_raw_data(raw_path))
        stages[-1].details = {"row_count": row_count}

        quality_report = _run(
            stages,
            "profile_quality",
            lambda: run_quality_analysis(raw_path, quality_report_path, plots_dir),
        )
        stages[-1].details = {
            "row_count": quality_report.row_count,
            "duplicate_id_rows": quality_report.uniqueness["duplicate_id_row_count"],
            "invalid_account_status_rows": quality_report.categorical_validity["invalid_row_count"],
        }

        pii_report = _run(
            stages, "detect_pii", lambda: run_pii_detection(raw_path, pii_report_path)
        )
        stages[-1].details = {
            "full_identity_profile_rows": pii_report.breach_risk["full_profile_record_count"],
        }

        raw_validation = _run(
            stages,
            "validate_raw",
            lambda: run_validation(
                raw_path, validation_report_path, title="VALIDATION RESULTS (raw data)"
            ),
        )
        stages[-1].details = {
            "invalid_row_count": raw_validation.invalid_row_count,
            "row_count": raw_validation.row_count,
        }

        cleaned_df, post_validation = _run(
            stages,
            "clean_and_revalidate",
            lambda: run_cleaning(raw_path, cleaned_csv_path, cleaning_log_path),
        )
        stages[-1].details = {
            "rows_out": len(cleaned_df),
            "post_clean_invalid_row_count": post_validation.invalid_row_count,
        }

        masked_df = _run(
            stages,
            "mask_pii",
            lambda: run_masking(cleaned_csv_path, masked_csv_path, masked_sample_path),
        )
        stages[-1].details = {"rows_masked": len(masked_df)}

    except Exception as exc:  # noqa: BLE001 - stage boundary, already logged in _run
        failure = exc

    total_duration = round(time.monotonic() - overall_start, 3)
    overall_status = "FAILED" if failure else "SUCCESS"
    report = PipelineExecutionReport(
        stages=stages, total_duration_seconds=total_duration, overall_status=overall_status
    )

    execution_report_path.parent.mkdir(parents=True, exist_ok=True)
    execution_report_path.write_text(render_execution_report(report), encoding="utf-8")

    logger.info(
        "Pipeline finished: overall_status=%s total_duration=%.2fs report=%s",
        overall_status,
        total_duration,
        execution_report_path,
    )

    if failure:
        raise failure
    return report


if __name__ == "__main__":
    run_pipeline()
