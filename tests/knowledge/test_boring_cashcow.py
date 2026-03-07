# tests/knowledge/test_boring_cashcow.py

from datetime import date

from src.knowledge.boring_cashcow import CashCowSection, parse_cashcow_html
from src.knowledge.cashcow_store import get_sections, upsert_section

# ---------------------------------------------------------------------------
# Minimal but realistic HTML fixture
# ---------------------------------------------------------------------------

_SAMPLE_HTML = """
<html><body>
<div aria-label="duckduckgo-email-protection-preview"
     data-email-protection="duckduckgo-email-protection-preview"
     style="display:none">
  Morning , Preview text here.
</div>
<table data-email-protection="duckduckgo-email-protection-banner"
       aria-label="duckduckgo-email-protection-banner">
  <tr><td>DuckDuckGo Banner Content</td></tr>
</table>

<div class="ck-section">
  <div class="ck-inner-section">
    <div style="max-width:640px">
      <p>Morning ,</p>
      <p>It's a beautiful day and I've been reflecting on building online businesses.</p>
      <p>Here's my secret: Build something with great potential, then validate quickly.</p>
      <p>Join our <a href="https://boringcashcow.com/premium">premium membership</a>!</p>
      <hr>
      <p>Keep pushing forward!</p>
      <p>P.S. Remember, you don't have to be great to start.</p>
      <p>Cheers,</p>
      <p>David Maker<br><a href="https://boringcashcow.com/">https://boringcashcow.com/</a></p>
    </div>
  </div>
</div>

<div class="ck-section ck-hide-in-public-posts">
  <div class="ck-inner-section">
    <div style="max-width:640px">
      <p><a href="https://example.com/unsub">Unsubscribe</a> · <a href="https://example.com/prefs">Preferences</a></p>
    </div>
  </div>
</div>

<div style="text-align:center">
  <a href="https://builtwith.kit.com/">
    <img src="https://cdn.convertkit.com/assets/light-built-with-badge.png" alt="Built with ConvertKit">
  </a>
</div>

<img src="https://b4d1b5e1.open.kit-mail3.com/tracking123" alt="">
</body></html>
"""


def test_extracts_content_as_markdown() -> None:
    md = parse_cashcow_html(_SAMPLE_HTML)
    assert "building online businesses" in md
    assert "Build something with great potential" in md


def test_strips_signoff() -> None:
    md = parse_cashcow_html(_SAMPLE_HTML)
    assert "Cheers," not in md
    assert "David Maker" not in md
    assert "https://boringcashcow.com/)" not in md  # bare sign-off link stripped


def test_strips_duckduckgo_banner() -> None:
    md = parse_cashcow_html(_SAMPLE_HTML)
    assert "DuckDuckGo Banner" not in md
    assert "duckduckgo" not in md.lower()


def test_strips_footer() -> None:
    md = parse_cashcow_html(_SAMPLE_HTML)
    assert "Unsubscribe" not in md
    assert "Preferences" not in md


def test_strips_greeting() -> None:
    md = parse_cashcow_html(_SAMPLE_HTML)
    assert not md.startswith("Morning")


def test_strips_convertkit_badge() -> None:
    md = parse_cashcow_html(_SAMPLE_HTML)
    assert "ConvertKit" not in md
    assert "builtwith.kit.com" not in md


def test_preserves_hyperlinks() -> None:
    md = parse_cashcow_html(_SAMPLE_HTML)
    assert "[premium membership](https://boringcashcow.com/premium)" in md


def test_empty_html() -> None:
    assert parse_cashcow_html("") == ""
    assert parse_cashcow_html("<html><body></body></html>") == ""


def test_no_ck_section() -> None:
    assert parse_cashcow_html("<html><body><p>Hello</p></body></html>") == ""


# ---------------------------------------------------------------------------
# cashcow_store tests
# ---------------------------------------------------------------------------


def test_upsert_and_query(tmp_path) -> None:
    db = tmp_path / "test.db"
    section = CashCowSection(
        title="Test Newsletter",
        content_md="# Test\n\nSome content.",
        newsletter_date=date(2026, 2, 28),
    )
    upsert_section(section, db_path=db)
    rows = get_sections(db_path=db)
    assert len(rows) == 1
    assert rows[0].title == "Test Newsletter"
    assert rows[0].newsletter_date == date(2026, 2, 28)


def test_upsert_idempotent(tmp_path) -> None:
    db = tmp_path / "test.db"
    section = CashCowSection(
        title="Test",
        content_md="v1",
        newsletter_date=date(2026, 2, 28),
    )
    upsert_section(section, db_path=db)
    section.content_md = "v2"
    upsert_section(section, db_path=db)
    rows = get_sections(db_path=db)
    assert len(rows) == 1
    assert rows[0].content_md == "v2"


def test_get_sections_since(tmp_path) -> None:
    db = tmp_path / "test.db"
    old = CashCowSection("Old", "old", newsletter_date=date(2026, 1, 1))
    new = CashCowSection("New", "new", newsletter_date=date(2026, 3, 7))
    upsert_section(old, db_path=db)
    upsert_section(new, db_path=db)
    rows = get_sections(since=date(2026, 3, 1), db_path=db)
    assert len(rows) == 1
    assert rows[0].title == "New"
