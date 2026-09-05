"""Part 2: Detect PII.

Identifies which columns hold personally identifiable information, uses regex
to confirm email/phone values actually look like contact info, and quantifies
breach risk (how many records carry a full identity profile).

Analysis functions are pure (DataFrame in, plain-data result out); I/O is
confined to run_pii_detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import (
    EMAIL_REGEX,
    FULL_PROFILE_COLUMNS,
    PHONE_REGEX,
    PII_CATEGORIES,
    PII_CATEGORY_RISK,
    PII_DETECTION_REPORT_PATH,
    RAW_CSV_PATH,
)
from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class PiiReport:
    row_count: int
    category_occurrences: dict[str, Any]
    regex_matches: dict[str, Any]
    breach_risk: dict[str, Any]


def load_raw_data(path: Path = RAW_CSV_PATH) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _non_missing(series: pd.Series) -> pd.Series:
    return series[series.str.strip() != ""]


def count_pii_occurrences(df: pd.DataFrame) -> dict[str, Any]:
    """Count populated values per PII category/column — each is one exposed field."""
    result: dict[str, Any] = {}
    for category, columns in PII_CATEGORIES.items():
        per_column = {col: int(len(_non_missing(df[col]))) for col in columns if col in df.columns}
        result[category] = {
            "columns": per_column,
            "total_occurrences": sum(per_column.values()),
            "risk_level": PII_CATEGORY_RISK[category],
        }
    return result


def regex_pattern_matches(df: pd.DataFrame) -> dict[str, Any]:
    """Confirm which populated email/phone values actually match the expected pattern."""
    email = _non_missing(df["email"])
    phone = _non_missing(df["phone"])

    email_matches = int(email.str.match(EMAIL_REGEX).sum())
    phone_matches = int(phone.str.match(PHONE_REGEX).sum())

    return {
        "email_populated": int(len(email)),
        "email_pattern_matches": email_matches,
        "email_pattern_non_matches": int(len(email)) - email_matches,
        "phone_populated": int(len(phone)),
        "phone_pattern_matches": phone_matches,
        "phone_pattern_non_matches": int(len(phone)) - phone_matches,
    }


def assess_breach_risk(df: pd.DataFrame) -> dict[str, Any]:
    total = len(df)
    non_missing_mask = pd.Series(True, index=df.index)
    for col in FULL_PROFILE_COLUMNS:
        non_missing_mask &= df[col].str.strip() != ""
    full_profile_count = int(non_missing_mask.sum())

    return {
        "total_records": total,
        "full_profile_columns": FULL_PROFILE_COLUMNS,
        "full_profile_record_count": full_profile_count,
        "full_profile_pct": round(100 * full_profile_count / total, 2) if total else 0.0,
    }


def build_pii_report(df: pd.DataFrame) -> PiiReport:
    return PiiReport(
        row_count=len(df),
        category_occurrences=count_pii_occurrences(df),
        regex_matches=regex_pattern_matches(df),
        breach_risk=assess_breach_risk(df),
    )


def render_report_text(report: PiiReport) -> str:
    lines: list[str] = []
    lines.append("PII DETECTION REPORT")
    lines.append("=" * 60)
    lines.append(f"Total records scanned: {report.row_count}")
    lines.append("")
    lines.append(
        "This report identifies which columns contain personally identifiable "
        "information (PII), how often that information is present, and how "
        "exposed the dataset would be in the event of a data breach."
    )
    lines.append("")

    lines.append("1. PII FOUND, BY CATEGORY")
    lines.append("-" * 60)
    for category, stats in report.category_occurrences.items():
        lines.append(f"  Category: {category}  (breach risk if exposed: {stats['risk_level']})")
        for column, count in stats["columns"].items():
            lines.append(f"      {column:<16} {count} populated values")
        lines.append(f"      -> {stats['total_occurrences']} total occurrences")
    lines.append("")

    lines.append("2. REGEX-CONFIRMED CONTACT INFO")
    lines.append("-" * 60)
    rm = report.regex_matches
    lines.append(
        f"  Email: {rm['email_populated']} populated, "
        f"{rm['email_pattern_matches']} match a valid email pattern, "
        f"{rm['email_pattern_non_matches']} do not."
    )
    lines.append(
        f"  Phone: {rm['phone_populated']} populated, "
        f"{rm['phone_pattern_matches']} match a valid phone pattern, "
        f"{rm['phone_pattern_non_matches']} do not."
    )
    lines.append("")

    lines.append("3. BREACH RISK ASSESSMENT")
    lines.append("-" * 60)
    br = report.breach_risk
    lines.append(
        "  A 'full identity profile' means a single record where name, email, "
        "phone, date of birth, AND address are all present — the combination "
        "most useful for identity theft or targeted fraud."
    )
    lines.append(
        f"  Records with a full identity profile: {br['full_profile_record_count']} "
        f"of {br['total_records']} ({br['full_profile_pct']}%)"
    )
    lines.append(
        "  Impact if breached: every one of these records could be used to "
        "impersonate a real customer, open fraudulent accounts in their name, "
        "or target them with convincing phishing attacks."
    )
    lines.append("")

    return "\n".join(lines)


def run_pii_detection(
    input_path: Path = RAW_CSV_PATH,
    output_report_path: Path = PII_DETECTION_REPORT_PATH,
) -> PiiReport:
    logger.info("Starting PII detection: input=%s", input_path)
    try:
        df = load_raw_data(input_path)
        report = build_pii_report(df)
        report_text = render_report_text(report)

        output_report_path.parent.mkdir(parents=True, exist_ok=True)
        output_report_path.write_text(report_text, encoding="utf-8")
    except (OSError, ValueError, KeyError):
        logger.exception("PII detection failed for %s", input_path)
        raise

    logger.info(
        "PII detection complete: %d records, %d with a full identity profile. Report: %s",
        report.row_count,
        report.breach_risk["full_profile_record_count"],
        output_report_path,
    )
    return report


if __name__ == "__main__":
    run_pii_detection()
