from dataclasses import dataclass, field
from typing import List, Tuple
from models.identity import ComicIdentity, IdentityEvidence
from pipeline.filename_parser import ParsedFilename
from pipeline.scoring import score_identity_candidate, ScoringWeights, DEFAULT_WEIGHTS

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
    has_critical_conflict: bool = False
    action: str = "SKIP"  # "UPDATE", "REVIEW", "SKIP"

def evaluate_confidence(
    candidate: ComicIdentity,
    parsed: ParsedFilename,
    weights: ScoringWeights = DEFAULT_WEIGHTS
) -> ConfidenceDecision:
    """
    Evaluates candidate confidence against target parsed signals and assigns decision level:
    - AUTO_ACCEPT (90+)
    - ACCEPT_WITH_WARNING (75-89)
    - MANUAL_REVIEW (50-74)
    - UNRESOLVED (<50)
    """
    score, evidence, reasons = score_identity_candidate(candidate, parsed, weights=weights)

    # Check for critical conflicts (conflicting series, conflicting publication year, conflicting issue)
    has_critical_conflict = any(ev.score < 0 for ev in evidence)

    if score >= 90.0 and not has_critical_conflict:
        level = LEVEL_AUTO_ACCEPT
        action = "UPDATE"
    elif score >= 75.0 and not has_critical_conflict:
        level = LEVEL_ACCEPT_WITH_WARNING
        action = "UPDATE"
    elif score >= 50.0:
        level = LEVEL_MANUAL_REVIEW
        action = "REVIEW"
    else:
        level = LEVEL_UNRESOLVED
        action = "SKIP"

    # Attach confidence data to candidate identity object
    candidate.confidence = score
    candidate.confidence_level = level
    candidate.confidence_reasons = reasons
    candidate.evidence = evidence

    return ConfidenceDecision(
        score=score,
        level=level,
        evidence=evidence,
        reasons=reasons,
        has_critical_conflict=has_critical_conflict,
        action=action
    )
