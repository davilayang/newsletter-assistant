# tests/knowledge/test_the_batch.py

from datetime import date

from src.knowledge.batch_store import get_sections, upsert_section
from src.knowledge.the_batch import BatchSection, parse_the_batch_html

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


def test_parse_extracts_section_titles() -> None:
    sections = parse_the_batch_html(_SAMPLE_HTML)
    titles = [s.title for s in sections]
    assert "Big AI Breakthrough" in titles
    assert "Robot Learns to Cook" in titles


def test_parse_extracts_andrew_letter() -> None:
    sections = parse_the_batch_html(_SAMPLE_HTML)
    assert sections[0].title == "Letter from Andrew Ng"
    assert "Dear friends" in sections[0].content_md


def test_parse_filters_trivial_sections() -> None:
    sections = parse_the_batch_html(_SAMPLE_HTML)
    titles = [s.title for s in sections]
    assert "News" not in titles
    assert "Work With Andrew Ng" not in titles
    assert "Learn More About AI With Data Points!" not in titles


def test_parse_preserves_hyperlinks() -> None:
    sections = parse_the_batch_html(_SAMPLE_HTML)
    section = next(s for s in sections if s.title == "Big AI Breakthrough")
    assert "[Example Lab](https://example.com/lab)" in section.content_md


def test_parse_letter_preserves_hyperlinks() -> None:
    sections = parse_the_batch_html(_SAMPLE_HTML)
    letter = sections[0]
    assert "[link](https://example.com)" in letter.content_md


def test_parse_empty_html() -> None:
    assert parse_the_batch_html("") == []
    assert parse_the_batch_html("<html><body></body></html>") == []


def test_parse_no_sections() -> None:
    html = "<html><body><p>Hello world</p></body></html>"
    assert parse_the_batch_html(html) == []


def test_section_count() -> None:
    """Letter + 2 real sections = 3 total."""
    sections = parse_the_batch_html(_SAMPLE_HTML)
    assert len(sections) == 3


# ---------------------------------------------------------------------------
# batch_store tests
# ---------------------------------------------------------------------------


def test_upsert_and_query(tmp_path) -> None:
    db = tmp_path / "test.db"
    section = BatchSection(
        title="Test Section",
        content_md="# Test\n\nSome content.",
        newsletter_date=date(2026, 3, 6),
    )
    upsert_section(section, db_path=db)
    rows = get_sections(db_path=db)
    assert len(rows) == 1
    assert rows[0].title == "Test Section"
    assert rows[0].newsletter_date == date(2026, 3, 6)


def test_upsert_idempotent(tmp_path) -> None:
    db = tmp_path / "test.db"
    section = BatchSection(
        title="Test",
        content_md="v1",
        newsletter_date=date(2026, 3, 6),
    )
    upsert_section(section, db_path=db)
    section.content_md = "v2"
    upsert_section(section, db_path=db)
    rows = get_sections(db_path=db)
    assert len(rows) == 1
    assert rows[0].content_md == "v2"


def test_get_sections_since(tmp_path) -> None:
    db = tmp_path / "test.db"
    old = BatchSection("Old", "old", newsletter_date=date(2026, 1, 1))
    new = BatchSection("New", "new", newsletter_date=date(2026, 3, 6))
    upsert_section(old, db_path=db)
    upsert_section(new, db_path=db)
    rows = get_sections(since=date(2026, 3, 1), db_path=db)
    assert len(rows) == 1
    assert rows[0].title == "New"
