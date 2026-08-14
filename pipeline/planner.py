"""
pipeline/planner.py — Phase 87: Separate Planning from Execution

Defines:
- ProcessingPlan dataclass
- plan_archive: pure planning stage that computes proposed changes and action
Stages:
Archive → Parse → Resolve → Plan → Execute
"""

import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.resolver import MetadataResolver, inspect_existing_comicinfo


@dataclass
class ProcessingPlan:
    """
    Phase 87.1: Authoritative execution plan computed before any archive write.
    """
    file_path: str
    action: str  # "EMBED", "UPDATE", "SKIP", "REVIEW"
    fields: List[str] = field(default_factory=list)
    provider: str = ""
    provider_id: str = ""
    confidence: float = 0.0
    candidate: Optional[ComicIdentity] = None
    proposed_comic: Optional[Comic] = None
    metadata_state: str = "METADATA_NOT_FOUND"
    reason: str = ""
    is_cbr: bool = False
    target_cbz_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "action": self.action,
            "fields": list(self.fields),
            "provider": self.provider,
            "provider_id": self.provider_id,
            "confidence": self.confidence,
            "metadata_state": self.metadata_state,
            "reason": self.reason,
            "is_cbr": self.is_cbr,
            "target_cbz_path": self.target_cbz_path
        }


def plan_archive(
    file_path: str,
    resolver: MetadataResolver,
    url_override: str = "",
    allow_update: bool = True
) -> ProcessingPlan:
    """
    Phase 87.1: Pure Planning Stage.
    Archive → Parse → Resolve → Plan
    Computes proposed changes, diffs against existing ComicInfo, and determines action
    WITHOUT creating temp files or modifying any archive on disk.
    """
    abs_path = os.path.abspath(file_path)
    is_cbr = abs_path.lower().endswith(".cbr")
    target_cbz_path = (os.path.splitext(abs_path)[0] + ".cbz") if is_cbr else abs_path

    identity, decision = resolver.resolve_identity(abs_path, url_override=url_override)

    conf_val = getattr(decision, "confidence", getattr(decision, "score", 0.0))
    if callable(conf_val):
        conf_val = conf_val()

    if not identity or decision.action == "SKIP":
        return ProcessingPlan(
            file_path=abs_path,
            action="SKIP",
            candidate=identity,
            confidence=conf_val,
            reason=f"Identity resolution skipped or below threshold (Confidence: {conf_val:.1f}%)",
            is_cbr=is_cbr,
            target_cbz_path=target_cbz_path
        )

    # Retrieve metadata from provider
    meta_res = resolver.retrieve_metadata_result(identity, file_path=abs_path)
    if meta_res.state != "METADATA_FOUND" or not meta_res.comic:
        action = "REVIEW" if decision.action == "REVIEW" else "SKIP"
        return ProcessingPlan(
            file_path=abs_path,
            action=action,
            candidate=identity,
            provider=identity.provider,
            confidence=conf_val,
            metadata_state=meta_res.state,
            reason=f"Metadata lookup resulted in {meta_res.state}: {meta_res.error_message}",
            is_cbr=is_cbr,
            target_cbz_path=target_cbz_path
        )

    proposed = meta_res.comic

    # Inspect existing ComicInfo to determine diff/fields
    existing_report = inspect_existing_comicinfo(abs_path)
    existing_comic = existing_report.comic

    fields_to_change = []
    if proposed.title: fields_to_change.append("Title")
    if proposed.series: fields_to_change.append("Series")
    if proposed.number: fields_to_change.append("Number")
    if proposed.publisher: fields_to_change.append("Publisher")
    if proposed.year: fields_to_change.append("Year")
    if proposed.writers: fields_to_change.append("Writer")
    if proposed.pencillers: fields_to_change.append("Penciller")
    if proposed.characters: fields_to_change.append("Characters")
    if proposed.summary: fields_to_change.append("Summary")

    if decision.action == "REVIEW":
        action = "REVIEW"
        reason = f"Confidence score ({conf_val:.1f}%) requires user review"
    elif existing_comic is not None:
        action = "UPDATE" if allow_update else "SKIP"
        reason = f"Existing ComicInfo found; updating {len(fields_to_change)} metadata fields"
    else:
        action = "EMBED"
        reason = f"Valid metadata resolved with confidence {conf_val:.1f}%"

    return ProcessingPlan(
        file_path=abs_path,
        action=action,
        fields=fields_to_change,
        provider=identity.provider,
        provider_id=identity.provider_id,
        confidence=conf_val,
        candidate=identity,
        proposed_comic=proposed,
        metadata_state=meta_res.state,
        reason=reason,
        is_cbr=is_cbr,
        target_cbz_path=target_cbz_path
    )
