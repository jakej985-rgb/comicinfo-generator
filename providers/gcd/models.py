from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class GCDIssue:
    id: str = ""
    number: str = ""
    title: str = ""
    series_name: str = ""
    publisher: str = ""
    year: int = 0
    month: int = 0
    day: int = 0
    url: str = ""
    summary: str = ""
    writers: List[str] = field(default_factory=list)
    pencillers: List[str] = field(default_factory=list)
    inkers: List[str] = field(default_factory=list)
    colorists: List[str] = field(default_factory=list)
    letterers: List[str] = field(default_factory=list)
    characters: List[str] = field(default_factory=list)


@dataclass
class GCDVolume:
    id: str = ""
    name: str = ""
    year: int = 0
    publisher: str = ""
    url: str = ""
    issue_count: int = 0
    issues: List[GCDIssue] = field(default_factory=list)
