from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class KapowarrIssue:
    id: str = ""
    issue_number: str = ""
    title: str = ""
    summary: str = ""
    release_date: str = ""
    comicvine_id: str = ""
    web_url: str = ""

    @classmethod
    def from_dict(cls, data: dict, base_url: str = "") -> "KapowarrIssue":
        iss_id = str(data.get("id", ""))
        return cls(
            id=iss_id,
            issue_number=str(data.get("issue_number") or data.get("number", "")).strip().lstrip("#"),
            title=data.get("name") or data.get("title") or "",
            summary=data.get("summary") or data.get("overview") or "",
            release_date=str(data.get("release_date") or data.get("date") or ""),
            comicvine_id=str(data.get("comicvine_id", "") or data.get("cv_id", "")),
            web_url=f"{base_url}/issue/{iss_id}" if base_url and iss_id else ""
        )


@dataclass
class KapowarrVolume:
    id: str = ""
    name: str = ""
    year: int = 0
    publisher: str = ""
    comicvine_id: str = ""
    folder_path: str = ""
    issue_count: int = 0
    issues: List[KapowarrIssue] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict, base_url: str = "") -> "KapowarrVolume":
        vol_id = str(data.get("id", ""))
        raw_year = str(data.get("year", ""))
        year_val = int(raw_year) if raw_year.isdigit() else 0

        issues = [
            KapowarrIssue.from_dict(i, base_url=base_url)
            for i in data.get("issues", [])
            if isinstance(i, dict)
        ]

        return cls(
            id=vol_id,
            name=data.get("name") or data.get("title") or "",
            year=year_val,
            publisher=data.get("publisher", ""),
            comicvine_id=str(data.get("comicvine_id", "") or data.get("cv_id", "")),
            folder_path=data.get("folder") or data.get("path") or "",
            issue_count=int(data.get("issue_count", 0)),
            issues=issues
        )
