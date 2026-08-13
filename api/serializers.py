"""
api/serializers.py — Phase 32

Pure data-conversion layer between Comic domain objects and JSON-serialisable dicts.
No business logic or HTTP dependencies.
"""
from models.comic import Comic


def comic_to_dict(c: Comic) -> dict:
    return {
        "title": c.title,
        "series": c.series,
        "number": c.number,
        "volume": c.volume,
        "count": c.count,
        "summary": c.summary,
        "notes": c.notes,
        "year": c.year,
        "month": c.month,
        "day": c.day,
        "publisher": c.publisher,
        "genre": c.genre,
        "web": c.web,
        "language": c.language,
        "format": c.format,
        "writers": c.writers,
        "pencillers": c.pencillers,
        "inkers": c.inkers,
        "colorists": c.colorists,
        "letterers": c.letterers,
        "cover_artists": c.cover_artists,
        "characters": c.characters,
        "teams": c.teams,
        "story_arcs": c.story_arcs,
        "story_arc_numbers": c.story_arc_numbers,
    }


def dict_to_comic(d: dict) -> Comic:
    c = Comic()
    c.title = str(d.get("title", ""))
    c.series = str(d.get("series", ""))
    c.number = str(d.get("number", ""))
    c.volume = str(d.get("volume", ""))
    c.count = int(d.get("count") or 1)
    c.summary = str(d.get("summary", ""))
    c.notes = str(d.get("notes", ""))
    c.year = int(d.get("year") or 0)
    c.month = int(d.get("month") or 0)
    c.day = int(d.get("day") or 0)
    c.publisher = str(d.get("publisher", ""))
    c.genre = str(d.get("genre", ""))
    c.web = str(d.get("web", ""))
    c.language = str(d.get("language", "en"))
    c.format = str(d.get("format", "Comic"))

    def to_list(val):
        if isinstance(val, list):
            return [str(v).strip() for v in val if str(v).strip()]
        if isinstance(val, str) and val.strip():
            return [v.strip() for v in val.split(",") if v.strip()]
        return []

    c.writers = to_list(d.get("writers"))
    c.pencillers = to_list(d.get("pencillers"))
    c.inkers = to_list(d.get("inkers"))
    c.colorists = to_list(d.get("colorists"))
    c.letterers = to_list(d.get("letterers"))
    c.cover_artists = to_list(d.get("cover_artists"))
    c.characters = to_list(d.get("characters"))
    c.teams = to_list(d.get("teams"))
    c.story_arcs = to_list(d.get("story_arcs"))
    c.story_arc_numbers = to_list(d.get("story_arc_numbers"))
    c.provider_name = str(d.get("provider_name") or d.get("provider") or "")
    return c
