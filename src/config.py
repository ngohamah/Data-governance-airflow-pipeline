"""Project-wide constants: paths, schema, validation thresholds, regex patterns.

Nothing here changes across a pipeline run — that's what makes it a config module
rather than logic. Logic modules import from here instead of hard-coding values.
"""

from __future__ import annotations

from pathlib import Path

# --- Paths -------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_RAW_DIR = BASE_DIR / "data" / "raw"
DATA_PROCESSED_DIR = BASE_DIR / "data" / "processed"
REPORTS_DIR = BASE_DIR / "reports"
PLOTS_DIR = REPORTS_DIR / "plots"
LOGS_DIR = BASE_DIR / "logs"

RAW_CSV_PATH = DATA_RAW_DIR / "customers_raw.csv"
CLEANED_CSV_PATH = DATA_PROCESSED_DIR / "customers_cleaned.csv"
MASKED_CSV_PATH = DATA_PROCESSED_DIR / "customers_masked.csv"

DATA_QUALITY_REPORT_PATH = REPORTS_DIR / "data_quality_report.txt"
PII_DETECTION_REPORT_PATH = REPORTS_DIR / "pii_detection_report.txt"
VALIDATION_RESULTS_PATH = REPORTS_DIR / "validation_results.txt"
CLEANING_LOG_PATH = REPORTS_DIR / "cleaning_log.txt"
MASKED_SAMPLE_PATH = REPORTS_DIR / "masked_sample.txt"
PIPELINE_EXECUTION_REPORT_PATH = REPORTS_DIR / "pipeline_execution_report.txt"

LOG_FILE_PATH = LOGS_DIR / "pipeline.log"

# --- Expected schema (Part 1 / brief section "Column Type & Validation Rules") ----

EXPECTED_COLUMNS = [
    "customer_id",
    "first_name",
    "last_name",
    "email",
    "phone",
    "date_of_birth",
    "address",
    "income",
    "account_status",
    "created_date",
]

ACCOUNT_STATUS_VALUES = {"active", "inactive", "suspended"}

DATE_FORMAT = "%Y-%m-%d"

NAME_MIN_LEN = 2
NAME_MAX_LEN = 50

ADDRESS_MIN_LEN = 10
ADDRESS_MAX_LEN = 200

INCOME_MIN = 0
INCOME_MAX = 10_000_000

MAX_PLAUSIBLE_AGE = 150
MIN_PLAUSIBLE_AGE = 0

# --- Regex patterns (Part 2 PII detection + Part 3 validation) ----------------

EMAIL_REGEX = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

# Matches the common raw phone shapes the generator emits: (555) 123-4567,
# 555.123.4567, 5551234567, +1-555-123-4567, 555-123-4567.
PHONE_REGEX = r"^\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}$"
PHONE_DIGIT_COUNT = 10
NORMALIZED_PHONE_TEMPLATE = "{}-{}-{}"  # XXX-XXX-XXXX

NAME_ALPHA_REGEX = r"^[A-Za-z]+(?:[ '-][A-Za-z]+)*$"

# --- Masking rules (Part 5) ---------------------------------------------------

MASKED_ADDRESS_PLACEHOLDER = "[MASKED ADDRESS]"

# --- Missing-value strategy (Part 4) ------------------------------------------

# Column -> strategy: "flag" keeps the row and records it, "placeholder" fills a
# safe default, "drop" removes the row. Chosen per column based on whether the
# column is required for the row to be usable downstream.
MISSING_VALUE_STRATEGY = {
    "customer_id": "drop",  # can't identify or dedupe a customer without this
    "first_name": "placeholder",
    "last_name": "placeholder",
    "email": "flag",
    "phone": "flag",
    "date_of_birth": "flag",
    "address": "flag",
    "income": "flag",
    "account_status": "placeholder",
    "created_date": "flag",
}

PLACEHOLDER_VALUES = {
    "first_name": "Unknown",
    "last_name": "Unknown",
    "account_status": "unknown",
}
