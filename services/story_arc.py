"""
services/story_arc.py — Phase 49

Encapsulates all Story Arc search, scraping, and device-side operations behind service-level abstractions.
API handlers must call these functions instead of importing from providers.story_arc directly.
"""
from typing import List, Dict, Any, Optional
from providers.story_arc import (
    search_story_arcs as _search_story_arcs,
    get_story_arc_details as _get_story_arc_details,
    fix_story_arcs_on_device as _fix_story_arcs_on_device,
    clean_duplicate_story_arcs_on_device as _clean_duplicate_story_arcs_on_device,
    rename_story_arc_on_device as _rename_story_arc_on_device,
    update_issue_arc_number_on_device as _update_issue_arc_number_on_device,
    parse_custom_chronological_reading_order as _parse_custom_chronological_reading_order,
    MARVEL_ZOMBIES_PRESET_TEXT
)


def search_story_arcs(query: str, api_key: str = "") -> List[Dict[str, Any]]:
    """Searches for story arcs across Comic Vine / web providers."""
    return _search_story_arcs(query, api_key=api_key)


def get_story_arc_details(arc_url: str) -> Dict[str, Any]:
    """Scrapes/retrieves detailed issue listing and reading order for a story arc."""
    return _get_story_arc_details(arc_url)


def fix_story_arcs_on_device(issues: List[Dict[str, Any]], story_arc_name: str = "") -> Dict[str, Any]:
    """Updates story arc tags and numbering across device comic files."""
    return _fix_story_arcs_on_device(issues, story_arc_name=story_arc_name)


def clean_duplicate_story_arcs_on_device(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cleans up duplicate story arc tags on device comic files."""
    return _clean_duplicate_story_arcs_on_device(issues)


def rename_story_arc_on_device(issues: List[Dict[str, Any]], old_name: str, new_name: str) -> Dict[str, Any]:
    """Renames an existing story arc tag on device comic files."""
    return _rename_story_arc_on_device(issues, old_name=old_name, new_name=new_name)


def update_issue_arc_number_on_device(file_path: str, story_arc_name: str, new_arc_number: str) -> Dict[str, Any]:
    """Updates a single issue's reading order number for a story arc."""
    return _update_issue_arc_number_on_device(file_path, story_arc_name=story_arc_name, new_arc_number=new_arc_number)


def parse_custom_chronological_reading_order(text: str) -> List[Dict[str, Any]]:
    """Parses text reading order into structured issue entries."""
    return _parse_custom_chronological_reading_order(text)
