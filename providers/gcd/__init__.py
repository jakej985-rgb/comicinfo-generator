from providers.gcd.client import GCDClient
from providers.gcd.parser import parse_gcp_text_refined, parse_gcd_soup, clean_creator_name
from providers.gcd.models import GCDVolume, GCDIssue
from providers.gcd.provider import GCPProvider

def scrape_gcp_issue(url_or_text: str, use_cache: bool = True):
    return GCPProvider()._scrape_issue(url_or_text, use_cache=use_cache)

def scrape_gcp_volume(volume_url: str):
    return GCPProvider()._scrape_volume(volume_url)

def search_gcp(query: str, search_type: str = "all"):
    return GCPProvider()._search_gcp(query, search_type=search_type)

__all__ = [
    "GCDClient", "GCDVolume", "GCDIssue", "GCPProvider",
    "parse_gcp_text_refined", "parse_gcd_soup", "clean_creator_name",
    "scrape_gcp_issue", "scrape_gcp_volume", "search_gcp"
]
