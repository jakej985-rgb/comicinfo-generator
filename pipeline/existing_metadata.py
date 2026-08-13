"""
pipeline/existing_metadata.py — Phase 45

Classifies and extracts authority signals from existing embedded ComicInfo.xml metadata:
- MISSING: No ComicInfo.xml present in archive.
- VALID: Complete, well-formed metadata that agrees with filename context.
- PARTIAL: Well-formed metadata missing essential identification fields (e.g. missing issue or series).
- MALFORMED: Corrupt XML syntax or unparseable byte stream.
- CONFLICTING: Valid XML metadata that explicitly contradicts filename signals (e.g. issue 1 vs 5, or Batman vs Superman).
"""
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Optional, List

from models.comic import Comic
from models.identity import ComicIdentity, IdentityEvidence
from pipeline.filename_parser import ParsedFilename
from pipeline.conflicts import detect_conflicts, detect_existing_xml_conflicts, Conflict, SEVERITY_FATAL, SEVERITY_ERROR
from writers.comicinfo import ComicInfoParser

STATE_MISSING = "MISSING"
STATE_VALID = "VALID"
STATE_PARTIAL = "PARTIAL"
STATE_MALFORMED = "MALFORMED"
STATE_CONFLICTING = "CONFLICTING"


@dataclass
class ExistingMetadataReport:
    """
    Structured report for existing embedded ComicInfo.xml metadata inspection.
    """
    state: str = STATE_MISSING
    comic: Optional[Comic] = None
    candidate_identity: Optional[ComicIdentity] = None
    conflicts: List[Conflict] = field(default_factory=list)
    raw_xml: Optional[bytes] = None
    error_message: str = ""


def inspect_existing_comicinfo(
    cbz_path: str,
    parsed: Optional[ParsedFilename] = None
) -> ExistingMetadataReport:
    """
    Inspects, extracts, and classifies existing embedded ComicInfo.xml in a .cbz archive.
    """
    if not cbz_path or not os.path.exists(cbz_path) or not cbz_path.lower().endswith(".cbz"):
        return ExistingMetadataReport(state=STATE_MISSING)

    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            xml_names = [n for n in zf.namelist() if n.lower() == "comicinfo.xml"]
            if not xml_names:
                return ExistingMetadataReport(state=STATE_MISSING)

            xml_bytes = zf.read(xml_names[0])
    except Exception as e:
        return ExistingMetadataReport(
            state=STATE_MALFORMED,
            error_message=f"Archive read error while accessing ComicInfo.xml: {e}"
        )

    # Attempt XML parsing
    try:
        comic = ComicInfoParser.parse_xml_bytes(xml_bytes)
        comic.provider_name = "ExistingXML"
    except Exception as e:
        return ExistingMetadataReport(
            state=STATE_MALFORMED,
            raw_xml=xml_bytes,
            error_message=f"Malformed ComicInfo.xml syntax: {e}"
        )

    # Extract Identity Candidate and Evidence
    candidate = ComicIdentity(
        provider="ExistingXML",
        series_name=comic.series or comic.title,
        issue_number=comic.number,
        publication_year=comic.year or 0,
        publisher=comic.publisher or "",
        volume=comic.volume or ""
    )

    evidence: List[IdentityEvidence] = []
    if candidate.series_name:
        evidence.append(IdentityEvidence(
            source="ExistingXML", field="series_name",
            expected="", actual=candidate.series_name, score=25.0,
            explanation=f"Embedded ComicInfo.xml contains series '{candidate.series_name}'"
        ))
    if candidate.issue_number:
        evidence.append(IdentityEvidence(
            source="ExistingXML", field="issue_number",
            expected="", actual=candidate.issue_number, score=30.0,
            explanation=f"Embedded ComicInfo.xml contains issue #{candidate.issue_number}"
        ))
    if candidate.publication_year > 0:
        evidence.append(IdentityEvidence(
            source="ExistingXML", field="year",
            expected="", actual=str(candidate.publication_year), score=15.0,
            explanation=f"Embedded ComicInfo.xml contains publication year {candidate.publication_year}"
        ))
    if candidate.publisher:
        evidence.append(IdentityEvidence(
            source="ExistingXML", field="publisher",
            expected="", actual=candidate.publisher, score=15.0,
            explanation=f"Embedded ComicInfo.xml contains publisher '{candidate.publisher}'"
        ))

    # Parse Web tag for direct provider ID (e.g. Comic Vine Issue ID)
    if comic.web:
        m_cv = re.search(r"comicvine\.gamespot\.com/.*?/4000-(\d+)", comic.web)
        if m_cv:
            candidate.issue_id = f"4000-{m_cv.group(1)}"
            candidate.issue_provider = "ComicVine"
            evidence.append(IdentityEvidence(
                source="ExistingXML", field="issue_id",
                expected="", actual=candidate.issue_id, score=90.0,
                explanation=f"Embedded Web URL contains Comic Vine Issue ID '{candidate.issue_id}'"
            ))

    candidate.evidence = evidence

    # Classify State: PARTIAL, CONFLICTING, or VALID
    is_partial = not (candidate.series_name and candidate.issue_number)
    detected_conflicts: List[Conflict] = []

    if parsed:
        detected_conflicts.extend(detect_conflicts(candidate, parsed))
        detected_conflicts.extend(detect_existing_xml_conflicts(parsed, comic))

    has_critical_conflict = any(
        c.severity in (SEVERITY_FATAL, SEVERITY_ERROR) for c in detected_conflicts
    )

    if has_critical_conflict:
        state = STATE_CONFLICTING
    elif is_partial:
        state = STATE_PARTIAL
    else:
        state = STATE_VALID

    return ExistingMetadataReport(
        state=state,
        comic=comic,
        candidate_identity=candidate,
        conflicts=detected_conflicts,
        raw_xml=xml_bytes
    )
