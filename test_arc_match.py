import re

def _is_story_arc_matching(expected_arc_name: str, actual_story_arc_tag: str) -> bool:
    if not expected_arc_name or not actual_story_arc_tag:
        return False
    
    norm_expected = re.sub(r'["\'\(\):]', " ", expected_arc_name).lower().strip()
    norm_actual = re.sub(r'["\'\(\):]', " ", actual_story_arc_tag).lower().strip()

    norm_expected_clean = " ".join(norm_expected.split())
    norm_actual_clean = " ".join(norm_actual.split())

    if not norm_expected_clean or not norm_actual_clean:
        return False

    if norm_expected_clean in norm_actual_clean or norm_actual_clean in norm_expected_clean:
        return True

    expected_words = [w for w in norm_expected_clean.split() if len(w) > 3]
    if expected_words and any(w in norm_actual_clean for w in expected_words):
        return True

    return False

# Test cases
tests = [
    ('"Marvel Multiverse" Marvel Zombies', 'Marvel Multiverse" Marvel Zombies', True),
    ("Marvel Zombies Complete Saga", 'Marvel Multiverse" Marvel Zombies', True),
    ("Marvel Zombies", 'Marvel Multiverse" Marvel Zombies', True),
    ("Marvel Zombies Complete Saga", "Marvel Zombies", True),
    ("Marvel Zombies", "Batman", False),
]

for exp, act, expected_res in tests:
    res = _is_story_arc_matching(exp, act)
    status = "✓" if res == expected_res else "✗ FAIL"
    print(f"  {status} exp={exp:35s} vs act={act:35s} -> {res}")
