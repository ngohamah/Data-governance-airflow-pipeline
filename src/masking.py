"""Part 5: Mask PII.

Masks the cleaned dataset's PII columns before it's safe to share:
  names      "John"              -> "J***"
  emails     "john.doe@x.com"    -> "j***@x.com"
  phone      "555-123-4567"      -> "***-***-4567"
  address    any value           -> "[MASKED ADDRESS]"
  DOB        "1985-03-15"        -> "1985-**-**"

Masking functions are pure (str -> str); I/O is confined to run_masking.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src.config import (
    CANONICAL_PHONE_REGEX,
    CLEANED_CSV_PATH,
    MASKED_ADDRESS_PLACEHOLDER,
    MASKED_CSV_PATH,
    MASKED_DOB_PLACEHOLDER,
    MASKED_GENERIC_PLACEHOLDER,
    MASKED_SAMPLE_PATH,
)
from src.logging_config import get_logger

logger = get_logger(__name__)


def mask_name(value: str) -> str:
    if value.strip() == "":
        return value
    return f"{value[0]}***"


def mask_email(value: str) -> str:
    if value.strip() == "":
        return value
    local, sep, domain = value.partition("@")
    if not sep or not local:
        return MASKED_GENERIC_PLACEHOLDER
    return f"{local[0]}***@{domain}"


def mask_phone(value: str) -> str:
    if value.strip() == "":
        return value
    if re.match(CANONICAL_PHONE_REGEX, value):
        return f"***-***-{value[-4:]}"
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 4:
        return f"***{digits[-4:]}"
    return MASKED_GENERIC_PLACEHOLDER


def mask_address(value: str) -> str:
    if value.strip() == "":
        return value
    return MASKED_ADDRESS_PLACEHOLDER


def mask_dob(value: str) -> str:
    if value.strip() == "":
        return value
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return f"{value[:4]}-**-**"
    return MASKED_DOB_PLACEHOLDER


_MASKERS = {
    "first_name": mask_name,
    "last_name": mask_name,
    "email": mask_email,
    "phone": mask_phone,
    "date_of_birth": mask_dob,
    "address": mask_address,
}


def mask_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    masked = df.copy()
    for column, masker in _MASKERS.items():
        masked[column] = df[column].apply(masker)
    return masked


def load_cleaned_data(path: Path = CLEANED_CSV_PATH) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def render_masked_sample(
    original: pd.DataFrame, masked: pd.DataFrame, sample_size: int = 10
) -> str:
    lines: list[str] = []
    lines.append("MASKED SAMPLE (before / after)")
    lines.append("=" * 60)
    lines.append(
        f"Showing {min(sample_size, len(original))} of {len(original)} rows across the "
        f"masked columns: {', '.join(_MASKERS.keys())}"
    )
    lines.append("")

    for i in range(min(sample_size, len(original))):
        lines.append(f"Row {i} (customer_id={original.iloc[i]['customer_id']})")
        for column in _MASKERS:
            before = original.iloc[i][column]
            after = masked.iloc[i][column]
            lines.append(f"    {column:<14} BEFORE: {before!r:<40} AFTER: {after!r}")
        lines.append("")

    return "\n".join(lines)


def run_masking(
    input_path: Path = CLEANED_CSV_PATH,
    output_csv_path: Path = MASKED_CSV_PATH,
    output_sample_path: Path = MASKED_SAMPLE_PATH,
    sample_size: int = 10,
) -> pd.DataFrame:
    logger.info("Starting PII masking: input=%s", input_path)
    try:
        df = load_cleaned_data(input_path)
        masked_df = mask_dataframe(df)

        sample_text = render_masked_sample(df, masked_df, sample_size)
        output_sample_path.parent.mkdir(parents=True, exist_ok=True)
        output_sample_path.write_text(sample_text, encoding="utf-8")

        output_csv_path.parent.mkdir(parents=True, exist_ok=True)
        masked_df.to_csv(output_csv_path, index=False)
    except (OSError, ValueError, KeyError):
        logger.exception("Masking failed for %s", input_path)
        raise

    logger.info(
        "Masking complete: %d rows masked across columns %s. Masked data: %s. Sample: %s",
        len(masked_df),
        list(_MASKERS.keys()),
        output_csv_path,
        output_sample_path,
    )
    return masked_df


if __name__ == "__main__":
    run_masking()
