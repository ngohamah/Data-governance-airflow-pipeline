"""Synthetic customers_raw.csv generator.

Produces a mostly-clean dataset with deliberately injected data-quality issues,
so every rule in the brief's validation table has real rows to catch. Faults are
seeded deterministically: the same --seed always produces the same file.

CLI:
    python -m src.data_generator --rows 2000 --seed 42 --error-rate 0.15 \\
        --output data/raw/customers_raw.csv

No external API is called — all data is generated locally via Faker — so there is
no rate-limit / batching concern for this module.
"""

from __future__ import annotations

import argparse
import random
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from faker import Faker

from src.config import ALTERNATE_DATE_FORMATS, EXPECTED_COLUMNS, RAW_CSV_PATH
from src.logging_config import get_logger

logger = get_logger(__name__)

Row = dict[str, Any]
FaultFn = Callable[[Row, Faker, random.Random], Row]

ACCOUNT_STATUSES = ("active", "inactive", "suspended")

INVALID_NAME_SAMPLES = ("J0hn", "M@rie", "A", "12345", "O'Brien!!", "X" * 60)
INVALID_EMAIL_SAMPLES = (
    "not-an-email",
    "missing.domain@",
    "user@nodot",
    "@no-local-part.com",
    "user domain.com",
)
INVALID_PHONE_SAMPLES = ("12345", "phone-number", "000-00-0000", "abcdefghij")
INVALID_ACCOUNT_STATUS_SAMPLES = ("Active", "ACTIVE", "pending", "closed", "N/A", "")


# --- Clean row generation ------------------------------------------------------


def _random_phone_digits(rng: random.Random) -> str:
    area = rng.randint(200, 999)
    exchange = rng.randint(200, 999)
    line = rng.randint(1000, 9999)
    return f"{area}{exchange}{line}"


def generate_clean_row(faker: Faker, rng: random.Random, customer_id: int) -> Row:
    """Build one fully schema-valid row."""
    first_name = faker.first_name()
    last_name = faker.last_name()
    dob = faker.date_of_birth(minimum_age=18, maximum_age=90)
    created = faker.date_between(start_date=dob + timedelta(days=365 * 18), end_date="today")
    digits = _random_phone_digits(rng)

    return {
        "customer_id": customer_id,
        "first_name": first_name,
        "last_name": last_name,
        "email": f"{first_name.lower()}.{last_name.lower()}@{faker.free_email_domain()}",
        "phone": f"{digits[:3]}-{digits[3:6]}-{digits[6:]}",
        "date_of_birth": dob.isoformat(),
        "address": faker.address().replace("\n", ", "),
        "income": round(rng.uniform(20_000, 250_000), 2),
        "account_status": rng.choice(ACCOUNT_STATUSES),
        "created_date": created.isoformat(),
    }


# --- Individual fault appliers (each returns a NEW row, input untouched) --------


def _with(row: Row, **changes: Any) -> Row:
    new_row = dict(row)
    new_row.update(changes)
    return new_row


def fault_missing(column: str) -> FaultFn:
    def _apply(row: Row, faker: Faker, rng: random.Random) -> Row:
        return _with(row, **{column: ""})

    return _apply


def fault_invalid_name(row: Row, faker: Faker, rng: random.Random) -> Row:
    column = rng.choice(["first_name", "last_name"])
    return _with(row, **{column: rng.choice(INVALID_NAME_SAMPLES)})


def fault_invalid_email(row: Row, faker: Faker, rng: random.Random) -> Row:
    return _with(row, email=rng.choice(INVALID_EMAIL_SAMPLES))


def fault_invalid_phone(row: Row, faker: Faker, rng: random.Random) -> Row:
    return _with(row, phone=rng.choice(INVALID_PHONE_SAMPLES))


def fault_phone_format_variation(row: Row, faker: Faker, rng: random.Random) -> Row:
    digits = re.sub(r"\D", "", row["phone"]) or _random_phone_digits(rng)
    area, exch, line = digits[:3], digits[3:6], digits[6:10]
    variant = rng.choice(
        [
            f"({area}) {exch}-{line}",
            f"{area}.{exch}.{line}",
            f"{area}{exch}{line}",
            f"+1-{area}-{exch}-{line}",
            f"+1 {area} {exch} {line}",
        ]
    )
    return _with(row, phone=variant)


def fault_invalid_date_literal(column: str) -> FaultFn:
    def _apply(row: Row, faker: Faker, rng: random.Random) -> Row:
        return _with(row, **{column: "invalid_date"})

    return _apply


def fault_age_over_150(row: Row, faker: Faker, rng: random.Random) -> Row:
    year = date.today().year - rng.randint(151, 200)
    return _with(row, date_of_birth=f"{year}-01-15")


def fault_age_negative(row: Row, faker: Faker, rng: random.Random) -> Row:
    future = date.today() + timedelta(days=rng.randint(30, 3650))
    return _with(row, date_of_birth=future.isoformat())


def fault_non_iso_date_format(column: str) -> FaultFn:
    def _apply(row: Row, faker: Faker, rng: random.Random) -> Row:
        parsed = datetime.strptime(row[column], "%Y-%m-%d")
        return _with(row, **{column: parsed.strftime(rng.choice(ALTERNATE_DATE_FORMATS))})

    return _apply


def fault_address_too_short(row: Row, faker: Faker, rng: random.Random) -> Row:
    return _with(row, address=rng.choice(["1 A St", "Short", "12 Elm"]))


def fault_address_too_long(row: Row, faker: Faker, rng: random.Random) -> Row:
    return _with(row, address=(row["address"] + " ") * 10)


def fault_negative_income(row: Row, faker: Faker, rng: random.Random) -> Row:
    return _with(row, income=-round(rng.uniform(1_000, 50_000), 2))


def fault_income_over_max(row: Row, faker: Faker, rng: random.Random) -> Row:
    return _with(row, income=round(rng.uniform(10_000_001, 20_000_000), 2))


def fault_invalid_account_status(row: Row, faker: Faker, rng: random.Random) -> Row:
    return _with(row, account_status=rng.choice(INVALID_ACCOUNT_STATUS_SAMPLES))


def fault_created_before_dob(row: Row, faker: Faker, rng: random.Random) -> Row:
    dob = datetime.strptime(row["date_of_birth"], "%Y-%m-%d").date()
    before = dob - timedelta(days=rng.randint(30, 3650))
    return _with(row, created_date=before.isoformat())


def _build_guaranteed_fault_specs() -> list[tuple[str, FaultFn]]:
    """One entry per distinct fault category the brief's validators must catch.

    Order matters only in that it determines which of the first N rows (N = number
    of specs) gets which guaranteed fault when --rows is small; most broadly useful
    faults are listed first so small datasets still cover the important cases.
    """
    specs: list[tuple[str, FaultFn]] = [
        ("invalid_name", fault_invalid_name),
        ("invalid_email", fault_invalid_email),
        ("invalid_phone", fault_invalid_phone),
        ("phone_format_variation", fault_phone_format_variation),
        ("invalid_date_literal_dob", fault_invalid_date_literal("date_of_birth")),
        ("age_over_150", fault_age_over_150),
        ("age_negative", fault_age_negative),
        ("non_iso_date_format_dob", fault_non_iso_date_format("date_of_birth")),
        ("non_iso_date_format_created", fault_non_iso_date_format("created_date")),
        ("address_too_short", fault_address_too_short),
        ("address_too_long", fault_address_too_long),
        ("negative_income", fault_negative_income),
        ("income_over_max", fault_income_over_max),
        ("invalid_account_status", fault_invalid_account_status),
        ("created_before_dob", fault_created_before_dob),
    ]
    # One guaranteed "missing value" row per column so completeness reporting has
    # a real gap in every column, not just a random subset.
    specs += [(f"missing_{col}", fault_missing(col)) for col in EXPECTED_COLUMNS]
    return specs


HARD_FAULT_POOL: list[FaultFn] = [fn for _, fn in _build_guaranteed_fault_specs()]


# --- Duplicate customer_id (whole-row-list operation, not a per-row fault) ------


def _inject_duplicate_ids(rows: list[Row], rng: random.Random, duplicate_rate: float) -> list[Row]:
    n = len(rows)
    if n < 2:
        return rows
    n_duplicates = max(1, round(n * duplicate_rate))
    result = [dict(r) for r in rows]
    for _ in range(n_duplicates):
        target_idx = rng.randrange(n)
        source_idx = rng.randrange(n)
        if source_idx == target_idx:
            continue
        result[target_idx]["customer_id"] = result[source_idx]["customer_id"]
    return result


# --- Dataset assembly ------------------------------------------------------------


def generate_dataset(
    n_rows: int,
    seed: int = 42,
    error_rate: float = 0.15,
    format_variation_rate: float = 0.3,
    duplicate_rate: float = 0.02,
) -> pd.DataFrame:
    """Build the full synthetic dataset as a DataFrame, columns in schema order."""
    if n_rows <= 0:
        raise ValueError("n_rows must be positive")
    if not 0 <= error_rate <= 1:
        raise ValueError("error_rate must be between 0 and 1")

    faker = Faker()
    faker.seed_instance(seed)
    rng = random.Random(seed)

    rows = [generate_clean_row(faker, rng, customer_id=i) for i in range(1, n_rows + 1)]

    guaranteed_specs = _build_guaranteed_fault_specs()
    if n_rows < len(guaranteed_specs):
        logger.warning(
            "rows=%d is smaller than the %d guaranteed fault categories; "
            "only the first %d categories will be represented",
            n_rows,
            len(guaranteed_specs),
            n_rows,
        )
    for i, (_name, fault_fn) in enumerate(guaranteed_specs):
        if i >= n_rows:
            break
        rows[i] = fault_fn(rows[i], faker, rng)

    for i in range(len(guaranteed_specs), n_rows):
        if rng.random() < error_rate:
            fault_fn = rng.choice(HARD_FAULT_POOL)
            rows[i] = fault_fn(rows[i], faker, rng)
        if rng.random() < format_variation_rate:
            rows[i] = fault_phone_format_variation(rows[i], faker, rng)

    rows = _inject_duplicate_ids(rows, rng, duplicate_rate)
    rng.shuffle(rows)

    return pd.DataFrame(rows)[EXPECTED_COLUMNS]


# --- CLI -------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic customers_raw.csv data.")
    parser.add_argument("--rows", "-n", type=int, default=1000, help="Number of rows to generate.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    parser.add_argument(
        "--error-rate",
        type=float,
        default=0.15,
        help="Probability a non-guaranteed row gets one injected hard fault.",
    )
    parser.add_argument(
        "--format-variation-rate",
        type=float,
        default=0.3,
        help="Probability a non-guaranteed row's phone gets a non-canonical format.",
    )
    parser.add_argument(
        "--duplicate-rate",
        type=float,
        default=0.02,
        help="Fraction of rows whose customer_id is overwritten with a duplicate.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(RAW_CSV_PATH),
        help="Output CSV path.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logger.info(
        "Generating synthetic dataset: rows=%d seed=%d error_rate=%.2f "
        "format_variation_rate=%.2f duplicate_rate=%.2f output=%s",
        args.rows,
        args.seed,
        args.error_rate,
        args.format_variation_rate,
        args.duplicate_rate,
        args.output,
    )
    try:
        df = generate_dataset(
            n_rows=args.rows,
            seed=args.seed,
            error_rate=args.error_rate,
            format_variation_rate=args.format_variation_rate,
            duplicate_rate=args.duplicate_rate,
        )
        output_path = args.output
        from pathlib import Path

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
    except (ValueError, OSError):
        logger.exception("Failed to generate synthetic dataset")
        raise
    else:
        logger.info("Wrote %d rows to %s", len(df), output_path)


if __name__ == "__main__":
    main()
