"""
Minimal drop-in replacement for the standard-library `imghdr` module,
which was removed in Python 3.13 (PEP 594).

Found 2026-11-13 wiring up local dispatch for Step 2 ("run selected
accounts through vertical pipelines"): healthcare_unified.py,
corporate_fixed.py and mdu_unified.py all call imghdr.what(None,
h=<bytes>) directly as part of their pre-VLM image validation (the
"validate images before VLM" step CLAUDE.md documents as the fix for
the corporate 0%-PROSPECT regression). On Python 3.13+ that raised
ModuleNotFoundError — caught by the processor-level try/except in
unified_worker.py, so the failure wasn't a crash, but every single
account would silently come back as an error/no_evidence result.

Only implements the one call shape this codebase actually uses:
what(None, h=<raw bytes>) — never called with a real file path/object.
Magic-byte signatures match CPython's own (removed) imghdr source for
the formats these enrichers validate (CLAUDE.md: "jpeg, png, gif,
webp"), plus bmp since mdu_unified.py's website-scraping source can
plausibly hit it. The jpeg check here is intentionally broader than
stdlib's (any \\xff\\xd8\\xff-prefixed SOI marker, not just
JFIF/Exif/\\xff\\xd8\\xff\\xdb) — every real JPEG starts that way, so
this can only produce MORE true positives, never a false negative on a
real jpeg stdlib would have caught.
"""


def what(file=None, h: bytes = None) -> str | None:
    if h is None:
        return None

    if h.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    if h.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if h[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if h[:4] == b'RIFF' and h[8:12] == b'WEBP':
        return 'webp'
    if h[:2] == b'BM':
        return 'bmp'
    return None
