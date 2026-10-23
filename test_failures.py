"""Debug the two test failures"""
import re

# Test 1: Why does meme screen match?
text1 = "They have this meme generation on the screen which is quite engaging and sometimes it shows you instructions"

# Check which pattern is matching
patterns = [
    (r"\btvs?\b", r"\b(watch|watching|view|viewing|showing|playing|on)\b"),
    (r"\bscreens?\b", r"\b(watch|watching|view|viewing|showing|playing|on)\b"),
]

print("Test 1: Meme Screen")
print(f"Text: {text1}\n")

for keyword, verb in patterns:
    keyword_match = re.search(keyword, text1, re.I)
    verb_match = re.search(verb, text1, re.I)
    
    if keyword_match and verb_match:
        print(f"Pattern: {keyword} + {verb}")
        print(f"  Keyword match: '{keyword_match.group()}' at position {keyword_match.start()}")
        print(f"  Verb match: '{verb_match.group()}' at position {verb_match.start()}")
        print(f"  Problem: 'on the screen' - 'on' is too generic!\n")

# Test 8: Check actual distance
text8 = "The waiting room was spacious and comfortable with nice chairs, magazines, coffee, and other amenities. They also had a TV mounted on the far wall."

print("\nTest 8: Waiting Room Distance")
print(f"Text: {text8}\n")

# Find positions
waiting_match = re.search(r"waiting room", text8, re.I)
tv_match = re.search(r"\btv\b", text8, re.I)

if waiting_match and tv_match:
    print(f"'waiting room' at position {waiting_match.start()}-{waiting_match.end()}")
    print(f"'TV' at position {tv_match.start()}-{tv_match.end()}")
    print(f"Distance: {tv_match.start() - waiting_match.end()} characters")
    print(f"Window limit: 30 characters")
    print(f"Should match: {tv_match.start() - waiting_match.end() <= 30}")

# Check what the actual pattern matches
pattern_fwd = r"\b(tv|television|screen)\b.{0,30}\b(waiting room|waiting area|lobby)\b"
pattern_rev = r"\b(waiting room|waiting area|lobby)\b.{0,30}\b(tv|television|screen)\b"

match_fwd = re.search(pattern_fwd, text8, re.I)
match_rev = re.search(pattern_rev, text8, re.I)

print(f"\nForward pattern match: {match_fwd is not None}")
print(f"Reverse pattern match: {match_rev is not None}")

if match_rev:
    print(f"Reverse match span: {match_rev.group()}")

