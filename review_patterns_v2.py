"""
Improved Pattern Matching with Sentence-Level Co-occurrence
Fixes:
1. Medium confidence patterns require viewing verb in SAME sentence
2. Waiting room patterns work bidirectionally (keyword-context OR context-keyword)
"""

import re
from typing import Dict, List, Tuple


# ============================================================================
# RESTAURANT/BAR PATTERNS
# ============================================================================

# High confidence - strong signal, low noise (no co-occurrence needed)
RESTAURANT_HIGH_PATTERNS = [
    r"\bwatch(ing)? (the )?(game|games|match|matches|fight|fights)\b",
    r"\blive sports\b",
    r"\bsports bar\b",
    r"\bcatch (the )?(game|match|fight)\b",
    r"\b(big[- ]screen|big screen) tvs?\b",
    r"\bmultiple tvs?\b",
    r"\bwall[- ]to[- ]wall tvs?\b",
    r"\bshowing (all )?(the )?(games|matches|fights)\b",
    r"\bgame[ -]?day\b",
    r"\bwatch party\b",
]

# Medium confidence - need viewing verb co-occurrence in same sentence
RESTAURANT_MEDIUM_PATTERNS = [
    # (keyword_pattern, required_viewing_verb_pattern)
    # Note: Removed "on" - too generic ("on the screen" isn't viewing)
    (r"\btvs?\b", r"\b(watch|watching|view|viewing|showing|playing)\b"),
    (r"\btelevisions?\b", r"\b(watch|watching|view|viewing|showing|playing)\b"),
    (r"\bscreens?\b", r"\b(watch|watching|view|viewing|showing|playing)\b"),
    (r"\bfootball\b", r"\b(watch|watching|view|game|playing)\b"),
    (r"\bsoccer\b", r"\b(watch|watching|view|game|playing)\b"),
    (r"\bbasketball\b", r"\b(watch|watching|view|game|playing)\b"),
    (r"\bnfl\b", r"\b(watch|watching|view|game|playing)\b"),
    (r"\bmlb\b", r"\b(watch|watching|view|game|playing)\b"),
    (r"\bnba\b", r"\b(watch|watching|view|game|playing)\b"),
    (r"\bnhl\b", r"\b(watch|watching|view|game|playing)\b"),
    (r"\bufc\b", r"\b(watch|watching|view|game|playing|fight)\b"),
    (r"\bgame night\b", r"\b(watch|watching|view|showing|playing)\b"),
]


# ============================================================================
# DENTAL/AUTO WAITING ROOM PATTERNS
# ============================================================================

# High confidence - strong signal (no co-occurrence needed)
# Limited to 50 chars to avoid matching across full review
WAITING_ROOM_HIGH_PATTERNS = [
    r"\bwaiting room.{0,50}\btv\b",
    r"\bwaiting area.{0,50}\bscreen\b",
    r"\blobby.{0,50}\btelevision\b",
    r"\bcomfortable wait.{0,50}\btv\b",
    r"\bservice area.{0,50}\bscreen\b",
    r"\bwhile (you )?wait.{0,50}\btv\b",
]

# Medium confidence - bidirectional proximity patterns
# These match within 30 chars in EITHER direction
WAITING_ROOM_MEDIUM_PATTERNS = [
    # (keyword, context, window_size) - bidirectional
    ("tv|television|screen", "waiting room|waiting area|lobby", 30),
    ("tv|television|screen", "while (you |I )?wait", 30),
    ("tv|television|screen", "service (area|lounge|center)", 30),
]


# ============================================================================
# SENTENCE SPLITTING
# ============================================================================

def split_into_sentences(text: str) -> List[str]:
    """
    Split text into sentences using simple heuristics.
    Handles common sentence endings: . ! ? with capital letter following.
    """
    if not text:
        return []

    # Replace common abbreviations to avoid false splits
    text = text.replace("Mr.", "Mr").replace("Mrs.", "Mrs").replace("Dr.", "Dr")
    text = text.replace("etc.", "etc").replace("i.e.", "ie").replace("e.g.", "eg")

    # Split on sentence boundaries: . ! ? followed by space and capital
    sentences = re.split(r'[.!?]+\s+(?=[A-Z])', text)

    # Also split on newlines (common in reviews)
    final_sentences = []
    for sent in sentences:
        final_sentences.extend(sent.split('\n'))

    return [s.strip() for s in final_sentences if s.strip()]


# ============================================================================
# IMPROVED MATCHING LOGIC
# ============================================================================

def check_cooccurrence_in_sentence(sentence: str, keyword_pattern: str, verb_pattern: str) -> bool:
    """
    Check if both keyword and viewing verb appear in the same sentence.

    Args:
        sentence: Single sentence to check
        keyword_pattern: Regex for keyword (e.g., r"\btvs?\b")
        verb_pattern: Regex for viewing verb (e.g., r"\b(watch|watching)\b")

    Returns:
        True if both patterns found in sentence
    """
    keyword_re = re.compile(keyword_pattern, re.I)
    verb_re = re.compile(verb_pattern, re.I)

    has_keyword = keyword_re.search(sentence) is not None
    has_verb = verb_re.search(sentence) is not None

    return has_keyword and has_verb


def check_bidirectional_proximity(text: str, keyword: str, context: str, window: int = 30) -> re.Match:
    """
    Check if keyword and context appear within window characters of each other,
    in EITHER direction.

    Args:
        text: Text to search
        keyword: Keyword pattern (e.g., "tv|television|screen")
        context: Context pattern (e.g., "waiting room|lobby")
        window: Maximum distance in characters

    Returns:
        Match object if found, None otherwise
    """
    # Pattern 1: keyword [gap] context
    pattern1 = rf"\b({keyword})\b.{{0,{window}}}\b({context})\b"
    match1 = re.search(pattern1, text, re.I)
    if match1:
        return match1

    # Pattern 2: context [gap] keyword
    pattern2 = rf"\b({context})\b.{{0,{window}}}\b({keyword})\b"
    match2 = re.search(pattern2, text, re.I)
    if match2:
        return match2

    return None


def match_review_v2(review_text: str,
                    high_patterns: List[str],
                    medium_patterns: List[Tuple[str, str]],
                    is_waiting_room: bool = False) -> Dict:
    """
    Match patterns against review text with sentence-level co-occurrence.

    Args:
        review_text: Review text to analyze
        high_patterns: List of high-confidence regex patterns (no co-occurrence needed)
        medium_patterns: List of (keyword, verb) tuples OR (keyword, context, window) tuples
        is_waiting_room: If True, use bidirectional proximity logic for medium patterns

    Returns:
        {
            'matched': bool,
            'confidence': 'High' | 'Medium' | None,
            'matched_pattern': str,
            'snippet': str,
            'matched_keyword': str
        }
    """
    if not review_text:
        return {
            'matched': False,
            'confidence': None,
            'matched_pattern': None,
            'snippet': None
        }

    # Check high confidence patterns (no co-occurrence required)
    for pattern_str in high_patterns:
        pattern = re.compile(pattern_str, re.I)
        match = pattern.search(review_text)
        if match:
            start = max(0, match.start() - 60)
            end = min(len(review_text), match.end() + 60)
            snippet = review_text[start:end].strip()
            return {
                'matched': True,
                'confidence': 'High',
                'matched_pattern': pattern_str,
                'snippet': snippet,
                'matched_keyword': match.group(0)
            }

    # Check medium confidence patterns with appropriate logic
    if is_waiting_room:
        # Bidirectional proximity for waiting room patterns
        for keyword, context, window in medium_patterns:
            match = check_bidirectional_proximity(review_text, keyword, context, window)
            if match:
                start = max(0, match.start() - 60)
                end = min(len(review_text), match.end() + 60)
                snippet = review_text[start:end].strip()
                return {
                    'matched': True,
                    'confidence': 'Medium',
                    'matched_pattern': f"{keyword} <within {window} chars> {context}",
                    'snippet': snippet,
                    'matched_keyword': match.group(0)
                }
    else:
        # Sentence-level co-occurrence for restaurant patterns
        sentences = split_into_sentences(review_text)

        for keyword_pattern, verb_pattern in medium_patterns:
            for sentence in sentences:
                if check_cooccurrence_in_sentence(sentence, keyword_pattern, verb_pattern):
                    # Find the match position for snippet
                    keyword_re = re.compile(keyword_pattern, re.I)
                    match = keyword_re.search(sentence)
                    if match:
                        # Return the full sentence as snippet
                        return {
                            'matched': True,
                            'confidence': 'Medium',
                            'matched_pattern': f"{keyword_pattern} + {verb_pattern}",
                            'snippet': sentence,
                            'matched_keyword': match.group(0)
                        }

    return {'matched': False}


def compile_patterns_v2(high: List[str],
                        medium: List,
                        is_waiting_room: bool = False) -> Tuple[List[str], List]:
    """
    Compile patterns for v2 matching.

    Args:
        high: List of high confidence pattern strings
        medium: List of tuples (keyword, verb) or (keyword, context, window)
        is_waiting_room: Whether these are waiting room patterns

    Returns:
        (high_patterns, medium_patterns) - already in correct format for match_review_v2
    """
    # High patterns stay as strings (will be compiled in match_review_v2)
    # Medium patterns stay as tuples
    return high, medium


# ============================================================================
# VALIDATION TESTS
# ============================================================================

if __name__ == "__main__":
    print("="*80)
    print("PATTERN MATCHING V2 - VALIDATION TESTS")
    print("="*80)

    # Test 1: Punch Bowl Social meme screen (should NOT match)
    print("\n1. Punch Bowl Social - Meme Screen Test")
    text1 = "They have this meme generation on the screen which is quite engaging and sometimes it shows you instructions"

    high, medium = compile_patterns_v2(RESTAURANT_HIGH_PATTERNS, RESTAURANT_MEDIUM_PATTERNS)
    result1 = match_review_v2(text1, high, medium, is_waiting_room=False)

    print(f"   Text: {text1[:80]}...")
    print(f"   Matched: {result1['matched']}")
    print(f"   Expected: False (no viewing verb)")
    print(f"   ✓ PASS" if not result1['matched'] else "   ✗ FAIL")

    # Test 2: Pinstripes soccer ball (should NOT match)
    print("\n2. Pinstripes - Soccer Ball Test")
    text2 = "darts, what looks like beer pong but with garbage cans and soccer ball! There were other things to play"

    result2 = match_review_v2(text2, high, medium, is_waiting_room=False)

    print(f"   Text: {text2[:80]}...")
    print(f"   Matched: {result2['matched']}")
    print(f"   Expected: False (no viewing verb)")
    print(f"   ✓ PASS" if not result2['matched'] else "   ✗ FAIL")

    # Test 3: Legitimate TV mention (SHOULD match)
    print("\n3. Legitimate TV Viewing Test")
    text3 = "Great sports bar! We watched the football game on multiple TVs while enjoying our meal."

    result3 = match_review_v2(text3, high, medium, is_waiting_room=False)

    print(f"   Text: {text3[:80]}...")
    print(f"   Matched: {result3['matched']}")
    print(f"   Confidence: {result3.get('confidence', 'N/A')}")
    print(f"   Expected: True (High confidence - 'watch' + 'game')")
    print(f"   ✓ PASS" if result3['matched'] else "   ✗ FAIL")

    # Test 4: TV with watching in different sentence (should NOT match)
    print("\n4. Cross-Sentence Test (should NOT match)")
    text4 = "The screen flickered during our visit. Later we were watching the sunset outside."

    result4 = match_review_v2(text4, high, medium, is_waiting_room=False)

    print(f"   Text: {text4[:80]}...")
    print(f"   Matched: {result4['matched']}")
    print(f"   Expected: False (screen and watching in different sentences)")
    print(f"   ✓ PASS" if not result4['matched'] else "   ✗ FAIL")

    # Test 5: TV with watching in SAME sentence (SHOULD match)
    print("\n5. Same-Sentence Co-occurrence Test (SHOULD match)")
    text5 = "They have TVs showing the game which was great to watch while eating."

    result5 = match_review_v2(text5, high, medium, is_waiting_room=False)

    print(f"   Text: {text5[:80]}...")
    print(f"   Matched: {result5['matched']}")
    print(f"   Confidence: {result5.get('confidence', 'N/A')}")
    print(f"   Expected: True (Medium confidence - TVs + showing/watch in same sentence)")
    print(f"   ✓ PASS" if result5['matched'] else "   ✗ FAIL")

    # Test 6: Bidirectional waiting room (forward order)
    print("\n6. Waiting Room - Forward Order Test")
    text6 = "Nice dental office with a TV in the waiting room to help pass the time."

    high_wr, medium_wr = compile_patterns_v2(
        WAITING_ROOM_HIGH_PATTERNS,
        WAITING_ROOM_MEDIUM_PATTERNS,
        is_waiting_room=True
    )
    result6 = match_review_v2(text6, high_wr, medium_wr, is_waiting_room=True)

    print(f"   Text: {text6[:80]}...")
    print(f"   Matched: {result6['matched']}")
    print(f"   Expected: True (TV near waiting room)")
    print(f"   ✓ PASS" if result6['matched'] else "   ✗ FAIL")

    # Test 7: Bidirectional waiting room (reverse order)
    print("\n7. Waiting Room - Reverse Order Test")
    text7 = "The waiting room has a nice flat screen TV for entertainment."

    result7 = match_review_v2(text7, high_wr, medium_wr, is_waiting_room=True)

    print(f"   Text: {text7[:80]}...")
    print(f"   Matched: {result7['matched']}")
    print(f"   Expected: True (waiting room before TV)")
    print(f"   ✓ PASS" if result7['matched'] else "   ✗ FAIL")

    # Test 8: Waiting room too far apart (should NOT match with 30 char window)
    print("\n8. Waiting Room - Too Far Apart Test")
    text8 = "The waiting room was spacious and comfortable with nice chairs, magazines, coffee, and other amenities. They also had a TV mounted on the far wall."

    result8 = match_review_v2(text8, high_wr, medium_wr, is_waiting_room=True)

    print(f"   Text: {text8[:80]}...")
    print(f"   Matched: {result8['matched']}")
    print(f"   Expected: False (TV > 30 chars from 'waiting room')")
    print(f"   ✓ PASS" if not result8['matched'] else "   ✗ FAIL")

    print("\n" + "="*80)
    print("VALIDATION COMPLETE")
    print("="*80)
