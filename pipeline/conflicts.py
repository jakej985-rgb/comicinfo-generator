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
        if norm_cand_series != norm_parsed_series and not (
            norm_cand_series.startswith(norm_parsed_series) or norm_parsed_series.startswith(norm_cand_series)
        ):
            conflicts.append(Conflict(
                type="series_conflict",
                severity=SEVERITY_FATAL,
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
