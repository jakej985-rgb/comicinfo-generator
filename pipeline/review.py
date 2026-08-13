import os
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from models.comic import Comic
from models.identity import ComicIdentity, IdentityEvidence
from pipeline.confidence import ConfidenceDecision
from pipeline.conflicts import Conflict

@dataclass
class ManualReviewReport:
    """
    Phase 25: Manual Review Report generated for uncertain matches (MANUAL_REVIEW state).
    Contains full evidence, current metadata, candidate options, conflicts, and recommendations.
    Never modifies the archive.
    """
    archive_path: str = ""
    current_metadata: Dict[str, Any] = field(default_factory=dict)
    candidates: List[ComicIdentity] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)
    decisions: List[ConfidenceDecision] = field(default_factory=list)
    recommended_candidate: Optional[ComicIdentity] = None

def generate_manual_review_report(
    archive_path: str,
    current_comic: Optional[Comic],
    candidates: List[ComicIdentity],
    decisions: List[ConfidenceDecision]
) -> ManualReviewReport:
    """Generates a ManualReviewReport data structure for uncertain identity resolutions."""
    cur_meta = {}
    if current_comic:
        cur_meta = {
            "series": current_comic.series,
            "number": current_comic.number,
            "year": current_comic.year,
            "publisher": current_comic.publisher,
            "title": current_comic.title,
            "provider": current_comic.provider_name
        }

    scores = [d.score for d in decisions]
    rec_cand = None
    if candidates and decisions:
        best_pair = sorted(zip(candidates, decisions), key=lambda p: p[1].score, reverse=True)[0]
        rec_cand = best_pair[0]


    return ManualReviewReport(
        archive_path=os.path.abspath(archive_path),
        current_metadata=cur_meta,
        candidates=candidates,
        scores=scores,
        decisions=decisions,
        recommended_candidate=rec_cand
    )

def format_review_report_markdown(report: ManualReviewReport) -> str:
    """Formats a ManualReviewReport as human-readable GitHub-style Markdown."""
    lines = []
    lines.append(f"# Manual Review Report for `{os.path.basename(report.archive_path)}`\n")
    lines.append(f"**Archive Path**: `{report.archive_path}`  ")
    lines.append(f"**Review Reason**: Candidate identity evaluation returned `MANUAL_REVIEW` status due to low confidence or explicit conflicts.\n")

    lines.append("## Current Metadata")
    if report.current_metadata:
        for k, v in report.current_metadata.items():
            lines.append(f"- **{k.title()}**: `{v}`")
    else:
        lines.append("*No existing ComicInfo.xml metadata found inside archive.*")

    lines.append("\n## Candidates & Evidence")
    for idx, (cand, dec) in enumerate(zip(report.candidates, report.decisions), 1):
        lines.append(f"### Candidate #{idx}: {cand.provider} - {cand.series_name} #{cand.issue_number}")
        lines.append(f"- **Confidence Score**: `{dec.score:.1f}%` ({dec.level})")
        lines.append(f"- **Provider ID**: `{cand.issue_id or cand.series_id or 'None'}`")

        if dec.evidence:
            lines.append("- **Evidence List**:")
            for ev in dec.evidence:
                sign = "+" if ev.score > 0 else ""
                lines.append(f"  - `{sign}{ev.score:.0f}`: {ev.explanation}")

        if dec.conflicts:
            lines.append("- **Conflicts Detected**:")
            for c in dec.conflicts:
                lines.append(f"  - `[{c.severity}]` {c.explanation}")

        lines.append("")

    lines.append("## Recommended Candidate")
    if report.recommended_candidate:
        rc = report.recommended_candidate
        lines.append(f"- **Provider**: `{rc.provider}`")
        lines.append(f"- **Series**: `{rc.series_name}`")
        lines.append(f"- **Issue Number**: `#{rc.issue_number}`")
        lines.append(f"- **Year**: `{rc.publication_year or 'Unknown'}`")
    else:
        lines.append("*No candidate reached the minimum threshold of 50% for recommendation.*")

    lines.append("\n> [!NOTE]\n> *This archive file has NOT been modified on disk. Please review the recommended candidate above.*")
    return "\n".join(lines)

def save_review_report(report: ManualReviewReport, output_dir: str = "reports") -> str:
    """Saves a ManualReviewReport to the specified output directory."""
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.basename(report.archive_path)
    file_name = f"review_{os.path.splitext(base_name)[0]}.md"
    out_path = os.path.join(output_dir, file_name)

    md_content = format_review_report_markdown(report)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return out_path
