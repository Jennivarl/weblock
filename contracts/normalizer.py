"""
Stage 2 of Evidence Freezer: normalize web content before hashing.

Two validators fetching the same page a few seconds apart get slightly
different bytes: rotating ads, view counters, "posted 3 minutes ago"
timestamps, session IDs in the URL. Hash that raw and validators never
agree, so the contract can never finalize under strict equality. This
module strips exactly that class of noise before anything gets hashed,
so the same underlying page always produces the same hash regardless of
which validator fetched it or when.

Plain Python, no GenLayer imports, no network calls, fully unit-testable
standalone.
"""

import hashlib
import re
from dataclasses import dataclass

_WHITESPACE_RE = re.compile(r"\s+")

# "3 minutes ago", "posted 2 hours ago", "updated 1 day ago"
_RELATIVE_TIME_RE = re.compile(
    r"\b\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b",
    re.IGNORECASE,
)

# "1,234 views", "42 comments", "3.2k likes", "128 upvotes"
_COUNTER_RE = re.compile(
    r"\b[\d,]+(?:\.\d+)?[kKmM]?\+?\s+"
    r"(?:views?|comments?|likes?|shares?|reads?|upvotes?|downvotes?|"
    r"downloads?|replies?|reactions?)\b",
    re.IGNORECASE,
)

# Query-string keys that identify a visitor/session/campaign rather than
# the actual resource, so they don't belong in a content-identity hash.
_TRACKING_PARAM_KEYS = frozenset(
    [
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "ref",
        "referrer",
        "session",
        "sessionid",
        "session_id",
        "sid",
        "_ga",
        "igshid",
        "spm",
    ]
)


@dataclass
class NormalizedPage:
    normalized_text: str
    text_hash: str


def normalize_text(text: str) -> str:
    """
    Collapse whitespace, strip relative-time stamps and engagement
    counters, and lowercase. This is deliberately aggressive: the goal
    is content-identity for hashing, not a readable diff.
    """
    if text is None:
        return ""
    normalized = _RELATIVE_TIME_RE.sub(" ", text)
    normalized = _COUNTER_RE.sub(" ", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip().lower()


def normalize_url(url: str) -> str:
    """
    Drop the fragment and any tracking query params, so
    example.com/a?utm_source=x and example.com/a are treated as the same
    resource. Remaining query params are kept but sorted, so param order
    (which shouldn't vary for the same logical request, but might) can't
    silently change the hash.
    """
    if url is None:
        return ""
    url = url.strip()
    url = url.split("#", 1)[0]

    if "?" not in url:
        return url

    base, query = url.split("?", 1)
    if not query:
        return base

    kept_params = []
    for pair in query.split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0].lower()
        if key in _TRACKING_PARAM_KEYS:
            continue
        kept_params.append(pair)

    if not kept_params:
        return base

    kept_params.sort()
    return base + "?" + "&".join(kept_params)


def hash_text(text: str) -> str:
    """Deterministic content hash of already-normalized text."""
    return "0x" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_bytes(data: bytes) -> str:
    """Deterministic hash of raw bytes, e.g. a screenshot."""
    if data is None:
        data = b""
    return "0x" + hashlib.sha256(data).hexdigest()


def normalize_and_hash(text: str) -> NormalizedPage:
    normalized = normalize_text(text)
    return NormalizedPage(normalized_text=normalized, text_hash=hash_text(normalized))


def excerpt_present(page_text: str, excerpt: str) -> bool:
    """
    True if `excerpt` appears in `page_text` after both are normalized
    the same way. Guards against freezing a claim about a page that
    never actually contained the excerpt in the first place.
    """
    normalized_page = normalize_text(page_text)
    normalized_excerpt = normalize_text(excerpt)
    if not normalized_excerpt:
        return False
    return normalized_excerpt in normalized_page
