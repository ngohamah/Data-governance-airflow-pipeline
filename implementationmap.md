# Implementation Map — PII Detection & Data Quality Validation Pipeline

Status: **DRAFT — awaiting user review before development starts.**
Source brief: [PII-Detection&Data.md](PII-Detection&Data.md)

This file is the single source of truth for scope and approach. If the plan changes
during the build, this file gets updated first so it stays trustworthy.

---

## 1. Decisions locked in with the user

| Decision | Choice | Why |
| :--- | :--- | :--- |
| Orchestration | **Apache Airflow via Docker Compose** (official `docker-compose.yaml`) | User request; more production-like than a local pip install |
| Data in git | **Gitignored** — `customers_raw.csv`, `customers_cleaned.csv`, `customers_masked.csv` are never committed | Synthetic data is fully reproducible via `data_generator.py --seed`; avoids committing PII-shaped data even if fake |
| Validation library (Part 3) | **Pandera** | DataFrame-native, fits functional style, integrates cleanly with pandas |
| `implementationmap.md` / brief | **Tracked in git, not gitignored** | Explicit user instruction |

---

## 2. Extra requirements beyond the brief (user-specified)

1. Airflow DAG orchestrates the 6 pipeline parts as tasks (see §5).
2. `data_generator.py` synthesizes `customers_raw.csv` locally (Faker, no external API),
   with an argparse CLI to control volume, and deliberately seeds every failure mode the
   brief's validation rules need to test (see §4).
3. `requirements.txt` for reproducible installs.
4. `try/except` error handling around I/O, parsing, and validation steps — no bare excepts,
   always logged with context.
5. Logging to a file (`logs/pipeline.log`) plus console, via a shared `logging_config.py`.
   No external API calls in this project, so the "batch-then-close" rule doesn't apply
   (Faker/synthetic generation is local, not rate-limited).
6. `src/config.py` holds constants: file paths, the expected schema, regex patterns,
   validation thresholds, masking rules. Nothing environment-specific lives inline in logic
   files.
7. No Jupyter notebooks — plain `.py` modules only.
8. Observability: every file the pipeline reads, writes, or **drops rows from** is logged
   with counts (e.g. "dropped 12 rows: invalid account_status").
9. Functional style: pure functions (DataFrame in → DataFrame/report out) composed in
   `pipeline.py`; side effects (I/O, logging) kept at the edges, not buried in the
   transformation functions.
10. Linting: **ruff** (lint + format in one tool, fast, minimal config) via `pyproject.toml`.
    *(Flagging this choice — not explicitly requested — happy to swap for flake8+black if
    you prefer.)*
11. Incremental commits — one logical change per commit, Claude commits on the user's
    behalf only (no co-author/collaborator trailer).
12. Plots (Part 1 completeness/format-issue visuals) get titles, axis labels, and plain-
    language framing for non-technical stakeholders — saved as PNGs alongside the reports,
    not shown inline (no notebooks).
13. Reports (`*.txt`) written in plain language for less-technical stakeholders — plain
    English section headers, no raw stack traces, no jargon.
14. `tests/` with `pytest` covering each module's main operation.
15. CI: GitHub Actions workflow running lint (`ruff`) + `pytest` on push/PR; README gets a
    status badge. *(Badge needs a GitHub remote to resolve — placeholder URL until you
    create/point me at the repo.)*
16. Never delete a file the user modified outside of Claude (especially logs) without
    asking first.

---

## 3. Directory layout (nothing created yet except this file + `.gitignore`)

```
DEM11/
├── PII-Detection&Data.md        # brief (tracked)
├── implementationmap.md         # this file (tracked)
├── README.md                    # setup, run instructions, CI badge
├── requirements.txt
├── .gitignore
├── .env.example                 # AIRFLOW_UID etc. (.env itself gitignored)
├── docker-compose.yaml          # official Airflow compose, customized image
├── Dockerfile                   # apache/airflow base + requirements.txt
├── pyproject.toml               # ruff + pytest config
│
├── src/
│   ├── __init__.py
│   ├── config.py                # constants: paths, schema, regex, thresholds, masking rules
│   ├── logging_config.py        # shared logger setup -> logs/pipeline.log + console
│   ├── data_generator.py        # argparse CLI: --rows --seed --error-rate --output
│   ├── quality_analysis.py      # Part 1: profiling
│   ├── pii_detection.py         # Part 2: PII regex + risk quantification
│   ├── validator.py             # Part 3: Pandera schemas + failure reporting
│   ├── cleaning.py              # Part 4: normalization + missing-value strategy
│   ├── masking.py               # Part 5: PII masking
│   └── pipeline.py              # Part 6: composes the above, callable standalone or from Airflow
│
├── dags/
│   └── pii_pipeline_dag.py      # Airflow TaskFlow DAG calling src.pipeline functions
│
├── data/
│   ├── raw/                     # customers_raw.csv (gitignored)
│   └── processed/               # customers_cleaned.csv, customers_masked.csv (gitignored)
│
├── reports/
│   ├── data_quality_report.txt
│   ├── pii_detection_report.txt
│   ├── validation_results.txt
│   ├── cleaning_log.txt
│   ├── masked_sample.txt
│   ├── pipeline_execution_report.txt
│   └── plots/                   # labeled PNGs backing the quality report
│
├── reflection.md
│
├── logs/                        # app + airflow logs (gitignored, .gitkeep tracked)
├── plugins/                     # empty, required by Airflow compose (.gitkeep tracked)
│
├── tests/
│   ├── __init__.py
│   ├── test_data_generator.py
│   ├── test_quality_analysis.py
│   ├── test_pii_detection.py
│   ├── test_validator.py
│   ├── test_cleaning.py
│   └── test_masking.py
│
└── .github/workflows/ci.yml     # ruff + pytest on push/PR
```

---

## 4. `data_generator.py` — coverage checklist

CLI: `python -m src.data_generator --rows 2000 --seed 42 --error-rate 0.15 --output data/raw/customers_raw.csv`

Must be able to deterministically produce, at a configurable rate, every case the brief's
validators need to catch:

- [ ] Duplicate `customer_id` values (uniqueness failure)
- [ ] Negative / zero `customer_id`
- [ ] Missing values in every column (completeness, varies by column)
- [ ] Non-alphabetic / too-short / too-long `first_name` / `last_name`
- [ ] Malformed `email` (missing `@`, missing domain, bad TLD, etc.)
- [ ] `phone` in multiple raw formats: `(555) 123-4567`, `555.123.4567`, `5551234567`,
      `+1-555-123-4567` — so normalization has real work to do
- [ ] `date_of_birth` as literal string `"invalid_date"`
- [ ] `date_of_birth` producing age > 150 and age < 0
- [ ] `date_of_birth` / `created_date` in non-ISO formats (`MM/DD/YYYY`, `DD-Mon-YYYY`) to
      exercise format-issue detection before normalization
- [ ] `address` too short (<10 chars) and too long (>200 chars)
- [ ] `income` negative and `income` > \$10,000,000
- [ ] `account_status` outside `{active, inactive, suspended}` (typos, different casing, nulls)
- [ ] `created_date` earlier than `date_of_birth` (logical inconsistency, bonus check)
- [ ] A clean majority of rows that pass every rule, so post-cleaning validation has a
      meaningful "valid" baseline to compare against

All faults are injected with independent, seedable probabilities so re-running with the
same `--seed` reproduces an identical file — required for repeatable tests and CI.

---

## 5. Airflow DAG shape (`pii_pipeline_dag.py`)

TaskFlow API, one task per brief part, all calling pure functions from `src/pipeline.py`
(so the same logic is unit-testable outside Airflow):

```
generate_or_sense_raw_data
        │
        ▼
   profile_quality  ──────────► data_quality_report.txt (+ plots/)
        │
        ▼
   detect_pii  ────────────────► pii_detection_report.txt
        │
        ▼
   validate_raw  ──────────────► validation_results.txt
        │
        ▼
   clean_data  ─────────────────► customers_cleaned.csv + cleaning_log.txt
        │
        ▼
   validate_cleaned (re-run validators, confirm fixes)
        │
        ▼
   mask_pii  ───────────────────► customers_masked.csv + masked_sample.txt
        │
        ▼
   write_pipeline_execution_report ─► pipeline_execution_report.txt
```

- Each task wraps its work in try/except, logs start/end/row-counts/dropped-rows, and
  raises on unrecoverable failure so Airflow marks it failed (no silent swallowing).
- `data_generator.py` is a standalone CLI the user runs manually (per their instruction —
  they own generating `customers_raw.csv`); the DAG's first task **senses** the file
  rather than generating it, so Airflow failure/retry semantics apply if it's missing.

### Retry + failure-alert policy (user-requested)

Applied via `default_args` on the DAG, so every task inherits it:

```python
default_args = {
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "email_on_retry": False,
    "email_on_failure": True,
    "email": [os.environ["ADMIN_EMAIL"]],
}
```

- On task failure: retry up to 3 times, 5 minutes apart.
- If all 3 retries are exhausted: Airflow emails `ADMIN_EMAIL` via its SMTP backend.
- `ADMIN_EMAIL` and SMTP credentials (`AIRFLOW__SMTP__SMTP_HOST/PORT/USER/PASSWORD/MAIL_FROM`)
  are read from `.env` (gitignored, real values filled in locally) — `.env.example` ships
  placeholders only, nothing sent anywhere without the user's own SMTP config.
- Note: this project has no external API calls (data is local/synthetic), so "API failure"
  becomes "any task failure" — the same retry/alert mechanics, applied pipeline-wide rather
  than to one API call specifically.

---

## 6. Open items / assumptions to confirm

1. **CI badge URL** — needs a GitHub remote. I'll add the workflow now and wire the badge
   once you tell me the repo URL (or push it yourself and share the URL).
2. **Ruff over flake8+black** for linting — flagging per your "inform me before
   implementing" instruction; say the word if you'd rather use something else.
3. **Docker Compose specifics** — I'll use the official Airflow 2.x `docker-compose.yaml`
   (Postgres metadata DB, `CeleryExecutor` is overkill for this size, so I'll default to
   `LocalExecutor` unless you want Celery). Will confirm image version in `Dockerfile`.
4. Report files (`.txt`) will be written by the pipeline at runtime into `reports/`, not
   hand-written — they're generated artifacts.
5. **Admin failure-alert email** — `ADMIN_EMAIL` and SMTP credentials ship as placeholders
   in `.env.example`; you'll fill in real values in your local `.env` (gitignored) before
   the DAG can actually send mail. Without it, tasks still retry 3x/5min but the final
   failure email will just fail to send (logged, not fatal to the DAG run).

---

## 7. Next steps after your review

Once you approve this map, the build order is:
1. Scaffold repo structure, `requirements.txt`, `config.py`, `logging_config.py`.
2. `data_generator.py` + its tests (so we have data to develop against immediately).
3. Parts 1–5 modules + tests, each committed separately.
4. `pipeline.py` composing them (Part 6) + its test.
5. Airflow DAG + Docker Compose wiring.
6. CI workflow + README (with badge placeholder).
7. `reflection.md` (Part 7) written last, once real findings from the pipeline exist to
   reflect on.
