from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from models.identity import ComicIdentity, IdentityEvidence
from pipeline.filename_parser import ParsedFilename
from pipeline.scoring import score_identity_candidate, ScoringWeights, DEFAULT_WEIGHTS, normalize_title
from pipeline.conflicts import detect_conflicts, detect_provider_disagreements, detect_existing_xml_conflicts, Conflict, SEVERITY_FATAL, SEVERITY_ERROR

LEVEL_AUTO_ACCEPT = "AUTO_ACCEPT"
LEVEL_ACCEPT_WITH_WARNING = "ACCEPT_WITH_WARNING"
LEVEL_MANUAL_REVIEW = "MANUAL_REVIEW"
LEVEL_UNRESOLVED = "UNRESOLVED"

@dataclass
class ConfidenceDecision:
    """
    Represents the evaluated confidence decision for a candidate ComicIdentity or candidate pool.
    """
    score: float = 0.0
    level: str = LEVEL_UNRESOLVED
    evidence: List[IdentityEvidence] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    has_critical_conflict: bool = False
    action: str = "SKIP"  # "UPDATE", "REVIEW", "SKIP"
    second_best_score: Optional[float] = None
    score_margin: Optional[float] = None
    is_ambiguous_margin: bool = False
    provider_agreement_count: int = 0

CandidateDecision = ConfidenceDecision


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
    has_fatal_series_conflict = any(
        c.type == "series_conflict" and c.severity == SEVERITY_FATAL for c in detected_conflicts
    )
    has_critical_conflict = any(c.severity in (SEVERITY_FATAL, SEVERITY_ERROR) for c in detected_conflicts)

    if score >= 90.0 and not has_critical_conflict:
        level = LEVEL_AUTO_ACCEPT
        action = "UPDATE"
    elif score >= 75.0 and not has_critical_conflict:
        level = LEVEL_ACCEPT_WITH_WARNING
        action = "UPDATE"
    elif not has_fatal_series_conflict and (score >= 50.0 or (has_critical_conflict and raw_positive_score >= 50.0)):
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


def evaluate_candidate_pool_decision(
    candidates: List[ComicIdentity],
    parsed: ParsedFilename,
    min_margin: float = 10.0,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
    existing_comic: Optional[object] = None
) -> Tuple[Optional[ComicIdentity], ConfidenceDecision]:
    """
    Phase 44 Central Candidate Decision Policy:
    Evaluates the complete candidate pool against parsed filename signals, existing ComicInfo.xml,
    and provider agreement/disagreement signals. Applies score margin protection.
    """
    if not candidates:
        return None, ConfidenceDecision(score=0.0, level=LEVEL_UNRESOLVED, action="SKIP")

    # 1. Detect provider agreement
    agreement_groups = {}
    external_providers = {"Kapowarr", "ComicVine", "GCD", "GCP"}
    for c in candidates:
        if c.provider in external_providers and c.series_name and c.issue_number:
            key = (normalize_title(c.series_name), c.issue_number.lstrip("0"))
            agreement_groups.setdefault(key, set()).add(c.provider)

    for c in candidates:
        if c.provider in external_providers and c.series_name and c.issue_number:
            key = (normalize_title(c.series_name), c.issue_number.lstrip("0"))
            providers = agreement_groups.get(key, set())
            if len(providers) >= 2:
                c.provider_agreement = list(providers)

    # 2. Detect provider disagreements
    disagreements = detect_provider_disagreements(candidates)

    # 3. Detect existing XML conflicts
    xml_conflicts = detect_existing_xml_conflicts(parsed, existing_comic)

    # 4. Evaluate each candidate
    scored_pairs = []
    for cand in candidates:
        dec = evaluate_confidence(cand, parsed, weights=weights)
        if disagreements:
            dec.conflicts.extend(disagreements)
            dec.has_critical_conflict = True
            if dec.level in (LEVEL_AUTO_ACCEPT, LEVEL_ACCEPT_WITH_WARNING):
                dec.level = LEVEL_MANUAL_REVIEW
                dec.action = "REVIEW"
                dec.reasons.append("Provider disagreement detected across candidate sources")
        if xml_conflicts:
            dec.conflicts.extend(xml_conflicts)
            dec.has_critical_conflict = True
            if dec.level in (LEVEL_AUTO_ACCEPT, LEVEL_ACCEPT_WITH_WARNING):
                dec.level = LEVEL_MANUAL_REVIEW
                dec.action = "REVIEW"
                dec.reasons.append("Existing ComicInfo.xml conflict detected against filename")
        scored_pairs.append((cand, dec))

    # 5. Sort candidates: non-conflicting first, then highest score
    scored_pairs.sort(key=lambda p: (not p[1].has_critical_conflict, p[1].score), reverse=True)
    best_cand, best_dec = scored_pairs[0]

    # 6. Apply score-margin protection against competing distinct candidates
    if len(scored_pairs) > 1:
        for second_cand, second_dec in scored_pairs[1:]:
            is_competing_distinct = (
                normalize_title(second_cand.series_name) != normalize_title(best_cand.series_name)
                or second_cand.issue_number.lstrip("0") != best_cand.issue_number.lstrip("0")
                or (second_cand.publication_year and best_cand.publication_year and abs(second_cand.publication_year - best_cand.publication_year) > 1)
            )
            if is_competing_distinct:
                margin = best_dec.score - second_dec.score
                best_dec.second_best_score = second_dec.score
                best_dec.score_margin = margin
                if margin <= min_margin and best_dec.level in (LEVEL_AUTO_ACCEPT, LEVEL_ACCEPT_WITH_WARNING):
                    best_dec.is_ambiguous_margin = True
                    best_dec.level = LEVEL_MANUAL_REVIEW
                    best_dec.action = "REVIEW"
                    reason = f"Ambiguous candidates: score margin {margin:.1f} is less than or equal to required minimum {min_margin:.1f} (top: {best_dec.score:.1f} vs runner-up: {second_dec.score:.1f})"
                    best_dec.reasons.append(reason)
                    best_dec.confidence_reasons = best_dec.reasons
                break

    if best_cand and hasattr(best_cand, "provider_agreement") and best_cand.provider_agreement:
        best_dec.provider_agreement_count = len(best_cand.provider_agreement)

    return (best_cand, best_dec) if best_dec.action != "SKIP" else (None, best_dec)
