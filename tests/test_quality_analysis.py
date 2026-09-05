import pandas as pd
import pytest

from src.quality_analysis import (
    analyze_categorical_validity,
    analyze_completeness,
    analyze_dtypes,
    analyze_format_issues,
    analyze_invalid_values,
    analyze_uniqueness,
    build_quality_report,
    render_report_text,
    run_quality_analysis,
)


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "customer_id": [1, 2, 2, None],
            "first_name": ["John", "Mary", "Mary", "Alex"],
            "last_name": ["Doe", "Smith", "Smith", "Lee"],
            "email": ["john@x.com", "not-an-email", "mary@x.com", "alex@x.com"],
            "phone": ["555-123-4567", "(555) 234-5678", "555-345-6789", "5554567890"],
            "date_of_birth": ["1990-01-01", "invalid_date", "1850-01-01", "1995-06-15"],
            "address": ["123 Main St, Springfield", "456 Oak Ave, Metropolis", None, "789 Pine Rd"],
            "income": [50000, -1000, 15000000, 60000],
            "account_status": ["active", "Active", "inactive", None],
            "created_date": ["2020-01-01", "2020-01-01", "01/02/2020", "2020-01-01"],
        }
    )


def test_analyze_completeness_counts_missing(sample_df):
    result = analyze_completeness(sample_df)
    assert result["customer_id"]["missing_count"] == 1
    assert result["address"]["missing_count"] == 1
    assert result["account_status"]["missing_pct"] == 25.0


def test_analyze_dtypes_flags_date_mismatch(sample_df):
    result = analyze_dtypes(sample_df)
    assert result["date_of_birth"]["matches_expected"] is False
    assert result["income"]["matches_expected"] is True


def test_analyze_format_issues_detects_non_canonical_phone_and_dates(sample_df):
    result = analyze_format_issues(sample_df)
    assert result["non_canonical_phone_count"] == 2  # "(555) 234-5678" and "5554567890"
    assert result["non_iso_date_counts"]["created_date"] == 1


def test_analyze_uniqueness_detects_duplicates(sample_df):
    result = analyze_uniqueness(sample_df)
    assert result["duplicate_id_row_count"] == 2
    assert 2.0 in result["duplicate_ids_sample"] or 2 in result["duplicate_ids_sample"]


def test_analyze_invalid_values_detects_all_categories(sample_df):
    result = analyze_invalid_values(sample_df)
    assert result["negative_income_count"] == 1
    assert result["income_over_max_count"] == 1
    assert result["invalid_date_literal_count"]["date_of_birth"] == 1
    assert result["age_over_150_count"] == 1


def test_analyze_categorical_validity_flags_bad_values(sample_df):
    result = analyze_categorical_validity(sample_df)
    assert result["invalid_row_count"] == 2  # "Active" (wrong case) + missing


def test_build_quality_report_and_render_text_smoke(sample_df):
    report = build_quality_report(sample_df)
    text = render_report_text(report)
    assert "DATA QUALITY REPORT" in text
    assert "COMPLETENESS" in text
    assert str(sample_df.shape[0]) in text


def test_run_quality_analysis_writes_report_and_plots(tmp_path, sample_df):
    input_path = tmp_path / "customers_raw.csv"
    sample_df.to_csv(input_path, index=False)
    output_report = tmp_path / "data_quality_report.txt"
    plots_dir = tmp_path / "plots"

    report = run_quality_analysis(
        input_path=input_path, output_report_path=output_report, plots_dir=plots_dir
    )

    assert output_report.exists()
    assert (plots_dir / "completeness_by_column.png").exists()
    assert (plots_dir / "account_status_distribution.png").exists()
    assert report.row_count == len(sample_df)
