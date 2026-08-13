ComicInfo Generator — Final Production Hardening Plan

Repository: jakej985-rgb/comicinfo-generator
Branch: main
Starting point: Phase 55 / commit fef25afc
Goal: Eliminate the remaining paths that could cause incorrect ComicInfo metadata to be automatically written to a real comic library.

---

1. Mission

The project has already implemented:

centralized identity resolution

confidence scoring

candidate-margin protection

existing ComicInfo classification

provider error classification

archive transaction safety

ZIP entry verification

durable job leases

API/service separation

dry-run isolation

automation self-write protection

end-to-end resolution tests

performance benchmarking

architectural invariants

245 passing tests

Do not redesign these systems.

The remaining work is to close the final correctness gaps.

The most important principle is:

> A resolved identity is not the same thing as successfully retrieved metadata.

The system must never automatically modify a CBZ merely because it has a plausible identity if the metadata needed to safely construct ComicInfo.xml could not be retrieved or validated.

---

Phase 56 — Separate Identity Resolution From Metadata Success

Priority: 🔴 P0

Problem

The current resolver can successfully identify a comic and then fail to retrieve provider metadata.

The implementation currently has a fallback similar to:

if not comic:
    comic = Comic(
        series=identity.series_name,
        number=identity.issue_number,
        year=identity.publication_year,
        publisher=identity.publisher,
        provider_name=identity.provider or "Resolver"
    )

This is dangerous.

A provider lookup failure can therefore become:

Provider lookup failed
        ↓
Comic object synthesized
        ↓
Pipeline thinks metadata exists
        ↓
ComicInfo.xml may be written

That behavior must be eliminated for automatic processing.

---

56.1 Create explicit metadata states

Introduce a clear metadata result model.

Use the existing architecture where possible rather than creating duplicate models.

The result must distinguish:

METADATA_FOUND
METADATA_PARTIAL
METADATA_NOT_FOUND
METADATA_PROVIDER_ERROR
METADATA_INVALID

If the project already has a suitable result type, extend it instead of creating another competing abstraction.

---

56.2 Identity state must remain separate

The pipeline must be able to represent:

Identity:
    RESOLVED

Metadata:
    FAILED

without converting the entire operation into a fake success.

Example:

Identity:
ComicVine 4000-12345
confidence = 96

Metadata:
ComicVine lookup = HTTP 500

Final:
REVIEW / FAILED

Not:

ComicInfo:
Series = Batman
Number = 1

and automatically write it.

---

56.3 Remove unsafe fallback

The fallback Comic(...) construction must not be used as a successful metadata retrieval result.

If identity-only metadata generation is intentionally supported for some special case, it must be explicitly marked:

source = IDENTITY_ONLY
metadata_complete = false

and must not be eligible for automatic archive modification.

---

56.4 Define automatic-write requirements

Automatic archive modification requires:

identity resolved
AND
confidence acceptable
AND
metadata retrieved
AND
metadata valid
AND
merge succeeds
AND
archive validation succeeds

Anything else becomes:

REVIEW

or:

FAILED

depending on the failure.

---

56.5 Tests

Add regression tests for:

Provider lookup succeeds

identity = valid
metadata = valid
→ AUTO_UPDATE

Provider lookup fails

identity = valid
metadata = provider error
→ REVIEW/FAILED
→ archive unchanged

Provider returns no metadata

identity = valid
metadata = NOT_FOUND
→ REVIEW/FAILED
→ archive unchanged

Provider returns malformed data

identity = valid
metadata = INVALID
→ REVIEW/FAILED
→ archive unchanged

Identity exists but metadata is incomplete

identity = valid
metadata = PARTIAL
→ no automatic update

---

Phase 57 — Make Provider Failure State Survive the Pipeline

Priority: 🔴 P0

Problem

Provider exceptions are now classified, but classification is not useful if the final pipeline loses that information.

The system must distinguish:

NOT_FOUND

from:

PROVIDER_FAILURE

from:

PROVIDER_OFFLINE

---

57.1 Create provider operation result

Use the existing provider contract if possible.

Every provider operation should expose:

provider
operation
status
error_type
retryable
message

Example:

ComicVine
operation: lookup_issue
status: RATE_LIMITED
retryable: true

---

57.2 Preserve provider states during resolution

The resolver should retain something like:

Kapowarr:
    SUCCESS

ComicVine:
    RATE_LIMITED

GCD:
    NOT_FOUND

instead of reducing everything to:

candidates = []

---

57.3 Resolution result

The final resolution result should contain:

identity
confidence
decision
provider_results
conflicts

This makes failures explainable.

---

57.4 Do not treat provider outage as "not found"

These are fundamentally different:

Provider says:
"No matching comic."

versus:

Provider says:
"Server unavailable."

The first permits fallback.

The second requires recording provider failure and applying the fallback policy.

---

57.5 Retry behavior

Respect the existing retry/rate-limit system.

For retryable failures:

attempt
   ↓
retry policy
   ↓
provider result

Do not repeatedly retry indefinitely.

---

57.6 Tests

Test:

404 / NOT_FOUND

timeout

connection failure

429

401

403

500

malformed response

empty response

successful fallback provider

Verify the final resolution result preserves the correct state.

---

Phase 58 — Formalize Identity Authority and Conflict Rules

Priority: 🔴 P0

The system now detects conflicts, but the remaining goal is to determine what the conflict actually means.

Do not simply use:

conflict = true
→ REVIEW

for every possible disagreement.

---

58.1 Define evidence hierarchy

Document the hierarchy.

A reasonable starting model:

Explicit user URL override
        ↓
Verified existing provider ID
        ↓
Multiple independent provider agreement
        ↓
Single trusted provider
        ↓
Existing ComicInfo identity
        ↓
Filename identity
        ↓
Directory/path hints

The exact ordering must be validated against the existing project behavior.

---

58.2 Existing XML conflict types

Differentiate:

XML ↔ filename conflict
XML ↔ provider conflict
XML ↔ provider-ID conflict
XML partial
XML malformed

These should not all have identical severity.

---

58.3 Provider agreement

Two providers agreeing on:

series
issue
volume
year

should be stronger evidence than two providers merely returning similar titles.

---

58.4 Provider disagreement

Example:

Kapowarr:
Batman (2016) #1

ComicVine:
Batman (1940) #1

must become:

MANUAL_REVIEW

unless there is explicit authoritative evidence resolving the difference.

---

58.5 Provider ID disagreement

This is especially important.

If two sources provide different authoritative issue IDs:

ComicVine = 4000-123
ComicVine = 4000-456

do not merge them merely because their titles look similar.

---

58.6 Tests

Add cases for:

XML vs filename

XML vs Kapowarr

XML vs ComicVine

Kapowarr vs ComicVine

Kapowarr + ComicVine + GCD agreement

provider-ID disagreement

variant disagreement

volume disagreement

year disagreement

---

Phase 59 — Canonical Comic Identity Key

Priority: 🟠 P1

The current candidate comparison uses series, issue number, and approximate year.

That is not enough for all comic numbering.

---

59.1 Create canonical identity comparison

The identity comparison should consider:

normalized series
volume
issue number
issue suffix
publication year
publisher
edition/variant

where available.

---

59.2 Preserve complex issue numbers

Never convert issue numbers to integers.

Correct:

1
1A
1B
1AU
0
0.5
10.1
Annual
Special
Director's Cut

must remain distinguishable.

---

59.3 Normalize only for comparison

Do not destroy the original issue string.

Example:

stored:
1A

comparison:
normalized representation

The original value must remain available for ComicInfo output.

---

59.4 Tests

Add candidate comparisons for:

1 vs 1A
1A vs 1B
1 vs 1.5
1 vs Annual
0 vs 1
10 vs 10.1
Volume 1 vs Volume 2
1940 vs 2016

---

Phase 60 — Strict Archive Integrity Mode

Priority: 🟠 P1

Current archive verification checks CRC and file size.

That is good for normal operation, but a strict verification mode should provide stronger guarantees.

---

60.1 Add entry SHA256 verification

For unchanged archive entries:

original entry SHA256
        ==
temporary entry SHA256

ComicInfo.xml is excluded because it is intentionally changed.

---

60.2 Keep CRC verification

Do not replace the existing CRC checks.

Use:

CRC + size

for fast verification.

Use:

SHA256

for strict verification.

---

60.3 Configuration

Add a configuration option such as:

strict_archive_verification

Use the project's existing configuration style.

---

60.4 Performance

Do not hash every archive entry multiple times during normal operation unless configured.

The Phase 53 benchmarks should determine the performance impact.

---

60.5 Tests

Create an archive containing:

multiple images

nested directories

text files

unusual filenames

existing ComicInfo

Verify unchanged entry SHA256 values before and after.

---

Phase 61 — Durability and fsync Error Handling

Priority: 🟠 P1

The archive writer currently treats some filesystem durability failures as non-fatal.

For example, helper functions currently catch exceptions broadly.

That is inappropriate for safety-critical durability operations.

---

61.1 Distinguish unsupported from failed

Possible states:

FSYNC_SUCCESS
FSYNC_UNSUPPORTED
FSYNC_FAILED

---

61.2 Never silently swallow actual fsync failures

If fsync() fails:

log the failure

classify it

apply configured safety policy

For production mode, the safest behavior is:

archive update = FAILED

rather than pretending the operation is durable.

---

61.3 Directory fsync

Retain:

write temp
→ fsync temp
→ replace
→ fsync final
→ fsync directory

---

61.4 Test failure injection

Inject failures into:

file fsync

directory fsync

replace

verification

Verify that the application reports the correct failure.

---

Phase 62 — Real Library Integration Validation

Priority: 🔴 P0 before production

This is the final gate.

Unit tests passing is not enough.

Do not immediately point the application at the entire library.

---

62.1 Build a test library

Create a small isolated directory containing representative CBZs.

Include:

Batman (2016) 001.cbz
Batman (2016) 001A.cbz
Batman (2016) 001B.cbz
Batman (1940) 001.cbz
TMNT 001.cbz
TMNT 001A.cbz
Annual
Special
0.5
10.1
TPB
collection
existing ComicInfo
malformed ComicInfo
missing ComicInfo

Use copies of real files.

---

62.2 Run dry-run first

The first execution must be:

python main.py --dry-run

Verify:

archives unchanged
timestamps unchanged
database unchanged
cache unchanged
no temp files

---

62.3 Review generated decisions

For every file record:

filename
identity
provider
confidence
decision
metadata state
conflicts

Manually inspect ambiguous cases.

---

62.4 Real write test

Only after dry-run is correct:

Process a small batch.

Example:

5 files

Then verify:

ComicInfo.xml
archive integrity
images
file permissions
ownership
timestamps

---

62.5 Kapowarr integration

Use an isolated/test Kapowarr library if possible.

Verify:

Kapowarr metadata
        ↓
resolver
        ↓
ComicInfo

and confirm the system doesn't accidentally modify Kapowarr-managed files in unexpected ways.

---

Phase 63 — Automation Stress Test

Priority: 🟠 P1

Test the actual watcher.

---

63.1 Self-write test

Watcher sees:

comic.cbz

It processes it.

The resulting write must not trigger endless processing.

Expected:

1 processing cycle

not:

2
3
4
...

---

63.2 Restart test

Process file.

Restart application.

Verify it does not immediately reprocess the same archive.

---

63.3 Rapid modification test

Simulate:

file appears
file changes
file changes again

The job system must deduplicate appropriately.

---

63.4 Failed processing test

Force a provider/archive failure.

Verify:

FAILED/REVIEW

doesn't produce an infinite retry loop.

---

Phase 64 — Multi-Worker Stress Test

Priority: 🟠 P1

Run multiple workers simultaneously.

Example:

worker-1
worker-2
worker-3
worker-4

against:

100 jobs

Verify:

each job processed once

unless intentionally retried.

---

64.1 Worker crash

Kill a worker while processing.

Verify:

lease expires
       ↓
job reclaimed
       ↓
new worker processes it

---

64.2 Poison job

Create a permanently failing archive.

Verify:

attempt 1
attempt 2
attempt 3
FAILED

and no infinite loop.

---

Phase 65 — Final Security/Safety Audit

Priority: 🟠 P1

Search the repository for dangerous patterns.

Run static searches for:

except Exception:
    pass

and:

int(issue_number)

and direct provider imports from:

api/

and archive operations outside the archive writer.

Also search for:

os.replace
shutil.move
os.remove
open(..., "w")

and verify each usage is intentional.

---

Phase 66 — Documentation Finalization

Priority: 🟡 P2

Update:

AGENTS.md
docs/architecture.md
docs/metadata-resolution.md
docs/provider-contract.md
docs/archive-safety.md
docs/automation.md
docs/testing.md
docs/invariants.md

Documentation must describe what the code actually guarantees.

Pay special attention to words such as:

always
never
guaranteed
atomic
durable
safe
automatic
authoritative

Do not claim guarantees that depend on an optional configuration setting.

---

Phase 67 — Final Regression

Run the complete suite:

./venv/bin/python -m unittest discover tests

Required:

0 failures
0 errors

Then run:

unit tests
integration tests
failure injection
property/fuzz
archive safety
queue concurrency
dry-run
automation
real-library test

---

Final Acceptance Criteria

The project is production-ready only when all of these are true.

Identity

[ ] Filename alone cannot produce an automatic identity.

[ ] Identity resolution and metadata retrieval are separate states.

[ ] Metadata failure cannot become successful metadata.

[ ] Provider disagreement causes review.

[ ] Critical identity conflicts cannot auto-update.

[ ] Score margin is enforced.

[ ] Complex issue numbers remain intact.

[ ] Variants/editions are distinguishable.

[ ] Existing XML authority is explicitly evaluated.

Providers

[ ] NOT_FOUND differs from provider failure.

[ ] Rate limiting is preserved.

[ ] Retryable errors are distinguished.

[ ] Provider state survives into the final job result.

[ ] No provider exception is silently discarded.

[ ] No live provider requests occur in unit tests.

Metadata

[ ] Successful identity does not imply successful metadata.

[ ] Partial metadata cannot silently become a full Comic.

[ ] Invalid metadata cannot be written.

[ ] Provider lookup failure leaves the archive untouched.

Archives

[ ] Temporary archive is on the same filesystem.

[ ] Pre-replacement verification passes.

[ ] Atomic replacement is used.

[ ] File fsync is performed.

[ ] Directory fsync is performed.

[ ] fsync failures are handled explicitly.

[ ] Existing entries are preserved.

[ ] CRC/size verification passes.

[ ] Strict SHA256 verification is available.

[ ] Post-replacement verification passes.

Queue

[ ] Jobs cannot be double-claimed.

[ ] Worker leases work.

[ ] Crashed workers are recoverable.

[ ] Poison jobs stop retrying.

[ ] Multiple workers can safely operate concurrently.

Automation

[ ] Self-written archives are ignored.

[ ] Restart does not cause duplicate processing.

[ ] Rapid file changes are deduplicated.

[ ] Failed jobs do not loop forever.

Dry Run

[ ] No archive modification.

[ ] No cache modification.

[ ] No job modification.

[ ] No temporary files.

[ ] No persistent database writes.

[ ] Before/after filesystem state is identical.

---

Implementation Order

The AI agent must implement in this order:

56
Identity / Metadata separation
        ↓
57
Provider failure propagation
        ↓
58
Identity authority/conflict rules
        ↓
59
Canonical identity comparison
        ↓
60
Strict archive verification
        ↓
61
fsync durability handling
        ↓
62
Real-library integration
        ↓
63
Automation stress testing
        ↓
64
Multi-worker stress testing
        ↓
65
Final safety audit
        ↓
66
Documentation
        ↓
67
Final regression

Do not move to the next phase if the previous phase has failing tests.

---

Most Important Rule for the Agent

The agent must enforce this invariant:

IDENTITY
                    │
                    ▼
              RESOLUTION OK?
                 /       \
               NO         YES
               │           │
             REVIEW        ▼
                     METADATA RETRIEVAL
                         /       \
                       FAIL      SUCCESS
                        │           │
                      REVIEW        ▼
                              METADATA VALID?
                                /       \
                              NO         YES
                              │           │
                            REVIEW        ▼
                                  MERGE/VALIDATION
                                      │
                                      ▼
                                  ARCHIVE WRITE
                                      │
                                      ▼
                               VERIFY + DURABILITY
                                      │
                                ┌─────┴─────┐
                                ▼           ▼
                              FAIL       SUCCESS
                                │           │
                              ROLLBACK     DONE

There must be no path from IDENTITY RESOLVED directly to ARCHIVE WRITE.

That is the most important remaining correction.

And the agent should not declare the project production-ready merely because 245 tests pass. The final gate is a controlled real-library dry run followed by a small real write test, then automation and multi-worker testing.
