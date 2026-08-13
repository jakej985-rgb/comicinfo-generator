# Metadata Resolution — ComicInfo Generator

## Purpose

Describes the **actual, implemented** two-phase metadata resolution and validation pipeline.

---

## Responsibilities

`pipeline/resolver.py → MetadataResolver`

1. **Stage 1 — Identity Resolution** (`resolve_identity`): determines *what* the comic is and produces a `ComicIdentity` with `CanonicalIdentityKey`.
2. **Stage 2 — Metadata Retrieval & Validation** (`retrieve_metadata_result`): fetches full details for a resolved identity and returns a structured `MetadataRetrievalResult` (`SUCCESS`, `NOT_FOUND`, `INVALID`, `PROVIDER_ERROR`).
3. **Pipeline Orchestration** (`resolve_file_pipeline`): executes the full end-to-end flow returning a structured `ResolutionResult` capturing provider operation outcomes, identity decisions, conflict lists, and candidate objects.

These phases are strictly separated. No metadata retrieval occurs before identity is confirmed, and no archive write occurs without successful metadata validation.

---

## Identity Resolution Flow & Canonical Key

```text
1. Direct URL override (CV/GCD URL)
   ↓
2. Existing embedded ComicInfo.xml inspection (pipeline/existing_metadata.py)
   ↓
3. Filename / directory signal extraction (pipeline/filename_parser.py)
   ↓
4. Provider candidate queries:
   - Kapowarr search (if online)
   - Comic Vine search
   - GCD search
   ↓
5. Canonical Identity Normalization (models/identity.py → CanonicalIdentityKey):
   - Normalized series name (alphanumeric, lowercase, trimmed)
   - Float numeric issue value + uppercase variant suffix
   - Normalized volume & publication year
   ↓
6. Formal Conflict Detection (pipeline/conflicts.py):
   - XML vs Filename / Provider discrepancies
   - Multi-provider disagreement across series/number/volume/year
   - Variant letter & volume/era conflicts
   ↓
7. Central Candidate Decision Policy (pipeline/confidence.py):
   - Scores all candidate identities
   - Checks multi-field provider agreement (+15.0 bonus)
   - Evaluates score-margin protection (margin <= 10.0 -> MANUAL_REVIEW)
   - Returns (resolved_identity, ConfidenceDecision)
```

---

## Confidence Decision Levels

| Level | Score | Condition | Action |
|---|---|---|---|
| `AUTO_ACCEPT` | ≥ 90 | Clear winner, margin > 10.0, zero critical conflicts | Embed immediately (`UPDATE`) |
| `ACCEPT_WITH_WARNING` | 70–89 | Adequate score, non-critical warning | Embed with warning logged |
| `MANUAL_REVIEW` | 50–69 | Ambiguous candidates (margin <= 10.0) or conflict detected | Add to review queue (`REVIEW`) |
| `UNRESOLVED` | < 50 | Low score or zero provider candidates | Skip, record state (`SKIP`) |

---

## Issue Number Normalization

`pipeline/issue_order.py` normalizes all issue numbers to `IssueOrder(numeric_value, letter_suffix)`.

- **Never** uses `int(issue_number)`.
- Handles fractional numbers (`0.5`, `½`), lettered variants (`1A`, `1B`), decimals (`10.1`), and named publications (`Annual`, `Special`).
- Guaranteed correct ordering without type errors or integer truncation.

---

## Invariants

1. **Strict Phase Separation**: Identity resolution happens before any archive write or metadata fetch.
2. **Signal Verification**: Filename signals alone without external corroboration or valid existing XML are never auto-accepted.
3. **Score Margin Protection**: Multiple plausible candidates with score margin <= 10.0 always trigger `MANUAL_REVIEW`.
4. **Provider Exception Survival**: Provider operational states (`NOT_FOUND`, `SERVER_ERROR`, `RATE_LIMITED`, `AUTH_FAILED`, `TIMEOUT`, `OFFLINE`) are tracked per provider and survive to the final job record.
5. **No Direct Path**: There is strictly NO path from Identity Resolved directly to Archive Write without successful, validated Metadata Retrieval.
