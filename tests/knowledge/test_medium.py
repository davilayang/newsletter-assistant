# tests/knowledge/test_medium.py


from src.knowledge.medium import (
    Article,
    _is_valid_content,
    check_auth_state,
    parse_medium_newsletter,
)

# ---------------------------------------------------------------------------
# Sample newsletter HTML (minimal but realistic structure)
# ---------------------------------------------------------------------------
# Article URLs end with a hex ID (8–12 hex chars) — the discriminator used by
# the new parser. Non-article links (sign-in, profile, bare domain) lack this.

_SAMPLE_HTML = """
<html><body>
  <table>
    <tr>
      <td>
        <a href="https://medium.com/towards-data-science/build-a-rag-pipeline-abc12345">
          <h2>How to Build a RAG Pipeline</h2>
          <h3>A practical guide to retrieval-augmented generation</h3>
        </a>
      </td>
    </tr>
    <tr>
      <td>
        <a href="https://medium.com/towards-data-science/build-a-rag-pipeline-abc12345?source=email">
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
        <a href="https://medium.com/@davilayang">Profile page (no hex ID)</a>
      </td>
    </tr>
    <tr>
      <td>
        <a href="https://medium.com">Bare domain (no hex ID)</a>
      </td>
    </tr>
    <tr>
      <td>
        <a href="https://towardsdatascience.com/another-great-article-def98765ab">
          <h2>Another Article on TDS</h2>
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
    articles = parse_medium_newsletter(_SAMPLE_HTML)
    urls = [a.url for a in articles]
    assert (
        "https://medium.com/towards-data-science/build-a-rag-pipeline-abc12345" in urls
    )
    assert "https://towardsdatascience.com/another-great-article-def98765ab" in urls


def test_parse_deduplicates_tracking_params() -> None:
    articles = parse_medium_newsletter(_SAMPLE_HTML)
    urls = [a.url for a in articles]
    # The duplicate with ?source=email should be stripped and deduplicated
    assert (
        urls.count(
            "https://medium.com/towards-data-science/build-a-rag-pipeline-abc12345"
        )
        == 1
    )


def test_parse_skips_signin_links() -> None:
    articles = parse_medium_newsletter(_SAMPLE_HTML)
    urls = [a.url for a in articles]
    assert not any("/m/signin" in u for u in urls)


def test_parse_skips_profile_pages() -> None:
    articles = parse_medium_newsletter(_SAMPLE_HTML)
    urls = [a.url for a in articles]
    assert "https://medium.com/@davilayang" not in urls


def test_parse_skips_bare_domain() -> None:
    articles = parse_medium_newsletter(_SAMPLE_HTML)
    urls = [a.url for a in articles]
    assert "https://medium.com" not in urls


def test_parse_skips_non_medium_domains() -> None:
    articles = parse_medium_newsletter(_SAMPLE_HTML)
    urls = [a.url for a in articles]
    assert "https://example.com/not-medium" not in urls


def test_parse_skips_medium_internal_pages() -> None:
    html = """
    <html><body>
      <a href="https://medium.com/jobs-at-medium/work-at-medium-959d1a85284e">Careers</a>
      <a href="https://medium.com/some-real-article-abc12345def"><h2>Real</h2></a>
    </body></html>
    """
    articles = parse_medium_newsletter(html)
    urls = [a.url for a in articles]
    assert "https://medium.com/jobs-at-medium/work-at-medium-959d1a85284e" not in urls
    assert "https://medium.com/some-real-article-abc12345def" in urls


def test_parse_empty_html() -> None:
    assert parse_medium_newsletter("") == []
    assert parse_medium_newsletter("<html><body></body></html>") == []


def test_parse_returns_article_dataclass() -> None:
    articles = parse_medium_newsletter(_SAMPLE_HTML)
    assert all(isinstance(a, Article) for a in articles)
    assert all(isinstance(a.title, str) for a in articles)


def test_parse_warns_when_too_few_articles(caplog) -> None:
    import logging

    # Only 2 article links — below the _MIN_EXPECTED_ARTICLES threshold
    html = """
    <html><body>
      <a href="https://medium.com/article-one-abc12345">First</a>
      <a href="https://medium.com/article-two-def67890">Second</a>
    </body></html>
    """
    with caplog.at_level(logging.WARNING, logger="src.knowledge.medium"):
        parse_medium_newsletter(html)
    assert any("expected" in r.message for r in caplog.records)


def test_parse_extracts_author_from_card() -> None:
    """Author name should be extracted from the profile link in the card container."""
    html = """
    <html><body>
      <div>
        <div>
          <a href="https://medium.com/@johndoe?source=email"><img alt="John Doe"></a>
          <span><a href="https://medium.com/@johndoe?source=email">John Doe</a></span>
        </div>
        <div>
          <a href="https://medium.com/@johndoe/my-great-article-abc12345def?source=email">
            <h2>My Great Article</h2>
            <h3>A short snippet about the article</h3>
          </a>
        </div>
      </div>
    </body></html>
    """
    articles = parse_medium_newsletter(html)
    assert len(articles) == 1
    assert articles[0].author == "John Doe"
    assert articles[0].title == "My Great Article"


def test_parse_extracts_h2_title() -> None:
    articles = parse_medium_newsletter(_SAMPLE_HTML)
    titles = [a.title for a in articles]
    assert "How to Build a RAG Pipeline" in titles


def test_parse_extracts_h3_snippet() -> None:
    articles = parse_medium_newsletter(_SAMPLE_HTML)
    rag_article = next(a for a in articles if "build-a-rag-pipeline" in a.url)
    assert "retrieval-augmented generation" in rag_article.snippet


def test_parse_caps_at_20() -> None:
    # Build HTML with 25 distinct medium article links (valid hex IDs)
    links = "".join(
        f'<a href="https://medium.com/some-article-{i:08x}">Article {i}</a>\n'
        for i in range(1, 26)
    )
    html = f"<html><body>{links}</body></html>"
    articles = parse_medium_newsletter(html)
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
    md = "ray id: `9d5755b5ab2b3238`\n\n" + "x" * 600
    assert _is_valid_content(md) is False


def test_medium_paywall_is_invalid() -> None:
    paywall = "This story is only available to Medium members" + "x" * 600
    assert _is_valid_content(paywall) is False


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
