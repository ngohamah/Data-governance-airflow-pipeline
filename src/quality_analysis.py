"""Part 1: Exploratory Data Quality Analysis.

Profiles the raw dataset (completeness, type mismatches, format issues,
uniqueness, invalid values, categorical validity) and writes a plain-language
report plus a couple of labeled charts for non-technical stakeholders.

All analysis functions are pure: DataFrame in, plain-data result out. I/O
(reading the CSV, writing the report/plots) is confined to run_quality_analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.config import (
    ACCOUNT_STATUS_VALUES,
    CANONICAL_PHONE_REGEX,
    DATA_QUALITY_REPORT_PATH,
    DATE_COLUMNS,
    DATE_FORMAT,
    EXPECTED_COLUMN_TYPES,
    MAX_PLAUSIBLE_AGE,
    MIN_PLAUSIBLE_AGE,
    PLOTS_DIR,
    RAW_CSV_PATH,
)
from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class QualityReport:
    row_count: int
    completeness: dict[str, dict[str, Any]]
    dtypes: dict[str, dict[str, Any]]
    format_issues: dict[str, Any]
    uniqueness: dict[str, Any]
    invalid_values: dict[str, Any]
    categorical_validity: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


# --- Loading ---------------------------------------------------------------------


def load_raw_data(path: Path = RAW_CSV_PATH) -> pd.DataFrame:
    """Load the raw CSV with default pandas type inference.

    Deliberately does NOT force dtype=str: letting pandas infer types the way it
    would for any analyst opening this file is what surfaces type-mismatch
    findings (e.g. customer_id inferred as float64 because of missing values).
    """
    return pd.read_csv(path)


# --- Individual analysis functions ------------------------------------------------


def analyze_completeness(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    total = len(df)
    result = {}
    for column in df.columns:
        missing = int(df[column].isna().sum())
        result[column] = {
            "missing_count": missing,
            "missing_pct": round(100 * missing / total, 2) if total else 0.0,
        }
    return result


def analyze_dtypes(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    result = {}
    for column, expected in EXPECTED_COLUMN_TYPES.items():
        if column not in df.columns:
            continue
        actual_dtype = str(df[column].dtype)
        if expected in ("integer", "numeric"):
            matches = pd.api.types.is_numeric_dtype(df[column])
        elif expected.startswith("date"):
            parsed = pd.to_datetime(df[column], format=DATE_FORMAT, errors="coerce")
            non_missing = df[column].notna()
            matches = bool((parsed.notna() | ~non_missing).all())
        else:
            matches = pd.api.types.is_object_dtype(df[column]) or pd.api.types.is_string_dtype(
                df[column]
            )
        result[column] = {
            "expected_type": expected,
            "actual_dtype": actual_dtype,
            "matches_expected": matches,
        }
    return result


def analyze_format_issues(df: pd.DataFrame) -> dict[str, Any]:
    phone = df["phone"].dropna().astype(str)
    non_canonical_phone = phone[~phone.str.match(CANONICAL_PHONE_REGEX)]

    date_issues: dict[str, int] = {}
    for column in DATE_COLUMNS:
        values = df[column].dropna().astype(str)
        values = values[values != "invalid_date"]  # counted separately as an invalid value
        non_iso = values[~values.str.match(r"^\d{4}-\d{2}-\d{2}$")]
        date_issues[column] = int(len(non_iso))

    return {
        "non_canonical_phone_count": int(len(non_canonical_phone)),
        "non_canonical_phone_sample": non_canonical_phone.head(5).tolist(),
        "non_iso_date_counts": date_issues,
    }


def analyze_uniqueness(df: pd.DataFrame) -> dict[str, Any]:
    ids = df["customer_id"].dropna()
    duplicated_mask = ids.duplicated(keep=False)
    duplicated_ids = sorted(ids[duplicated_mask].unique().tolist())
    return {
        "total_rows": len(df),
        "unique_customer_ids": int(ids.nunique()),
        "duplicate_id_row_count": int(duplicated_mask.sum()),
        "duplicate_ids_sample": duplicated_ids[:10],
    }


def analyze_invalid_values(df: pd.DataFrame) -> dict[str, Any]:
    income = pd.to_numeric(df["income"], errors="coerce")
    negative_income = int((income < 0).sum())
    over_max_income = int((income > 10_000_000).sum())

    dob_literal_invalid = int((df["date_of_birth"] == "invalid_date").sum())
    created_literal_invalid = int((df["created_date"] == "invalid_date").sum())

    dob_parsed = pd.to_datetime(df["date_of_birth"], format=DATE_FORMAT, errors="coerce")
    today = pd.Timestamp.today()
    age_years = (today - dob_parsed).dt.days / 365.25
    age_over_150 = int((age_years > MAX_PLAUSIBLE_AGE).sum())
    age_negative = int((age_years < MIN_PLAUSIBLE_AGE).sum())

    non_positive_ids = df["customer_id"].dropna()
    non_positive_ids = int((pd.to_numeric(non_positive_ids, errors="coerce") <= 0).sum())

    return {
        "negative_income_count": negative_income,
        "income_over_max_count": over_max_income,
        "invalid_date_literal_count": {
            "date_of_birth": dob_literal_invalid,
            "created_date": created_literal_invalid,
        },
        "age_over_150_count": age_over_150,
        "age_negative_count": age_negative,
        "non_positive_customer_id_count": non_positive_ids,
    }


def analyze_categorical_validity(df: pd.DataFrame) -> dict[str, Any]:
    counts = df["account_status"].value_counts(dropna=False).to_dict()
    invalid = {
        str(value): int(count)
        for value, count in counts.items()
        if value not in ACCOUNT_STATUS_VALUES
    }
    return {
        "value_counts": {str(k): int(v) for k, v in counts.items()},
        "invalid_values": invalid,
        "invalid_row_count": sum(invalid.values()),
    }


def build_quality_report(df: pd.DataFrame) -> QualityReport:
    return QualityReport(
        row_count=len(df),
        completeness=analyze_completeness(df),
        dtypes=analyze_dtypes(df),
        format_issues=analyze_format_issues(df),
        uniqueness=analyze_uniqueness(df),
        invalid_values=analyze_invalid_values(df),
        categorical_validity=analyze_categorical_validity(df),
    )


# --- Plain-language report rendering ----------------------------------------------


def render_report_text(report: QualityReport) -> str:
    lines: list[str] = []
    lines.append("DATA QUALITY REPORT")
    lines.append("=" * 60)
    lines.append(f"Total rows analyzed: {report.row_count}")
    lines.append("")

    lines.append("1. COMPLETENESS (missing data by column)")
    lines.append("-" * 60)
    for column, stats in report.completeness.items():
        count, pct = stats["missing_count"], stats["missing_pct"]
        lines.append(f"  {column:<16} {count:>6} missing  ({pct}%)")
    lines.append("")

    lines.append("2. DATA TYPES (does the stored type match what's expected?)")
    lines.append("-" * 60)
    for column, stats in report.dtypes.items():
        flag = "OK" if stats["matches_expected"] else "MISMATCH"
        lines.append(
            f"  {column:<16} expected={stats['expected_type']:<22} "
            f"actual_dtype={stats['actual_dtype']:<10} [{flag}]"
        )
    lines.append("")

    lines.append("3. FORMAT ISSUES (values that parse but aren't in the standard format)")
    lines.append("-" * 60)
    fi = report.format_issues
    lines.append(f"  Phone numbers not in XXX-XXX-XXXX format: {fi['non_canonical_phone_count']}")
    if fi["non_canonical_phone_sample"]:
        lines.append(f"    e.g. {fi['non_canonical_phone_sample']}")
    for column, count in fi["non_iso_date_counts"].items():
        lines.append(f"  {column} not in YYYY-MM-DD format: {count}")
    lines.append("")

    lines.append("4. UNIQUENESS (customer_id)")
    lines.append("-" * 60)
    uq = report.uniqueness
    lines.append(f"  Total rows: {uq['total_rows']}")
    lines.append(f"  Unique customer_id values: {uq['unique_customer_ids']}")
    lines.append(f"  Rows sharing a duplicated customer_id: {uq['duplicate_id_row_count']}")
    if uq["duplicate_ids_sample"]:
        lines.append(f"    e.g. IDs {uq['duplicate_ids_sample']}")
    lines.append("")

    lines.append("5. INVALID VALUES")
    lines.append("-" * 60)
    iv = report.invalid_values
    invalid_dates = iv["invalid_date_literal_count"]
    lines.append(f"  Negative income: {iv['negative_income_count']}")
    lines.append(f"  Income above $10,000,000: {iv['income_over_max_count']}")
    lines.append(f"  Literal 'invalid_date' in date_of_birth: {invalid_dates['date_of_birth']}")
    lines.append(f"  Literal 'invalid_date' in created_date: {invalid_dates['created_date']}")
    lines.append(f"  Implied age over 150 years: {iv['age_over_150_count']}")
    lines.append(f"  Implied negative age (birth date in the future): {iv['age_negative_count']}")
    lines.append(f"  Non-positive customer_id: {iv['non_positive_customer_id_count']}")
    lines.append("")

    lines.append("6. CATEGORICAL VALIDITY (account_status)")
    lines.append("-" * 60)
    cv = report.categorical_validity
    lines.append(f"  Value counts: {cv['value_counts']}")
    lines.append(
        f"  Rows with an invalid status (not active/inactive/suspended): "
        f"{cv['invalid_row_count']}"
    )
    if cv["invalid_values"]:
        lines.append(f"    Invalid values seen: {cv['invalid_values']}")
    lines.append("")

    return "\n".join(lines)


# --- Plots (labeled for a non-technical audience) ---------------------------------


def plot_completeness(report: QualityReport, output_dir: Path = PLOTS_DIR) -> Path:
    columns = list(report.completeness.keys())
    pct_missing = [report.completeness[c]["missing_pct"] for c in columns]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(columns, pct_missing, color="#c0392b")
    ax.set_title("Percentage of Missing Data by Column", fontsize=14)
    ax.set_xlabel("Column")
    ax.set_ylabel("Missing (%)")
    ax.set_ylim(0, max(100, max(pct_missing, default=0) + 5))
    ax.tick_params(axis="x", rotation=45)
    for i, value in enumerate(pct_missing):
        ax.text(i, value + 0.5, f"{value}%", ha="center", fontsize=8)
    fig.tight_layout()

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "completeness_by_column.png"
    fig.savefig(output_path)
    plt.close(fig)
    return output_path


def plot_account_status_distribution(report: QualityReport, output_dir: Path = PLOTS_DIR) -> Path:
    counts = report.categorical_validity["value_counts"]
    labels = list(counts.keys())
    values = list(counts.values())
    colors = ["#2e7d32" if label in ACCOUNT_STATUS_VALUES else "#c0392b" for label in labels]

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.bar(labels, values, color=colors)
    ax.set_title("Account Status Values Found in Raw Data\n(red = not a valid status)", fontsize=13)
    ax.set_xlabel("account_status value")
    ax.set_ylabel("Number of customers")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "account_status_distribution.png"
    fig.savefig(output_path)
    plt.close(fig)
    return output_path


# --- Orchestration (the only place doing I/O) -------------------------------------


def run_quality_analysis(
    input_path: Path = RAW_CSV_PATH,
    output_report_path: Path = DATA_QUALITY_REPORT_PATH,
    plots_dir: Path = PLOTS_DIR,
) -> QualityReport:
    logger.info("Starting quality analysis: input=%s", input_path)
    try:
        df = load_raw_data(input_path)
        report = build_quality_report(df)
        report_text = render_report_text(report)

        output_report_path.parent.mkdir(parents=True, exist_ok=True)
        output_report_path.write_text(report_text, encoding="utf-8")

        completeness_plot = plot_completeness(report, plots_dir)
        status_plot = plot_account_status_distribution(report, plots_dir)
    except (OSError, ValueError, KeyError):
        logger.exception("Quality analysis failed for %s", input_path)
        raise

    logger.info(
        "Quality analysis complete: %d rows, %d duplicate-id rows, %d invalid account_status rows. "
        "Report written to %s. Plots: %s, %s",
        report.row_count,
        report.uniqueness["duplicate_id_row_count"],
        report.categorical_validity["invalid_row_count"],
        output_report_path,
        completeness_plot,
        status_plot,
    )
    return report


if __name__ == "__main__":
    run_quality_analysis()
