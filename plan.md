ComicInfo Generator — Remaining Work Completion Plan

Repository: jakej985-rgb/comicinfo-generator
Branch: main
Goal: Finish the remaining production-hardening work without adding unnecessary features or reopening completed CBR functionality.

> Important: CBR conversion is not part of this plan as a problem. The intended behavior is correct: CBR → CBZ → embed ComicInfo.xml → optionally delete the original CBR.




---

1. Project Completion Goal

The project should be considered complete when it can reliably:

Comic archive discovered
        ↓
Determine existing metadata
        ↓
Use cached/local information first
        ↓
Prefer Kapowarr when available
        ↓
Use ComicVine/GCD only when necessary
        ↓
Resolve identity with confidence/evidence
        ↓
Generate/merge ComicInfo.xml
        ↓
Safely write archive
        ↓
Verify archive
        ↓
Record completed state
        ↓
Watcher ignores its own changes

And importantly:

Provider failure ≠ metadata not found
API credentials never exposed
Dry-run never modifies data
Restart does not reprocess completed files
Concurrent workers cannot duplicate work


---

PHASE 80 — Security Hardening

80.1 Remove API keys from /api/config

Current problem

The API currently returns the actual ComicVine and Kapowarr API keys through /api/config.

That must be removed.

Change

Instead of:

{
  "comicvine": {
    "api_key": "actual-secret"
  }
}

return:

{
  "comicvine": {
    "api_key_set": true
  }
}

and:

{
  "kapowarr": {
    "url": "http://localhost:5656",
    "api_key_set": true
  }
}

Requirements

Never return raw API keys through GET.

Never include raw API keys in error messages.

Never include raw API keys in logs.

Never include raw API keys in exception traces sent to the browser.

Preserve the ability to update a key.

An empty/missing key should still be representable.


Tests

Add tests proving:

configured ComicVine key is not returned

configured Kapowarr key is not returned

api_key_set == true

missing key produces false

error responses don't contain the key



---

80.2 Fix CORS

Current behavior effectively allows:

Access-Control-Allow-Origin: *

This should not remain the default.

Preferred behavior

For the local application:

localhost
127.0.0.1

should be allowed.

Make CORS configurable if remote browser access is intentionally supported.

Example:

server:
  host: "127.0.0.1"
  cors_origins:
    - "http://127.0.0.1:5005"

Tests

Verify:

allowed origin receives CORS header

unauthorized origin does not

default configuration is restrictive



---

80.3 Bind safely by default

Make sure the application does not accidentally expose the management API to the entire LAN.

Default:

127.0.0.1

rather than:

0.0.0.0

If LAN access is desired, make it an explicit configuration choice.


---

PHASE 81 — Configuration Hardening

81.1 Make startup validation mandatory

validate_startup_config() already exists.

The problem is that configuration can be loaded without necessarily passing through the validation boundary.

New startup flow

load_config()
      ↓
validate_startup_config()
      ↓
ApplicationContext
      ↓
start server / queue / watcher

Do not allow production components to start with invalid configuration.


---

81.2 Separate errors from warnings

Configuration problems should be classified:

Fatal

invalid URL
invalid worker count
unusable cache path
invalid configuration type

Application startup stops.

Warning

ComicVine key missing
Kapowarr unavailable
7z/unrar unavailable

Application can start, but clearly reports the limitation.


---

81.3 Validate configuration types

Do not rely on:

int(...)
bool(...)
str(...)

without controlled error handling.

For example, malformed YAML such as:

workers: bananas

should produce a clean:

Configuration error:
automation.workers must be an integer >= 1

rather than an unexpected Python exception.


---

81.4 Add configuration tests

Cover:

defaults

YAML

environment variables

CLI overrides

invalid YAML

invalid worker count

invalid URLs

invalid log level

invalid cache directory

missing conversion utilities

precedence rules


Verify:

CLI > environment > YAML > defaults


---

PHASE 82 — Provider Resolution Redesign

This is the most important functional phase.

The goal is to minimize unnecessary external requests while improving accuracy.


---

82.1 Establish the authoritative resolution order

Implement this exact strategy:

1. Explicit URL / explicit provider ID
       ↓
2. Existing ComicInfo.xml
       ↓
3. Persistent cache
       ↓
4. Local filename / folder identity
       ↓
5. Kapowarr
       ↓
6. ComicVine
       ↓
7. GCD
       ↓
8. REVIEW / unresolved

However, existing ComicInfo should not automatically win if it is obviously invalid or conflicts with explicit user information.


---

82.2 Existing ComicInfo should be treated as evidence

Don't simply do:

ComicInfo exists → done

Instead:

ComicInfo exists
      ↓
validate
      ↓
complete?
      ↓
consistent?
      ↓
trusted?

A valid existing ComicInfo can eliminate network calls.


---

82.3 Cache must be checked before network providers

Before calling any provider:

normalized identity
        ↓
cache lookup
        ↓
valid cached result?
        ↓
YES → use cached result
NO  → provider resolution

This is especially important for ComicVine request conservation.


---

82.4 Kapowarr-first behavior

When Kapowarr is configured and reachable:

filename
 ↓
Kapowarr search
 ↓
candidate
 ↓
confidence

Only call ComicVine if:

Kapowarr unavailable
OR
Kapowarr returns no useful candidate
OR
confidence below threshold

Do not call ComicVine merely because it exists as another provider.


---

82.5 ComicVine fallback

ComicVine should be a fallback rather than an automatic first-class network request for every file.

Track:

ComicVine requested?
reason?
query?
cache hit?
rate limited?
result?

This will let you verify that the application is actually conserving requests.


---

82.6 GCD fallback

GCD should behave the same way:

GCD requested only when previous resolution stages fail

It should not be silently queried as part of every resolution.


---

82.7 Add provider resolution reason

Every final result should expose something like:

{
  "provider": "Kapowarr",
  "resolution_source": "kapowarr",
  "fallback_used": false
}

or:

{
  "provider": "ComicVine",
  "resolution_source": "comicvine_fallback",
  "fallback_used": true,
  "fallback_reason": "Kapowarr returned no match"
}

This will make debugging dramatically easier.


---

PHASE 83 — Provider Error Semantics

The provider base classes already have useful states:

SUCCESS
NOT_FOUND
CONNECTION_ERROR
AUTH_ERROR
RATE_LIMITED
PARSE_ERROR
INVALID_RESPONSE

Now make the entire application consistently use them.


---

83.1 Never convert provider errors into None

Avoid patterns such as:

try:
    ...
except Exception:
    return None

because that turns:

RATE_LIMITED

into:

NOT_FOUND


---

83.2 Standardize provider result

Use one structure:

ProviderOperationResult(
    status=SUCCESS,
    provider="ComicVine",
    data=...,
    error_code=None,
    retryable=False
)

Failure:

ProviderOperationResult(
    status=RATE_LIMITED,
    provider="ComicVine",
    data=None,
    error_code="RATE_LIMITED",
    retryable=True
)


---

83.3 Define retry policy

Retry

CONNECTION_ERROR
RATE_LIMITED
temporary server failure

Don't retry automatically

AUTH_ERROR
NOT_FOUND
INVALID_RESPONSE
PARSE_ERROR


---

83.4 Preserve provider errors through the resolver

The final result should be able to say:

No metadata found

versus:

ComicVine could not be queried because it was rate limited

Those are completely different outcomes.


---

PHASE 84 — Provider Registry

Clean up the current partial provider abstraction.


---

84.1 Create ProviderRegistry

Example architecture:

providers/
├── base.py
├── registry.py
├── comicvine/
├── gcd/
└── kapowarr/

Registry:

ProviderRegistry
 ├── kapowarr
 ├── comicvine
 └── gcd


---

84.2 Resolver should depend on registry

Instead of:

self.kapowarr = KapowarrProvider(...)
self.comicvine = ComicVineProvider(...)
self.gcd = GCPProvider(...)

the resolver should request providers from the registry.


---

84.3 Provider priority should be configuration

Example:

providers:
  priority:
    - kapowarr
    - comicvine
    - gcd

This allows the project to evolve without rewriting resolver logic.


---

PHASE 85 — Job/Queue State Consolidation

Currently there are several pieces involved in processing state:

ProcessingQueue
CacheManager
tracker
JobStore
watcher

These should have clearly defined responsibilities.


---

85.1 JobStore becomes authoritative for processing state

Use:

DISCOVERED
QUEUED
PROCESSING
COMPLETED
FAILED
RETRYING
REVIEW


---

85.2 Hash tracker becomes identity/idempotency data

It should answer:

Has this exact archive state already been processed?

It should not become a second job system.


---

85.3 ProcessingQueue becomes execution only

The queue should:

claim job
 ↓
execute
 ↓
report result
 ↓
release/complete job

It should not maintain a competing permanent state model.


---

PHASE 86 — Watcher Reliability

86.1 Add file stability detection

Current flow:

filesystem event
 ↓
process

Change to:

filesystem event
 ↓
wait
 ↓
check size/mtime
 ↓
wait
 ↓
check again
 ↓
unchanged?
 ↓
enqueue

For example:

stability_window = 1–3 seconds

Make it configurable.


---

86.2 Debounce rapid events

Multiple events for the same file should collapse into one pending operation.

Batman.cbz
  create
  modify
  modify
  modify
       ↓
    ONE JOB


---

86.3 Handle rename events

Explicitly support:

on_created
on_modified
on_moved
on_deleted

For moved files:

old path → new path

should be handled safely.


---

86.4 Watcher restart test

Verify:

application stops
 ↓
library unchanged
 ↓
application starts
 ↓
existing processed archive
 ↓
ZERO duplicate processing

The current test already covers part of this; retain it and add the real watcher lifecycle version.


---

PHASE 87 — Dry-Run Architecture

The current dry-run implementation is good enough functionally, but strengthen the architecture.


---

87.1 Separate planning from execution

Create:

Resolution
Planning
Execution

Pipeline:

Archive
 ↓
Parse
 ↓
Resolve
 ↓
Plan
 ↓
Execute

The planner returns:

ProcessingPlan(
    action="UPDATE",
    fields=[...],
    provider="Kapowarr",
    confidence=...
)


---

87.2 Dry-run executes only planning

Dry-run:

Archive
 ↓
Parse
 ↓
Resolve
 ↓
Plan
 ↓
DISPLAY

Normal run:

Archive
 ↓
Parse
 ↓
Resolve
 ↓
Plan
 ↓
Write
 ↓
Verify
 ↓
Track

This removes the need to continually patch every future writer.


---

PHASE 88 — Library Configuration

Remove hard-coded environment-specific paths from core logic.

Instead of relying on locations such as:

~/Downloads
~/Desktop
~/Comics
/mnt
/media/m3tal

provide:

library:
  roots:
    - /mnt/comics


---

Requirements

multiple roots supported

recursive search supported

configurable

no assumptions about username

no assumptions about /mnt

no assumptions about your current server



---

PHASE 89 — API Input Validation

Audit every API endpoint.

For each endpoint define:

input
validation
allowed values
failure status
side effects

Example:

/api/batch-preview

folder_path
 ├── required
 ├── must exist
 ├── must be directory
 └── must be inside configured library roots


---

Security boundary

Do not allow arbitrary filesystem access if the server is ever exposed outside localhost.


---

PHASE 90 — ComicVine Resilience

The current ComicVine scraper is necessarily tied to ComicVine HTML structure.

Add regression fixtures for:

Series

normal volume

volume with many pages

missing pagination

alternate title

renamed series

volume slug mismatch


Issues

#1

#01

#1.5

#1/2

#½

#0

annual

special

FCBD

preview

one-shot


Exclusions

Ensure these aren't incorrectly matched:

TPB
HC
GN
Omnibus
Compendium
Masterworks
Collection
Deluxe
Edition
Volume


---

PHASE 91 — Failure Injection Tests

This is important before release.

Simulate failures during:

provider request
provider parsing
cache read
cache write
archive read
archive write
archive verification
database write
watcher callback

Verify the system never leaves the archive in a corrupt or misleading state.


---

PHASE 92 — Production Observability

Add structured logging for every processing job.

Example:

JOB START
file=Batman #001.cbz

IDENTITY
series=Batman
issue=1
year=2016

RESOLUTION
provider=Kapowarr
fallback=false
confidence=96

ACTION
UPDATE ComicInfo.xml

WRITE
archive verified=true

RESULT
COMPLETED

For fallback:

RESOLUTION
Kapowarr=NOT_FOUND
ComicVine=SUCCESS
fallback=true

For failure:

RESOLUTION
ComicVine=RATE_LIMITED
retryable=true

Never log API keys.


---

PHASE 93 — Final Regression Suite

Before release, run:

python -m unittest discover tests -v

Then specifically:

python -m unittest discover tests -v

under Python 3.11 and 3.12.

Verify:

all tests pass
zero unexpected warnings
zero traceback


---

PHASE 94 — Real-World Canary Test

Before processing your full comic library, create a small test library:

test-library/
├── Batman #001.cbz
├── Batman #002.cbz
├── Superman #001.cbz
├── SomeComic.cbr
├── ExistingMetadata.cbz
└── AmbiguousComic.cbz

Test:

Case 1

Existing ComicInfo.

Expected:

No unnecessary provider request

Case 2

Kapowarr match.

Expected:

Kapowarr used
ComicVine not queried

Case 3

Kapowarr unavailable.

Expected:

ComicVine fallback

Case 4

No provider match.

Expected:

REVIEW
archive unchanged

Case 5

CBR.

Expected:

CBR → CBZ
ComicInfo embedded
optional CBR deletion

Case 6

Watcher detects new file.

Expected:

ONE job
ONE processing cycle

Case 7

Restart.

Expected:

ZERO duplicate processing


---

PHASE 95 — Release Gate

Do not call the project complete until every item below is true.

Security

[ ] API keys never returned by API

[ ] API keys never logged

[ ] CORS restricted

[ ] localhost is safe default

[ ] filesystem paths validated

[ ] remote access is explicit


Configuration

[ ] startup validation enforced

[ ] invalid values produce clear errors

[ ] precedence tested

[ ] warnings separated from fatal errors


Resolution

[ ] existing ComicInfo checked first

[ ] cache checked before network

[ ] Kapowarr preferred

[ ] ComicVine used only when needed

[ ] GCD used as fallback

[ ] resolution reason recorded

[ ] provider errors preserved


Providers

[ ] provider registry implemented

[ ] resolver no longer hard-codes provider implementations

[ ] retry policy standardized

[ ] rate limiting handled correctly

[ ] authentication failures handled correctly


Automation

[ ] queue/job state unified

[ ] watcher debounced

[ ] file stability checked

[ ] restart safe

[ ] duplicate events safe

[ ] provider failures bounded


Dry-run

[ ] no archive modification

[ ] no persistent DB mutation

[ ] no destructive operations

[ ] planning and execution separated


Archive

[ ] CBZ atomic writing verified

[ ] archive verification passing

[ ] metadata preservation passing

[ ] CBR → CBZ workflow passing

[ ] CBR deletion behavior passing


Testing

[ ] full suite passes

[ ] Python 3.11 passes

[ ] Python 3.12 passes

[ ] security tests pass

[ ] provider failure tests pass

[ ] watcher lifecycle tests pass

[ ] real-library canary passes



---

Recommended implementation order

Don't give the AI agent all of this as one giant "fix everything" instruction. Do it in controlled milestones:

80  Security
 ↓
81  Configuration
 ↓
82  Provider Resolution
 ↓
83  Provider Errors
 ↓
84  Provider Registry
 ↓
85  Job/Queue State
 ↓
86  Watcher Reliability
 ↓
87  Dry-Run Architecture
 ↓
88  Library Configuration
 ↓
89  API Validation
 ↓
90  ComicVine Resilience
 ↓
91  Failure Injection
 ↓
92  Observability
 ↓
93  Regression
 ↓
94  Canary
 ↓
95  Release Gate

Most important change

If you're handing this to an AI coding agent, Phase 82 should be treated as the core functional requirement:

> Do not query ComicVine/GCD when the existing ComicInfo, cache, or Kapowarr can resolve the comic.



That directly matches the design you've been building toward and prevents the generator from wasting ComicVine requests on comics Kapowarr already knows about.

CBR conversion should remain in the implementation and tests, but should not be treated as an outstanding architectural problem.