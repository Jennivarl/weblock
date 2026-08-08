"""
Unit tests for the Stage 2 normalizer (contracts/normalizer.py). Pure
Python, no GenLayer runtime, no network calls -- run with plain `pytest`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contracts.normalizer import (
    excerpt_present,
    hash_bytes,
    hash_text,
    normalize_and_hash,
    normalize_text,
    normalize_url,
)


def test_collapses_whitespace():
    assert normalize_text("hello   \n\n  world") == "hello world"


def test_lowercases():
    assert normalize_text("Hello World") == "hello world"


def test_strips_relative_time_stamps():
    text = "Breaking news, posted 3 minutes ago, updated 2 hours ago."
    normalized = normalize_text(text)
    assert "minutes ago" not in normalized
    assert "hours ago" not in normalized
    assert "breaking news" in normalized


def test_strips_view_counters():
    text = "Great article. 1,234 views. 42 comments. 3.2k likes."
    normalized = normalize_text(text)
    assert "views" not in normalized
    assert "comments" not in normalized
    assert "likes" not in normalized
    assert "great article" in normalized


def test_same_page_different_counters_same_hash():
    page_at_noon = "Contract terms unchanged. 100 views. Posted 5 minutes ago."
    page_at_five = "Contract terms unchanged. 4,502 views. Posted 5 hours ago."
    assert normalize_text(page_at_noon) == normalize_text(page_at_five)


def test_none_text_returns_empty():
    assert normalize_text(None) == ""


def test_url_strips_fragment():
    assert normalize_url("https://example.com/a#section-2") == "https://example.com/a"


def test_url_strips_tracking_params():
    url = "https://example.com/a?utm_source=twitter&utm_campaign=x&id=42"
    assert normalize_url(url) == "https://example.com/a?id=42"


def test_url_strips_all_tracking_leaves_bare_url():
    url = "https://example.com/a?utm_source=twitter&fbclid=abc"
    assert normalize_url(url) == "https://example.com/a"


def test_url_sorts_remaining_params():
    url1 = "https://example.com/a?b=2&a=1"
    url2 = "https://example.com/a?a=1&b=2"
    assert normalize_url(url1) == normalize_url(url2)


def test_url_with_no_query_string_unchanged():
    assert normalize_url("https://example.com/a") == "https://example.com/a"


def test_url_none_returns_empty():
    assert normalize_url(None) == ""


def test_hash_text_is_deterministic():
    assert hash_text("same text") == hash_text("same text")


def test_hash_text_differs_for_different_text():
    assert hash_text("text a") != hash_text("text b")


def test_hash_text_has_0x_prefix_and_hex_length():
    h = hash_text("anything")
    assert h.startswith("0x")
    assert len(h) == 2 + 64


def test_hash_bytes_deterministic():
    assert hash_bytes(b"\x89PNG\r\n") == hash_bytes(b"\x89PNG\r\n")


def test_hash_bytes_none_does_not_crash():
    result = hash_bytes(None)
    assert result.startswith("0x")


def test_normalize_and_hash_matches_manual_steps():
    result = normalize_and_hash("Hello   World")
    assert result.normalized_text == "hello world"
    assert result.text_hash == hash_text("hello world")


def test_excerpt_present_exact_match():
    page = "The full agreement is available. The deadline is March 1st. Thank you."
    assert excerpt_present(page, "The deadline is March 1st.") is True


def test_excerpt_present_survives_counter_noise():
    page = "Important notice. 5,921 views. The deadline is March 1st. Posted 2 hours ago."
    assert excerpt_present(page, "the deadline is march 1st") is True


def test_excerpt_absent():
    page = "This page says nothing about any deadlines at all."
    assert excerpt_present(page, "The deadline is March 1st.") is False


def test_excerpt_empty_string_never_present():
    assert excerpt_present("any page text here", "") is False
    assert excerpt_present("any page text here", "   ") is False
