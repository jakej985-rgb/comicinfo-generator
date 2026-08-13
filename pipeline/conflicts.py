from dataclasses import dataclass, field
from typing import List, Optional
from models.identity import ComicIdentity
from pipeline.filename_parser import ParsedFilename
from pipeline.scoring import normalize_title

SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"
SEVERITY_FATAL = "FATAL"

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
    returning a list of structured Conflict objects.
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
                type="series_conflict",
                severity=severity,
                source_a=f"Target Filename ('{parsed.series_name}')",
                source_b=f"Candidate ('{candidate.series_name}')",
                explanation=f"Series name mismatch: Target is '{parsed.series_name}' but candidate is '{candidate.series_name}'."
            ))

    # 2. Publication Year / Volume Conflict
    if candidate.publication_year > 0 and parsed.year > 0:
        diff = abs(candidate.publication_year - parsed.year)
        if diff > 1:
            severity = SEVERITY_FATAL if diff >= 5 else SEVERITY_ERROR
            conflicts.append(Conflict(
                type="year_conflict",
                severity=severity,
                source_a=f"Target Year ({parsed.year})",
                source_b=f"Candidate Year ({candidate.publication_year})",
                explanation=f"Publication year conflict: Target specifies {parsed.year} but candidate volume is from {candidate.publication_year}."
            ))

    # 3. Issue Number Conflict
    if candidate.issue_number and parsed.issue_number:
        if candidate.issue_number.lstrip("0") != parsed.issue_number.lstrip("0"):
            conflicts.append(Conflict(
                type="issue_conflict",
                severity=SEVERITY_FATAL,
                source_a=f"Target Issue (#{parsed.issue_number})",
                source_b=f"Candidate Issue (#{candidate.issue_number})",
                explanation=f"Issue number conflict: Target is #{parsed.issue_number} but candidate is #{candidate.issue_number}."
            ))

    # 4. Publisher Conflict
    if candidate.publisher and parsed.publisher:
        if normalize_title(candidate.publisher) != normalize_title(parsed.publisher):
            conflicts.append(Conflict(
                type="publisher_conflict",
                severity=SEVERITY_WARNING,
                source_a=f"Target Publisher ('{parsed.publisher}')",
                source_b=f"Candidate Publisher ('{candidate.publisher}')",
                explanation=f"Publisher mismatch: Target specifies '{parsed.publisher}' but candidate is '{candidate.publisher}'."
            ))

    return conflicts


def detect_provider_disagreements(candidates: List[ComicIdentity]) -> List[Conflict]:
    """
    Detects if independent provider candidates (Kapowarr, ComicVine, GCD, GCP, ExistingXML)
    return disagreeing identities (e.g. conflicting issue numbers or conflicting series).
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

            if c1.issue_number and c2.issue_number:
                if c1.issue_number.lstrip("0") != c2.issue_number.lstrip("0"):
                    conflicts.append(Conflict(
                        type="provider_disagreement",
                        severity=SEVERITY_ERROR,
                        source_a=f"{p1} (#{c1.issue_number})",
                        source_b=f"{p2} (#{c2.issue_number})",
                        explanation=f"Provider disagreement on issue number: {p1} returns #{c1.issue_number} but {p2} returns #{c2.issue_number}."
                    ))

            s1 = normalize_title(c1.series_name)
            s2 = normalize_title(c2.series_name)
            if s1 and s2 and s1 != s2:
                conflicts.append(Conflict(
                    type="provider_disagreement",
                    severity=SEVERITY_ERROR,
                    source_a=f"{p1} ('{c1.series_name}')",
                    source_b=f"{p2} ('{c2.series_name}')",
                    explanation=f"Provider disagreement on series name: {p1} returns '{c1.series_name}' but {p2} returns '{c2.series_name}'."
                ))
    return conflicts


def detect_existing_xml_conflicts(parsed: ParsedFilename, existing_comic: Optional[object]) -> List[Conflict]:
    """
    Detects if an existing ComicInfo.xml metadata contradicts filename signals.
    """
    conflicts: List[Conflict] = []
    if not existing_comic:
        return conflicts

    ex_series = getattr(existing_comic, "series", "") or getattr(existing_comic, "title", "")
    ex_number = getattr(existing_comic, "number", "")

    if ex_number and parsed.issue_number:
        if str(ex_number).lstrip("0") != str(parsed.issue_number).lstrip("0"):
            conflicts.append(Conflict(
                type="existing_xml_conflict",
                severity=SEVERITY_ERROR,
                source_a=f"Target Filename (#{parsed.issue_number})",
                source_b=f"Existing ComicInfo.xml (#{ex_number})",
                explanation=f"Existing ComicInfo.xml issue #{ex_number} contradicts filename issue #{parsed.issue_number}."
            ))

    norm_ex_series = normalize_title(ex_series)
    norm_parsed_series = normalize_title(parsed.series_name)
    if norm_ex_series and norm_parsed_series and norm_ex_series != norm_parsed_series:
        conflicts.append(Conflict(
            type="existing_xml_conflict",
            severity=SEVERITY_ERROR,
            source_a=f"Target Filename ('{parsed.series_name}')",
            source_b=f"Existing ComicInfo.xml ('{ex_series}')",
            explanation=f"Existing ComicInfo.xml series '{ex_series}' contradicts filename series '{parsed.series_name}'."
        ))

    return conflicts
