import pandas as pd
import pytest

from src.masking import (
    mask_address,
    mask_dataframe,
    mask_dob,
    mask_email,
    mask_name,
    mask_phone,
    render_masked_sample,
    run_masking,
)


def test_mask_name():
    assert mask_name("John") == "J***"
    assert mask_name("") == ""


def test_mask_email_well_formed():
    assert mask_email("john.doe@gmail.com") == "j***@gmail.com"


def test_mask_email_malformed_falls_back():
    assert mask_email("not-an-email") == "***"
    assert mask_email("") == ""


def test_mask_phone_canonical_format():
    assert mask_phone("555-123-4567") == "***-***-4567"


def test_mask_phone_non_canonical_fallback():
    assert mask_phone("(555) 123-4567") == "***4567"
    assert mask_phone("12") == "***"
    assert mask_phone("") == ""


def test_mask_address_always_replaces_populated_values():
    assert mask_address("123 Main St, Springfield") == "[MASKED ADDRESS]"
    assert mask_address("") == ""


def test_mask_dob_iso_format():
    assert mask_dob("1985-03-15") == "1985-**-**"


def test_mask_dob_non_iso_fallback():
    assert mask_dob("invalid_date") == "****-**-**"
    assert mask_dob("") == ""


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "customer_id": ["1", "2"],
            "first_name": ["John", "Mary"],
            "last_name": ["Doe", "Smith"],
            "email": ["john.doe@gmail.com", "mary@x.com"],
            "phone": ["555-123-4567", "555-234-5678"],
            "date_of_birth": ["1985-03-15", "1990-01-01"],
            "address": ["123 Main St, Springfield", "456 Oak Ave, Metropolis"],
            "income": ["50000", "60000"],
            "account_status": ["active", "inactive"],
            "created_date": ["2020-01-01", "2020-01-01"],
        }
    )


def test_mask_dataframe_masks_only_pii_columns(sample_df):
    masked = mask_dataframe(sample_df)
    assert masked["first_name"].tolist() == ["J***", "M***"]
    assert masked["income"].tolist() == sample_df["income"].tolist()
    assert masked["account_status"].tolist() == sample_df["account_status"].tolist()


def test_render_masked_sample_shows_before_and_after(sample_df):
    masked = mask_dataframe(sample_df)
    text = render_masked_sample(sample_df, masked, sample_size=2)
    assert "BEFORE" in text
    assert "AFTER" in text
    assert "John" in text
    assert "J***" in text


def test_run_masking_writes_csv_and_sample(tmp_path, sample_df):
    input_path = tmp_path / "customers_cleaned.csv"
    sample_df.to_csv(input_path, index=False)
    output_csv = tmp_path / "customers_masked.csv"
    output_sample = tmp_path / "masked_sample.txt"

    masked_df = run_masking(
        input_path=input_path,
        output_csv_path=output_csv,
        output_sample_path=output_sample,
        sample_size=2,
    )

    assert output_csv.exists()
    assert output_sample.exists()
    assert masked_df["email"].tolist() == ["j***@gmail.com", "m***@x.com"]
