from providers.comicvine.client import ComicVineClient
from providers.comicvine.parser import (
    parse_html, parse_series, parse_issue_number, parse_title,
    parse_publisher, parse_release_date, parse_summary,
    parse_creators, parse_characters, parse_teams, parse_story_arcs
)
from providers.comicvine.models import ComicVineVolume, ComicVineIssue
from providers.comicvine.provider import ComicVineProvider

def scrape_issue(url: str, use_cache: bool = True):
    return ComicVineProvider()._scrape_issue(url, use_cache=use_cache)

def scrape_volume(volume_url: str, max_pages_limit: int = 50, use_cache: bool = True):
    return ComicVineProvider()._scrape_volume(volume_url, max_pages_limit=max_pages_limit, use_cache=use_cache)

def search_comicvine(query: str, search_type: str = "all", use_cache: bool = True):
    return ComicVineProvider()._search_comicvine(query, search_type=search_type, use_cache=use_cache)

__all__ = [
    "ComicVineClient", "ComicVineVolume", "ComicVineIssue", "ComicVineProvider",
    "parse_html", "parse_series", "parse_issue_number", "parse_title",
    "parse_publisher", "parse_release_date", "parse_summary", "parse_creators",
    "parse_characters", "parse_teams", "parse_story_arcs",
    "scrape_issue", "scrape_volume", "search_comicvine"
]
