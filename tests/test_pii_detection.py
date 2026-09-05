import pandas as pd
import pytest

from src.pii_detection import (
    assess_breach_risk,
    build_pii_report,
    count_pii_occurrences,
    regex_pattern_matches,
    render_report_text,
    run_pii_detection,
)


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "customer_id": ["1", "2", "3"],
            "first_name": ["John", "", "Alex"],
            "last_name": ["Doe", "Smith", ""],
            "email": ["john@x.com", "not-an-email", "alex@x.com"],
            "phone": ["555-123-4567", "555-234-5678", "garbage"],
            "date_of_birth": ["1990-01-01", "1985-05-05", ""],
            "address": ["123 Main St, Springfield", "456 Oak Ave", "789 Pine Rd"],
            "income": ["50000", "60000", ""],
            "account_status": ["active", "inactive", "active"],
            "created_date": ["2020-01-01", "2020-01-01", "2020-01-01"],
        }
    )


def test_count_pii_occurrences_per_category(sample_df):
    result = count_pii_occurrences(sample_df)
    assert result["name"]["columns"]["first_name"] == 2
    assert result["name"]["columns"]["last_name"] == 2
    assert result["contact_info"]["total_occurrences"] == 6
    assert result["sensitive_personal"]["risk_level"] == "High"


def test_regex_pattern_matches_flags_malformed(sample_df):
    result = regex_pattern_matches(sample_df)
    assert result["email_populated"] == 3
    assert result["email_pattern_matches"] == 2
    assert result["phone_populated"] == 3
    assert result["phone_pattern_matches"] == 2


def test_assess_breach_risk_full_profile_count(sample_df):
    result = assess_breach_risk(sample_df)
    # Only row 0 (John Doe) has every full-profile column populated.
    assert result["full_profile_record_count"] == 1
    assert result["total_records"] == 3


def test_render_report_text_smoke(sample_df):
    report = build_pii_report(sample_df)
    text = render_report_text(report)
    assert "PII DETECTION REPORT" in text
    assert "BREACH RISK ASSESSMENT" in text


def test_run_pii_detection_writes_report(tmp_path, sample_df):
    input_path = tmp_path / "customers_raw.csv"
    sample_df.to_csv(input_path, index=False)
    output_report = tmp_path / "pii_detection_report.txt"

    report = run_pii_detection(input_path=input_path, output_report_path=output_report)

    assert output_report.exists()
    assert report.row_count == 3
