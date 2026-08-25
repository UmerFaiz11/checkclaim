"""
Claim parsing.

Turns a piece of natural-language text into one of a small, fixed set
of claim types, using plain regex. No LLM, no fuzzy matching. If the
text doesn't match a known pattern, we return None and the caller has
to treat that as "unknown," never as "true."

The patterns are deliberately narrow. Better to miss a claim (which is
safe, it just falls back to UNKNOWN) than to guess at something and be
wrong. Widening these is fine as long as UNKNOWN stays the fallback for
anything that doesn't clearly match.
"""

import re

_TEST_RE = re.compile(r"\btests?\s+(pass(ed)?|succeeded)\b", re.I)
_BUILD_RE = re.compile(r"\bbuild\s+(succeeded|passed|success(ful)?)\b", re.I)
_COMMIT_RE = re.compile(
    r"\bcommit\s+(was\s+)?created\b|\bcommitted\s+the\s+changes\b|\bchanges\s+(were\s+)?committed\b",
    re.I,
)

# a few common ways people phrase "a file was created"
#   File 'output.txt' was created
#   The file "output.txt" was created
#   Created file output.txt
_FILE_RE_A = re.compile(r"\bfile\s+['\"]([^'\"]+)['\"]\s+was\s+created\b", re.I)
_FILE_RE_B = re.compile(r"\bcreated\s+(?:the\s+)?file\s+['\"]?([\w./\-]+)['\"]?\b", re.I)
_FILE_RE_C = re.compile(r"\bfile\s+(\S+)\s+was\s+created\b", re.I)
_FILE_RE_NO_NAME = re.compile(r"\bfile\s+was\s+created\b", re.I)


def parse_claim(text):
    """
    Look for a single claim in `text`.

    Returns (claim_type, params). claim_type is None if nothing matched,
    which callers must treat as "can't verify this," never as "true."
    """
    for pattern in (_FILE_RE_A, _FILE_RE_B, _FILE_RE_C):
        m = pattern.search(text)
        if m:
            return "FILE_CREATED", {"filename": m.group(1)}
    if _FILE_RE_NO_NAME.search(text):
        return "FILE_CREATED", {"filename": None}

    if _COMMIT_RE.search(text):
        return "COMMIT_CREATED", {}

    if _BUILD_RE.search(text):
        return "BUILD_SUCCEEDED", {}

    if _TEST_RE.search(text):
        return "TEST_PASSED", {}

    return None, {}


# order matters here: more specific patterns for a given claim type go
# first, so parse_claims_multi picks up the best match at each position
_ALL_PATTERNS = [
    ("FILE_CREATED", _FILE_RE_A, lambda m: {"filename": m.group(1)}),
    ("FILE_CREATED", _FILE_RE_B, lambda m: {"filename": m.group(1)}),
    ("FILE_CREATED", _FILE_RE_C, lambda m: {"filename": m.group(1)}),
    ("FILE_CREATED", _FILE_RE_NO_NAME, lambda m: {"filename": None}),
    ("COMMIT_CREATED", _COMMIT_RE, lambda m: {}),
    ("BUILD_SUCCEEDED", _BUILD_RE, lambda m: {}),
    ("TEST_PASSED", _TEST_RE, lambda m: {}),
]


def parse_claims_multi(text):
    """
    Find every claim in `text`, not just the first one. A single message
    can easily say "I ran the tests and they passed, and I created
    login.html", and both of those need checking.

    Returns a list of (claim_type, params, matched_snippet) in the order
    they appear. If two patterns match the same span of text, only the
    first (highest priority) one is kept, so a sentence isn't counted
    twice.
    """
    found = []
    claimed_spans = []
    for ctype, pattern, params_fn in _ALL_PATTERNS:
        for m in pattern.finditer(text):
            span = m.span()
            if any(not (span[1] <= s[0] or span[0] >= s[1]) for s in claimed_spans):
                continue
            claimed_spans.append(span)
            found.append((span[0], ctype, params_fn(m), m.group(0)))
    found.sort(key=lambda x: x[0])
    return [(ctype, params, snippet) for _, ctype, params, snippet in found]
