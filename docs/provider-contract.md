# Provider Contract — ComicInfo Generator

## Purpose

Defines the interface contract that every provider must satisfy.  
This describes the **actual implemented** provider interface, not a wishlist.

---

## Responsibilities

Providers are responsible **only** for:
1. Accepting a search query or URL
2. Returning structured data (`Comic` objects or raw dicts)
3. Raising typed exceptions on failure (`RetryableError`, `NonRetryableError`)
4. Participating in `ProviderOperationResult` state tracking

Providers must **never**:
- Write to archives
- Modify the `ComicIdentity` of an already-resolved candidate
- Make decisions about confidence or scoring
- Call other providers

---

## Inputs

| Method | Input |
|---|---|
| `search_issue(query: str)` | Filename or series+issue string |
| `search_series(query: str)` | Series title |
| `lookup_issue(url_or_id: str)` | Provider URL or ID |
| `lookup_volume(url: str)` | Volume/series URL |
| `test_connection() → bool` | No input — verifies provider is reachable |

---

## Outputs

| Method | Output |
|---|---|
| `search_issue` | `list[dict]` or `list[ComicIdentity]` |
| `search_series` | `list[dict]` with `id`, `title`, `url` keys |
| `lookup_issue` | `Comic` dataclass or `None` |
| `lookup_volume` | `(series_name: str, issue_map: dict, issues_list: list)` |

---

## Provider Operation Taxonomy & State Propagation

Every provider operation is classified and recorded in `ProviderOperationResult`:

| Status State | Description | Retryable |
|---|---|---|
| `SUCCESS` | Candidates or metadata successfully retrieved | N/A |
| `NOT_FOUND` | Query returned zero results (valid negative match) | False |
| `SERVER_ERROR` | Provider HTTP 5xx or server crash | True |
| `RATE_LIMITED` | HTTP 429 Too Many Requests | True |
| `TIMEOUT` | Socket/connection timeout | True |
| `AUTH_FAILED` | HTTP 401/403 Invalid API key or credentials | False |
| `OFFLINE` | `test_connection()` failed (e.g. Kapowarr unreachable) | True |

---

## Registered Providers

| Provider | Module | Type |
|---|---|---|
| Kapowarr | `providers/kapowarr/provider.py` | REST API (local) |
| Comic Vine | `providers/comicvine/provider.py` | HTML scraper / API |
| Grand Comics Database | `providers/gcd/provider.py` | HTML scraper |
| Story Arc | `providers/story_arc.py` | HTML scraper + custom parser |

---

## Rate Limiting (Phase 35)

All providers route through `observability/rate_limiter.py` before making HTTP requests.

| Provider | Default Limit |
|---|---|
| ComicVine | 200 req / 15 min (burst 10) |
| GCD | 60 req / min (burst 5) |
| Kapowarr | Unlimited (local service) |

Acquire a token before every HTTP call:
```python
from observability import rate_limiter
rate_limiter.acquire("ComicVine")
```

---

## Retry Policy (Phase 36)

Use `@with_retry` from `observability/retry.py` on any provider HTTP call.

**Retryable errors**: `TimeoutError`, `ConnectionResetError`, HTTP 429, HTTP 502/503/504  
**Non-retryable errors**: HTTP 404, HTTP 401/403, parse failure, `NonRetryableError`

```python
from observability import with_retry

@with_retry(max_attempts=4, base_delay=1.0, provider="ComicVine")
def fetch_issue(url: str) -> Comic:
    ...
```

---

## Invariants

1. A provider returning zero results is a valid `NOT_FOUND` state, distinct from provider server failure.
2. A provider must raise a typed exception on genuine failure — never silently swallow errors.
3. Provider results are **never** embedded without passing through `MetadataResolver`.
4. Provider HTML parsing failures are `NonRetryableError` — never retried.
5. All provider tests use mocked network calls — no live HTTP requests during tests.
