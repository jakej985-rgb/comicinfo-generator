"""
Phase 28 & 29: Real field-level Metadata Merge Policy.

Phase 28: Preserve issue-level metadata (identities, summaries, creators,
          characters, story arcs, source URLs, provider IDs) when merging.

Phase 29: Every field has an explicit source priority chain.
          No single global provider priority for all fields.

Field priorities:
  title      : explicit collection override > provider > filename
  publisher  : Kapowarr identity > provider > filename
  year       : collection publication year > earliest issue year
  summary    : collection summary > per-issue summaries (with issue headers)
  characters : union + deduplicate (order-preserving)
  creators   : union + deduplicate per role
  story_arcs : union + deduplicate
  web        : collection web > comma-joined issue URLs
  provider_id: collection-level ID > first issue ID
"""
from dataclasses import dataclass, field
from typing import List, Optional
from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.issue_order import sort_issues, parse_issue_order


@dataclass
class MergeSource:
    """Tracks the winning source for a merged field."""
    field_name: str
    value: object
    source: str   # e.g. "collection_override", "Kapowarr", "ComicVine", "filename", "issue_union"


@dataclass
class MergeResult:
    """Result of a field-level policy merge."""
    comic: Comic
    provenance: List[MergeSource] = field(default_factory=list)  # audit trail per field


def _dedup_list(items: List[str]) -> List[str]:
    """Deduplicates a list while preserving insertion order."""
    seen = set()
    result = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _union_lists(*lists: List[str]) -> List[str]:
    """Union of multiple lists with deduplication."""
    combined = []
    for lst in lists:
        combined.extend(lst)
    return _dedup_list(combined)


def merge_with_policy(
    issues: List[Comic],
    collection_override: Optional[Comic] = None,
    kapowarr_identity: Optional[ComicIdentity] = None
) -> MergeResult:
    """
    Phase 28 & 29: Merges a list of issue Comic objects into a collected edition
    using explicit field-level priority rules.

    Args:
        issues:               Ordered list of individual issue Comic objects.
        collection_override:  Optional collection-level metadata that takes
                              highest priority for scalar fields.
        kapowarr_identity:    Optional Kapowarr volume identity (highest
                              publisher authority).
    Returns:
        MergeResult with merged Comic and per-field provenance audit trail.
    """
    if not issues:
        return MergeResult(comic=Comic())

    provenance: List[MergeSource] = []
    merged = Comic()
    merged.format = "Trade Paperback"
    merged.count = len(issues)

    # --- SERIES (from first issue, non-overridable by design) ---
    merged.series = issues[0].series or ""
    provenance.append(MergeSource("series", merged.series, "first_issue"))

    # --- LANGUAGE (from first issue) ---
    merged.language = issues[0].language or "en"

    # --- GENRE (from first issue) ---
    merged.genre = issues[0].genre or ""

    # --- TITLE: explicit collection override > provider > filename ---
    if collection_override and collection_override.title:
        merged.title = collection_override.title
        provenance.append(MergeSource("title", merged.title, "collection_override"))
    else:
        # Build a range title from sorted issue numbers
        numbers = [c.number for c in issues if c.number]
        sorted_nums = sort_issues(numbers) if numbers else []
        if sorted_nums:
            range_str = f"{sorted_nums[0]}-{sorted_nums[-1]}" if len(sorted_nums) > 1 else sorted_nums[0]
            merged.title = f"{merged.series} #{range_str}" if merged.series else range_str
            merged.number = range_str
        provenance.append(MergeSource("title", merged.title, "generated_range"))

    # --- PUBLISHER: Kapowarr identity > provider > filename ---
    if kapowarr_identity and kapowarr_identity.publisher:
        merged.publisher = kapowarr_identity.publisher
        provenance.append(MergeSource("publisher", merged.publisher, "Kapowarr"))
    elif collection_override and collection_override.publisher:
        merged.publisher = collection_override.publisher
        provenance.append(MergeSource("publisher", merged.publisher, "collection_override"))
    elif issues[0].publisher:
        merged.publisher = issues[0].publisher
        provenance.append(MergeSource("publisher", merged.publisher, "first_issue_provider"))

    # --- YEAR: collection publication year > earliest issue year ---
    if collection_override and collection_override.year and collection_override.year > 0:
        merged.year = collection_override.year
        merged.month = collection_override.month
        merged.day = collection_override.day
        provenance.append(MergeSource("year", merged.year, "collection_override"))
    else:
        dated = [c for c in issues if c.year > 0]
        if dated:
            dated_sorted = sorted(dated, key=lambda c: (c.year, c.month or 1, c.day or 1))
            merged.year = dated_sorted[0].year
            merged.month = dated_sorted[0].month
            merged.day = dated_sorted[0].day
            provenance.append(MergeSource("year", merged.year, "earliest_issue"))

    # --- SUMMARY: collection summary > per-issue summaries (with issue headers) ---
    if collection_override and collection_override.summary:
        merged.summary = collection_override.summary
        provenance.append(MergeSource("summary", "(collection summary)", "collection_override"))
    else:
        issue_summaries = []
        for c in issues:
            if c.summary:
                label = f"Issue #{c.number}" if c.number else (c.title or "Issue")
                issue_summaries.append(f"--- {label} ---\n{c.summary}")
        merged.summary = "\n\n".join(issue_summaries)
        provenance.append(MergeSource("summary", "(per-issue summaries)", "issue_union"))

    # --- NOTES: append collection notes then issue notes ---
    notes_parts = []
    if collection_override and collection_override.notes:
        notes_parts.append(collection_override.notes)
    for c in issues:
        if c.notes:
            notes_parts.append(c.notes)
    merged.notes = "\n".join(notes_parts)

    # --- WEB: collection web > comma-joined issue URLs ---
    if collection_override and collection_override.web:
        merged.web = collection_override.web
        provenance.append(MergeSource("web", merged.web, "collection_override"))
    else:
        webs = [c.web for c in issues if c.web]
        merged.web = ", ".join(webs)
        provenance.append(MergeSource("web", merged.web, "issue_urls_joined"))

    # --- CREATORS: union + deduplicate per role ---
    for role in ("writers", "pencillers", "inkers", "colorists", "letterers", "cover_artists"):
        per_issue_lists = [getattr(c, role, []) for c in issues]
        merged_list = _union_lists(*per_issue_lists)
        setattr(merged, role, merged_list)
        provenance.append(MergeSource(role, merged_list, "issue_union_dedup"))

    # --- CHARACTERS: union + deduplicate ---
    merged.characters = _union_lists(*[c.characters for c in issues])
    provenance.append(MergeSource("characters", merged.characters, "issue_union_dedup"))

    # --- TEAMS: union + deduplicate ---
    merged.teams = _union_lists(*[c.teams for c in issues])

    # --- STORY ARCS: union + deduplicate ---
    merged.story_arcs = _union_lists(*[c.story_arcs for c in issues])
    provenance.append(MergeSource("story_arcs", merged.story_arcs, "issue_union_dedup"))

    # --- PROVIDER ID: collection-level > first resolved issue ---
    if collection_override and collection_override.provider_id:
        merged.provider_id = collection_override.provider_id
        merged.provider_name = collection_override.provider_name
        provenance.append(MergeSource("provider_id", merged.provider_id, "collection_override"))
    else:
        first_with_id = next((c for c in issues if c.provider_id), None)
        if first_with_id:
            merged.provider_id = first_with_id.provider_id
            merged.provider_name = first_with_id.provider_name
            provenance.append(MergeSource("provider_id", merged.provider_id, "first_issue"))

    return MergeResult(comic=merged, provenance=provenance)
