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

# a small, fixed set of words that negate whatever comes after them.
# used to avoid matching a claim that's actually being denied, like
# "I'm not going to tell you the tests passed" or "the build didn't
# succeed." this isn't real negation handling, just a guard against the
# most common ways someone denies a claim right before stating it.
_NEGATION_CUE_RE = re.compile(
    r"\b(not|never|no)\b|"
    r"\b(?:did|does|is|was|were|are|can|could|would|should|won)n['’]t\b",
    re.I,
)


def _preceded_by_negation(text, start, window=45):
    preceding = text[max(0, start - window):start]
    return bool(_NEGATION_CUE_RE.search(preceding))


_TEST_PASSED_RE = re.compile(
    r"\btests?\s+(?:(?:is|are)\s+)?(?:still\s+|now\s+|already\s+|finally\s+)?"
    r"(?:pass(?:ed|ing)?|succeeded)\b"
    r"|\b(?:everything|all)(?:'s|\s+is)?\s+green\b",
    re.I,
)
_TEST_FAILED_RE = re.compile(
    r"\btests?\s+(?:(?:is|are)\s+)?(?:still\s+)?"
    r"(?:fail(?:ed|ing)?|did\s+not\s+pass|didn['’]t\s+pass)\b",
    re.I,
)
_BUILD_SUCCEEDED_RE = re.compile(
    r"\bbuild\s+(?:(?:is|are)\s+)?(?:succeed(?:ed|s|ing)?|pass(?:ed|es|ing)?|success(?:ful)?)\b", re.I
)
_BUILD_FAILED_RE = re.compile(
    r"\bbuild\s+(?:(?:is|are)\s+)?(?:fail(?:ed|s|ing)?|broke|broken)\b", re.I
)
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


# priority order: more specific claim types first. also used directly
# by parse_claims_multi to find every claim in a longer message.
_ALL_PATTERNS = [
    ("FILE_CREATED", _FILE_RE_A, lambda m: {"filename": m.group(1)}),
    ("FILE_CREATED", _FILE_RE_B, lambda m: {"filename": m.group(1)}),
    ("FILE_CREATED", _FILE_RE_C, lambda m: {"filename": m.group(1)}),
    ("FILE_CREATED", _FILE_RE_NO_NAME, lambda m: {"filename": None}),
    ("COMMIT_CREATED", _COMMIT_RE, lambda m: {}),
    ("BUILD_FAILED", _BUILD_FAILED_RE, lambda m: {}),
    ("BUILD_SUCCEEDED", _BUILD_SUCCEEDED_RE, lambda m: {}),
    ("TEST_FAILED", _TEST_FAILED_RE, lambda m: {}),
    ("TEST_PASSED", _TEST_PASSED_RE, lambda m: {}),
]


def parse_claim(text):
    """
    Look for a single claim in `text`.

    Returns (claim_type, params). claim_type is None if nothing matched,
    which callers must treat as "can't verify this," never as "true."
    """
    for ctype, pattern, params_fn in _ALL_PATTERNS:
        for m in pattern.finditer(text):
            if _preceded_by_negation(text, m.start()):
                continue
            return ctype, params_fn(m)
    return None, {}


def parse_claims_multi(text):
    """
    Find every claim in `text`, not just the first one. A single message
    can easily say "I ran the tests and they passed, and I created
    login.html", and both of those need checking.

    Returns a list of (claim_type, params, matched_snippet) in the order
    they appear. If two patterns match the same span of text, only the
    first (highest priority) one is kept, so a sentence isn't counted
    twice. Matches immediately preceded by a negation cue are skipped
    entirely rather than counted as an assertion.
    """
    found = []
    claimed_spans = []
    for ctype, pattern, params_fn in _ALL_PATTERNS:
        for m in pattern.finditer(text):
            span = m.span()
            if _preceded_by_negation(text, span[0]):
                continue
            if any(not (span[1] <= s[0] or span[0] >= s[1]) for s in claimed_spans):
                continue
            claimed_spans.append(span)
            found.append((span[0], ctype, params_fn(m), m.group(0)))
    found.sort(key=lambda x: x[0])
    return [(ctype, params, snippet) for _, ctype, params, snippet in found]
