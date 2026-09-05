import pandas as pd
import pytest

from src.validator import render_report_text, run_validation, validate_dataframe


@pytest.fixture
def valid_df():
    return pd.DataFrame(
        {
            "customer_id": ["1", "2", "3"],
            "first_name": ["John", "Mary", "Alex"],
            "last_name": ["Doe", "Smith", "Lee"],
            "email": ["john@x.com", "mary@x.com", "alex@x.com"],
            "phone": ["555-123-4567", "555-234-5678", "555-345-6789"],
            "date_of_birth": ["1990-01-01", "1985-05-05", "2000-12-31"],
            "address": [
                "123 Main Street, Springfield",
                "456 Oak Avenue, Metropolis",
                "789 Pine Road",
            ],
            "income": ["50000", "60000", "75000"],
            "account_status": ["active", "inactive", "suspended"],
            "created_date": ["2020-01-01", "2019-06-15", "2021-03-10"],
        }
    )


def test_valid_dataframe_passes(valid_df):
    result = validate_dataframe(valid_df)
    assert result.is_valid
    assert result.invalid_row_count == 0


def test_duplicate_customer_id_flagged(valid_df):
    df = valid_df.copy()
    df.loc[1, "customer_id"] = "1"
    result = validate_dataframe(df)
    assert not result.is_valid
    assert "customer_id.unique" in result.failures_by_check


def test_missing_required_field_flagged(valid_df):
    df = valid_df.copy()
    df.loc[0, "email"] = ""
    result = validate_dataframe(df)
    assert "email.required" in result.failures_by_check


def test_invalid_email_format_flagged(valid_df):
    df = valid_df.copy()
    df.loc[0, "email"] = "not-an-email"
    result = validate_dataframe(df)
    assert "email.valid_email" in result.failures_by_check


def test_invalid_account_status_flagged(valid_df):
    df = valid_df.copy()
    df.loc[0, "account_status"] = "pending"
    result = validate_dataframe(df)
    assert "account_status.valid_status" in result.failures_by_check


def test_income_out_of_range_flagged(valid_df):
    df = valid_df.copy()
    df.loc[0, "income"] = "-500"
    df.loc[1, "income"] = "20000000"
    result = validate_dataframe(df)
    assert result.failures_by_check["income.in_range"]["failure_count"] == 2


def test_implausible_age_flagged(valid_df):
    df = valid_df.copy()
    df.loc[0, "date_of_birth"] = "1800-01-01"
    result = validate_dataframe(df)
    assert "date_of_birth.plausible_age" in result.failures_by_check


def test_invalid_date_literal_flagged(valid_df):
    df = valid_df.copy()
    df.loc[0, "created_date"] = "invalid_date"
    result = validate_dataframe(df)
    assert "created_date.valid_date_format" in result.failures_by_check


def test_render_report_text_all_valid(valid_df):
    result = validate_dataframe(valid_df)
    text = render_report_text(result)
    assert "All rows passed every validation rule." in text


def test_render_report_text_with_failures(valid_df):
    df = valid_df.copy()
    df.loc[0, "email"] = "bad"
    result = validate_dataframe(df)
    text = render_report_text(result)
    assert "FAILURES BY COLUMN AND RULE" in text
    assert "email.valid_email" in text


def test_run_validation_writes_report(tmp_path, valid_df):
    input_path = tmp_path / "customers_raw.csv"
    valid_df.to_csv(input_path, index=False)
    output_report = tmp_path / "validation_results.txt"

    result = run_validation(input_path=input_path, output_report_path=output_report)

    assert output_report.exists()
    assert result.is_valid
