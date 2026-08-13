from dataclasses import dataclass, field
from typing import List
from models.identity import ComicIdentity, IdentityEvidence
from pipeline.filename_parser import ParsedFilename
from pipeline.scoring import score_identity_candidate, ScoringWeights, DEFAULT_WEIGHTS
from pipeline.conflicts import detect_conflicts, Conflict, SEVERITY_FATAL, SEVERITY_ERROR

LEVEL_AUTO_ACCEPT = "AUTO_ACCEPT"
LEVEL_ACCEPT_WITH_WARNING = "ACCEPT_WITH_WARNING"
LEVEL_MANUAL_REVIEW = "MANUAL_REVIEW"
LEVEL_UNRESOLVED = "UNRESOLVED"

@dataclass
class ConfidenceDecision:
    """
    Represents the evaluated confidence decision for a candidate ComicIdentity.
    """
    score: float = 0.0
    level: str = LEVEL_UNRESOLVED
    evidence: List[IdentityEvidence] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    has_critical_conflict: bool = False
    action: str = "SKIP"  # "UPDATE", "REVIEW", "SKIP"

def evaluate_confidence(
    candidate: ComicIdentity,
    parsed: ParsedFilename,
    weights: ScoringWeights = DEFAULT_WEIGHTS
) -> ConfidenceDecision:
    """
    Evaluates candidate confidence against target parsed signals and detects explicit conflicts:
    - AUTO_ACCEPT (90+ and no critical conflicts)
    - ACCEPT_WITH_WARNING (75-89 and no fatal conflicts)
    - MANUAL_REVIEW (50-74 or any critical conflict)
    - UNRESOLVED (<50)
    """
    score, evidence, reasons = score_identity_candidate(candidate, parsed, weights=weights)
    detected_conflicts = detect_conflicts(candidate, parsed)

    raw_positive_score = sum(ev.score for ev in evidence if ev.score > 0)
    has_critical_conflict = any(c.severity in (SEVERITY_FATAL, SEVERITY_ERROR) for c in detected_conflicts)

    if score >= 90.0 and not has_critical_conflict:
        level = LEVEL_AUTO_ACCEPT
        action = "UPDATE"
    elif score >= 75.0 and not has_critical_conflict:
        level = LEVEL_ACCEPT_WITH_WARNING
        action = "UPDATE"
    elif score >= 50.0 or (has_critical_conflict and raw_positive_score >= 50.0):
        level = LEVEL_MANUAL_REVIEW
        action = "REVIEW"
    else:
        level = LEVEL_UNRESOLVED
        action = "SKIP"

    # Attach confidence and conflict data to candidate identity object
    candidate.confidence = score
    candidate.confidence_level = level
    candidate.confidence_reasons = reasons
    candidate.evidence = evidence

    return ConfidenceDecision(
        score=score,
        level=level,
        evidence=evidence,
        reasons=reasons,
        conflicts=detected_conflicts,
        has_critical_conflict=has_critical_conflict,
        action=action
    )
