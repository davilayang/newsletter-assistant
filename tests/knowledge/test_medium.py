# tests/knowledge/test_medium.py


from src.knowledge.medium import Article, _is_valid_content, check_auth_state, parse_newsletter_email

# ---------------------------------------------------------------------------
# Sample newsletter HTML (minimal but realistic structure)
# ---------------------------------------------------------------------------

_SAMPLE_HTML = """
<html><body>
  <table>
    <tr>
      <td>
        <a href="https://medium.com/towards-data-science/real-article-abc123">
          How to Build a RAG Pipeline
        </a>
      </td>
    </tr>
    <tr>
      <td>
        <a href="https://medium.com/towards-data-science/real-article-abc123?source=email">
          Duplicate with tracking params
        </a>
      </td>
    </tr>
    <tr>
      <td>
        <a href="https://medium.com/m/signin?redirect=https://medium.com/foo">Sign in</a>
      </td>
    </tr>
    <tr>
      <td>
        <a href="https://towardsdatascience.com/another-article-xyz">
          Another Article on TDS
        </a>
      </td>
    </tr>
    <tr>
      <td>
        <a href="https://example.com/not-medium">Should be ignored</a>
      </td>
    </tr>
  </table>
</body></html>
"""


def test_parse_extracts_medium_articles() -> None:
    articles = parse_newsletter_email(_SAMPLE_HTML)
    urls = [a.url for a in articles]
    assert "https://medium.com/towards-data-science/real-article-abc123" in urls
    assert "https://towardsdatascience.com/another-article-xyz" in urls


def test_parse_deduplicates_tracking_params() -> None:
    articles = parse_newsletter_email(_SAMPLE_HTML)
    urls = [a.url for a in articles]
    # The duplicate with ?source=email should be stripped and deduplicated
    assert (
        urls.count("https://medium.com/towards-data-science/real-article-abc123") == 1
    )


def test_parse_skips_signin_links() -> None:
    articles = parse_newsletter_email(_SAMPLE_HTML)
    urls = [a.url for a in articles]
    assert not any("/m/signin" in u for u in urls)


def test_parse_skips_non_medium_domains() -> None:
    articles = parse_newsletter_email(_SAMPLE_HTML)
    urls = [a.url for a in articles]
    assert "https://example.com/not-medium" not in urls


def test_parse_empty_html() -> None:
    assert parse_newsletter_email("") == []
    assert parse_newsletter_email("<html><body></body></html>") == []


def test_parse_returns_article_dataclass() -> None:
    articles = parse_newsletter_email(_SAMPLE_HTML)
    assert all(isinstance(a, Article) for a in articles)
    assert all(isinstance(a.title, str) for a in articles)


def test_parse_caps_at_20() -> None:
    # Build HTML with 25 distinct medium article links
    links = "".join(
        f'<a href="https://medium.com/article-{i}">Article Title Number {i} is here</a>\n'
        for i in range(25)
    )
    html = f"<html><body>{links}</body></html>"
    articles = parse_newsletter_email(html)
    assert len(articles) <= 20


# ---------------------------------------------------------------------------
# _is_valid_content
# ---------------------------------------------------------------------------


def test_valid_content_passes() -> None:
    md = "# How to Build a RAG Pipeline\n\n" + ("x" * 600)
    assert _is_valid_content(md) is True


def test_too_short_content_is_invalid() -> None:
    assert _is_valid_content("# Short") is False
    assert _is_valid_content("") is False


def test_cloudflare_challenge_is_invalid() -> None:
    cf = (
        "## Performing security verification\n\n"
        "This website uses a security service to protect against malicious bots. "
        "Enable JavaScript and cookies to continue\n\nRay ID: `abc123`"
    )
    assert _is_valid_content(cf) is False


def test_cloudflare_ray_id_marker_is_invalid() -> None:
    # Even with enough chars, a Ray ID line flags it as a block page
    md = ("ray id: `9d5755b5ab2b3238`\n\n" + "x" * 600)
    assert _is_valid_content(md) is False


# ---------------------------------------------------------------------------
# check_auth_state
# ---------------------------------------------------------------------------


def test_check_auth_state_missing_logs_warning(tmp_path, caplog) -> None:
    import logging

    missing = tmp_path / "no_auth.json"
    with caplog.at_level(logging.WARNING, logger="src.knowledge.medium"):
        check_auth_state(missing)
    assert any("not found" in r.message for r in caplog.records)


def test_check_auth_state_fresh_file_no_warning(tmp_path, caplog) -> None:
    import logging

    auth = tmp_path / "auth.json"
    auth.write_text("{}")
    with caplog.at_level(logging.WARNING, logger="src.knowledge.medium"):
        check_auth_state(auth)
    assert not any("days old" in r.message for r in caplog.records)
