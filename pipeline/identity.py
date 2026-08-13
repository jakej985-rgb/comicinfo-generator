from typing import List
from models.archive import ArchiveRecord
from models.identity import ComicIdentity, IdentityEvidence
from pipeline.filename_parser import parse_filename_identity
from pipeline.archive_identity import extract_archive_identity
from pipeline.issue_number import IssueNumber

def extract_identity_candidates(archive_path: str) -> List[ComicIdentity]:
    """
    Extracts all candidate identity signals from an archive file on disk,
    including filename parsing, folder structure, and embedded ComicInfo.xml metadata.
    """
    archive_rec = ArchiveRecord.from_file(archive_path)
    candidates: List[ComicIdentity] = []

    # 1. Candidate from Filename
    parsed_file = parse_filename_identity(archive_path)
    file_identity = ComicIdentity(
        provider="FilenameParser",
        series_name=parsed_file.series_name,
        issue_number=parsed_file.issue_number,
        publication_year=parsed_file.year,
        volume=parsed_file.volume,
        publisher=parsed_file.publisher,
        identity_type="TPB" if parsed_file.is_tpb else ("Annual" if parsed_file.is_annual else "Issue")
    )

    file_evidence = [
        IdentityEvidence(
            source="FilenameParser", field="series_name",
            expected="", actual=parsed_file.series_name, score=25.0,
            explanation=f"Filename extracted series name '{parsed_file.series_name}'"
        ),
        IdentityEvidence(
            source="FilenameParser", field="issue_number",
            expected="", actual=parsed_file.issue_number, score=30.0,
            explanation=f"Filename extracted issue number #{parsed_file.issue_number}"
        )
    ]
    if parsed_file.year > 0:
        file_evidence.append(IdentityEvidence(
            source="FilenameParser", field="year",
            expected="", actual=str(parsed_file.year), score=15.0,
            explanation=f"Filename extracted year {parsed_file.year}"
        ))

    file_identity.evidence = file_evidence
    candidates.append(file_identity)

    # 2. Candidate from Embedded Archive / Directory Structure
    archive_identity = extract_archive_identity(archive_rec)
    if archive_identity:
        candidates.append(archive_identity)

    return candidates
