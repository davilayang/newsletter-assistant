# tests/knowledge/test_the_batch.py

from datetime import date

from src.knowledge.batch_store import get_articles, upsert_article
from src.knowledge.the_batch import BatchArticle, parse_the_batch_html

# ---------------------------------------------------------------------------
# Minimal but realistic HTML fragments
# ---------------------------------------------------------------------------

_SAMPLE_HTML = """
<html><body>
<div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_module">
  <div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_rich_text">
    <div style="text-align:center">
      <a href="#" style="color:#f53b0d">Subscribe</a>
      <a href="mailto:x">Submit a tip</a>
    </div>
    <p>Dear friends,</p>
    <p>Here is the letter content with a <a href="https://example.com">link</a>.</p>
    <p>Keep building!</p>
    <p>Andrew</p>
  </div>
</div>

<div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_module">
  <div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_rich_text">
    <h2>A MESSAGE FROM DEEPLEARNING.AI</h2>
  </div>
</div>

<div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_module">
  <div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_rich_text">
    <p>Now available: "Build and Train an LLM with JAX." <a href="#">Enroll now</a></p>
  </div>
</div>

<div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_module">
  <div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_rich_text">
    <h1>News</h1>
  </div>
</div>

<div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_module">
  <div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_rich_text">
    <h1>Big AI Breakthrough</h1>
    <p>Researchers at <a href="https://example.com/lab">Example Lab</a> announced a new model.</p>
    <p><b>Why it matters:</b> This changes everything.</p>
  </div>
</div>

<div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_module">
  <div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_rich_text">
    <h1>Robot Learns to Cook</h1>
    <p>A robot learned to prepare meals using <a href="https://example.com/paper">reinforcement learning</a>.</p>
  </div>
</div>

<div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_module">
  <div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_rich_text">
    <h1>Learn More About AI With Data Points!</h1>
    <p>Subscribe today!</p>
  </div>
</div>

<div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_module">
  <div class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_rich_text">
    <h1>Work With Andrew Ng</h1>
    <p>Join the teams!</p>
  </div>
</div>

<p>Unsubscribe | Manage preferences</p>
</body></html>
"""


def test_parse_extracts_article_titles() -> None:
    articles = parse_the_batch_html(_SAMPLE_HTML)
    titles = [a.title for a in articles]
    assert "Big AI Breakthrough" in titles
    assert "Robot Learns to Cook" in titles


def test_parse_extracts_andrew_letter() -> None:
    articles = parse_the_batch_html(_SAMPLE_HTML)
    assert articles[0].title == "Letter from Andrew Ng"
    assert "Dear friends" in articles[0].content_md


def test_parse_filters_trivial_sections() -> None:
    articles = parse_the_batch_html(_SAMPLE_HTML)
    titles = [a.title for a in articles]
    assert "News" not in titles
    assert "Work With Andrew Ng" not in titles
    assert "Learn More About AI With Data Points!" not in titles


def test_parse_preserves_hyperlinks() -> None:
    articles = parse_the_batch_html(_SAMPLE_HTML)
    # Find the "Big AI Breakthrough" article
    article = next(a for a in articles if a.title == "Big AI Breakthrough")
    # markdownify should produce [text](url) links
    assert "[Example Lab](https://example.com/lab)" in article.content_md


def test_parse_letter_preserves_hyperlinks() -> None:
    articles = parse_the_batch_html(_SAMPLE_HTML)
    letter = articles[0]
    assert "[link](https://example.com)" in letter.content_md


def test_parse_empty_html() -> None:
    assert parse_the_batch_html("") == []
    assert parse_the_batch_html("<html><body></body></html>") == []


def test_parse_no_articles() -> None:
    html = "<html><body><p>Hello world</p></body></html>"
    assert parse_the_batch_html(html) == []


def test_article_count() -> None:
    """Letter + 2 real articles = 3 total."""
    articles = parse_the_batch_html(_SAMPLE_HTML)
    assert len(articles) == 3


# ---------------------------------------------------------------------------
# batch_store tests
# ---------------------------------------------------------------------------


def test_upsert_and_query(tmp_path) -> None:
    db = tmp_path / "test.db"
    article = BatchArticle(
        title="Test Article",
        content_md="# Test\n\nSome content.",
        newsletter_date=date(2026, 3, 6),
    )
    upsert_article(article, db_path=db)
    rows = get_articles(db_path=db)
    assert len(rows) == 1
    assert rows[0].title == "Test Article"
    assert rows[0].newsletter_date == date(2026, 3, 6)


def test_upsert_idempotent(tmp_path) -> None:
    db = tmp_path / "test.db"
    article = BatchArticle(
        title="Test",
        content_md="v1",
        newsletter_date=date(2026, 3, 6),
    )
    upsert_article(article, db_path=db)
    # Update content
    article.content_md = "v2"
    upsert_article(article, db_path=db)
    rows = get_articles(db_path=db)
    assert len(rows) == 1
    assert rows[0].content_md == "v2"


def test_get_articles_since(tmp_path) -> None:
    db = tmp_path / "test.db"
    old = BatchArticle("Old", "old", newsletter_date=date(2026, 1, 1))
    new = BatchArticle("New", "new", newsletter_date=date(2026, 3, 6))
    upsert_article(old, db_path=db)
    upsert_article(new, db_path=db)
    rows = get_articles(since=date(2026, 3, 1), db_path=db)
    assert len(rows) == 1
    assert rows[0].title == "New"
