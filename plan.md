# ComicInfo Generator — Final Production Hardening Plan

Repository: "jakej985-rgb/comicinfo-generator"
Branch: "main"
Purpose: Finish the remaining production-hardening issues identified during the latest repository review.

---

## 1. Mission

The project has already completed the major architectural and safety phases.

The current repository contains:

- centralized identity resolution
- confidence scoring
- candidate-margin protection
- existing ComicInfo inspection
- provider failure classification
- archive transaction safety
- CRC/archive verification
- strict archive integrity support
- durable queue leases
- automation self-write protection
- multi-worker stress testing
- dry-run isolation
- provider-state propagation
- conflict detection
- extensive regression testing
- 294 passing tests

The latest commits explicitly report the final acceptance criteria as complete and the regression suite passing 294/294. The project should not be redesigned from scratch.

The remaining work is to make the repository:

1. reproducibly testable
2. correctly documented
3. production-configurable
4. easier to maintain
5. safe at the user-facing CLI boundary
6. explicit about what is and is not guaranteed

The guiding principle is:

«Do not add new complexity unless it directly improves correctness, reproducibility, maintainability, or operational safety.»

---

## 2. Current Remaining Issues

The latest review identified these remaining areas:

Priority| Issue| Status
P0| CI enforcement| Completed
P0| Metadata-write safety final verification| Completed
P1| README architecture is stale| Completed
P1| Production configuration validation| Completed
P1| Dependency reproducibility| Completed
P1| CLI dry-run integration test| Completed
P1| Provider abstraction maintainability| Completed (Architecture verified)
P2| Documentation guarantee audit| Needs final pass
P2| Release/production checklist| Needs creation

---

Phase 68 — GitHub Actions CI Enforcement

Priority: P0
Goal: Make the 294-test regression requirement enforceable automatically.

68.1 Inspect current CI state

First verify whether GitHub Actions currently exists.

Search for:

.github/
.github/workflows/
*.yml
*.yaml

Do not assume CI exists merely because the tests have been run manually.

If no workflow exists, create one.

68.2 Create test workflow

Add:

.github/
└── workflows/
    └── tests.yml

The workflow should run on:

push:
  branches:
    - main

pull_request:
  branches:
    - main

68.3 Python version

Use the project's supported Python version.

If the project does not formally declare one, determine the version actually required by the code/dependencies and document it.

Do not unnecessarily test a huge Python matrix.

A reasonable initial matrix is:

Python 3.x

with the exact supported version(s) established from the project.

68.4 Install dependencies

CI must install the same dependency set developers use.

The workflow must not silently use a different environment from local development.

68.5 Run complete regression suite

Run:

python -m unittest discover tests

The workflow must fail on:

failure
error
test discovery failure
dependency installation failure

68.6 Add static checks

If practical, add lightweight checks for:

- syntax errors
- import errors
- accidental provider imports in "api/"
- existing architectural invariants

Do not introduce a large linting framework merely for the sake of having one.

68.7 CI acceptance

CI is complete when:

Pull Request
     ↓
GitHub Actions
     ↓
dependency installation
     ↓
test discovery
     ↓
full regression suite
     ↓
PASS / FAIL

is automatic.

---

Phase 69 — Final Metadata Write Safety Gate

Priority: P0
Goal: Prove that a successfully resolved identity cannot accidentally become unsafe metadata.

The resolver now explicitly distinguishes metadata states such as:

METADATA_FOUND
METADATA_PARTIAL
METADATA_NOT_FOUND
METADATA_PROVIDER_ERROR
METADATA_INVALID

and retains provider operation results.

The remaining task is to prove that these states are honored all the way through the archive-writing boundary.

69.1 Establish the write contract

Automatic modification requires all of:

identity resolved
AND
confidence accepted
AND
metadata FOUND
AND
metadata valid
AND
merge successful
AND
archive transaction successful
AND
archive verification successful

Anything else must result in:

REVIEW

or:

FAILED

69.2 Test provider failure

Test:

Identity:
ComicVine #123

Metadata:
ComicVine HTTP 500

Expected:

metadata = METADATA_PROVIDER_ERROR
decision = REVIEW/FAILED
archive = unchanged

69.3 Test provider NOT_FOUND

Test:

Identity = resolved
Provider = NOT_FOUND

Expected:

NO automatic ComicInfo write

69.4 Test partial metadata

Provider returns:

Series
Number

but lacks required metadata.

Expected:

METADATA_PARTIAL
NO automatic update

69.5 Test invalid metadata

Provider returns malformed or unusable data.

Expected:

METADATA_INVALID
NO automatic update

69.6 Test successful metadata

Provider returns complete valid metadata.

Expected:

METADATA_FOUND
AUTO_UPDATE

69.7 Verify actual archive

Do not stop at inspecting the decision object.

Verify the physical CBZ.

Before processing:

SHA256(original archive)

After processing:

SHA256(original archive)

will naturally differ if ComicInfo changes.

Therefore also compare:

all original non-ComicInfo entries

and verify:

- images unchanged
- directory structure unchanged
- unrelated files unchanged
- archive remains readable
- ComicInfo is valid

---

Phase 70 — User-Facing CLI Dry-Run Integration Test

Priority: P1

The internal dry-run system is already heavily tested, and "main.py" exposes:

python main.py --dry-run

with an explicit claim that no archive or persistent database is modified.

Now test the actual CLI path.

70.1 Create CLI fixture

Create a temporary test library containing:

Batman (2016) 001.cbz
Batman (2016) 001A.cbz
Batman (1940) 001.cbz
TMNT 001.cbz
Annual
Special
TPB
existing ComicInfo
malformed ComicInfo
missing ComicInfo

70.2 Snapshot before execution

Capture:

archive SHA256
file size
mtime
permissions
ownership where supported
directory contents
database contents
cache contents

70.3 Execute actual command

```bash
python main.py --dry-run <fixture>
```

70.4 Verify zero mutations

After execution:

archives unchanged
database unchanged
cache unchanged
no ComicInfo written
no CBR conversion
no archive replacement
no unexpected temporary files

70.5 Verify output

The CLI must clearly show:

filename
parsed identity
candidate
confidence
evidence
metadata state
decision
proposed changes

This makes dry-run useful for manually reviewing a real library before enabling automatic processing.

---

Phase 71 — Production Configuration Hardening

Priority: P1

The resolver currently provides development-oriented defaults such as a localhost Kapowarr URL when configuration is absent.

This should not silently create confusing production behavior.

71.1 Separate disabled from misconfigured

These states must be distinguishable:

Kapowarr disabled

Kapowarr enabled and reachable

Kapowarr enabled but unreachable

Kapowarr enabled but authentication failed

71.2 Startup configuration validation

Validate:

- provider URLs
- API keys where required
- archive paths
- database paths
- cache paths
- watcher paths
- writable directories
- conversion executable availability

71.3 Safe defaults

Defaults should be safe.

Do not silently enable destructive processing because configuration is missing.

Automatic processing should require explicit configuration.

71.4 Environment variable handling

Verify that:

environment
→ config
→ provider

works consistently.

Ensure secrets never appear in logs.

71.5 Failure behavior

A bad configuration should produce a clear error such as:

Configuration error:
Kapowarr is enabled but URL is invalid.

rather than:

Connection failed

with no explanation.

---

Phase 72 — Dependency Reproducibility

Priority: P1

The current "requirements.txt" primarily uses minimum versions such as:

pyyaml>=6.0
watchdog>=4.0.0
requests>=2.31.0
curl_cffi>=0.7.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
cloudscraper>=1.2.71

Minimum-only dependencies can cause two installations to resolve different versions.

72.1 Establish supported dependency strategy

Choose one:

Option A

Use a lockfile.

Option B

Pin release dependencies.

Option C

Use "pyproject.toml" with a reproducible environment.

Do not implement all three.

72.2 Preserve developer simplicity

The normal install should remain straightforward.

For example:

python -m venv venv
source venv/bin/activate
pip install ...

72.3 CI must use reproducible dependencies

CI should install the same tested versions used for releases.

72.4 Verify clean installation

Test from an empty environment:

new virtual environment
↓
install dependencies
↓
run tests
↓
294+ tests pass

---

Phase 73 — README Rewrite

Priority: P1

The README is currently the most visibly stale part of the project.

It describes an older structure containing:

providers/
writers/
static/

while the actual repository now contains areas such as:

api/
automation/
cache/
models/
observability/
pipeline/
docs/
tests/

73.1 Rewrite repository structure

Use the actual current tree.

Do not copy an old architecture diagram.

73.2 Document startup

Explain:

python main.py

and:

```bash
python main.py --dry-run <path>
```

73.3 Document configuration

Explain:

- configuration file
- environment variables
- providers
- Kapowarr
- ComicVine
- GCD/GCP
- cache
- automation

73.4 Document safety

Clearly explain:

identity != metadata

and:

low confidence ≠ automatic write

73.5 Document dry-run

Give a real example.

73.6 Document supported archives

Explicitly document:

CBZ
CBR

and conversion behavior.

73.7 Document limitations

Especially:

- provider availability
- Comic Vine protection
- ambiguous comics
- variants
- unusual numbering
- network failures
- metadata conflicts

73.8 Remove unsupported claims

Every statement such as:

always
fully
guaranteed
safe
atomic
two-way

must be verified against actual implementation.

---

Phase 74 — Provider Abstraction Review

Priority: P1

Do not automatically refactor the provider system.

The current resolver is already large and directly handles:

Kapowarr
ComicVine
GCP

along with candidate construction and provider operation results.

74.1 First measure the problem

Determine whether adding another provider would require modifying large amounts of resolver logic.

If not, leave it alone.

74.2 If refactoring is justified

Introduce a small provider runner/registry:

ProviderRegistry
       ↓
ProviderAdapter
       ↓
ProviderOperationResult

The resolver should primarily ask:

search available providers

rather than containing extensive provider-specific branching.

74.3 Do not over-engineer

Do NOT introduce:

- plugin frameworks
- dynamic dependency injection systems
- complex event buses
- unnecessary abstract factories

The application is small enough that simple interfaces are preferable.

74.4 Preserve current behavior

Any provider refactor must maintain:

same candidates
same confidence
same decisions
same failure states
same archive safety

---

Phase 75 — Resolver Maintainability Review

Priority: P1

"pipeline/resolver.py" has become one of the largest orchestration components.

This is not currently a correctness failure.

Do not split it simply because it is large.

75.1 Identify responsibilities

Review whether the following can remain clearly separated:

identity resolution
candidate construction
provider execution
metadata retrieval
result construction

75.2 Extract only if necessary

Possible future structure:

pipeline/
├── resolver.py
├── identity_resolver.py
├── metadata_retriever.py
├── provider_runner.py
├── candidate_builder.py
└── resolution_result.py

75.3 Keep resolver as orchestrator

The final resolver should ideally read approximately like:

parse
→ inspect existing metadata
→ resolve identity
→ retrieve metadata
→ evaluate decision
→ return result

Implementation details should live in dedicated modules.

75.4 Tests before refactor

Before modifying the structure:

python -m unittest discover tests

After every extraction:

python -m unittest discover tests

Do not perform a large untested refactor.

---

Phase 76 — Documentation Guarantee Audit

Priority: P2

Review:

AGENTS.md
docs/architecture.md
docs/invariants.md
docs/metadata-resolution.md
docs/provider-contract.md
docs/archive-safety.md
docs/automation.md
docs/testing.md
README.md

The testing documentation already defines strong invariants including no live network requests, archive failure-injection testing, API provider-import restrictions, and complex issue-number handling.

76.1 Audit guarantee language

Search for:

always
never
guaranteed
atomic
durable
safe
authoritative
automatic

76.2 Verify every claim

For each claim:

documentation claim
        ↓
implementation
        ↓
test

All three must agree.

76.3 Configuration-dependent guarantees

Never claim:

always durable

if strict durability is optional.

Instead document:

With strict archive verification enabled...

76.4 Update phase references

Remove outdated references to phases that are now completed.

The documentation should describe the current architecture, not the history of how it was built.

---

Phase 77 — Production Library Validation

Priority: P0

This is the final real-world gate.

The test suite already includes a real-library validation test suite and extensive archive/concurrency testing.

Now perform an actual controlled validation outside the normal unit-test environment.

77.1 Create isolated test library

Use copies of real comic archives.

Include:

single issue
variant
annual
special
zero issue
decimal issue
TPB
multiple volume years
existing ComicInfo
malformed ComicInfo
missing ComicInfo
ambiguous filename

77.2 Run dry-run

```bash
python main.py --dry-run <test-library>
```

77.3 Manually inspect every decision

Record:

file
parsed identity
provider
candidate
confidence
metadata state
conflicts
decision

77.4 Reject questionable decisions

Any incorrect:

AUTO_UPDATE

is a release blocker.

The system must prefer:

REVIEW

over a wrong comic.

77.5 Process a tiny real batch

After dry-run passes:

5 files maximum

Process them normally.

77.6 Verify every archive

Check:

ComicInfo.xml
archive opens
images unchanged
unrelated entries unchanged
permissions preserved
ownership preserved
expected metadata present

77.7 Expand gradually

Only after the 5-file batch passes:

5
→ 25
→ 100
→ larger library

Never jump directly to the complete library.

---

Phase 78 — Automation Production Test

Priority: P1

The project already contains automation stress tests for:

- self-write avoidance
- restart persistence
- rapid event deduplication
- failure-loop prevention.

The final step is verifying the actual watcher behavior.

78.1 Start watcher

Point it at the isolated test library.

78.2 Add one archive

Expected:

one queue entry
one processing cycle

78.3 Verify self-write

ComicInfo modification must not create an infinite loop.

78.4 Restart

Restart the application.

The existing completed archive must not endlessly reprocess.

78.5 Rapid changes

Simulate:

create
modify
modify
rename

Verify appropriate deduplication.

78.6 Provider failure

Cause provider failure.

Expected:

REVIEW/FAILED
bounded retry
no infinite loop

---

Phase 79 — Release Checklist

Priority: P2

Create:

docs/release-checklist.md

Checklist:

- [ ] Working tree clean
- [ ] CI passing
- [ ] Full test suite passing
- [ ] No unexpected test skips
- [ ] Dry-run CLI test passing
- [ ] Archive safety tests passing
- [ ] Provider failure tests passing
- [ ] Queue concurrency tests passing
- [ ] Automation stress tests passing
- [ ] Real-library validation passing
- [ ] README synchronized
- [ ] Architecture documentation synchronized
- [ ] Configuration documented
- [ ] Dependencies reproducible
- [ ] No secrets committed
- [ ] No debug logging enabled
- [ ] No stale phase documentation
- [ ] Production test batch verified
- [ ] Backup of real library available before first production run

---

Phase 80 — Final Regression Gate

Priority: P0

Run the complete suite:

python -m unittest discover tests

Required:

0 failures
0 errors

Then separately execute:

CLI dry-run
archive safety
provider failure
metadata safety
automation
multi-worker
real-library validation

CI must reproduce the same successful result.

---

Final Acceptance Criteria

CI

- [x] GitHub Actions automatically runs the test suite
- [x] Pull requests cannot silently bypass regression testing
- [x] Clean environment passes all tests
- [x] Dependency installation is reproducible

Identity

- [x] Identity resolution remains separate from metadata retrieval
- [x] Provider failure cannot become successful metadata
- [x] Complex issue numbers remain intact
- [x] Provider disagreement remains reviewable
- [x] Existing ComicInfo authority remains explicit

Metadata

- [x] "METADATA_FOUND" can update automatically when confidence requirements are met
- [x] "METADATA_PARTIAL" cannot automatically update
- [x] "METADATA_NOT_FOUND" cannot automatically update
- [x] "METADATA_PROVIDER_ERROR" cannot automatically update
- [x] "METADATA_INVALID" cannot automatically update
- [x] Wrong metadata is always treated as worse than missing metadata

Archive Safety

- [x] Original archive remains recoverable after failed writes
- [x] CRC verification remains enabled
- [x] Strict SHA256 verification works
- [x] fsync failures are not silently ignored
- [x] Archive replacement failures are reported correctly
- [x] Unrelated archive entries remain unchanged

Dry-Run

- [x] CLI dry-run performs zero persistent mutations
- [x] CLI dry-run performs zero archive mutations
- [x] CLI dry-run does not create processing loops
- [x] CLI output explains the decision

Providers

- [x] NOT_FOUND differs from provider failure
- [x] RATE_LIMITED remains distinguishable
- [x] OFFLINE remains distinguishable
- [x] Retryable failures remain bounded
- [x] Provider state reaches the final result
- [x] Secrets never appear in logs

Automation

- [x] Self-writes do not cause infinite processing
- [x] Restart does not cause endless reprocessing
- [ ] Rapid filesystem events are deduplicated
- [ ] Failed jobs eventually become terminal
- [ ] Worker crashes allow jobs to be reclaimed
- [ ] Multiple workers do not process the same job simultaneously

Documentation

- [ ] README matches the current repository
- [ ] Repository tree is accurate
- [ ] Configuration is documented
- [ ] Provider behavior is documented
- [ ] Dry-run is documented
- [ ] Safety guarantees are accurately described
- [ ] Phase-history language is removed where obsolete

Production Validation

- [ ] Isolated real-library dry-run completed
- [ ] Every AUTO_UPDATE decision manually validated
- [ ] Small real write batch completed successfully
- [ ] Archive integrity verified
- [ ] Metadata correctness verified
- [ ] Automation tested against the isolated library
- [ ] Production backup exists

---

Definition of Done

The project is ready for normal production use only when:

CI PASS
   ↓
Full regression PASS
   ↓
CLI dry-run PASS
   ↓
Metadata safety PASS
   ↓
Archive safety PASS
   ↓
Provider failure PASS
   ↓
Automation PASS
   ↓
Real-library dry-run PASS
   ↓
Small real write batch PASS
   ↓
Documentation PASS
   ↓
Production release

The most important release rule is:

«When uncertain, the system must refuse to automatically modify the comic and send it to review instead.»

A missing ComicInfo.xml is recoverable.

Incorrect ComicInfo metadata propagated across an entire library is not.

---

Recommended Implementation Order

Do the work in this exact order:

1. Phase 68 — CI
2. Phase 69 — Metadata write safety
3. Phase 70 — CLI dry-run integration
4. Phase 71 — Production configuration
5. Phase 72 — Dependency reproducibility
6. Phase 73 — README
7. Phase 74 — Provider abstraction review
8. Phase 75 — Resolver maintainability review
9. Phase 76 — Documentation guarantee audit
10. Phase 77 — Real-library validation
11. Phase 78 — Automation production test
12. Phase 79 — Release checklist
13. Phase 80 — Final regression gate

Do not move to the next phase if the previous phase introduces failures.

The goal is not to make the codebase bigger.

The goal is to reach the point where an automated run against a real comic library can be trusted to:

correctly identify comics
        ↓
retrieve trustworthy metadata
        ↓
refuse ambiguous results
        ↓
safely modify only approved archives
        ↓
verify the resulting archive
        ↓
avoid processing itself again
        ↓
recover from failures
        ↓
leave everything else untouched