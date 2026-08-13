ComicInfo Generator — Remaining Remediation & Hardening Plan

1. Purpose

This document defines the remaining work required to take "comicinfo-generator" from its current partially hardened state to a reliable, deterministic, unattended metadata processor for a Kapowarr-managed comic library.

Repository:

"jakej985-rgb/comicinfo-generator"

The goal is not to rewrite the application from scratch.

The goal is to:

- preserve the existing working functionality
- make comic identity resolution deterministic
- prevent incorrect metadata from silently replacing correct metadata
- make CBZ modification transactionally safe
- make automation persistent and restart-safe
- preserve existing ComicInfo metadata
- make provider failures distinguishable from "no match"
- make the codebase understandable to future AI coding agents
- provide enough tests that an AI agent cannot accidentally regress the critical behavior

---

1. Target Architecture

The final processing pipeline should be:

CBZ/CBR
   │
   ▼
Archive Inspection
   │
   ├── Existing ComicInfo.xml
   ├── Filename
   ├── Folder structure
   └── Archive fingerprint
   │
   ▼
Local Identity Extraction
   │
   ▼
Kapowarr Identity
   │
   ▼
Provider Candidate Generation
   │
   ├── Comic Vine
   ├── GCD
   └── Other providers later
   │
   ▼
Candidate Normalization
   │
   ▼
Evidence / Confidence Scoring
   │
   ▼
Conflict Detection
   │
   ├── AUTO_ACCEPT
   ├── REVIEW
   └── UNRESOLVED
   │
   ▼
Metadata Resolution
   │
   ▼
Comic Model
   │
   ▼
ComicInfo.xml Generation
   │
   ▼
Safe CBZ Transaction
   │
   ▼
Archive Verification
   │
   ▼
Durable Processing State

The most important architectural rule is:

«Providers produce candidates. The resolver decides which candidate, if any, is correct.»

No provider should be allowed to implicitly decide that its first search result is the correct comic.

---

1. Phase 0 — Freeze and Establish the Baseline

Goal

Create a known-good baseline before further architectural changes.

Tasks

3.1 Run the complete test suite

Run:

pytest -q

Record:

- passed
- failed
- skipped
- warnings
- missing fixtures
- environment-dependent failures

3.2 Record the current repository structure

Document the current architecture before changing it.

3.3 Establish Python compatibility

Document:

- supported Python versions
- operating systems
- Docker requirements
- external tools
- CBR conversion requirements
- Kapowarr requirements

3.4 Create a regression fixture library

Create test archives representing real-world cases:

tests/fixtures/archives/
├── simple_issue.cbz
├── existing_comicinfo.cbz
├── malformed_comicinfo.cbz
├── duplicate_comicinfo.cbz
├── alternate_cover.cbz
├── annual.cbz
├── decimal_issue.cbz
├── collected_edition.cbz
├── multi_issue_tpb.cbz
├── empty_archive.cbz
└── corrupt_archive.cbz

Do not use only artificial unit tests.

The application operates on real comic archives, so representative archive fixtures are required.

---

1. Phase 1 — Finish the Domain Model Separation

Priority

P0

Problem

"Comic" currently contains both metadata and identity/processing information.

The final system should separate those concepts.

4.1 Create "ComicIdentity"

Create:

models/identity.py

The model should represent:

ComicIdentity
├── provider
├── provider_id
├── series_provider
├── series_id
├── issue_provider
├── issue_id
├── series_name
├── publisher
├── publication_year
├── volume
├── issue_number
├── identity_type
├── confidence
├── confidence_level
└── evidence

4.2 Create identity evidence

Create a structure representing why a candidate matched.

Example:

IdentityEvidence
├── source
├── field
├── expected
├── actual
├── score
└── explanation

Example:

Comic Vine
issue_number
expected: 1
actual: 1
score: +30
reason: exact issue number

4.3 Create "ArchiveRecord"

Create:

models/archive.py

Represent:

ArchiveRecord
├── path
├── filename
├── extension
├── sha256
├── size
├── mtime
├── archive_type
└── comicinfo_present

4.4 Create processing state separately

Create:

models/processing.py

Represent:

ProcessingRecord
├── job_id
├── archive_path
├── archive_sha256
├── status
├── provider
├── provider_id
├── confidence
├── started_at
├── completed_at
├── attempts
├── error_code
├── error_message
└── generator_version

---

1. Phase 2 — Build the Identity Extraction Layer

Priority

P0

Create:

pipeline/
├── identity.py
├── filename_parser.py
└── archive_identity.py

5.1 Parse existing ComicInfo.xml

If valid ComicInfo contains:

Web
Notes
provider identifiers

extract usable identity information.

Existing metadata should be evidence.

It should not automatically override a stronger known identity.

5.2 Parse filename

Support:

Batman (2016) #001.cbz
Batman 001.cbz
Batman #1.cbz
Batman 1 - I Am Gotham.cbz

Extract:

- series
- year
- issue
- volume
- edition
- annual/special indicators

5.3 Parse directory structure

Support common Kapowarr structures such as:

Batman (2016)/
    Batman (2016) 001.cbz

Use folder information as evidence.

Do not assume folder names are authoritative.

5.4 Normalize issue numbers

Create a dedicated issue-number representation.

Support:

1
001
1A
1B
1.5
Annual
Special
0
0.5

Do not convert all issue numbers to integers.

---

1. Phase 3 — Make Kapowarr the Library Identity Source

Priority

P0

This is especially important for the intended deployment.

6.1 Build a Kapowarr client

Refactor:

providers/kapowarr.py

into:

providers/kapowarr/
├── client.py
├── models.py
└── provider.py

"client.py"

Responsible only for:

- HTTP
- authentication
- timeout
- retries
- status codes
- response decoding

"models.py"

Contains normalized Kapowarr API structures.

"provider.py"

Converts Kapowarr information into application domain models.

---

1. Phase 6 — Implement Candidate Scoring

Priority

P0

Create:

pipeline/scoring.py

Initial scoring model:

Exact issue provider ID       +100
Exact volume provider ID       +90
Exact Kapowarr identity        +90
Exact issue number             +30
Exact normalized series        +25
Publisher match               +15
Year match                    +15
Volume match                  +15
Folder match                  +10
Filename similarity            +10
Existing metadata match        +10
Alternate-cover evidence       +5

Conflicting series             -50
Conflicting publisher          -25
Conflicting volume             -50
Conflicting issue              -60

These weights are starting values.

They must be configurable and tested against real comic examples.

---

 1. Phase 7 — Implement Confidence Decisions

Create:

pipeline/confidence.py

Use explicit states:

AUTO_ACCEPT
ACCEPT_WITH_WARNING
MANUAL_REVIEW
UNRESOLVED

Suggested starting thresholds:

90+       AUTO_ACCEPT

75–89     ACCEPT_WITH_WARNING

50–74     MANUAL_REVIEW

<50       UNRESOLVED

Important:

«A high score is not enough if there is a critical identity conflict.»

For example:

Series:
Batman

Publisher:
DC

Issue:
1

Year:
2016

BUT:

Kapowarr volume:
Batman (1940)

This should not automatically overwrite metadata simply because the filename looks similar.

---

 1. Phase 8 — Build Explicit Conflict Detection

Create:

pipeline/conflicts.py

Detect:

series conflict
publisher conflict
volume conflict
issue conflict
year conflict
provider ID conflict
existing ComicInfo conflict
Kapowarr conflict

Return structured results:

Conflict
├── type
├── severity
├── source_a
├── source_b
└── explanation

Severity:

INFO
WARNING
ERROR
FATAL

---

 1. Phase 9 — Separate Identity Resolution From Metadata Retrieval

The resolver should become:

resolve_identity()

followed by:

retrieve_metadata(identity)

Never mix these responsibilities.

Example:

ComicIdentity
    ↓
Comic Vine issue ID
    ↓
Comic Vine metadata

This prevents metadata retrieval from accidentally becoming identity resolution.

---

 1. Phase 10 — Comic Vine Provider Refactor

Priority

P1

Refactor the current scraper into:

providers/comicvine/
├── client.py
├── parser.py
├── models.py
└── provider.py

13.1 Client

Responsible for:

- HTTP
- retries
- timeout
- rate limiting
- response handling

13.2 Parser

Responsible for HTML parsing only.

Create functions:

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

13.3 Provider

Responsible for:

- search
- lookup
- candidate creation
- normalization

---

 1. Phase 11 — Build Comic Vine HTML Fixtures

Create:

tests/fixtures/comicvine/

Include real captured HTML for:

batman_2016_001.html
batman_1940_001.html
marvel_zombies_001.html
dead_days_001.html
annual.html
alternate_cover.html
decimal_issue.html
special.html
cloudflare.html
missing_page.html

Tests must run without contacting Comic Vine.

---

 1. Phase 12 — Improve GCD Provider

Refactor GCD/GCP similarly:

providers/gcd/
├── client.py
├── parser.py
├── models.py
└── provider.py

The provider should produce normalized candidates.

It should not directly modify the final "Comic".

---

 1. Phase 13 — Define the Provider Contract

Create:

providers/base.py

Define a strict interface.

Conceptually:

search()
lookup()
normalize()

Provider results should have explicit states:

SUCCESS
NOT_FOUND
CONNECTION_ERROR
AUTH_ERROR
RATE_LIMITED
PARSE_ERROR
INVALID_RESPONSE

Do not represent all of these as:

None

---

 1. Phase 14 — Eliminate Silent Provider Failures

Remove normal-path patterns like:

except Exception:
    pass

Replace them with specific exceptions.

Required exceptions:

ProviderError
ProviderConnectionError
ProviderAuthenticationError
ProviderRateLimitError
ProviderParseError
ProviderResponseError
MetadataNotFoundError

The application must distinguish:

No result

from:

Provider unavailable

from:

Provider parser broken

---

 1. Phase 15 — Finish ComicInfo Lossless Handling

Priority

P0

The application must guarantee:

ComicInfo.xml
    ↓
Comic
    ↓
ComicInfo.xml

does not unintentionally destroy information.

18.1 Preserve known fields

Ensure every field represented by "Comic" is parsed and written.

18.2 Preserve unknown fields

The current "extra_fields" dictionary is only a partial solution.

Eventually preserve:

- unknown tags
- attributes
- nested elements
- duplicate elements
- namespaces where applicable

Prefer an XML-node preservation structure rather than only:

Dict[str, str]

18.3 Add round-trip tests

Test:

XML → Comic → XML

Normalize XML before comparison.

---

 1. Phase 16 — Fix Archive Transaction Safety

Priority

P0

Keep the current temporary-file architecture.

Remove the unsafe cross-filesystem fallback:

shutil.move()

if it compromises atomicity.

Required behavior:

Create temporary archive in same directory
        ↓
Write archive
        ↓
Verify archive
        ↓
fsync temporary file
        ↓
os.replace()
        ↓
Verify final archive

If a same-filesystem atomic replacement cannot be performed:

FAIL

Do not downgrade to an unsafe replacement operation.

---

 1. Phase 17 — Preserve File Metadata

Where supported, preserve:

- permissions
- modification time
- ownership where appropriate
- filesystem attributes

Do not change ownership automatically.

This is particularly important for your Docker/Kapowarr/Jellyfin environment.

---

 1. Phase 18 — Verify Archive Contents Before Replacement

The existing verification should be expanded.

Before replacing the original:

Verify:

valid ZIP
ZIP test passes
ComicInfo.xml exists
ComicInfo.xml parses
image count is valid
original entries remain
no unexpected deletion

Ideally compare:

original archive entries
new archive entries

and ensure the only intentional modification is:

ComicInfo.xml

---

 1. Phase 19 — Make CBR Conversion Safe

Current CBR processing needs its own transaction.

Required workflow:

CBR
 ↓
Create CBZ
 ↓
Verify CBZ
 ↓
Embed ComicInfo
 ↓
Verify CBZ
 ↓
Record success
 ↓
Only then delete original CBR

Never delete the CBR merely because conversion started successfully.

---

 1. Phase 20 — Build Durable Processing State

Priority

P0

The current in-memory queue is insufficient for unattended operation.

Use SQLite as the durable job store.

Create:

cache/jobs.py

Database table:

processing_jobs

Fields:

id
path
sha256
size
mtime
status
attempts
provider
provider_id
confidence
created_at
started_at
completed_at
error_code
error_message
generator_version

Statuses:

PENDING
PROCESSING
SUCCESS
SKIPPED
REVIEW
UNRESOLVED
FAILED

---

 1. Phase 21 — Make Queue Restart-Safe

On startup:

PROCESSING jobs
      ↓
find stale jobs
      ↓
reset to PENDING

The system must survive:

Docker restart
machine reboot
power failure
application crash
network outage

without losing work.

---

 1. Phase 22 — Deduplicate Jobs

Prevent the same archive from being queued multiple times simultaneously.

Use:

path + SHA256

as the primary deduplication identity.

Example:

same path
same SHA256
     ↓
already queued
     ↓
do not queue again

If SHA256 changes:

new processing job

---

 1. Phase 23 — Make Automation Ignore Its Own Changes

This is critical.

After successfully modifying:

Batman #1.cbz

the watcher will observe the changed file.

The system must recognize:

known SHA256 / known processing state

and avoid immediately processing it again.

Required:

write
 ↓
new SHA256
 ↓
record SUCCESS
 ↓
watcher event
 ↓
recognized known result
 ↓
SKIP

---

 1. Phase 24 — Add Dry-Run Mode

Implement:

python main.py --dry-run

Dry run must never modify an archive.

Example output:

Archive:
  Batman (2016) 001.cbz

Identity:
  Batman (2016)
  Issue #1

Candidate:
  Comic Vine #4000-123456

Confidence:
  97%

Evidence:
  +90 exact volume
  +30 exact issue
  +25 exact series
  +15 publisher
  +15 year

Action:
  UPDATE

Changes:
  Title
  Publisher
  Writer
  Characters

---

 1. Phase 25 — Add Manual Review Output

For uncertain matches:

MANUAL_REVIEW

Generate a report containing:

Archive
Current metadata
Candidates
Scores
Evidence
Conflicts
Recommended candidate

Do not modify the archive.

---

 1. Phase 26 — Improve TPB / Collected Edition Merging

Create:

pipeline/collection.py
pipeline/issue_order.py

Before merging, validate:

same series
compatible publisher
same provider volume
compatible numbering
no conflicting identities

Reject:

Batman #1
Detective Comics #1

Warn:

Batman #1
Batman #1A

Accept:

Batman #1
Batman #2
Batman #3

---

 1. Phase 27 — Implement Complex Issue Ordering

Do not sort issues using:

int(number)

Create a normalized ordering system.

Support:

0
0.5
1
1A
1B
1.5
2
Annual
Special

Represent the ordering explicitly.

---

 1. Phase 28 — Improve Collected Edition Metadata

When merging issues:

Preserve:

- issue identities
- issue summaries
- creators
- characters
- story arcs
- source URLs
- provider IDs

Avoid blindly combining unrelated metadata.

---

 1. Phase 29 — Build a Real Metadata Merge Policy

Create:

pipeline/merge.py

Define field-level rules.

Example:

Title
  explicit collection metadata > provider > filename

Publisher
  Kapowarr identity > provider

Year
  collection publication year > issue year

Summary
  collection summary > generated issue summaries

Characters
  union + deduplicate

Creators
  union + deduplicate

Every field should have an explicit source priority.

Do not use one global provider priority for every field.

---

 1. Phase 30 — Expand Cache Architecture

Current caching should be expanded to include:

Comic Vine issue ID
Comic Vine volume ID
GCD issue ID
Kapowarr volume ID
Kapowarr issue ID
URL
filename fingerprint
archive SHA256

Every cached provider result should contain:

provider
provider_id
fetched_at
expires_at
schema_version
source_hash

---

 1. Phase 31 — Add Cache Invalidation

Cache must be invalidated when:

- provider schema changes
- parser version changes
- metadata is manually refreshed
- cached data is expired
- provider data changes

Never let stale metadata become permanent merely because it is cached.

---

 1. Phase 32 — Refactor "app.py"

Once the core domain and services are stable, split the large application module.

Target:

api/
├── server.py
├── handlers.py
└── serializers.py

services/
├── metadata.py
├── processing.py
└── search.py

"app.py" should not contain business logic.

Target architecture:

HTTP/UI
   ↓
API handlers
   ↓
Services
   ↓
Domain models
   ↓
Providers / repositories

---

 1. Phase 33 — Add Structured Logging

Replace ad-hoc logging with structured events.

Each processing job should include:

job_id
archive
sha256
provider
provider_id
confidence
status
duration

Example:

job=1234
archive=Batman_001.cbz
provider=ComicVine
issue=4000-123456
confidence=97
status=SUCCESS

---

 1. Phase 34 — Add Metrics

Track:

files processed
files skipped
files successfully resolved
files unresolved
manual reviews
provider failures
archive failures
average processing time
provider response time
cache hit rate

This will make large-library debugging much easier.

---

 1. Phase 35 — Add Provider Rate Limiting

Comic Vine and other external providers must not be hammered by multiple workers.

Implement:

per-provider rate limiter

Workers can run concurrently, but external provider requests must respect provider limits.

---

 1. Phase 36 — Add Provider Retry Policy

Retries should only occur for retryable errors.

Retry:

timeout
connection reset
HTTP 429
temporary 5xx

Do not retry indefinitely for:

404
invalid response
authentication failure
parse failure

Use exponential backoff.

---

 1. Phase 37 — Add Integration Tests

Test the complete pipeline:

CBZ
 ↓
identity
 ↓
Kapowarr
 ↓
Comic Vine
 ↓
scoring
 ↓
ComicInfo
 ↓
archive replacement
 ↓
verification
 ↓
processing state

Use mocked providers.

No live internet should be required for normal CI.

---

 1. Phase 38 — Add Failure-Injection Tests

Intentionally simulate:

permission denied
provider timeout
provider 429
provider 500
malformed HTML
invalid XML
corrupt CBZ
disk full
temporary file failure
os.replace failure
application crash

The expected result should always be:

original archive remains safe
job state records failure
useful error is logged
job can be retried

---

 1. Phase 39 — Add Property-Based / Fuzz Testing

Particularly test:

- filenames
- issue numbers
- XML
- provider HTML
- archive contents

Examples:

Batman #1
Batman #001
Batman 1A
Batman 1.5
Batman Annual 1
Batman Special

The parser must never crash the entire processing service.

---

 1. Phase 40 — Create AI-Agent Documentation

Create and maintain:

docs/
├── architecture.md
├── metadata-resolution.md
├── provider-contract.md
├── archive-safety.md
├── automation.md
└── testing.md

These documents should describe the actual implemented architecture, not merely the intended architecture.

Each document should contain:

Purpose
Responsibilities
Inputs
Outputs
Invariants
Failure modes
Testing requirements
Do-not-do rules

---

 1. Phase 41 — Add AI Coding Agent Rules

Create a root-level:

AGENTS.md

or equivalent project-specific AI instructions.

It should explicitly state:

Do not rewrite the application from scratch.

Do not bypass the identity resolver.

Do not accept the first provider search result automatically.

Do not modify archives without archive verification.

Do not delete CBR until converted CBZ is verified.

Do not silently swallow provider exceptions.

Do not change Kapowarr ownership/permissions.

Do not remove unknown ComicInfo fields.

Do not add provider-specific logic to the domain model.

Every identity-resolution change requires tests.
Every archive-writing change requires safety tests.

This is particularly important if multiple AI agents will work on the repository.

---

 1. Phase 42 — Establish Architectural Invariants

Create a permanent list of rules.

Identity

A filename is never sufficient proof of identity.

Providers

Providers return candidates.
Providers do not select the final identity.

Metadata

Identity and metadata are separate concepts.

Archives

Never replace an original archive with an unverified archive.

Existing metadata

Existing valid metadata is never destroyed merely because new metadata exists.

Automation

Every processing operation is restart-safe.

Errors

No match != provider failure.

Kapowarr

Kapowarr identity is preferred when it can be reliably associated with the archive.

---

 1. Phase 43 — Performance Optimization

Only after correctness is established.

Optimize:

Kapowarr snapshot lookup
provider cache
HTML parsing
SHA256 calculation
archive copying
database queries

Do not optimize by weakening validation.

Correctness is more important than throughput.

---

 1. Phase 44 — Large-Library Testing

Before calling the application production-ready, test against a representative library.

Include:

single issues
old comics
modern comics
Marvel
DC
independent publishers
annuals
specials
decimal issues
variant covers
TPBs
omnibuses
collections
missing metadata
incorrect existing metadata
duplicate filenames
similar series names

Measure:

auto-accept rate
manual-review rate
unresolved rate
false-positive rate
provider failures
processing speed

The most important metric is:

«false positive identity matches»

That number should be driven as close to zero as practical.

---

 1. Phase 45 — Production Safety Mode

Before enabling automatic processing against the real Kapowarr library, require:

dry-run

first.

Then:

manual review

Then:

limited test directory

Then:

small real library subset

Only after successful validation:

full library automation

---

 1. Recommended Implementation Order

Do not implement these phases in arbitrary order.

Use this order:

P0-1  Establish tests/baseline
P0-2  Domain model separation
P0-3  Identity extraction
P0-4  Kapowarr snapshot/identity
P0-5  Candidate system
P0-6  Scoring
P0-7  Conflict detection
P0-8  Identity → metadata separation
P0-9  Archive transaction hardening
P0-10 Durable processing state
P0-11 Restart-safe queue
P0-12 TPB validation

Then:

P1-1  Comic Vine refactor
P1-2  GCD refactor
P1-3  Provider contracts
P1-4  Error handling
P1-5  ComicInfo preservation
P1-6  Cache improvements
P1-7  Rate limiting
P1-8  Retry policies

Then:

P2-1  app.py decomposition
P2-2  structured logging
P2-3  metrics
P2-4  dry-run UI
P2-5  manual review UI
P2-6  performance optimization

Finally:

P3
Large-library validation
Production rollout

---

 1. Definition of Done

The project should not be considered production-ready until all of the following are true.

Identity

- [x] Filename parsing works.
- [x] Folder parsing works.
- [x] Existing ComicInfo identity can be extracted.
- [x] Kapowarr identity can be associated reliably.
- [x] Providers return candidates.
- [x] Candidates are scored.
- [x] Conflicts are detected.
- [x] Low-confidence matches are not automatically written.
- [x] First-result selection has been eliminated.

Metadata

- [x] Identity is separate from metadata.
- [x] Provider metadata is normalized.
- [x] Field-level merge rules exist.
- [x] TPB/collection metadata is validated.

ComicInfo

- [x] All supported fields round-trip.
- [x] Unknown fields are preserved.
- [x] Existing metadata is not silently destroyed.
- [x] XML validation exists.

Archives

- [x] Temporary archive is created on the same filesystem.
- [x] Temporary archive is validated.
- [x] Atomic replacement is used.
- [x] Unsafe cross-filesystem replacement is not silently used.
- [x] Final archive is verified.
- [x] Original content entries are preserved.
- [x] CBR deletion occurs only after successful CBZ verification.

Automation

- [x] Jobs are stored durably.
- [x] Queue survives restart.
- [x] Processing jobs can recover after crashes.
- [x] Duplicate jobs are prevented.
- [x] Watcher does not repeatedly process its own output.
- [x] SHA256 state is recorded.

Providers

- [x] Provider contracts are defined.
- [x] Provider failures are typed.
- [x] Rate limiting exists.
- [x] Retry policy exists.
- [x] Provider responses are cached.
- [x] Parser fixtures exist.

Testing

- [x] Unit tests pass.
- [x] Integration tests pass.
- [x] Archive tests pass.
- [x] Provider fixture tests pass.
- [x] Failure-injection tests pass.
- [x] Restart/recovery tests pass.
- [x] Large-library test set passes.

Documentation

- [x] Architecture documentation exists.
- [x] Metadata resolution documentation exists.
- [x] Provider contract documentation exists.
- [x] Archive safety documentation exists.
- [x] Automation documentation exists.
- [x] Testing documentation exists.
- [x] AI-agent instructions exist.

---

 1. Final Architecture Goal

The final application should make the following decision safely:

Batman (2016) 001.cbz

The system should not think:

"Search Batman 001 and use whatever comes first."

It should think:

Archive
 ↓
Existing metadata
 ↓
Filename evidence
 ↓
Folder evidence
 ↓
Kapowarr identity
 ↓
Comic Vine candidates
 ↓
GCD candidates
 ↓
Normalize candidates
 ↓
Compare evidence
 ↓
Detect conflicts
 ↓
Calculate confidence
 ↓
Select identity
 ↓
Retrieve metadata
 ↓
Merge according to field policy
 ↓
Generate ComicInfo.xml
 ↓
Build temporary archive
 ↓
Verify archive
 ↓
Atomic replace
 ↓
Verify final archive
 ↓
Record SHA256 + identity + result

The desired end state is:

«If the application is unsure, it stops. It never guesses.»

That principle should drive every remaining implementation decision.
