import re
from typing import Tuple, List
from models.identity import ComicIdentity
from pipeline.filename_parser import ParsedFilename

STATUS_AUTO_ACCEPT = "AUTO_ACCEPT"
STATUS_MANUAL_REVIEW = "MANUAL_REVIEW"
STATUS_UNRESOLVED = "UNRESOLVED"

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

def score_identity_candidate(candidate: ComicIdentity, parsed: ParsedFilename) -> Tuple[float, str, List[str]]:
    """
    Scores a candidate ComicIdentity against target parsed filename signals.
    Returns (score_percentage, status_label, reasons_list).
    """
    score = 0.0
    reasons = []

    # 1. Direct Provider Issue ID (+100)
    if candidate.issue_id:
        score += 100.0
        reasons.append("Exact provider issue ID matched (+100)")
    elif candidate.series_id:
        score += 60.0
        reasons.append("Provider volume ID matched (+60)")

    # 2. Issue Number Matching (+30 / -30)
    if candidate.issue_number and parsed.issue_number:
        if candidate.issue_number.lstrip("0") == parsed.issue_number.lstrip("0"):
            score += 30.0
            reasons.append(f"Issue number matched (#{candidate.issue_number}) (+30)")
        else:
            score -= 30.0
            reasons.append(f"Issue number mismatch ({candidate.issue_number} vs {parsed.issue_number}) (-30)")

    # 3. Series Name Matching (+25 / -50)
    norm_cand_series = normalize_title(candidate.series_name)
    norm_parsed_series = normalize_title(parsed.series_name)

    if norm_cand_series and norm_parsed_series:
        if norm_cand_series == norm_parsed_series:
            score += 25.0
            reasons.append(f"Series name matched '{candidate.series_name}' (+25)")
        elif norm_cand_series.startswith(norm_parsed_series) or norm_parsed_series.startswith(norm_cand_series):
            score += 15.0
            reasons.append(f"Partial series name match '{candidate.series_name}' (+15)")
        else:
            score -= 50.0
            reasons.append(f"Conflicting series name '{candidate.series_name}' vs '{parsed.series_name}' (-50)")

    # 4. Publication Year Matching (+15 / -50)
    if candidate.publication_year > 0 and parsed.year > 0:
        if candidate.publication_year == parsed.year:
            score += 15.0
            reasons.append(f"Publication year matched ({candidate.publication_year}) (+15)")
        elif abs(candidate.publication_year - parsed.year) <= 1:
            score += 5.0
            reasons.append(f"Close publication year ({candidate.publication_year} vs {parsed.year}) (+5)")
        else:
            score -= 50.0
            reasons.append(f"Conflicting publication year ({candidate.publication_year} vs {parsed.year}) (-50)")

    # 5. Publisher Matching (+15 / -25)
    if candidate.publisher and parsed.publisher:
        if normalize_title(candidate.publisher) == normalize_title(parsed.publisher):
            score += 15.0
            reasons.append(f"Publisher matched '{candidate.publisher}' (+15)")
        else:
            score -= 25.0
            reasons.append(f"Conflicting publisher '{candidate.publisher}' vs '{parsed.publisher}' (-25)")

    # Clamp score between 0.0 and 100.0
    final_score = max(0.0, min(100.0, score))

    if final_score >= 90.0:
        status = STATUS_AUTO_ACCEPT
    elif final_score >= 50.0:
        status = STATUS_MANUAL_REVIEW
    else:
        status = STATUS_UNRESOLVED

    return final_score, status, reasons
