"""
observability/retry.py — Phase 36

Provider retry policy with exponential backoff and retryable error classification.

Retry:
  - HTTP 429 (Too Many Requests)
  - HTTP 502, 503, 504 (temporary 5xx)
  - Timeout (requests.Timeout, socket.timeout)
  - Connection reset / network errors

Never retry:
  - HTTP 404 (Not Found)
  - HTTP 401, 403 (authentication failure)
  - Invalid / malformed response (parse failure)
  - Any non-retryable application error

Uses exponential backoff with jitter:
  delay = min(base * 2**attempt + jitter, max_delay)
"""
import logging
import random
import time
from functools import wraps
from typing import Callable, Optional, Set, Tuple, Type

import urllib.error

_logger = logging.getLogger("comicinfo.retry")

# --- Error classification ------------------------------------------------ #

# HTTP status codes that are safe to retry
RETRYABLE_HTTP_CODES: Set[int] = {429, 500, 502, 503, 504}

# HTTP status codes that must never be retried
NON_RETRYABLE_HTTP_CODES: Set[int] = {400, 401, 403, 404, 422}


# --- Provider Result States --- #
PROVIDER_STATE_FOUND = "FOUND"
PROVIDER_STATE_NOT_FOUND = "NOT_FOUND"
PROVIDER_STATE_OFFLINE = "OFFLINE"
PROVIDER_STATE_TIMEOUT = "TIMEOUT"
PROVIDER_STATE_RATE_LIMITED = "RATE_LIMITED"
PROVIDER_STATE_AUTH_FAILED = "AUTH_FAILED"
PROVIDER_STATE_SERVER_ERROR = "SERVER_ERROR"
PROVIDER_STATE_PARSE_ERROR = "PARSE_ERROR"
PROVIDER_STATE_INVALID_RESPONSE = "INVALID_RESPONSE"


class RetryableError(Exception):
    """Raised to signal that an operation should be retried."""


class NonRetryableError(Exception):
    """Raised to signal that an operation must NOT be retried."""


class ProviderUnavailable(RetryableError):
    """Raised when a provider is temporarily unreachable or returns 5xx."""


class ProviderTimeout(RetryableError):
    """Raised when a provider request times out."""


class ProviderRateLimited(RetryableError):
    """Raised when a provider rate limit (HTTP 429) is exceeded."""


class ProviderNotFound(NonRetryableError):
    """Raised when a provider returns HTTP 404 Not Found."""


class ProviderAuthError(NonRetryableError):
    """Raised when provider authentication/authorization fails (HTTP 401, 403)."""


class ProviderParseError(NonRetryableError):
    """Raised when a provider response fails to parse or returns malformed data."""


class ProviderInvalidResponse(NonRetryableError):
    """Raised when a provider returns an invalid response payload."""


def sanitize_log_url(url: str) -> str:
    """
    Strips sensitive credentials (api_key, key, token, secret, password) from a URL for safe logging.
    """
    if not url:
        return ""
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url)
        if not parsed.query:
            return url
        query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        sanitized_params = []
        sensitive_keys = {"api_key", "apikey", "key", "token", "secret", "password", "auth"}
        for k, v in query_params:
            if k.lower() in sensitive_keys:
                sanitized_params.append((k, "[REDACTED]"))
            else:
                sanitized_params.append((k, v))
        new_query = urllib.parse.urlencode(sanitized_params)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))
    except Exception:
        import re
        return re.sub(r"(api_?key|token|secret|password)=[^&]+", r"\1=[REDACTED]", url, flags=re.IGNORECASE)


def classify_http_error(status_code: int, url: str = "") -> None:
    """
    Raises typed RetryableError or NonRetryableError subclass based on HTTP status code.
    Call from provider code after receiving a non-2xx response.
    """
    safe_url = sanitize_log_url(url)
    if status_code == 429:
        raise ProviderRateLimited(f"HTTP 429 from {safe_url!r} — rate limited")
    if status_code in (500, 502, 503, 504):
        raise ProviderUnavailable(f"HTTP {status_code} from {safe_url!r} — server error")
    if status_code == 404:
        raise ProviderNotFound(f"HTTP 404 from {safe_url!r} — not found")
    if status_code in (401, 403):
        raise ProviderAuthError(f"HTTP {status_code} from {safe_url!r} — auth error")

    if status_code in RETRYABLE_HTTP_CODES:
        raise RetryableError(f"HTTP {status_code} from {safe_url!r} — retryable")
    if status_code in NON_RETRYABLE_HTTP_CODES:
        raise NonRetryableError(f"HTTP {status_code} from {safe_url!r} — not retryable")


def classify_provider_error(
    exc: BaseException,
    provider: str = "",
    operation: str = "",
    query_or_url: str = "",
    attempt: int = 1,
    correlation_id: str = ""
) -> Tuple[str, bool]:
    """
    Classifies an exception into (provider_state, is_retryable) and logs structured telemetry without credentials.
    """
    safe_query = sanitize_log_url(query_or_url)
    retryable = is_retryable_exception(exc)

    if isinstance(exc, ProviderRateLimited):
        state = PROVIDER_STATE_RATE_LIMITED
    elif isinstance(exc, ProviderTimeout) or isinstance(exc, (TimeoutError,)):
        state = PROVIDER_STATE_TIMEOUT
    elif isinstance(exc, (ProviderUnavailable,)):
        state = PROVIDER_STATE_SERVER_ERROR
    elif isinstance(exc, (ProviderNotFound,)):
        state = PROVIDER_STATE_NOT_FOUND
    elif isinstance(exc, (ProviderAuthError,)):
        state = PROVIDER_STATE_AUTH_FAILED
    elif isinstance(exc, (ProviderParseError,)):
        state = PROVIDER_STATE_PARSE_ERROR
    elif isinstance(exc, (ProviderInvalidResponse,)):
        state = PROVIDER_STATE_INVALID_RESPONSE
    elif retryable:
        state = PROVIDER_STATE_SERVER_ERROR
    else:
        state = PROVIDER_STATE_PARSE_ERROR

    _logger.warning(
        "PROVIDER_ERROR provider=%s operation=%s query=%s state=%s retryable=%s attempt=%d correlation_id=%s error=%r",
        provider, operation, safe_query, state, retryable, attempt, correlation_id, exc
    )
    return state, retryable


def is_retryable_exception(exc: BaseException) -> bool:
    """
    Returns True if the exception is safe to retry.
    Covers: network timeouts, connection resets, temporary HTTP errors.
    """
    import socket

    # Our own markers
    if isinstance(exc, RetryableError):
        return True
    if isinstance(exc, NonRetryableError):
        return False

    # urllib errors
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_HTTP_CODES

    # Network / timeout
    if isinstance(exc, (TimeoutError, ConnectionResetError, ConnectionRefusedError,
                        socket.timeout, OSError)):
        return True

    # requests library (optional dependency — guard import)
    try:
        import requests
        if isinstance(exc, requests.Timeout):
            return True
        if isinstance(exc, requests.ConnectionError):
            return True
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            return exc.response.status_code in RETRYABLE_HTTP_CODES
    except ImportError:
        pass

    return False


# --- Retry decorator ----------------------------------------------------- #

def with_retry(
    max_attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: float = 0.5,
    provider: str = ""
):
    """
    Decorator that retries a function with exponential backoff.

    Retryable exceptions are retried up to `max_attempts` times.
    NonRetryableError and all unclassified exceptions propagate immediately.

    Args:
        max_attempts: Total attempts (including first try).
        base_delay:   Initial backoff in seconds.
        max_delay:    Maximum backoff cap in seconds.
        jitter:       Random fraction added to each delay (reduces thundering herd).
        provider:     Provider name for log context.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return fn(*args, **kwargs)
                except NonRetryableError:
                    raise
                except Exception as exc:
                    attempt += 1
                    if not is_retryable_exception(exc) or attempt >= max_attempts:
                        if is_retryable_exception(exc):
                            _logger.warning(
                                f"RETRY_EXHAUSTED provider={provider or fn.__name__} "
                                f"attempt={attempt}/{max_attempts} error={exc!r}"
                            )
                        raise

                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    delay += random.uniform(0, jitter)
                    _logger.warning(
                        f"RETRY provider={provider or fn.__name__} "
                        f"attempt={attempt}/{max_attempts} "
                        f"error={exc!r} "
                        f"backoff={delay:.2f}s"
                    )
                    time.sleep(delay)
        return wrapper
    return decorator


def retry_call(
    fn: Callable,
    *args,
    max_attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    provider: str = "",
    **kwargs
):
    """
    Imperative retry helper for call sites that can't use the decorator.
    Useful for lambdas or one-off dynamic calls.
    """
    decorated = with_retry(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        provider=provider
    )(fn)
    return decorated(*args, **kwargs)
