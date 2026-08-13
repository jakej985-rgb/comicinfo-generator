# Provider Contract — ComicInfo Generator

## Purpose

Defines the interface contract that every provider must satisfy.  
This describes the **actual implemented** provider interface, not a wishlist.

---

## Responsibilities

Providers are responsible **only** for:
1. Accepting a search query or URL
2. Returning structured data (`Comic` objects or raw dicts)
3. Raising typed exceptions on failure

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
| `search_issue` | `list[dict]` with `url`, `title` keys |
| `search_series` | `list[dict]` with `id`, `title`, `url` keys |
| `lookup_issue` | `Comic` dataclass or `None` |
| `lookup_volume` | `(series_name: str, issue_map: dict, issues_list: list)` |

---

## Registered Providers

| Provider | Module | Type |
|---|---|---|
| Kapowarr | `providers/kapowarr.py` | REST API (local) |
| Comic Vine | `providers/comicvine.py` | HTML scraper |
| Grand Comics Database | `providers/gcp.py` | HTML scraper |
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

1. A provider must return `None` (not raise) when it genuinely cannot find a result.
2. A provider must raise a typed exception (`RetryableError`, `NonRetryableError`) on failure — never silently swallow errors.
3. Provider results are **never** embedded without passing through `MetadataResolver`.
4. Provider HTML parsing failures are `NonRetryableError` — never retried.

---

## Failure Modes

| Failure | Expected Behaviour |
|---|---|
| HTTP 429 | Raise `RetryableError` → retried with backoff |
| HTTP 404 | Raise `NonRetryableError` → not retried |
| Cloudflare block | Raise `NonRetryableError` → flagged for manual review |
| Malformed HTML | Raise `NonRetryableError` → not retried |
| Timeout | Raise `RetryableError` → retried up to `max_attempts` |
| Connection reset | Raise `RetryableError` → retried with backoff |

---

## Testing Requirements

- All provider tests must use mocked HTTP responses — no live network.
- Fixture HTML files live in `tests/fixtures/comicvine/` and `tests/fixtures/gcp/`.
- Every provider must have at least one test covering: success, 404, timeout, Cloudflare block.

---

## Do-Not-Do Rules

- Do not call providers from `api/handlers.py` directly.
- Do not hardcode API keys in provider code — always read from `config.py`.
- Do not add Comic Vine-specific or GCD-specific fields to `Comic` or `ComicIdentity`.
- Do not suppress provider exceptions without logging them.
- Do not retry 404 responses.
