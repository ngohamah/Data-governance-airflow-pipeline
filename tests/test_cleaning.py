import pandas as pd
import pytest

from src.cleaning import (
    apply_missing_value_strategy,
    clean_data,
    normalize_date,
    normalize_name,
    normalize_phone,
    render_cleaning_log,
    run_cleaning,
)
from src.validator import validate_dataframe


def test_normalize_phone_reformats_various_shapes():
    s = pd.Series(["(555) 123-4567", "555.234.5678", "5553456789", "+1-555-456-7890", ""])
    result = normalize_phone(s)
    assert result.tolist() == [
        "555-123-4567",
        "555-234-5678",
        "555-345-6789",
        "555-456-7890",
        "",
    ]


def test_normalize_phone_leaves_unrecoverable_values_unchanged():
    s = pd.Series(["12345", "not-a-phone"])
    result = normalize_phone(s)
    assert result.tolist() == ["12345", "not-a-phone"]


def test_normalize_date_converts_alternate_formats():
    s = pd.Series(["03/15/1985", "15-Mar-1985", "1990-01-01", "invalid_date", ""])
    result = normalize_date(s)
    assert result.tolist() == ["1985-03-15", "1985-03-15", "1990-01-01", "invalid_date", ""]


def test_normalize_name_title_cases():
    s = pd.Series(["john", "MARY", "o'brien", ""])
    result = normalize_name(s)
    assert result.tolist() == ["John", "Mary", "O'Brien", ""]


@pytest.fixture
def raw_df():
    return pd.DataFrame(
        {
            "customer_id": ["1", "", "3", "4"],
            "first_name": ["john", "mary", "", "alex"],
            "last_name": ["doe", "smith", "lee", ""],
            "email": ["john@x.com", "mary@x.com", "", "alex@x.com"],
            "phone": ["(555) 123-4567", "555-234-5678", "555-345-6789", ""],
            "date_of_birth": ["1990-01-01", "03/15/1985", "1995-06-15", ""],
            "address": ["123 Main St, Springfield", "456 Oak Ave", "789 Pine Rd", "321 Elm St"],
            "income": ["50000", "60000", "", "75000"],
            "account_status": ["active", "unused", "", "suspended"],
            "created_date": ["2020-01-01", "2020-01-01", "2020-01-01", ""],
        }
    )


def test_apply_missing_value_strategy_drops_missing_customer_id(raw_df):
    cleaned, log = apply_missing_value_strategy(raw_df)
    assert len(cleaned) == 3
    assert log["dropped_by_column"]["customer_id"] == 1


def test_apply_missing_value_strategy_fills_placeholders(raw_df):
    cleaned, log = apply_missing_value_strategy(raw_df)
    assert log["placeholder_fills"]["first_name"] == 1
    assert log["placeholder_fills"]["last_name"] == 1
    assert log["placeholder_fills"]["account_status"] == 1
    assert "Unknown" in cleaned["first_name"].tolist()


def test_apply_missing_value_strategy_flags_without_fabricating(raw_df):
    _, log = apply_missing_value_strategy(raw_df)
    assert log["flagged_counts"]["email"] == 1
    assert log["flagged_counts"]["income"] == 1


def test_clean_data_normalizes_and_handles_missing(raw_df):
    cleaned, log = clean_data(raw_df)
    assert (cleaned["phone"].str.match(r"^\d{3}-\d{3}-\d{4}$|^$")).all()
    assert log["normalization"]["phone"] >= 1
    assert log["normalization"]["date_of_birth"] >= 1


def test_cleaning_improves_or_maintains_validation_pass_rate(raw_df):
    cleaned, _ = clean_data(raw_df)
    pre = validate_dataframe(raw_df)
    post = validate_dataframe(cleaned)
    assert post.invalid_row_count <= pre.invalid_row_count


def test_render_cleaning_log_smoke(raw_df):
    cleaned, log = clean_data(raw_df)
    pre = validate_dataframe(raw_df)
    post = validate_dataframe(cleaned)
    text = render_cleaning_log(log, pre, post)
    assert "CLEANING LOG" in text
    assert "POST-CLEANING VALIDATION" in text


def test_run_cleaning_writes_csv_and_log(tmp_path, raw_df):
    input_path = tmp_path / "customers_raw.csv"
    raw_df.to_csv(input_path, index=False)
    output_csv = tmp_path / "customers_cleaned.csv"
    output_log = tmp_path / "cleaning_log.txt"

    cleaned_df, post_validation = run_cleaning(
        input_path=input_path, output_csv_path=output_csv, output_log_path=output_log
    )

    assert output_csv.exists()
    assert output_log.exists()
    assert len(cleaned_df) == 3
    assert post_validation.row_count == 3
