"""
services/kapowarr.py — Phase 49

Encapsulates all Kapowarr provider interactions behind service-level abstractions.
API handlers must call these functions instead of importing KapowarrProvider directly.
"""
from typing import List, Dict, Any, Optional
from config import Config
from providers.kapowarr import KapowarrProvider


def get_kapowarr_library(cfg: Config) -> List[Dict[str, Any]]:
    """Fetches all volumes in the Kapowarr library."""
    kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
    return kap.get_volumes()


def get_kapowarr_library_status(cfg: Config) -> Dict[str, Any]:
    """Fetches library items and online status."""
    kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
    items = kap.get_library_status(prefer_kapowarr=cfg.automation.prefer_kapowarr)
    return {"online": kap.test_connection(), "items": items}


def get_kapowarr_volume_issues(cfg: Config, volume_id: int) -> List[Dict[str, Any]]:
    """Fetches all issues for a specific Kapowarr volume."""
    kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
    return kap.get_volume_issues(volume_id)


def test_kapowarr_connection(url: str, api_key: str) -> bool:
    """Tests connection to a Kapowarr server instance."""
    kap = KapowarrProvider(url=url, api_key=api_key)
    return kap.test_connection()


def request_kapowarr_issue_download(
    cfg: Config,
    issue_id: str = "",
    cv_volume_id: str = "",
    issue_title: str = ""
) -> Dict[str, Any]:
    """Requests issue download via Kapowarr."""
    kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
    return kap.request_issue_download(
        issue_id=issue_id,
        cv_volume_id=cv_volume_id,
        issue_title=issue_title
    )
