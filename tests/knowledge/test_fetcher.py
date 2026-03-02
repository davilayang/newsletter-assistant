# tests/knowledge/test_fetcher.py
# Unit tests for the tiered article fetcher.
# All HTTP calls and camoufox are mocked — no network access required.

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.knowledge.fetcher import (
    _fetch_via_jina,
    _fetch_via_mediumapi,
    _medium_article_id,
    fetch_and_cache,
    fetch_articles,
)

# ---------------------------------------------------------------------------
# _medium_article_id
# ---------------------------------------------------------------------------


def test_extract_article_id_standard() -> None:
    url = "https://medium.com/towards-data-science/build-a-rag-pipeline-abc1234567"
    assert _medium_article_id(url) == "abc1234567"


def test_extract_article_id_with_query_string() -> None:
    url = "https://medium.com/some-article-def98765ab?source=email"
    assert _medium_article_id(url) == "def98765ab"


def test_extract_article_id_with_trailing_slash() -> None:
    url = "https://medium.com/some-article-abc12345678/"
    assert _medium_article_id(url) == "abc12345678"


def test_extract_article_id_no_hex_suffix() -> None:
    # URL without a hex ID at the end — Tier 2 should be skipped
    url = "https://medium.com/towards-data-science/no-id-here"
    assert _medium_article_id(url) is None


def test_extract_article_id_too_short_hex() -> None:
    # Hex part too short (< 8 chars) — should not match
    url = "https://medium.com/article-abc123"
    assert _medium_article_id(url) is None


# ---------------------------------------------------------------------------
# _fetch_via_jina — Tier 1
# ---------------------------------------------------------------------------

_VALID_CONTENT = "# Great Article\n\n" + ("x" * 600)
_SHORT_CONTENT = "Too short"
_PAYWALL_CONTENT = "This story is only available to Medium members" + "x" * 600


@patch("src.knowledge.fetcher.httpx.get")
def test_jina_returns_valid_content(mock_get: MagicMock) -> None:
    mock_get.return_value = MagicMock(status_code=200, text=_VALID_CONTENT)
    result = _fetch_via_jina("https://medium.com/article-abc12345678")
    assert result == _VALID_CONTENT


@patch("src.knowledge.fetcher.httpx.get")
def test_jina_returns_empty_on_short_content(mock_get: MagicMock) -> None:
    mock_get.return_value = MagicMock(status_code=200, text=_SHORT_CONTENT)
    assert _fetch_via_jina("https://medium.com/article-abc12345678") == ""


@patch("src.knowledge.fetcher.httpx.get")
def test_jina_returns_empty_on_paywall(mock_get: MagicMock) -> None:
    mock_get.return_value = MagicMock(status_code=200, text=_PAYWALL_CONTENT)
    assert _fetch_via_jina("https://medium.com/article-abc12345678") == ""


@patch("src.knowledge.fetcher.httpx.get")
def test_jina_skips_on_429(mock_get: MagicMock) -> None:
    mock_get.return_value = MagicMock(status_code=429, text="Rate limited")
    assert _fetch_via_jina("https://medium.com/article-abc12345678") == ""


@patch("src.knowledge.fetcher.httpx.get")
def test_jina_skips_on_5xx(mock_get: MagicMock) -> None:
    mock_get.return_value = MagicMock(status_code=503, text="Service unavailable")
    assert _fetch_via_jina("https://medium.com/article-abc12345678") == ""


@patch("src.knowledge.fetcher.httpx.get")
def test_jina_skips_on_timeout(mock_get: MagicMock) -> None:
    import httpx

    mock_get.side_effect = httpx.TimeoutException("timeout")
    assert _fetch_via_jina("https://medium.com/article-abc12345678") == ""


# ---------------------------------------------------------------------------
# _fetch_via_mediumapi — Tier 2
# ---------------------------------------------------------------------------


@patch("src.knowledge.fetcher.settings")
def test_mediumapi_raises_without_key(mock_settings: MagicMock) -> None:
    mock_settings.rapidapi_key = ""
    with pytest.raises(ValueError, match="RAPIDAPI_KEY"):
        _fetch_via_mediumapi("https://medium.com/article-abc12345678")


@patch("src.knowledge.fetcher.httpx.get")
@patch("src.knowledge.fetcher.settings")
def test_mediumapi_returns_valid_content(
    mock_settings: MagicMock, mock_get: MagicMock
) -> None:
    mock_settings.rapidapi_key = "test-key"
    mock_get.return_value = MagicMock(
        status_code=200,
        headers={"x-ratelimit-requests-remaining": "100"},
        json=MagicMock(return_value={"id": "abc12345678", "markdown": _VALID_CONTENT}),
    )
    result = _fetch_via_mediumapi("https://medium.com/article-abc12345678")
    assert result == _VALID_CONTENT


@patch("src.knowledge.fetcher.httpx.get")
@patch("src.knowledge.fetcher.settings")
def test_mediumapi_skipped_when_quota_zero(
    mock_settings: MagicMock, mock_get: MagicMock
) -> None:
    mock_settings.rapidapi_key = "test-key"
    mock_get.return_value = MagicMock(
        status_code=200,
        headers={"x-ratelimit-requests-remaining": "0"},
        json=MagicMock(return_value={"id": "abc12345678", "markdown": _VALID_CONTENT}),
    )
    assert _fetch_via_mediumapi("https://medium.com/article-abc12345678") == ""


@patch("src.knowledge.fetcher.settings")
def test_mediumapi_skipped_when_no_article_id(mock_settings: MagicMock) -> None:
    mock_settings.rapidapi_key = "test-key"
    # URL without hex ID suffix
    assert _fetch_via_mediumapi("https://medium.com/towards-data-science/no-id") == ""


@patch("src.knowledge.fetcher.httpx.get")
@patch("src.knowledge.fetcher.settings")
def test_mediumapi_skipped_on_404(
    mock_settings: MagicMock, mock_get: MagicMock
) -> None:
    mock_settings.rapidapi_key = "test-key"
    mock_get.return_value = MagicMock(
        status_code=404,
        headers={"x-ratelimit-requests-remaining": "50"},
    )
    assert _fetch_via_mediumapi("https://medium.com/article-abc12345678") == ""


# ---------------------------------------------------------------------------
# fetch_articles — escalation logic
# ---------------------------------------------------------------------------


@patch("src.knowledge.fetcher._fetch_via_camoufox_batched")
@patch("src.knowledge.fetcher._fetch_via_mediumapi")
@patch("src.knowledge.fetcher._fetch_via_jina")
def test_fetch_articles_jina_success_no_escalation(
    mock_jina: MagicMock,
    mock_mediumapi: MagicMock,
    mock_camoufox: MagicMock,
) -> None:
    url = "https://medium.com/article-abc12345678"
    mock_jina.return_value = _VALID_CONTENT

    results = fetch_articles([url])

    assert results[url] == _VALID_CONTENT
    mock_mediumapi.assert_not_called()
    mock_camoufox.assert_not_called()


@patch("src.knowledge.fetcher._fetch_via_camoufox_batched")
@patch("src.knowledge.fetcher._fetch_via_mediumapi")
@patch("src.knowledge.fetcher._fetch_via_jina")
def test_fetch_articles_escalates_to_tier2(
    mock_jina: MagicMock,
    mock_mediumapi: MagicMock,
    mock_camoufox: MagicMock,
) -> None:
    url = "https://medium.com/article-abc12345678"
    mock_jina.return_value = ""
    mock_mediumapi.return_value = _VALID_CONTENT

    results = fetch_articles([url])

    assert results[url] == _VALID_CONTENT
    mock_camoufox.assert_not_called()


@patch("src.knowledge.fetcher._fetch_via_camoufox_batched")
@patch("src.knowledge.fetcher._fetch_via_mediumapi")
@patch("src.knowledge.fetcher._fetch_via_jina")
def test_fetch_articles_escalates_to_tier3(
    mock_jina: MagicMock,
    mock_mediumapi: MagicMock,
    mock_camoufox: MagicMock,
) -> None:
    url = "https://medium.com/article-abc12345678"
    mock_jina.return_value = ""
    mock_mediumapi.return_value = ""
    mock_camoufox.return_value = {url: _VALID_CONTENT}

    results = fetch_articles([url])

    assert results[url] == _VALID_CONTENT
    mock_camoufox.assert_called_once_with([url])


@patch("src.knowledge.fetcher._fetch_via_camoufox_batched")
@patch("src.knowledge.fetcher._fetch_via_mediumapi")
@patch("src.knowledge.fetcher._fetch_via_jina")
def test_fetch_articles_all_tiers_fail(
    mock_jina: MagicMock,
    mock_mediumapi: MagicMock,
    mock_camoufox: MagicMock,
) -> None:
    url = "https://medium.com/article-abc12345678"
    mock_jina.return_value = ""
    mock_mediumapi.return_value = ""
    mock_camoufox.return_value = {url: ""}

    results = fetch_articles([url])

    assert results[url] == ""


# ---------------------------------------------------------------------------
# fetch_and_cache
# ---------------------------------------------------------------------------


@patch("src.knowledge.fetcher.raw_store.upsert_article")
@patch("src.knowledge.fetcher.fetch_articles")
def test_fetch_and_cache_stores_full_content(
    mock_fetch: MagicMock,
    mock_raw_upsert: MagicMock,
    tmp_path: Path,
) -> None:
    url = "https://medium.com/article-abc12345678"
    mock_fetch.return_value = {url: _VALID_CONTENT}

    result = fetch_and_cache(url, title="My Article", author="Alice")

    assert result == _VALID_CONTENT
    mock_raw_upsert.assert_called_once()
    call_kwargs = mock_raw_upsert.call_args
    assert call_kwargs.kwargs.get("scrape_status") == "full" or (
        call_kwargs.args[5] == "full" if len(call_kwargs.args) > 5 else False
    )


@patch("src.knowledge.fetcher.raw_store.upsert_article")
@patch("src.knowledge.fetcher.fetch_articles")
def test_fetch_and_cache_stores_snippet_on_failure(
    mock_fetch: MagicMock,
    mock_raw_upsert: MagicMock,
) -> None:
    url = "https://medium.com/article-abc12345678"
    mock_fetch.return_value = {url: ""}

    result = fetch_and_cache(url)

    assert result == ""
    mock_raw_upsert.assert_called_once()
