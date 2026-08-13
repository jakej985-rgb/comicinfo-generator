from dataclasses import dataclass, field
from typing import Optional, Dict
from models.identity import ComicIdentity

@dataclass
class Comic:
    title: str = ""
    series: str = ""
    number: str = ""
    volume: str = ""
    count: Optional[int] = None
    summary: str = ""
    notes: str = ""
    year: int = 0
    month: int = 0
    day: int = 0
    publisher: str = ""
    genre: str = ""
    web: str = ""
    language: str = "en"
    format: str = "Comic"
    writers: list[str] = field(default_factory=list)
    pencillers: list[str] = field(default_factory=list)
    inkers: list[str] = field(default_factory=list)
    colorists: list[str] = field(default_factory=list)
    letterers: list[str] = field(default_factory=list)
    cover_artists: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)
    story_arcs: list[str] = field(default_factory=list)
    story_arc_numbers: list[str] = field(default_factory=list)
    provider_name: str = ""
    provider_id: str = ""
    sha256: str = ""
    identity: Optional[ComicIdentity] = None
    extra_fields: Dict[str, str] = field(default_factory=dict)
    extra_nodes: list = field(default_factory=list)
    metadata_complete: bool = True
    source: str = ""

def merge_comics(comics: list[Comic]) -> Comic:
    """
    Merges multiple single issue Comic objects into one unified Comic object
    for collected editions, TPBs, or omnibuses.
    """
    if not comics:
        return Comic()
    if len(comics) == 1:
        return comics[0]

    merged = Comic()
    merged.series = comics[0].series
    merged.publisher = comics[0].publisher
    merged.volume = comics[0].volume
    merged.genre = comics[0].genre
    merged.language = comics[0].language
    merged.format = "Trade Paperback"
    merged.count = len(comics)

    # Calculate issue range e.g. "1-6"
    numbers = [c.number for c in comics if c.number]
    if numbers:
        if all(n.isdigit() for n in numbers):
            nums_sorted = sorted([int(n) for n in numbers])
            merged.number = f"{nums_sorted[0]}-{nums_sorted[-1]}" if len(nums_sorted) > 1 else str(nums_sorted[0])
        else:
            merged.number = ", ".join(numbers)

    # Title e.g. "Series Name #1-6"
    titles = [c.title for c in comics if c.title]
    if titles:
        merged.title = f"{merged.series} #{merged.number}" if merged.series else " / ".join(titles)

    # Earliest release date
    dated_comics = [c for c in comics if c.year > 0]
    if dated_comics:
        dated_comics.sort(key=lambda c: (c.year, c.month or 1, c.day or 1))
        merged.year = dated_comics[0].year
        merged.month = dated_comics[0].month
        merged.day = dated_comics[0].day

    # Combine Web URLs
    webs = [c.web for c in comics if c.web]
    merged.web = ", ".join(webs)

    # Combine summaries with issue headers
    summaries = []
    for c in comics:
        if c.summary:
            label = f"Issue #{c.number}" if c.number else c.title
            summaries.append(f"--- {label} ---\n{c.summary}")
    merged.summary = "\n\n".join(summaries)

    # Merge and deduplicate lists while preserving order
    def merge_lists(attr):
        res = []
        for c in comics:
            for item in getattr(c, attr, []):
                if item and item not in res:
                    res.append(item)
        return res

    merged.writers = merge_lists("writers")
    merged.pencillers = merge_lists("pencillers")
    merged.inkers = merge_lists("inkers")
    merged.colorists = merge_lists("colorists")
    merged.letterers = merge_lists("letterers")
    merged.cover_artists = merge_lists("cover_artists")
    merged.characters = merge_lists("characters")
    merged.teams = merge_lists("teams")
    merged.story_arcs = merge_lists("story_arcs")
    merged.story_arc_numbers = merge_lists("story_arc_numbers")

    return merged
