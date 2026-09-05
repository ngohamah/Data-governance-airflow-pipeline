"""Part 4: Clean the Data.

Normalizes phone/date/name formats, applies a per-column missing-value
strategy (drop / placeholder / flag), and re-runs the Part 3 validator on
the result to confirm the fixes actually worked.

Normalization functions are pure (Series in, Series out); orchestration and
I/O live in run_cleaning.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import (
    ALTERNATE_DATE_FORMATS,
    CLEANED_CSV_PATH,
    CLEANING_LOG_PATH,
    DATE_FORMAT,
    MISSING_VALUE_STRATEGY,
    PLACEHOLDER_VALUES,
    RAW_CSV_PATH,
)
from src.logging_config import get_logger
from src.validator import ValidationResult, load_data, validate_dataframe

logger = get_logger(__name__)

_DATE_PARSE_FORMATS = (DATE_FORMAT, *ALTERNATE_DATE_FORMATS)


# --- Normalization (pure, Series -> Series) ---------------------------------------


def normalize_phone(s: pd.Series) -> pd.Series:
    def _normalize(value: str) -> str:
        if value.strip() == "":
            return value
        digits = re.sub(r"\D", "", value)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]  # strip US country code
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        return value  # not recoverable by reformatting; left as-is, still invalid downstream

    return s.apply(_normalize)


def normalize_date(s: pd.Series) -> pd.Series:
    def _normalize(value: str) -> str:
        if value.strip() == "":
            return value
        for fmt in _DATE_PARSE_FORMATS:
            try:
                return datetime.strptime(value, fmt).strftime(DATE_FORMAT)
            except ValueError:
                continue
        return value  # unparseable (e.g. literal "invalid_date"), left as-is

    return s.apply(_normalize)


def normalize_name(s: pd.Series) -> pd.Series:
    return s.apply(lambda value: value if value.strip() == "" else value.title())


def normalize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Apply all normalizations and report how many values each one changed."""
    normalized = df.copy()
    normalized["phone"] = normalize_phone(df["phone"])
    normalized["date_of_birth"] = normalize_date(df["date_of_birth"])
    normalized["created_date"] = normalize_date(df["created_date"])
    normalized["first_name"] = normalize_name(df["first_name"])
    normalized["last_name"] = normalize_name(df["last_name"])

    changed = {
        "phone": int((df["phone"] != normalized["phone"]).sum()),
        "date_of_birth": int((df["date_of_birth"] != normalized["date_of_birth"]).sum()),
        "created_date": int((df["created_date"] != normalized["created_date"]).sum()),
        "first_name": int((df["first_name"] != normalized["first_name"]).sum()),
        "last_name": int((df["last_name"] != normalized["last_name"]).sum()),
    }
    return normalized, changed


# --- Missing-value strategy --------------------------------------------------------


def apply_missing_value_strategy(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    working = df.copy()
    dropped_by_column: dict[str, int] = {}
    placeholder_fills: dict[str, int] = {}
    flagged_counts: dict[str, int] = {}

    for column, strategy in MISSING_VALUE_STRATEGY.items():
        if strategy != "drop":
            continue
        missing_mask = working[column].str.strip() == ""
        count = int(missing_mask.sum())
        if count:
            dropped_by_column[column] = count
            working = working[~missing_mask]

    for column, strategy in MISSING_VALUE_STRATEGY.items():
        if strategy != "placeholder":
            continue
        missing_mask = working[column].str.strip() == ""
        count = int(missing_mask.sum())
        if count:
            working.loc[missing_mask, column] = PLACEHOLDER_VALUES[column]
            placeholder_fills[column] = count

    for column, strategy in MISSING_VALUE_STRATEGY.items():
        if strategy != "flag":
            continue
        missing_mask = working[column].str.strip() == ""
        count = int(missing_mask.sum())
        if count:
            flagged_counts[column] = count

    working = working.reset_index(drop=True)
    log = {
        "dropped_rows": sum(dropped_by_column.values()),
        "dropped_by_column": dropped_by_column,
        "placeholder_fills": placeholder_fills,
        "flagged_counts": flagged_counts,
    }
    return working, log


def clean_data(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    normalized, normalization_log = normalize_columns(df)
    cleaned, missing_value_log = apply_missing_value_strategy(normalized)
    return cleaned, {"normalization": normalization_log, "missing_values": missing_value_log}


# --- Reporting ----------------------------------------------------------------


def render_cleaning_log(
    log: dict[str, Any],
    pre_validation: ValidationResult,
    post_validation: ValidationResult,
) -> str:
    lines: list[str] = []
    lines.append("CLEANING LOG")
    lines.append("=" * 60)
    lines.append("")

    lines.append("1. NORMALIZATION (values reformatted, not changed in meaning)")
    lines.append("-" * 60)
    for column, count in log["normalization"].items():
        lines.append(f"  {column:<16} {count} value(s) reformatted")
    lines.append("")

    lines.append("2. MISSING VALUE STRATEGY")
    lines.append("-" * 60)
    mv = log["missing_values"]
    lines.append(f"  Rows dropped (required field missing): {mv['dropped_rows']}")
    for column, count in mv["dropped_by_column"].items():
        lines.append(f"      {column}: {count} row(s) dropped")
    lines.append("  Placeholder values filled in:")
    for column, count in mv["placeholder_fills"].items():
        lines.append(f"      {column}: {count} row(s) filled")
    lines.append("  Flagged for manual review (left blank, not fabricated):")
    for column, count in mv["flagged_counts"].items():
        lines.append(f"      {column}: {count} row(s) flagged")
    lines.append("")

    lines.append("3. POST-CLEANING VALIDATION (confirms whether fixes worked)")
    lines.append("-" * 60)
    pre_pct = (
        round(100 * pre_validation.invalid_row_count / pre_validation.row_count, 2)
        if pre_validation.row_count
        else 0
    )
    post_pct = (
        round(100 * post_validation.invalid_row_count / post_validation.row_count, 2)
        if post_validation.row_count
        else 0
    )
    lines.append(
        f"  Before cleaning: {pre_validation.invalid_row_count}/{pre_validation.row_count} "
        f"rows failed validation ({pre_pct}%)"
    )
    lines.append(
        f"  After cleaning:  {post_validation.invalid_row_count}/{post_validation.row_count} "
        f"rows failed validation ({post_pct}%)"
    )
    if post_validation.failures_by_check:
        lines.append("  Remaining failures (not fixable by reformatting alone):")
        for stats in post_validation.failures_by_check.values():
            lines.append(
                f"      {stats['column']}.{stats['check']}: {stats['failure_count']} row(s)"
            )
    else:
        lines.append("  All rows now pass every validation rule.")
    lines.append("")

    return "\n".join(lines)


def run_cleaning(
    input_path: Path = RAW_CSV_PATH,
    output_csv_path: Path = CLEANED_CSV_PATH,
    output_log_path: Path = CLEANING_LOG_PATH,
) -> tuple[pd.DataFrame, ValidationResult]:
    logger.info("Starting cleaning: input=%s", input_path)
    try:
        raw_df = load_data(input_path)
        pre_validation = validate_dataframe(raw_df)

        cleaned_df, log = clean_data(raw_df)
        post_validation = validate_dataframe(cleaned_df)

        log_text = render_cleaning_log(log, pre_validation, post_validation)
        output_log_path.parent.mkdir(parents=True, exist_ok=True)
        output_log_path.write_text(log_text, encoding="utf-8")

        output_csv_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned_df.to_csv(output_csv_path, index=False)
    except (OSError, ValueError, KeyError):
        logger.exception("Cleaning failed for %s", input_path)
        raise

    dropped = log["missing_values"]["dropped_rows"]
    if dropped:
        logger.info("Dropped %d row(s) with a missing required field during cleaning", dropped)
    logger.info(
        "Cleaning complete: %d rows in, %d rows out. Validation failures %d -> %d. "
        "Cleaned data: %s. Log: %s",
        len(raw_df),
        len(cleaned_df),
        pre_validation.invalid_row_count,
        post_validation.invalid_row_count,
        output_csv_path,
        output_log_path,
    )
    return cleaned_df, post_validation


if __name__ == "__main__":
    run_cleaning()
