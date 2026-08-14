import re
from dataclasses import dataclass, field
from typing import Tuple, List, Optional
from models.identity import ComicIdentity, IdentityEvidence
from pipeline.filename_parser import ParsedFilename

@dataclass
class ScoringWeights:
    """Configurable scoring weights for comic candidate identity evidence."""
    exact_issue_provider_id: float = 100.0
    exact_volume_provider_id: float = 90.0
    exact_kapowarr_identity: float = 90.0
    exact_issue_number: float = 30.0
    exact_series_name: float = 25.0
    publisher_match: float = 15.0
    year_match: float = 15.0
    volume_match: float = 15.0
    folder_match: float = 10.0
    filename_similarity: float = 10.0
    existing_metadata_match: float = 10.0
    alternate_cover_evidence: float = 5.0

    conflicting_series: float = -50.0
    conflicting_publisher: float = -25.0
    conflicting_volume: float = -50.0
    conflicting_issue: float = -60.0

DEFAULT_WEIGHTS = ScoringWeights()

def normalize_title(title: str) -> str:
    """Normalizes series/comic title string for robust string comparison."""
    if not title:
        return ""
    t = title.lower().strip()
    for article in ["the ", "a ", "an "]:
        if t.startswith(article):
            t = t[len(article):]
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())

def score_identity_candidate(
    candidate: ComicIdentity,
    parsed: ParsedFilename,
    weights: ScoringWeights = DEFAULT_WEIGHTS
) -> Tuple[float, List[IdentityEvidence], List[str]]:
    """
    Scores a candidate ComicIdentity against target parsed filename signals using configurable weights.
    Returns (score_percentage, evidence_list, reasons_list).
    """
    score = 0.0
    evidence: List[IdentityEvidence] = []
    reasons: List[str] = []

    # 1. Kapowarr / Direct Provider ID / Existing XML (+100 / +90)
    if candidate.provider == "ExistingXML":
        score += weights.exact_issue_provider_id
        ev = IdentityEvidence(
            source="ExistingXML", field="existing_xml",
            expected="", actual="ComicInfo.xml",
            score=weights.exact_issue_provider_id,
            explanation=f"Existing embedded ComicInfo.xml metadata matched (+{weights.exact_issue_provider_id})"
        )
        evidence.append(ev)
        reasons.append(ev.explanation)
    elif candidate.provider == "Kapowarr" and (candidate.issue_id or candidate.series_id):
        score += weights.exact_kapowarr_identity
        ev = IdentityEvidence(
            source="Kapowarr", field="provider_id",
            expected="", actual=candidate.issue_id or candidate.series_id,
            score=weights.exact_kapowarr_identity,
            explanation=f"Exact Kapowarr identity matched (+{weights.exact_kapowarr_identity})"
        )
        evidence.append(ev)
        reasons.append(ev.explanation)
    elif candidate.issue_id:
        prov_score = 20.0
        score += prov_score
        ev = IdentityEvidence(
            source=candidate.provider, field="issue_id",
            expected="", actual=candidate.issue_id,
            score=prov_score,
            explanation=f"Provider candidate issue ID matched (+{prov_score})"
        )
        evidence.append(ev)
        reasons.append(ev.explanation)
    elif candidate.series_id:
        prov_score = 15.0
        score += prov_score
        ev = IdentityEvidence(
            source=candidate.provider, field="series_id",
            expected="", actual=candidate.series_id,
            score=prov_score,
            explanation=f"Provider candidate volume ID matched (+{prov_score})"
        )
        evidence.append(ev)
        reasons.append(ev.explanation)

    # Provider Agreement Bonus (+15)
    if getattr(candidate, "provider_agreement", None) and len(candidate.provider_agreement) >= 2:
        prov_list = ", ".join(sorted(candidate.provider_agreement))
        score += 15.0
        ev = IdentityEvidence(
            source="ProviderAgreement", field="provider_agreement",
            expected="", actual=prov_list,
            score=15.0,
            explanation=f"Independent providers agree on identity: {prov_list} (+15.0)"
        )
        evidence.append(ev)
        reasons.append(ev.explanation)

    # 2. Issue Number Matching (+30 / -60)
    if candidate.issue_number and parsed.issue_number:
        if candidate.issue_number.lstrip("0") == parsed.issue_number.lstrip("0"):
            score += weights.exact_issue_number
            ev = IdentityEvidence(
                source="FilenameParser", field="issue_number",
                expected=parsed.issue_number, actual=candidate.issue_number,
                score=weights.exact_issue_number,
                explanation=f"Issue number matched (#{candidate.issue_number}) (+{weights.exact_issue_number})"
            )
            evidence.append(ev)
            reasons.append(ev.explanation)
        else:
            score += weights.conflicting_issue
            ev = IdentityEvidence(
                source="FilenameParser", field="issue_number",
                expected=parsed.issue_number, actual=candidate.issue_number,
                score=weights.conflicting_issue,
                explanation=f"Conflicting issue number ({candidate.issue_number} vs {parsed.issue_number}) ({weights.conflicting_issue})"
            )
            evidence.append(ev)
            reasons.append(ev.explanation)

    # TPB / Collection format check (Phase 90.3)
    cand_name_lower = (candidate.series_name or "").lower()
    cand_is_tpb = any(k in cand_name_lower for k in ["tpb", "trade paperback", "omnibus", "compendium", "masterworks", "collection", "deluxe edition", "graphic novel"])
    if parsed.is_tpb and not cand_is_tpb and candidate.issue_number:
        score -= 50.0
        ev = IdentityEvidence(
            source="FilenameParser", field="format",
            expected="TPB/Collection", actual="Single Issue",
            score=-50.0,
            explanation="Target file is a TPB/Collection but candidate is a single issue (-50.0)"
        )
        evidence.append(ev)
        reasons.append(ev.explanation)
    elif not parsed.is_tpb and cand_is_tpb:
        score -= 50.0
        ev = IdentityEvidence(
            source="FilenameParser", field="format",
            expected="Single Issue", actual="TPB/Collection",
            score=-50.0,
            explanation="Target file is a single issue but candidate is a TPB/Collection (-50.0)"
        )
        evidence.append(ev)
        reasons.append(ev.explanation)

    # 3. Series Name Matching (+25 / -50)
    norm_cand_series = normalize_title(candidate.series_name)
    norm_parsed_series = normalize_title(parsed.series_name)

    if norm_cand_series and norm_parsed_series:
        if norm_cand_series == norm_parsed_series:
            score += weights.exact_series_name
            ev = IdentityEvidence(
                source="FilenameParser", field="series_name",
                expected=parsed.series_name, actual=candidate.series_name,
                score=weights.exact_series_name,
                explanation=f"Exact series name matched '{candidate.series_name}' (+{weights.exact_series_name})"
            )
            evidence.append(ev)
            reasons.append(ev.explanation)
        elif norm_cand_series.startswith(norm_parsed_series) or norm_parsed_series.startswith(norm_cand_series):
            partial_score = weights.exact_series_name * 0.6
            score += partial_score
            ev = IdentityEvidence(
                source="FilenameParser", field="series_name",
                expected=parsed.series_name, actual=candidate.series_name,
                score=partial_score,
                explanation=f"Partial series name match '{candidate.series_name}' (+{partial_score:.0f})"
            )
            evidence.append(ev)
            reasons.append(ev.explanation)
        else:
            score += weights.conflicting_series
            ev = IdentityEvidence(
                source="FilenameParser", field="series_name",
                expected=parsed.series_name, actual=candidate.series_name,
                score=weights.conflicting_series,
                explanation=f"Conflicting series name '{candidate.series_name}' vs '{parsed.series_name}' ({weights.conflicting_series})"
            )
            evidence.append(ev)
            reasons.append(ev.explanation)

    # 4. Publication Year Matching (+15 / -50)
    if candidate.publication_year > 0 and parsed.year > 0:
        if candidate.publication_year == parsed.year:
            score += weights.year_match
            ev = IdentityEvidence(
                source="FilenameParser", field="year",
                expected=str(parsed.year), actual=str(candidate.publication_year),
                score=weights.year_match,
                explanation=f"Publication year matched ({candidate.publication_year}) (+{weights.year_match})"
            )
            evidence.append(ev)
            reasons.append(ev.explanation)
        elif abs(candidate.publication_year - parsed.year) <= 1:
            score += 5.0
            ev = IdentityEvidence(
                source="FilenameParser", field="year",
                expected=str(parsed.year), actual=str(candidate.publication_year),
                score=5.0,
                explanation=f"Close publication year ({candidate.publication_year} vs {parsed.year}) (+5)"
            )
            evidence.append(ev)
            reasons.append(ev.explanation)
        else:
            score += weights.conflicting_volume
            ev = IdentityEvidence(
                source="FilenameParser", field="year",
                expected=str(parsed.year), actual=str(candidate.publication_year),
                score=weights.conflicting_volume,
                explanation=f"Conflicting publication year ({candidate.publication_year} vs {parsed.year}) ({weights.conflicting_volume})"
            )
            evidence.append(ev)
            reasons.append(ev.explanation)

    # 5. Publisher Matching (+15 / -25)
    if candidate.publisher and parsed.publisher:
        if normalize_title(candidate.publisher) == normalize_title(parsed.publisher):
            score += weights.publisher_match
            ev = IdentityEvidence(
                source="FilenameParser", field="publisher",
                expected=parsed.publisher, actual=candidate.publisher,
                score=weights.publisher_match,
                explanation=f"Publisher matched '{candidate.publisher}' (+{weights.publisher_match})"
            )
            evidence.append(ev)
            reasons.append(ev.explanation)
        else:
            score += weights.conflicting_publisher
            ev = IdentityEvidence(
                source="FilenameParser", field="publisher",
                expected=parsed.publisher, actual=candidate.publisher,
                score=weights.conflicting_publisher,
                explanation=f"Conflicting publisher '{candidate.publisher}' vs '{parsed.publisher}' ({weights.conflicting_publisher})"
            )
            evidence.append(ev)
            reasons.append(ev.explanation)

    # Clamp score between 0.0 and 100.0
    final_score = max(0.0, min(100.0, score))
    return final_score, evidence, reasons
