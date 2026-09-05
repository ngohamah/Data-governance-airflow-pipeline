"""Part 3: Data Validator (Pandera).

Applies the brief's column validation rules to a customers DataFrame and
reports every specific row/column failure. Reusable as-is for the raw data
(Part 3) and, after cleaning, for the post-validation re-check (Part 4).

Loads the target CSV as plain strings — validation should judge the data
exactly as it arrives, before any type coercion masks a problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pandera as pa
from pandera import Check, Column, DataFrameSchema

from src.config import (
    ACCOUNT_STATUS_VALUES,
    ADDRESS_MAX_LEN,
    ADDRESS_MIN_LEN,
    DATE_FORMAT,
    EMAIL_REGEX,
    INCOME_MAX,
    INCOME_MIN,
    MAX_PLAUSIBLE_AGE,
    MIN_PLAUSIBLE_AGE,
    NAME_ALPHA_REGEX,
    NAME_MAX_LEN,
    NAME_MIN_LEN,
    PHONE_REGEX,
    RAW_CSV_PATH,
    VALIDATION_RESULTS_PATH,
)
from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ValidationResult:
    row_count: int
    is_valid: bool
    failure_cases: pd.DataFrame  # columns: column, check, index, failure_case
    failures_by_check: dict[str, Any]
    invalid_row_count: int


def load_data(path: Path = RAW_CSV_PATH) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


# --- Vectorized rule helpers -------------------------------------------------------


def _is_present(s: pd.Series) -> pd.Series:
    return s.str.strip() != ""


def _where_present(s: pd.Series, validity_fn) -> pd.Series:
    """Apply validity_fn only to present values; missing values pass this check
    (missingness itself is asserted by a separate 'required' check)."""
    present = _is_present(s)
    result = pd.Series(True, index=s.index)
    if present.any():
        result[present] = validity_fn(s[present]).to_numpy(dtype=bool)
    return result


def _numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _parsed_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format=DATE_FORMAT, errors="coerce")


# --- Per-column checks --------------------------------------------------------


def check_customer_id_positive_integer(s: pd.Series) -> pd.Series:
    def validity(vals: pd.Series) -> pd.Series:
        numeric = _numeric(vals)
        return numeric.notna() & (numeric % 1 == 0) & (numeric > 0)

    return _where_present(s, validity)


def check_customer_id_unique(s: pd.Series) -> pd.Series:
    present_mask = _is_present(s)
    duplicated = s[present_mask].duplicated(keep=False)
    result = pd.Series(True, index=s.index)
    result[duplicated[duplicated].index] = False
    return result


def check_name_valid(s: pd.Series) -> pd.Series:
    def validity(vals: pd.Series) -> pd.Series:
        return vals.str.match(NAME_ALPHA_REGEX) & vals.str.len().between(NAME_MIN_LEN, NAME_MAX_LEN)

    return _where_present(s, validity)


def check_email_valid(s: pd.Series) -> pd.Series:
    return _where_present(s, lambda vals: vals.str.match(EMAIL_REGEX))


def check_phone_valid(s: pd.Series) -> pd.Series:
    return _where_present(s, lambda vals: vals.str.match(PHONE_REGEX))


def check_date_format_valid(s: pd.Series) -> pd.Series:
    return _where_present(s, lambda vals: _parsed_date(vals).notna())


def check_dob_plausible_age(s: pd.Series) -> pd.Series:
    def validity(vals: pd.Series) -> pd.Series:
        parsed = _parsed_date(vals)
        age_years = (pd.Timestamp.today() - parsed).dt.days / 365.25
        return parsed.notna() & age_years.between(MIN_PLAUSIBLE_AGE, MAX_PLAUSIBLE_AGE)

    return _where_present(s, validity)


def check_address_length(s: pd.Series) -> pd.Series:
    return _where_present(s, lambda vals: vals.str.len().between(ADDRESS_MIN_LEN, ADDRESS_MAX_LEN))


def check_income_in_range(s: pd.Series) -> pd.Series:
    def validity(vals: pd.Series) -> pd.Series:
        numeric = _numeric(vals)
        return numeric.notna() & numeric.between(INCOME_MIN, INCOME_MAX)

    return _where_present(s, validity)


def check_account_status_valid(s: pd.Series) -> pd.Series:
    return _where_present(s, lambda vals: vals.isin(ACCOUNT_STATUS_VALUES))


def build_schema() -> DataFrameSchema:
    return DataFrameSchema(
        {
            "customer_id": Column(
                str,
                checks=[
                    Check(_is_present, name="required"),
                    Check(check_customer_id_positive_integer, name="positive_integer"),
                    Check(check_customer_id_unique, name="unique"),
                ],
            ),
            "first_name": Column(
                str,
                checks=[
                    Check(_is_present, name="required"),
                    Check(check_name_valid, name="valid_name"),
                ],
            ),
            "last_name": Column(
                str,
                checks=[
                    Check(_is_present, name="required"),
                    Check(check_name_valid, name="valid_name"),
                ],
            ),
            "email": Column(
                str,
                checks=[
                    Check(_is_present, name="required"),
                    Check(check_email_valid, name="valid_email"),
                ],
            ),
            "phone": Column(
                str,
                checks=[
                    Check(_is_present, name="required"),
                    Check(check_phone_valid, name="valid_phone"),
                ],
            ),
            "date_of_birth": Column(
                str,
                checks=[
                    Check(_is_present, name="required"),
                    Check(check_date_format_valid, name="valid_date_format"),
                    Check(check_dob_plausible_age, name="plausible_age"),
                ],
            ),
            "address": Column(
                str,
                checks=[
                    Check(_is_present, name="required"),
                    Check(check_address_length, name="valid_length"),
                ],
            ),
            "income": Column(
                str,
                checks=[
                    Check(_is_present, name="required"),
                    Check(check_income_in_range, name="in_range"),
                ],
            ),
            "account_status": Column(
                str,
                checks=[
                    Check(_is_present, name="required"),
                    Check(check_account_status_valid, name="valid_status"),
                ],
            ),
            "created_date": Column(
                str,
                checks=[
                    Check(_is_present, name="required"),
                    Check(check_date_format_valid, name="valid_date_format"),
                ],
            ),
        },
        coerce=False,
    )


def validate_dataframe(df: pd.DataFrame) -> ValidationResult:
    schema = build_schema()
    try:
        schema.validate(df, lazy=True)
        failure_cases = pd.DataFrame(columns=["column", "check", "index", "failure_case"])
    except pa.errors.SchemaErrors as err:
        failure_cases = err.failure_cases[["column", "check", "index", "failure_case"]]

    failures_by_check: dict[str, Any] = {}
    if not failure_cases.empty:
        for (column, check), group in failure_cases.groupby(["column", "check"]):
            failures_by_check[f"{column}.{check}"] = {
                "column": column,
                "check": check,
                "failure_count": len(group),
                "sample_indices": group["index"].dropna().head(5).astype(int).tolist(),
            }

    invalid_row_count = (
        int(failure_cases["index"].dropna().nunique()) if not failure_cases.empty else 0
    )

    return ValidationResult(
        row_count=len(df),
        is_valid=failure_cases.empty,
        failure_cases=failure_cases,
        failures_by_check=failures_by_check,
        invalid_row_count=invalid_row_count,
    )


def render_report_text(result: ValidationResult, title: str = "VALIDATION RESULTS") -> str:
    lines: list[str] = []
    lines.append(title)
    lines.append("=" * 60)
    lines.append(f"Total rows validated: {result.row_count}")
    invalid_pct = (
        round(100 * result.invalid_row_count / result.row_count, 2) if result.row_count else 0
    )
    lines.append(f"Rows with at least one failed rule: {result.invalid_row_count} ({invalid_pct}%)")
    lines.append("")

    if result.is_valid:
        lines.append("All rows passed every validation rule.")
        return "\n".join(lines)

    lines.append("FAILURES BY COLUMN AND RULE")
    lines.append("-" * 60)
    for stats in result.failures_by_check.values():
        lines.append(
            f"  {stats['column']}.{stats['check']}: {stats['failure_count']} row(s) failed"
        )
        if stats["sample_indices"]:
            lines.append(f"      example row indices: {stats['sample_indices']}")
    lines.append("")

    return "\n".join(lines)


def run_validation(
    input_path: Path = RAW_CSV_PATH,
    output_report_path: Path = VALIDATION_RESULTS_PATH,
    title: str = "VALIDATION RESULTS (raw data)",
) -> ValidationResult:
    logger.info("Starting validation: input=%s", input_path)
    try:
        df = load_data(input_path)
        result = validate_dataframe(df)
        report_text = render_report_text(result, title=title)

        output_report_path.parent.mkdir(parents=True, exist_ok=True)
        output_report_path.write_text(report_text, encoding="utf-8")
    except (OSError, ValueError, KeyError):
        logger.exception("Validation failed for %s", input_path)
        raise

    logger.info(
        "Validation complete: %d/%d rows failed at least one rule. Report: %s",
        result.invalid_row_count,
        result.row_count,
        output_report_path,
    )
    return result


if __name__ == "__main__":
    run_validation()
