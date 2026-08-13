# Metadata Resolution — ComicInfo Generator

## Purpose

Describes the **actual, implemented** two-phase metadata resolution pipeline.

---

## Responsibilities

`pipeline/resolver.py → MetadataResolver`

1. **Phase 1 — Identity Resolution** (`resolve_identity`): determines *what* the comic is.
2. **Phase 2 — Metadata Retrieval** (`retrieve_metadata`): fetches full details for a resolved identity.

These two phases are strictly separated. No metadata retrieval occurs before identity is confirmed.

---

## Identity Resolution Priority & Candidate Pool

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
5. Central Candidate Decision Policy (pipeline/confidence.py):
   - Scores all candidate identities
   - Checks provider agreement (+15.0 bonus)
   - Detects provider and XML conflicts
   - Evaluates score-margin protection (margin <= 10.0 -> MANUAL_REVIEW)
   - Returns (resolved_identity, ConfidenceDecision)
```

---

## Confidence Decision Levels

| Level | Score | Condition | Action |
|---|---|---|---|
| `AUTO_ACCEPT` | ≥ 90 | Clear winner, margin > 10.0, no critical conflicts | Embed immediately (`UPDATE`) |
| `ACCEPT_WITH_WARNING` | 70–89 | Adequate score, non-critical warning | Embed with warning logged |
| `MANUAL_REVIEW` | 50–69 | Ambiguous candidates (margin <= 10.0) or conflict detected | Add to review queue (`REVIEW`) |
| `UNRESOLVED` | < 50 | Low score or zero provider candidates | Skip, record state (`SKIP`) |

---

## Issue Number Normalization

`pipeline/issue_order.py` normalizes all issue numbers to `IssueOrder(numeric_value, letter_suffix)`.

- **Never** uses `int(issue_number)`.
- Handles fractional numbers (`0.5`, `½`), lettered variants (`1A`, `1B`), and named publications (`Annual`, `Special`).
- Guaranteed correct ordering without type errors or int truncation.

---

## Invariants

1. Identity resolution happens before any archive write or metadata fetch.
2. Filename signals alone without external corroboration or valid existing XML are never auto-accepted.
3. Multiple plausible candidates with score margin <= 10.0 always trigger `MANUAL_REVIEW`.
4. Provider results are never embedded without passing through `MetadataResolver`.
