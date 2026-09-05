# Reflection & Governance

> **Note on the numbers below:** this reflection is a hand-written document,
> not a generated report — unlike the files in `reports/`, it does not get
> rewritten when the pipeline runs again. Every figure cited here (duplicate
> counts, invalid-row percentages, PII risk stats, etc.) comes from one
> specific run:
>
> ```bash
> python -m src.data_generator --rows 500 --seed 2026 --output data/raw/customers_raw.csv
> python -m src.pipeline
> ```
>
> Generating data with different `--rows`/`--seed`/`--error-rate` values will
> change the numbers in `reports/*.txt` but will **not** update this file —
> the qualitative conclusions (which issue types occur, why each fix/masking
> choice was made, the validation/production-ops reasoning) still hold, but
> the specific figures should be treated as a snapshot from the run above,
> not a live summary of whatever is currently in `reports/`.

## 1. Top 5 Data Quality Issues

**1. Duplicate `customer_id` (20 of 500 rows, 4%).**
Identified by the Part 3 validator's uniqueness check. The cleaning stage
(Part 4) does *not* fix this — per the brief, Part 4's scope is normalization
and missing-value handling, not deduplication/entity resolution, so these 20
rows still fail validation after cleaning. Impact: any downstream join or
aggregation keyed on `customer_id` (billing, support lookups, analytics)
would silently double-count or misattribute these customers. This is the
single largest category of *unresolved* failure after cleaning and, in a
real project, would need its own remediation step (e.g. flag-for-manual-merge
rather than silent overwrite).

**2. Missing values scattered across every column (0.2%-1.0% each).**
Identified via the Part 1 completeness report. Fixed with a per-column
strategy rather than one blanket rule: drop the row if `customer_id` is
missing (unusable without it), fill a placeholder for low-stakes categorical
fields (`first_name`/`last_name`/`account_status`), and leave everything else
blank but logged for manual review. Impact if left unhandled: naive
`dropna()` would have discarded far more rows than necessary (every row with
*any* gap, not just the ones that matter).

**3. Inconsistent phone formats (123 of 500 raw values not in `XXX-XXX-XXXX`).**
Identified via format-issue detection in Part 1. Fixed by extracting digits
and re-formatting (119 values changed after also stripping a leading `1`
country code). Impact if unfixed: string-matching or export logic downstream
would treat `(555) 123-4567` and `555-123-4567` as different phone numbers
for the same person.

**4. Implausible or literally invalid dates (`invalid_date` literal x5,
age > 150 x4, age < 0 x5, non-ISO formats x11 combined).**
Identified by combining Part 1's format/invalid-value checks with Part 3's
date-format and plausible-age rules. Reformattable dates (different but
valid formats) were fixed; the literal string `"invalid_date"` and
implausible ages were *not* fabricated a fix — they're left failing and
flagged, since guessing a birth date would be worse than admitting it's
unknown. Impact: age-based segmentation or eligibility logic would silently
misfire on ~2% of rows if these weren't caught first.

**5. Invalid `account_status` values (8 of 500 — case variants, `pending`, and
missing).** Identified by categorical validity checks in Parts 1 and 3.
Missing values got a placeholder of `"unknown"` — deliberately *not* one of
the three valid statuses, so it still fails validation after cleaning rather
than silently becoming `"active"` by default. Impact: without this
distinction, an automated pipeline might accidentally activate or suspend an
account based on a guess.

## 2. Risk Assessment: PII Sensitivity

**96.2% of records (481/500) carry a "full identity profile"** — name,
email, phone, date of birth, *and* address all present simultaneously. That
combination is the one most useful for identity theft, account takeover, or
convincing phishing, so a breach of this dataset would be high-impact almost
across the board, not a tail risk affecting a small subset. Contact info and
sensitive personal data (DOB/address) are the highest-risk categories
because they're both highly identifying *and* directly actionable by an
attacker; name alone is lower risk in isolation but compounds the others.
Income was categorized as PII in Part 2 (financial category) but — see
below — is a scope gap in what actually gets masked.

## 3. Masking Trade-offs: Utility vs. Privacy

Every masking choice traded some analytical utility for privacy:

- **Names → `J***`**: preserves first-initial for alphabetized displays, loses
  everything else. Reversible only by someone who already has other
  identifying context.
- **Email → `j***@domain.com`**: keeps the domain, which preserves the
  ability to analyze provider distribution (Gmail vs. corporate domains) —
  a deliberate utility/privacy compromise, not an oversight.
- **Phone → `***-***-4567`**: keeping the last 4 digits mirrors how banks and
  support desks verify identity ("can you confirm the last 4 of your
  number?"), so it retains real operational utility, at the cost of a small
  re-identification risk if cross-referenced with another leaked source that
  has the same last 4.
- **Address → `[MASKED ADDRESS]`**: full replacement, zero utility retained.
  Chosen because even a partial address (city/state) can narrow down a
  person significantly when combined with the other fields — the privacy
  cost of any partial reveal outweighed the analytical benefit.
- **DOB → `1985-**-**`**: keeps birth year, enough for age-bucket analytics
  (e.g. "30-40 age group"), but not enough to do date-of-birth identity
  verification.
- **Income was deliberately left unmasked.** This is a real scope gap
  against Part 2's own PII categorization (which flagged income as
  "financial" risk) — the brief's Part 5 examples only cover
  name/email/phone/address/DOB, and this implementation followed that
  literally rather than masking income too. In a real production system this
  inconsistency should be resolved explicitly (either mask/bucket income, or
  formally document it as an accepted exception), not left implicit.

## 4. Validation Strategy: Effectiveness

The Pandera-based validator (Part 3) caught real, distinct issues in every
rule category defined in the brief, and lazy validation (`schema.validate(df,
lazy=True)`) meant every failure was reported in one pass rather than
stopping at the first error — essential for a report that has to say *how
much* is wrong, not just *whether* something is wrong. Re-running the exact
same validator after cleaning (Part 4) turned this into a real feedback
loop: total failing rows dropped from 110/500 (22.0%) to 88/495 (17.78%),
and the report shows precisely *which* rule categories cleaning could and
couldn't fix — reformatting issues resolved completely, fabrication-requiring
issues (missing required fields, genuinely invalid data, duplicate IDs)
correctly remained. The main limitation: treating every "required" field as
equally mandatory is a blunt instrument — in a real system, some of these
fields (e.g. `address`) might legitimately be optional for a subset of
customers, and the validator has no way to express that nuance today.

## 5. Production Operations: Scheduling and Failure Handling

The Airflow DAG runs `@daily`, a reasonable default for a nightly batch
ingestion of new customer records — easily changed if the real cadence
differs. Failure handling has two layers: inside `src/pipeline.py`, each of
the 6 stages is individually timed and wrapped in error handling, so a
failure at any stage still produces a `pipeline_execution_report.txt`
showing exactly which stage failed and everything that succeeded before it
— that's true even when Airflow itself isn't involved. On top of that,
Airflow retries the whole pipeline task 3 times, 5 minutes apart, before
emailing an admin — safe because the pipeline is idempotent (it only reads
the raw CSV and overwrites its own outputs, never appends or mutates state
elsewhere).

## 6. Lessons Learned

- **Letting pandas infer types (rather than forcing `dtype=str` everywhere)
  was itself a data-quality finding**: `customer_id` silently became
  `float64` because of missing values, which is exactly the kind of subtle
  type mismatch the brief's Part 1 asks to catch — forcing string types
  upfront would have hidden it.
- **Synthetic test data needs deliberate coverage guarantees, not just
  randomness.** An early version of the generator relied purely on
  probability to produce edge cases; at low row counts, rare fault types
  (like a literal `"invalid_date"`) sometimes didn't appear at all. Reserving
  the first N rows for one guaranteed instance of each fault category made
  every validation rule testable regardless of dataset size.
- **"Fixed" and "flagged" are different outcomes, and conflating them is
  worse than reporting both.** Filling a missing `account_status` with
  `"unknown"` looks superficially like a fix (no more blank cell) but is
  still an invalid status — keeping it failing post-cleaning, rather than
  quietly picking a default like `"active"`, was the more honest choice even
  though it makes the "issues fixed" number look smaller.
- **Cleaning has a real, discoverable boundary.** Reformatting fixes format
  problems; it cannot resolve duplicate identities, fabricate a genuinely
  missing required value, or guess a corrupted date. Re-running the
  validator after cleaning made that boundary visible instead of assumed.
