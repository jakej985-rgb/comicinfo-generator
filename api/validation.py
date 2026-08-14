"""
api/validation.py — Phase 89: API Input Validation & Security Boundary

Enforces strict input validation and filesystem security boundaries for all API endpoints.
Requirements 89.1:
- Validates required inputs, types, and allowed values.
- Enforces filesystem boundaries (preventing directory traversal and unauthorized access outside library roots).
- Blocks sensitive OS system paths.
"""

import os
from typing import List, Optional, Tuple
from urllib.parse import urlparse


FORBIDDEN_SYSTEM_PREFIXES = (
    "/etc",
    "/root",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/var/run",
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/sbin",
)


class ValidationError(Exception):
    """Raised when an API request input fails validation."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def sanitize_and_resolve_path(raw_path: str) -> str:
    """
    Expands user home and resolves canonical realpath, eliminating symlink/traversal tricks.
    """
    if not raw_path or not isinstance(raw_path, str):
        raise ValidationError("Path must be a non-empty string.", 400)
    
    clean_path = raw_path.strip()
    if not clean_path:
        raise ValidationError("Path cannot be blank.", 400)

    expanded = os.path.expanduser(clean_path)
    return os.path.realpath(os.path.abspath(expanded))


def is_path_inside_root(target_path: str, root_path: str) -> bool:
    """Checks if target_path is strictly within root_path directory hierarchy."""
    real_target = os.path.realpath(os.path.abspath(os.path.expanduser(target_path)))
    real_root = os.path.realpath(os.path.abspath(os.path.expanduser(root_path)))
    try:
        common = os.path.commonpath([real_root, real_target])
        return common == real_root
    except ValueError:
        return False


def validate_filesystem_boundary(
    target_path: str,
    configured_roots: Optional[List[str]] = None,
    allow_empty_roots: bool = True
) -> str:
    """
    Phase 89.1: Validates that a file or folder path is within configured library roots
    and does not access forbidden OS system directories.
    """
    resolved = sanitize_and_resolve_path(target_path)

    # 1. System path traversal protection
    for prefix in FORBIDDEN_SYSTEM_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            raise ValidationError(f"Access to system directory '{prefix}' is forbidden.", 403)

    # 2. Configured library roots boundary check
    if configured_roots:
        valid_roots = [r for r in configured_roots if r and os.path.exists(os.path.expanduser(r))]
        if valid_roots:
            if not any(is_path_inside_root(resolved, root) for root in valid_roots):
                raise ValidationError(
                    f"Path '{target_path}' is outside configured library roots.", 403
                )
    elif not allow_empty_roots:
        raise ValidationError("No library roots configured.", 403)

    return resolved


def validate_folder_path(
    folder_path: str,
    configured_roots: Optional[List[str]] = None,
    must_exist: bool = True
) -> str:
    """Validates that folder_path exists, is a directory, and respects security boundaries."""
    resolved = validate_filesystem_boundary(folder_path, configured_roots=configured_roots)
    if must_exist:
        if not os.path.exists(resolved):
            raise ValidationError(f"Folder directory '{folder_path}' not found.", 404)
        if not os.path.isdir(resolved):
            raise ValidationError(f"Path '{folder_path}' is not a directory.", 400)
    return resolved


def validate_comic_file_path(
    file_path: str,
    configured_roots: Optional[List[str]] = None,
    allowed_extensions: Tuple[str, ...] = (".cbz", ".cbr"),
    must_exist: bool = True
) -> str:
    """Validates comic file extension, existence, and filesystem boundaries."""
    resolved = validate_filesystem_boundary(file_path, configured_roots=configured_roots)
    ext = os.path.splitext(resolved)[1].lower()
    if ext not in allowed_extensions:
        raise ValidationError(
            f"Invalid file format '{ext}'. Allowed formats: {', '.join(allowed_extensions)}", 400
        )
    if must_exist:
        if not os.path.exists(resolved):
            raise ValidationError(f"File '{file_path}' not found.", 404)
        if not os.path.isfile(resolved):
            raise ValidationError(f"Path '{file_path}' is not a regular file.", 400)
    return resolved


def validate_url(url: str, allowed_schemes: Tuple[str, ...] = ("http", "https")) -> str:
    """Validates that a URL is a valid HTTP/HTTPS URL."""
    if not url or not isinstance(url, str):
        raise ValidationError("URL must be a non-empty string.", 400)
    clean_url = url.strip()
    parsed = urlparse(clean_url)
    if not parsed.scheme or parsed.scheme.lower() not in allowed_schemes:
        raise ValidationError(
            f"Invalid URL scheme '{parsed.scheme}'. Allowed: {', '.join(allowed_schemes)}", 400
        )
    if not parsed.netloc:
        raise ValidationError("URL must include a valid host/domain name.", 400)
    return clean_url


def validate_search_query(query: str, max_length: int = 250) -> str:
    """Validates search query string length and presence."""
    if not query or not isinstance(query, str):
        raise ValidationError("Missing search query.", 400)
    clean = query.strip()
    if not clean:
        raise ValidationError("Search query cannot be blank.", 400)
    if len(clean) > max_length:
        raise ValidationError(f"Search query exceeds maximum length of {max_length} characters.", 400)
    return clean
