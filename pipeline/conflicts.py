from dataclasses import dataclass, field
from typing import List, Optional
from models.identity import ComicIdentity
from pipeline.filename_parser import ParsedFilename
from pipeline.scoring import normalize_title

SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"
SEVERITY_FATAL = "FATAL"

# Formal Conflict Types (Phase 58)
CONFLICT_SERIES = "series_conflict"
CONFLICT_YEAR = "year_conflict"
CONFLICT_ISSUE = "issue_conflict"
CONFLICT_PUBLISHER = "publisher_conflict"
CONFLICT_VOLUME = "volume_conflict"
CONFLICT_VARIANT = "variant_conflict"
CONFLICT_XML_FILENAME = "existing_xml_conflict"
CONFLICT_XML_PROVIDER = "xml_provider_conflict"
CONFLICT_XML_PROVIDER_ID = "xml_provider_id_conflict"
CONFLICT_PROVIDER_DISAGREEMENT = "provider_disagreement"
CONFLICT_PROVIDER_ID_DISAGREEMENT = "provider_id_disagreement"


@dataclass
class Conflict:
    """
    Represents a structured conflict detected between target file evidence and a candidate identity.
    """
    type: str = ""              # e.g. "series_conflict", "year_conflict", "publisher_conflict"
    severity: str = SEVERITY_WARNING # INFO, WARNING, ERROR, FATAL
    source_a: str = ""          # e.g. "Target File (Batman 2016)"
    source_b: str = ""          # e.g. "Candidate (Batman 1940)"
    explanation: str = ""       # Detailed explanation for review report


def detect_conflicts(candidate: ComicIdentity, parsed: ParsedFilename) -> List[Conflict]:
    """
    Analyzes candidate identity against target parsed filename and folder evidence,
    returning a list of structured Conflict objects (Phase 44 & Phase 58).
    """
    conflicts: List[Conflict] = []

    # 1. Series Name Conflict
    norm_cand_series = normalize_title(candidate.series_name)
    norm_parsed_series = normalize_title(parsed.series_name)

    if norm_cand_series and norm_parsed_series:
        if norm_cand_series != norm_parsed_series:
            is_partial = (
                norm_cand_series.startswith(norm_parsed_series) or norm_parsed_series.startswith(norm_cand_series)
            )
            severity = SEVERITY_ERROR if is_partial else SEVERITY_FATAL
            conflicts.append(Conflict(
                type=CONFLICT_SERIES,
                severity=severity,
                source_a=f"Target Filename ('{parsed.series_name}')",
                source_b=f"Candidate ('{candidate.series_name}')",
                explanation=f"Series name mismatch: Target is '{parsed.series_name}' but candidate is '{candidate.series_name}'."
            ))

    # 2. Publication Year Conflict
    if candidate.publication_year > 0 and parsed.year > 0:
        diff = abs(candidate.publication_year - parsed.year)
        if diff > 1:
            severity = SEVERITY_FATAL if diff >= 5 else SEVERITY_ERROR
            conflicts.append(Conflict(
                type=CONFLICT_YEAR,
                severity=severity,
                source_a=f"Target Year ({parsed.year})",
                source_b=f"Candidate Year ({candidate.publication_year})",
                explanation=f"Publication year conflict: Target specifies {parsed.year} but candidate is from {candidate.publication_year}."
            ))

    # 3. Issue Number & Variant Conflict
    if candidate.issue_number and parsed.issue_number:
        cand_num = candidate.issue_number.strip().lstrip("0")
        target_num = parsed.issue_number.strip().lstrip("0")
        if cand_num != target_num:
            # Check if it is a variant letter difference e.g. "1" vs "1A"
            if cand_num.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") == target_num.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
                conflicts.append(Conflict(
                    type=CONFLICT_VARIANT,
                    severity=SEVERITY_WARNING,
                    source_a=f"Target Issue (#{parsed.issue_number})",
                    source_b=f"Candidate Issue (#{candidate.issue_number})",
                    explanation=f"Variant letter mismatch: Target is #{parsed.issue_number} but candidate is #{candidate.issue_number}."
                ))
            else:
                conflicts.append(Conflict(
                    type=CONFLICT_ISSUE,
                    severity=SEVERITY_FATAL,
                    source_a=f"Target Issue (#{parsed.issue_number})",
                    source_b=f"Candidate Issue (#{candidate.issue_number})",
                    explanation=f"Issue number conflict: Target is #{parsed.issue_number} but candidate is #{candidate.issue_number}."
                ))

    # 4. Volume Conflict
    if getattr(candidate, "volume", None) and getattr(parsed, "volume", None):
        if str(candidate.volume).strip().lower() != str(parsed.volume).strip().lower():
            conflicts.append(Conflict(
                type=CONFLICT_VOLUME,
                severity=SEVERITY_ERROR,
                source_a=f"Target Volume ({parsed.volume})",
                source_b=f"Candidate Volume ({candidate.volume})",
                explanation=f"Volume mismatch: Target is Vol {parsed.volume} but candidate is Vol {candidate.volume}."
            ))

    # 5. Publisher Conflict
    if candidate.publisher and parsed.publisher:
        if normalize_title(candidate.publisher) != normalize_title(parsed.publisher):
            conflicts.append(Conflict(
                type=CONFLICT_PUBLISHER,
                severity=SEVERITY_WARNING,
                source_a=f"Target Publisher ('{parsed.publisher}')",
                source_b=f"Candidate Publisher ('{candidate.publisher}')",
                explanation=f"Publisher mismatch: Target specifies '{parsed.publisher}' but candidate is '{candidate.publisher}'."
            ))

    return conflicts


def detect_provider_disagreements(candidates: List[ComicIdentity]) -> List[Conflict]:
    """
    Detects if independent provider candidates (Kapowarr, ComicVine, GCD, GCP, ExistingXML)
    return disagreeing identities (conflicting series, issue numbers, or years) (Phase 58).
    """
    conflicts: List[Conflict] = []
    prov_cands = [
        c for c in candidates 
        if c.provider in ("Kapowarr", "ComicVine", "GCD", "GCP", "ExistingXML") and (c.series_name or c.issue_number)
    ]
    if len(prov_cands) < 2:
        return conflicts

    prov_map = {}
    for c in prov_cands:
        prov_map.setdefault(c.provider, []).append(c)

    if len(prov_map) < 2:
        return conflicts

    providers = list(prov_map.keys())
    for i in range(len(providers)):
        for j in range(i + 1, len(providers)):
            p1, p2 = providers[i], providers[j]
            c1, c2 = prov_map[p1][0], prov_map[p2][0]

            # Issue number disagreement
            if c1.issue_number and c2.issue_number:
                if c1.issue_number.lstrip("0") != c2.issue_number.lstrip("0"):
                    conflicts.append(Conflict(
                        type=CONFLICT_PROVIDER_DISAGREEMENT,
                        severity=SEVERITY_ERROR,
                        source_a=f"{p1} (#{c1.issue_number})",
                        source_b=f"{p2} (#{c2.issue_number})",
                        explanation=f"Provider disagreement on issue number: {p1} returns #{c1.issue_number} but {p2} returns #{c2.issue_number}."
                    ))

            # Series name disagreement
            s1 = normalize_title(c1.series_name)
            s2 = normalize_title(c2.series_name)
            if s1 and s2 and s1 != s2:
                conflicts.append(Conflict(
                    type=CONFLICT_PROVIDER_DISAGREEMENT,
                    severity=SEVERITY_ERROR,
                    source_a=f"{p1} ('{c1.series_name}')",
                    source_b=f"{p2} ('{c2.series_name}')",
                    explanation=f"Provider disagreement on series name: {p1} returns '{c1.series_name}' but {p2} returns '{c2.series_name}'."
                ))

            # Publication year disagreement (>= 2 years)
            if c1.publication_year > 0 and c2.publication_year > 0:
                if abs(c1.publication_year - c2.publication_year) >= 2:
                    conflicts.append(Conflict(
                        type=CONFLICT_PROVIDER_DISAGREEMENT,
                        severity=SEVERITY_ERROR,
                        source_a=f"{p1} ({c1.publication_year})",
                        source_b=f"{p2} ({c2.publication_year})",
                        explanation=f"Provider disagreement on publication year: {p1} indicates {c1.publication_year} but {p2} indicates {c2.publication_year}."
                    ))
    return conflicts


def detect_existing_xml_conflicts(parsed: ParsedFilename, existing_comic: Optional[object]) -> List[Conflict]:
    """
    Detects if an existing ComicInfo.xml metadata contradicts filename signals (Phase 45 & Phase 58).
    """
    conflicts: List[Conflict] = []
    if not existing_comic:
        return conflicts

    ex_series = getattr(existing_comic, "series", "") or getattr(existing_comic, "title", "")
    ex_number = getattr(existing_comic, "number", "")
    ex_year = getattr(existing_comic, "year", 0)

    if ex_number and parsed.issue_number:
        if str(ex_number).lstrip("0") != str(parsed.issue_number).lstrip("0"):
            conflicts.append(Conflict(
                type=CONFLICT_XML_FILENAME,
                severity=SEVERITY_ERROR,
                source_a=f"Target Filename (#{parsed.issue_number})",
                source_b=f"Existing ComicInfo.xml (#{ex_number})",
                explanation=f"Existing ComicInfo.xml issue #{ex_number} contradicts filename issue #{parsed.issue_number}."
            ))

    norm_ex_series = normalize_title(ex_series)
    norm_parsed_series = normalize_title(parsed.series_name)
    if norm_ex_series and norm_parsed_series and norm_ex_series != norm_parsed_series:
        conflicts.append(Conflict(
            type=CONFLICT_XML_FILENAME,
            severity=SEVERITY_ERROR,
            source_a=f"Target Filename ('{parsed.series_name}')",
            source_b=f"Existing ComicInfo.xml ('{ex_series}')",
            explanation=f"Existing ComicInfo.xml series '{ex_series}' contradicts filename series '{parsed.series_name}'."
        ))

    if ex_year > 0 and parsed.year > 0 and abs(ex_year - parsed.year) >= 2:
        conflicts.append(Conflict(
            type=CONFLICT_XML_FILENAME,
            severity=SEVERITY_ERROR,
            source_a=f"Target Filename ({parsed.year})",
            source_b=f"Existing ComicInfo.xml ({ex_year})",
            explanation=f"Existing ComicInfo.xml year {ex_year} contradicts filename year {parsed.year}."
        ))

    return conflicts


def detect_xml_provider_conflicts(existing_comic: Optional[object], candidate: ComicIdentity) -> List[Conflict]:
    """
    Detects conflicts between existing embedded ComicInfo.xml and candidate identity (Phase 58).
    """
    conflicts: List[Conflict] = []
    if not existing_comic or not candidate or candidate.provider == "ExistingXML":
        return conflicts

    ex_series = getattr(existing_comic, "series", "") or getattr(existing_comic, "title", "")
    ex_number = getattr(existing_comic, "number", "")
    ex_year = getattr(existing_comic, "year", 0)
    ex_id = getattr(existing_comic, "provider_id", "") or getattr(existing_comic, "notes", "")

    # 1. Provider ID Conflict (Fatal)
    if ex_id and candidate.issue_id:
        if str(ex_id).strip() and str(candidate.issue_id).strip() and str(ex_id).strip() != str(candidate.issue_id).strip():
            # Check if both look like ComicVine IDs (e.g. 4000-123 vs 4000-456)
            if "4000-" in str(ex_id) and "4000-" in str(candidate.issue_id):
                conflicts.append(Conflict(
                    type=CONFLICT_XML_PROVIDER_ID,
                    severity=SEVERITY_FATAL,
                    source_a=f"Existing XML Provider ID ({ex_id})",
                    source_b=f"Candidate Provider ID ({candidate.issue_id})",
                    explanation=f"Existing ComicInfo provider ID '{ex_id}' conflicts with candidate provider ID '{candidate.issue_id}'."
                ))

    # 2. Issue Number Conflict
    if ex_number and candidate.issue_number:
        if str(ex_number).lstrip("0") != str(candidate.issue_number).lstrip("0"):
            conflicts.append(Conflict(
                type=CONFLICT_XML_PROVIDER,
                severity=SEVERITY_ERROR,
                source_a=f"Existing XML Issue (#{ex_number})",
                source_b=f"Candidate Issue (#{candidate.issue_number})",
                explanation=f"Existing XML issue #{ex_number} contradicts provider candidate issue #{candidate.issue_number}."
            ))

    # 3. Series Name Conflict
    norm_ex = normalize_title(ex_series)
    norm_cand = normalize_title(candidate.series_name)
    if norm_ex and norm_cand and norm_ex != norm_cand:
        conflicts.append(Conflict(
            type=CONFLICT_XML_PROVIDER,
            severity=SEVERITY_ERROR,
            source_a=f"Existing XML Series ('{ex_series}')",
            source_b=f"Candidate Series ('{candidate.series_name}')",
            explanation=f"Existing XML series '{ex_series}' contradicts provider candidate series '{candidate.series_name}'."
        ))

    # 4. Publication Year Conflict
    if ex_year > 0 and candidate.publication_year > 0 and abs(ex_year - candidate.publication_year) >= 2:
        conflicts.append(Conflict(
            type=CONFLICT_XML_PROVIDER,
            severity=SEVERITY_ERROR,
            source_a=f"Existing XML Year ({ex_year})",
            source_b=f"Candidate Year ({candidate.publication_year})",
            explanation=f"Existing XML year {ex_year} contradicts provider candidate year {candidate.publication_year}."
        ))

    return conflicts
