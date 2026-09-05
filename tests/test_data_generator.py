import pandas as pd
import pytest

from src.config import ACCOUNT_STATUS_VALUES, EXPECTED_COLUMNS
from src.data_generator import generate_dataset, parse_args


@pytest.fixture
def df():
    return generate_dataset(n_rows=500, seed=7)


def test_columns_match_schema(df):
    assert list(df.columns) == EXPECTED_COLUMNS


def test_row_count(df):
    assert len(df) == 500


def test_deterministic_with_same_seed():
    first = generate_dataset(n_rows=200, seed=42)
    second = generate_dataset(n_rows=200, seed=42)
    pd.testing.assert_frame_equal(first, second)


def test_different_seed_changes_output():
    first = generate_dataset(n_rows=200, seed=1)
    second = generate_dataset(n_rows=200, seed=2)
    assert not first.equals(second)


def test_contains_duplicate_customer_ids(df):
    assert df["customer_id"].duplicated().sum() > 0


def test_contains_missing_value_in_every_column(df):
    as_na = df.replace("", pd.NA)
    missing_counts = as_na.isna().sum()
    assert (missing_counts > 0).all(), missing_counts[missing_counts == 0].index.tolist()


def test_contains_invalid_date_literal(df):
    assert (df["date_of_birth"] == "invalid_date").any()


def test_contains_account_status_outside_allowed_values(df):
    invalid = ~df["account_status"].isin(ACCOUNT_STATUS_VALUES)
    assert invalid.sum() > 0


def test_contains_negative_and_over_max_income(df):
    numeric_income = pd.to_numeric(df["income"], errors="coerce")
    assert (numeric_income < 0).sum() > 0
    assert (numeric_income > 10_000_000).sum() > 0


def test_contains_non_canonical_phone_formats(df):
    canonical = df["phone"].str.match(r"^\d{3}-\d{3}-\d{4}$")
    assert (~canonical.fillna(True)).sum() > 0


def test_rejects_non_positive_row_count():
    with pytest.raises(ValueError):
        generate_dataset(n_rows=0)


def test_rejects_out_of_range_error_rate():
    with pytest.raises(ValueError):
        generate_dataset(n_rows=10, error_rate=1.5)


def test_small_row_count_does_not_crash():
    small = generate_dataset(n_rows=5, seed=1)
    assert len(small) == 5


def test_parse_args_defaults():
    args = parse_args([])
    assert args.rows == 1000
    assert args.seed == 42
    assert 0 <= args.error_rate <= 1


def test_cli_writes_csv(tmp_path):
    from src.data_generator import main

    output = tmp_path / "customers_raw.csv"
    main(["--rows", "30", "--seed", "3", "--output", str(output)])

    assert output.exists()
    written = pd.read_csv(output, dtype=str, keep_default_na=False)
    assert len(written) == 30
    assert list(written.columns) == EXPECTED_COLUMNS
