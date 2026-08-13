"""
app.py — Phase 32 refactored shim.

Business logic has been split into:
  api/      — HTTP layer (server.py, handlers.py, serializers.py)
  services/ — domain services (metadata.py, processing.py, search.py)

This module re-exports symbols so existing callers continue to work.
"""
# Re-export run_server from new location
from api.server import run_server                           # noqa: F401

# Re-export serializers for any code that still uses app.comic_to_dict etc.
from api.serializers import comic_to_dict, dict_to_comic   # noqa: F401

# Re-export service helpers
from services.metadata import (                             # noqa: F401
    detect_provider, scrape_single_url, scrape_any_volume,
    fetch_and_merge_urls, search_all_providers
)
from services.search import extract_issue_num_from_filename # noqa: F401
from services.processing import (                           # noqa: F401
    find_file_path, open_native_file_picker, open_native_folder_picker,
    embed_and_track
)
