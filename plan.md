# ComicInfo Generator — Remediation & Hardening Plan

## 1. Objective

Bring `jakej985-rgb/comicinfo-generator` from its current functional state to a safe, deterministic, library-scale metadata pipeline that can run unattended against a Kapowarr-managed comic library.

Target pipeline:

```text
Comic archive
    ↓
Parse local identity
    ↓
Check existing ComicInfo.xml
    ↓
Resolve comic identity
    ↓
Kapowarr metadata
    ↓
Comic Vine metadata
    ↓
GCD fallback
    ↓
Confidence validation
    ↓
Build normalized Comic model
    ↓
Generate ComicInfo.xml
    ↓
Safely update CBZ
    ↓
Record processing state
```

Core principles:

- Never guess silently.
- Never destroy good metadata.
- Never modify the library in a way that cannot be recovered safely.
- Prefer Kapowarr's known identity when available.
- Use Comic Vine/GCD to enrich or resolve missing information.
- Make unattended processing idempotent and restart-safe.

---

# 2. Phase 0 — Establish the Current Baseline

## 2.1 Record the current architecture

Keep the existing high-level separation:

```text
app.py
cli.py
main.py
config.py

models/
    comic.py

providers/
    base.py
    kapowarr.py
    comicvine.py
    gcp.py
    story_arc.py

pipeline/
    resolver.py

cache/
    db.py
    tracker.py

writers/
    archive.py
    comicinfo.py

automation/
    queue.py
    watcher.py

converters/
    cbr_to_cbz.py

static/
    index.html
    app.js
    style.css
```

Do not rewrite the project from scratch.

## 2.2 Establish a test baseline

Run:

```bash
pytest -q
```

Record:

- Tests passed
- Tests failed
- Tests skipped
- Warnings
- Known failures

## 2.3 Add architecture documentation

Create:

```text
docs/
├── architecture.md
├── metadata-resolution.md
├── provider-contract.md
├── archive-safety.md
├── automation.md
└── testing.md
```

These documents become the design reference for future changes and AI coding agents.

---

# 3. Phase 1 — Make Archive Modification Safe

**Priority: CRITICAL**

## Problem

`writers/archive.py` currently contains automatic folder-permission takeover behavior that can rename an entire volume directory, recreate it, and copy files back.

That is too destructive for an unattended metadata application.

## Required behavior

The application must never automatically restructure a comic directory.

### Remove or disable automatic takeover

Remove automatic invocation of:

```python
_try_takeover_folder_permissions()
```

If retained for diagnostics, it must be explicitly invoked by a manual/admin operation and never by normal processing.

## 3.1 Create explicit archive exceptions

Add:

```text
ArchiveError
ArchiveReadError
ArchiveWriteError
ArchiveValidationError
```

Errors should contain:

- Archive path
- Operation
- Original exception
- Recommended action

Example:

```text
Unable to update Batman #1.cbz.

The archive is readable, but the application does not have permission
to replace the file.

Check ownership/permissions for the Kapowarr comic directory.
```

## 3.2 Use safe atomic replacement

Preferred algorithm:

```text
Read original
    ↓
Write temporary CBZ
    ↓
Verify temporary CBZ
    ↓
Flush/sync temporary file
    ↓
Atomic replace
```

Use `os.replace()` where supported.

## 3.3 Preserve file metadata where practical

Preserve:

- File permissions
- Modification time
- Other relevant filesystem metadata

## 3.4 Verify the finished archive

Before declaring success:

- Confirm archive is a valid ZIP.
- Run ZIP integrity testing.
- Confirm `ComicInfo.xml` exists.
- Confirm `ComicInfo.xml` parses.
- Confirm original comic files still exist.
- Confirm archive can be reopened.

If verification fails, do not replace the original.

---

# 4. Phase 2 — Separate Identity From Metadata

**Priority: CRITICAL**

## Problem

The current `Comic` model represents both:

1. What comic the file is.
2. Metadata describing that comic.

The resolver also relies heavily on filename searching.

This can produce false matches.

## 4.1 Create `ComicIdentity`

Create:

```text
models/identity.py
```

with a model conceptually like:

```python
ComicIdentity
```

Suggested fields:

```text
provider
provider_id

series_provider
series_id

issue_provider
issue_id

series_name
publisher
publication_year

volume
issue_number

confidence
confidence_reasons
```

Example:

```text
ComicIdentity
├── provider: ComicVine
├── series_id: 4050-12345
├── issue_id: 4000-98765
├── series_name: Batman
├── publisher: DC Comics
├── year: 2016
├── number: 1
├── confidence: 0.98
└── reasons:
    ├── exact CV volume
    ├── exact issue number
    └── publisher/year match
```

## 4.2 Separate identity resolution from metadata retrieval

The architecture should become:

```text
"What comic is this?"
        ↓
ComicIdentity
        ↓
"What metadata do we know about it?"
        ↓
Comic
```

This distinction is fundamental.

---

# 5. Phase 3 — Build a Real Identity Resolver

Create:

```text
pipeline/
├── resolver.py
├── identity.py
├── filename_parser.py
└── scoring.py
```

## 5.1 Filename parser

Extract candidates for:

- Series
- Volume
- Issue number
- Year
- Publisher
- Edition markers

Examples:

```text
Batman (2016) #001.cbz

Batman/
└── Batman 001.cbz

Batman (2016)/
└── Batman 001 - I Am Gotham.cbz
```

## 5.2 Filename matching is evidence, not identity

Filename similarity must never independently force a metadata match.

---

# 6. Phase 4 — Provider Identity Hierarchy

Use the following priority:

### Tier 1 — Existing embedded identity

If `ComicInfo.xml` contains a recognized provider ID, use it.

### Tier 2 — Kapowarr identity

Kapowarr is the library manager, so its known volume/issue relationship should have high priority.

### Tier 3 — Explicit Comic Vine URL

An explicitly supplied URL should be treated as authoritative unless it is invalid.

### Tier 4 — Comic Vine matching

Use multiple signals.

### Tier 5 — GCD

Use GCD as fallback.

### Tier 6 — No match

Return:

```text
UNRESOLVED
```

Do not invent a match.

---

# 7. Phase 5 — Add Confidence Scoring

Create:

```text
pipeline/scoring.py
```

Every candidate gets a score.

Suggested starting weights:

| Evidence | Score |
|---|---:|
| Exact provider issue ID | +100 |
| Exact provider volume ID | +90 |
| Exact issue number | +30 |
| Exact normalized series | +25 |
| Publisher match | +15 |
| Year match | +15 |
| Filename similarity | +10 |
| Alternate-cover evidence | +5 |
| Conflicting series | -50 |
| Conflicting publisher | -25 |
| Different volume | -50 |

Suggested thresholds:

```text
90–100  AUTO_ACCEPT
75–89   ACCEPT_WITH_WARNING
50–74   MANUAL_REVIEW
0–49    UNRESOLVED
```

These values should be configurable and tuned using real library data.

## Critical rule

Low-confidence matches must never silently overwrite an archive.

---

# 8. Phase 6 — Refactor Comic Vine Scraping

The current Comic Vine provider relies heavily on HTML structure, CSS classes, flattened page text, and regular expressions.

Break parsing into independent functions:

```python
parse_series()
parse_issue_number()
parse_title()
parse_publisher()
parse_release_date()
parse_summary()
parse_creators()
parse_characters()
parse_teams()
parse_story_arcs()
```

## 8.1 Separate scraping from parsing

Use:

```text
HTTP client
    ↓
raw HTML
    ↓
Comic Vine parser
    ↓
normalized provider object
```

This allows parser tests to use saved HTML without making live requests.

## 8.2 Build Comic Vine fixtures

Create:

```text
tests/fixtures/comicvine/
```

Include:

```text
batman_2016_001.html
batman_1940_001.html
marvel_zombies_001.html
dead_days_001.html
annual.html
alternate_cover.html
decimal_issue.html
cloudflare.html
```

Add tests for each fixture.

---

# 9. Phase 7 — Replace Loose Slug Matching

Do not use:

```text
issue slug starts with series slug
```

as primary identity logic.

Prefer:

1. Comic Vine volume ID
2. Kapowarr volume ID
3. Exact normalized series
4. Publisher
5. Publication year
6. Issue number
7. URL relationship
8. Filename similarity

Slug matching becomes secondary evidence only.

Explicitly distinguish similar series such as:

```text
Marvel Zombies
Marvel Zombies: Dead Days
Marvel Zombies: Return
Marvel Zombies Origins
Marvel Zombies Halloween
```

---

# 10. Phase 8 — Refactor Kapowarr Provider

## Problem

The current provider repeatedly retrieves the complete volume list and then requests individual volume details while searching.

This can result in a large number of unnecessary API calls.

## 10.1 Create a Kapowarr client

Recommended structure:

```text
providers/kapowarr/
├── client.py
├── models.py
└── provider.py
```

### Client responsibilities

- HTTP requests
- Authentication
- Timeouts
- Retries
- HTTP error handling
- API response validation

### Provider responsibilities

- Convert Kapowarr data to `ComicIdentity`
- Convert Kapowarr data to `Comic`
- Perform provider-specific matching

---

# 11. Phase 9 — Build a Kapowarr Snapshot

Create an in-memory snapshot:

```text
KapowarrSnapshot
├── volumes_by_id
├── volumes_by_cv_id
├── issues_by_id
├── issues_by_cv_id
└── issues_by_volume
```

Load once:

```text
Kapowarr API
    ↓
Snapshot
    ↓
All lookups
```

Refresh when necessary instead of repeatedly walking every volume.

This is especially important for large libraries.

---

# 12. Phase 10 — Improve Error Handling

Remove broad patterns such as:

```python
except Exception:
    pass
```

from normal provider and processing paths.

Create explicit exceptions:

```text
ProviderError
ProviderConnectionError
ProviderAuthenticationError
ProviderRateLimitError
ProviderParseError
MetadataNotFoundError
ArchiveReadError
ArchiveWriteError
ArchiveValidationError
```

Provider operations should expose meaningful states:

```text
SUCCESS
NOT_FOUND
CONNECTION_ERROR
AUTH_ERROR
RATE_LIMITED
PARSE_ERROR
```

The UI and logs must distinguish:

```text
"Kapowarr found nothing"
```

from:

```text
"Kapowarr was unavailable"
```

---

# 13. Phase 11 — Make ComicInfo Read/Write Lossless

The `Comic` model supports fields such as:

```text
cover_artists
teams
story_arcs
story_arc_numbers
```

The XML reader/writer must support every field represented by the model.

## Required property

This operation:

```text
ComicInfo.xml
    ↓
Comic
    ↓
ComicInfo.xml
```

must not unintentionally destroy metadata.

Create clear components:

```text
ComicInfoParser
ComicInfoWriter
```

## 13.1 Add round-trip tests

Test:

```text
XML → Comic → XML
```

by comparing normalized XML trees.

---

# 14. Phase 12 — Preserve Unknown ComicInfo Fields

ComicInfo has fields beyond those currently represented by the application.

Do not silently discard fields the application does not understand.

Possible approaches:

```python
Comic.extra_fields
```

or preservation of unknown XML nodes.

Rule:

> The generator owns fields it understands and preserves fields it does not understand.

---

# 15. Phase 13 — Harden TPB/Collected-Edition Merging

The merge function currently assumes all supplied issues belong together.

Before merging, validate:

- Same series
- Same provider volume
- Same publisher where appropriate
- Compatible numbering
- No conflicting identities

Reject:

```text
Batman #1
Batman #2
Detective Comics #1
```

Warn on:

```text
Batman #1
Batman #1A
```

Accept:

```text
Batman #1
Batman #2
Batman #3
```

## 15.1 Support complex numbering

Do not rely exclusively on integer sorting.

Support:

```text
1
1A
1B
1.5
Annual
Special
```

## 15.2 Preserve intended issue order

Use explicit sort logic rather than converting everything to integers.

---

# 16. Phase 14 — Improve Merged Summaries

Keep issue-level summaries but structure them:

```text
Issue #1
summary

Issue #2
summary

Issue #3
summary
```

Avoid redundant metadata when information is already represented elsewhere.

---

# 17. Phase 15 — Expand Cache Architecture

The existing cache system should become central to the application.

Cache:

```text
URL → raw HTML
Comic Vine issue ID → metadata
Comic Vine volume ID → metadata
Kapowarr volume → metadata
Kapowarr issue → metadata
GCD issue → metadata
filename fingerprint → identity
archive SHA256 → processing state
```

Each cache record should include:

```text
provider
provider_id
fetched_at
expires_at
source_hash
schema_version
```

---

# 18. Phase 16 — Add Durable Archive Processing State

Create a processing-state table.

Suggested fields:

```text
path
sha256
size
mtime
status
provider
provider_id
confidence
processed_at
error
generator_version
```

States:

```text
PENDING
PROCESSING
SUCCESS
SKIPPED
UNRESOLVED
FAILED
```

This allows the application to know exactly what happened to every file.

---

# 19. Phase 17 — Harden Automation Watcher

The watcher/queue should use durable processing state.

Desired workflow:

```text
New/changed file
    ↓
Queue
    ↓
Deduplicate
    ↓
Process
    ↓
Verify
    ↓
Record hash/state
```

If the same SHA256 is seen again:

```text
SKIP
```

If the SHA256 changes:

```text
PROCESS AGAIN
```

This prevents the application from repeatedly processing its own output.

---

# 20. Phase 18 — Make Automation Restart-Safe

The application must survive:

- Docker restart
- Machine reboot
- Network outage
- Provider outage
- Power loss

without losing queue state or corrupting archives.

Queue records must be persistent.

Jobs stuck in `PROCESSING` should be recoverable after restart.

---

# 21. Phase 19 — Add Dry-Run Mode

Add:

```bash
python main.py --dry-run ...
```

Dry run should show:

```text
Archive
Identity candidate
Provider
Confidence
Metadata changes
Action
```

Example:

```text
Batman #1.cbz

Match:
  Comic Vine: Batman (2016) #1
  Confidence: 97%

Would change:
  Title
  Publisher
  Date
  Writer
  Penciller
  Characters

Action:
  UPDATE
```

Dry-run mode must make no filesystem modifications.

---

# 22. Phase 20 — Add Manual Review Workflow

For scores below the automatic threshold:

```text
Batman #1.cbz

Candidate A — 88%
Candidate B — 71%
Candidate C — 42%
```

Allow:

```text
Accept A
Accept B
Skip
Enter Comic Vine URL
```

Persist the selected identity so the application does not repeatedly ask about the same file.

---

# 23. Phase 21 — Make Provider Precedence Configurable

Do not permanently hard-code provider order.

Example:

```yaml
providers:
  identity:
    - kapowarr
    - comicvine
    - gcd

  metadata:
    - kapowarr
    - comicvine
    - gcd

matching:
  auto_accept: 90
  review_threshold: 70
```

This lets the behavior evolve without rewriting the resolver.

---

# 24. Phase 22 — Add Structured Logging

Create:

```text
logs/
├── application.log
├── resolver.log
├── provider.log
├── archive.log
└── automation.log
```

Every processing job should receive a correlation ID:

```text
JOB-20260813-000142
```

Example:

```text
JOB-20260813-000142
├── archive discovered
├── identity parsed
├── Kapowarr matched
├── Comic Vine skipped
├── ComicInfo generated
├── archive verified
└── SUCCESS
```

---

# 25. Phase 23 — Build a Complete Test Suite

Target:

```text
tests/
├── fixtures/
│   ├── comicvine/
│   ├── gcd/
│   └── comicinfo/
│
├── test_identity.py
├── test_filename_parser.py
├── test_matching.py
├── test_scoring.py
├── test_comicvine.py
├── test_kapowarr.py
├── test_gcd.py
├── test_comic_model.py
├── test_comicinfo.py
├── test_archive_writer.py
├── test_merge.py
├── test_cache.py
├── test_pipeline.py
└── test_automation.py
```

---

# 26. Phase 24 — Build Regression Cases From the Real Library

Use difficult real-world cases as permanent fixtures.

Include:

- Alternate covers
- Different volume years
- Relaunches
- TPBs
- Omnibus editions
- Annuals
- Specials
- Decimal issues
- Lettered issues
- Marvel Zombies
- Batman
- TMNT
- Archie
- Mirage
- Collections
- Crossovers
- Story arcs

Every discovered bad match should result in:

```text
Real-world failure
    ↓
Fixture
    ↓
Regression test
    ↓
Resolver fix
```

This continuously improves matching accuracy.

---

# 27. Phase 25 — Security and Operational Hardening

Review:

- API key handling
- Filesystem traversal
- Untrusted archive contents
- ZIP bombs
- Oversized XML
- Symlinks
- Path traversal inside archives
- HTTP timeouts
- Retry limits
- Provider rate limits

Never allow archive extraction or temporary processing to escape its intended directory.

Reject archive paths containing traversal such as:

```text
../../somewhere
```

---

# 28. Phase 26 — Centralize Configuration

Move defaults into configuration.

Example:

```yaml
storage:
  watch_folder: /mnt/disk1/Comics

kapowarr:
  url: http://kapowarr:5656

comicvine:
  enabled: true

gcd:
  enabled: true

processing:
  overwrite_existing: false
  minimum_confidence: 90
  dry_run: false

automation:
  enabled: true
```

Avoid scattering provider URLs, paths, thresholds, and processing flags throughout the codebase.

---

# 29. Phase 27 — Update UI Around the Actual Pipeline

For every archive, show:

```text
Identity
Metadata
Confidence
Provider
Changes
Processing status
```

Example:

```text
Batman #001.cbz

Identity
Batman (2016) #1

Source
Kapowarr

Confidence
98%

ComicInfo
✓ Existing file
✓ Valid XML

Changes
Publisher: DC Comics
Year: 2016
Writer: Tom King

Action
No changes required
```

---

# 30. Phase 28 — Add Provider Debugging

For difficult matches, expose:

```text
Filename
Directory
Parsed series
Parsed issue
Kapowarr candidates
Comic Vine candidates
GCD candidates
Scores
Rejected candidates
Final decision
```

This will make real-world matching problems much easier to diagnose.

---

# 31. Phase 29 — Version the Metadata Schema

Record:

```text
generator_version
metadata_schema_version
```

in processing state.

This allows future versions of the application to identify archives processed by older versions.

---

# 32. Phase 30 — Release Process

Before enabling unattended processing:

## Stage 1 — Dry run

Run against the entire library.

## Stage 2 — Generate report

Report:

```text
Total
Already tagged
Would update
Skipped
Unresolved
Low confidence
Failed
```

## Stage 3 — Test directory

Run against a small isolated comic directory.

## Stage 4 — One real series

Run against one known-good series.

## Stage 5 — Enable watcher

Enable automatic processing.

## Stage 6 — Enable unattended mode

Only after archive safety, identity resolution, and regression tests are passing.

---

# 33. Recommended Implementation Order

Do not implement everything simultaneously.

Use this order:

```text
1. Archive safety
2. ComicInfo lossless read/write
3. ComicIdentity model
4. Filename parser
5. Confidence scoring
6. Resolver refactor
7. Kapowarr snapshot/cache
8. Comic Vine parser refactor
9. GCD integration cleanup
10. Merge validation
11. Processing-state database
12. Automation hardening
13. Error handling
14. Comprehensive tests
15. Dry-run mode
16. Manual review
17. UI updates
18. Documentation
19. Full-library validation
```

---

# 34. Definition of Done

The project is not production-ready until all of these are true:

- [ ] Existing ComicInfo is never silently destroyed.
- [ ] Archive replacement is atomic/safe.
- [ ] No automatic directory renaming/copy takeover occurs.
- [ ] Identity is separate from metadata.
- [ ] Provider IDs are preserved.
- [ ] Filename matching cannot directly force a match.
- [ ] Confidence scoring exists.
- [ ] Low-confidence matches require review.
- [ ] Kapowarr data is cached.
- [ ] Comic Vine requests are cached.
- [ ] Provider errors are visible.
- [ ] ComicInfo round-trip is lossless.
- [ ] TPB merging validates inputs.
- [ ] Processing state survives restart.
- [ ] Watcher is idempotent.
- [ ] Dry-run mode works.
- [ ] Real-library regression tests exist.
- [ ] Archive corruption is detected.
- [ ] ZIP path traversal is handled safely.
- [ ] Full-library dry run completes without modifying files.

---

# 35. Target Architecture

```text
                         ┌─────────────────┐
                         │   File Watcher   │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ Processing Queue │
                         └────────┬────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │ Archive Inspector   │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │ Filename / Folder   │
                       │ Identity Parser     │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │ Identity Resolver   │
                       └──────────┬──────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
        ┌───────────┐       ┌───────────┐       ┌──────────┐
        │ Kapowarr  │       │ Comic Vine│       │   GCD    │
        └─────┬─────┘       └─────┬─────┘       └────┬─────┘
              └───────────────────┼───────────────────┘
                                  ▼
                         ┌─────────────────┐
                         │ Confidence      │
                         │ Scoring         │
                         └────────┬────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
                    ▼                            ▼
              AUTO ACCEPT                  MANUAL REVIEW
                    │
                    ▼
             ┌──────────────┐
             │ Comic Model  │
             └──────┬───────┘
                    │
                    ▼
             ┌──────────────┐
             │ ComicInfo    │
             │ Generator    │
             └──────┬───────┘
                    │
                    ▼
             ┌──────────────┐
             │ Safe Archive │
             │ Replacement  │
             └──────┬───────┘
                    │
                    ▼
             ┌──────────────┐
             │ Verify +     │
             │ SHA256       │
             └──────┬───────┘
                    │
                    ▼
             ┌──────────────┐
             │ Processing DB│
             └──────────────┘
```

---

# 36. End Goal

The finished application should function as a reliable metadata normalization layer for the Kapowarr library:

```text
Kapowarr downloads comic
        ↓
Watcher detects CBZ
        ↓
Existing ComicInfo checked
        ↓
Kapowarr identity used when available
        ↓
Comic Vine enriches metadata when needed
        ↓
GCD provides fallback data
        ↓
Identity confidence calculated
        ↓
High-confidence result automatically accepted
        ↓
Low-confidence result sent to review
        ↓
ComicInfo.xml generated
        ↓
CBZ safely replaced
        ↓
Archive integrity verified
        ↓
Processing state recorded
        ↓
Komga/Kavita/Jellyfin can consume the updated metadata
```

The guiding rule throughout the implementation is:

> **Kapowarr data first → external metadata when needed → verify identity → preserve existing information → make safe changes only → record exactly what happened.**
