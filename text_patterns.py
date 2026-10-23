"""
Text Pattern Matching for TV/Screen Evidence
Reused from Usage.py with MPLC-specific enhancements
"""

import re
from typing import List, Dict, Tuple

# Pattern groups from Usage.py + variants for missed cases
HIGH_CONFIDENCE_PATTERNS = [
    r"\bwatch (the )?(game|games|match|matches|fight|fights)\b",
    r"\blive sports\b",
    r"\bsports bar\b",
    r"\bcatch (the )?(game|match|fight)\b",
    r"\b(big[- ]screen|big screen) tvs?\b",
    r"\bmultiple tvs?\b",
    r"\bwall[- ]to[- ]wall tvs?\b",
    r"\bshowing (all )?(the )?(games|matches|fights)\b",
    r"\bgame[ -]?day\b",  # Added: gameday, game-day, game day
    r"\bwatch party\b",
    r"\bnfl sunday ticket\b",
    r"\bfootball on\b",
    r"\bcollege football\b",
    r"\bshowing live sports\b",
    r"\bcome watch\b",
    r"\bjoin us to watch\b",
    r"\bfitness center.*\btv\b",
    r"\bgym.*\bscreen\b",
    r"\bbreak room.*\btv\b",
    r"\blounge.*\btelevision\b",
    r"\bgame[ -]?time\b",  # Added: gametime variant
    r"\bbig screens?\b",  # Added: big screen variant
]

MEDIUM_CONFIDENCE_PATTERNS = [
    r"\btvs?\b",
    r"\btelevisions?\b",
    r"\bscreens?\b",
    r"\bprojector\b",
    r"\bfootball\b",
    r"\bsoccer\b",
    r"\bfooty\b",
    r"\bnfl\b",
    r"\bmlb\b",
    r"\bnba\b",
    r"\bnhl\b",
    r"\bufc\b",
    r"\bboxing\b",
    r"\bpay[- ]per[- ]view\b",
    r"\bgame night\b",
    r"\bsports lounge\b",
    r"\bgame-day\b",
    r"\bmarch madness\b",
]

LOW_CONFIDENCE_PATTERNS = [
    r"\bentertainment\b",
    r"\blive events\b",
    r"\bgame\b",
    r"\bmatch\b",
    r"\bfight night\b",
]

NEGATIVE_PATTERNS = [
    r"\bno tv\b",
    r"\bwithout tv\b",
    r"\bno televisions\b",
    r"\bno screens?\b",
]

# Compile patterns
HIGH_REGEXES = [re.compile(p, re.I) for p in HIGH_CONFIDENCE_PATTERNS]
MEDIUM_REGEXES = [re.compile(p, re.I) for p in MEDIUM_CONFIDENCE_PATTERNS]
LOW_REGEXES = [re.compile(p, re.I) for p in LOW_CONFIDENCE_PATTERNS]
NEGATIVE_REGEXES = [re.compile(p, re.I) for p in NEGATIVE_PATTERNS]


def get_text_snippet(text: str, start: int, end: int, window: int = 120) -> str:
    """Extract context around match"""
    snippet_start = max(0, start - window)
    snippet_end = min(len(text), end + window)
    snippet = text[snippet_start:snippet_end]
    snippet = re.sub(r"\s+", " ", snippet).strip()
    return snippet


def score_match(snippet: str, pattern_group: str, matched_keyword: str) -> int:
    """Score a text match based on pattern group and context"""
    score = 0
    snippet_lower = snippet.lower()

    if pattern_group == "high":
        score += 90
    elif pattern_group == "medium":
        score += 60
    elif pattern_group == "low":
        score += 35

    # CRITICAL FIX: For sports/game keywords, require co-occurring viewing/screen term
    # Prevents "game day appetizers" and "Sports Bar" title-tag false positives
    sports_keywords = ["game", "match", "sports", "football", "soccer", "nfl", "nba", "mlb", "nhl", "ufc"]
    viewing_screen_terms = ["watch", "watching", "screen", "screens", "tv", "tvs", "television",
                           "showing", "catch", "big screen", "which game", "what's on"]

    keyword_lower = matched_keyword.lower()
    is_sports_keyword = any(sk in keyword_lower for sk in sports_keywords)
    has_viewing_context = any(vt in snippet_lower for vt in viewing_screen_terms)

    # If sports keyword without viewing context, penalize heavily
    if is_sports_keyword and not has_viewing_context and pattern_group in ["medium", "low"]:
        score -= 40

    # BUG FIX 2: MENU/FOOD CONTEXT DISQUALIFIES MATCH ENTIRELY
    # A sentence cannot be both menu copy AND venue evidence
    # If sentence contains menu/food-order vocabulary + sports/TV keyword → ZERO OUT
    menu_food_terms = [
        "menu", "crave", "appetizer", "appetizers", "entrée", "entree",
        "burger", "sandwich", "dish", "food", "meal",
        "platter", "platters", "catering", "order", "pickup", "delivery", "to-go", "togo"
    ]

    has_menu_food_context = any(mt in snippet_lower for mt in menu_food_terms)

    # If menu/food vocabulary present alongside sports/TV keyword WITHOUT viewing context
    # This is menu copy describing food, not venue evidence describing TVs
    if has_menu_food_context and is_sports_keyword and not has_viewing_context:
        return 0  # Disqualify entirely - not a penalty, a rejection

    # Additional catering-specific disqualification
    # "Party" + catering terms = party platter copy
    has_party_keyword = "party" in snippet_lower
    catering_specific = ["platter", "platters", "catering"]
    has_catering_specific = any(ct in snippet_lower for ct in catering_specific)

    if has_party_keyword and has_catering_specific:
        return 0  # Party platters = catering copy, not watch party evidence

    # Boost for supportive terms (only if not menu/food context)
    if not has_menu_food_context:
        boost_terms = [
            "sports", "football", "soccer", "nfl", "ufc", "boxing",
            "watch", "game", "match", "fight", "bar", "lounge",
            "gym", "fitness", "breakroom", "cafeteria"
        ]
        boost_count = sum(1 for t in boost_terms if t in snippet_lower)
        score += min(boost_count * 3, 15)

    # Penalty for negative patterns
    for neg in NEGATIVE_REGEXES:
        if neg.search(snippet):
            score -= 50

    return max(0, min(score, 100))


def classify_score(score: int) -> str:
    """Classify confidence level"""
    if score >= 85:
        return "Very Strong"
    elif score >= 75:
        return "Strong"
    elif score >= 50:
        return "Medium"
    elif score > 0:
        return "Weak"
    return "Not Applicable"


def find_text_evidence(text: str, source_url: str) -> List[Dict]:
    """Find all TV/screen evidence in text"""
    matches = []

    # HARD MINIMUM THRESHOLD: 50
    # Below 50 = noise (generic word overlap like "game", "match"), not signal
    MINIMUM_QUALIFYING_SCORE = 50

    # Check high confidence patterns
    for regex in HIGH_REGEXES:
        for m in regex.finditer(text):
            snippet = get_text_snippet(text, m.start(), m.end())
            matched_kw = m.group(0)
            score = score_match(snippet, "high", matched_kw)

            # BUG FIX 1: Only include if meets minimum threshold
            if score >= MINIMUM_QUALIFYING_SCORE:
                matches.append({
                    "matched_keyword": matched_kw,
                    "evidence_text": snippet,
                    "confidence_score": score,
                    "pattern_group": "high",
                    "evidence_flag": classify_score(score),
                    "source_url": source_url,
                })

    # Check medium confidence patterns
    for regex in MEDIUM_REGEXES:
        for m in regex.finditer(text):
            snippet = get_text_snippet(text, m.start(), m.end())
            matched_kw = m.group(0)
            score = score_match(snippet, "medium", matched_kw)

            # BUG FIX 1: Only include if meets minimum threshold
            if score >= MINIMUM_QUALIFYING_SCORE:
                matches.append({
                    "matched_keyword": matched_kw,
                    "evidence_text": snippet,
                    "confidence_score": score,
                    "pattern_group": "medium",
                    "evidence_flag": classify_score(score),
                    "source_url": source_url,
                })

    # Check low confidence patterns (only if no better matches)
    if not matches:
        for regex in LOW_REGEXES:
            for m in regex.finditer(text):
                snippet = get_text_snippet(text, m.start(), m.end())
                matched_kw = m.group(0)
                score = score_match(snippet, "low", matched_kw)

                # BUG FIX 1: Only include if meets minimum threshold
                if score >= MINIMUM_QUALIFYING_SCORE:
                    matches.append({
                        "matched_keyword": matched_kw,
                        "evidence_text": snippet,
                        "confidence_score": score,
                        "pattern_group": "low",
                        "evidence_flag": classify_score(score),
                        "source_url": source_url,
                    })
    
    # Deduplicate and sort by score
    seen = set()
    deduped = []
    for item in sorted(matches, key=lambda x: x["confidence_score"], reverse=True):
        key = (item["matched_keyword"].lower(), item["evidence_text"][:50].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    
    return deduped[:10]  # Top 10 matches


def aggregate_text_evidence(all_matches: List[Dict]) -> Tuple[str, int, List[Dict]]:
    """
    Aggregate multiple text matches into overall strength assessment.
    Returns (evidence_strength, best_score, top_matches)
    """
    if not all_matches:
        return "Not Applicable", 0, []
    
    # Get best score
    best_score = max(m["confidence_score"] for m in all_matches)
    
    # Count independent sources (different URLs)
    unique_sources = len(set(m["source_url"] for m in all_matches))
    
    # Boost score if multiple independent sources
    if unique_sources >= 3 and best_score >= 60:
        best_score = min(best_score + 15, 100)
    elif unique_sources >= 2 and best_score >= 75:
        best_score = min(best_score + 10, 100)
    
    strength = classify_score(best_score)
    
    # Get top 3 matches for evidence
    top_matches = sorted(all_matches, key=lambda x: x["confidence_score"], reverse=True)[:3]
    
    return strength, best_score, top_matches
