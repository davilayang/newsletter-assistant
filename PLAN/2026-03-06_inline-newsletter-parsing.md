# Extract Clean Text from Inline Newsletters

## Problem

Newsletters like **The Batch** contain full article text inline in the email HTML, but:
- The `text/plain` MIME part is polluted with HubSpot tracking URLs, invisible Unicode characters (`\u2007`, `\u034F`, `\xAD`), and quoted-printable artifacts
- The current `_extract_best_body_text()` prefers `text/plain` → returns garbage
- The HTML part has clean content but buried under email boilerplate (tables, MSO conditionals, tracking pixels, style blocks)
- The pipeline currently **skips** non-Medium newsletters entirely (`is_medium: true` filter)

## Goal

Parse content-rich HTML newsletters into clean markdown, store in `raw_store`, and index into `vector_store` — same as Medium articles but treating the email body itself as the "article."

## Plan

### 1. Add `parse_inline_newsletter(html: str) -> list[Article]`

New function in `src/knowledge/newsletter.py` (or extend `medium.py` → rename to parser).

**Approach:** Use [markitdown](https://github.com/microsoft/markitdown) (Microsoft) for HTML→Markdown, then post-process.

`markitdown` handles HTML tables, links, lists, headings out of the box via `convert_stream()`:
```python
from io import BytesIO
from markitdown import MarkItDown

md = MarkItDown()
result = md.convert_stream(BytesIO(html.encode()), file_extension=".html")
clean_md = result.text_content
```

**Steps:**

1. **Pre-process HTML** (BeautifulSoup) before feeding to markitdown:
   - Remove `display:none` elements (preview text, hidden spacers)
   - Remove DuckDuckGo email protection banner (`id="duckduckgo-email-protection-*"`)
   - Remove tracking pixels (`<img>` with 1x1 dimensions or tracking domains)
   - Strip HubSpot tracking redirect URLs — replace `<a href="info.deeplearning.ai/e3t/...">text</a>` with just `<a>text</a>` (keeps anchor text, drops unresolvable URL)
2. **Convert to markdown** with `markitdown.convert_stream()`
3. **Post-process markdown:**
   - Clean invisible Unicode characters (`\u2007`, `\u034F`, `\xAD`, zero-width spaces)
   - Strip excessive blank lines
   - Split on `# ` (H1) markers to extract individual article sections
4. **Return** a list of `Article` objects (one per `<h1>` section), with:
   - `url` = synthesized key like `email:{message_id}#section-{n}` (since there's no external URL)
   - `title` = H1 text
   - `raw_markdown` = cleaned section content

**Fallback:** If H1 splitting finds < 2 sections, store the entire email body as a single article.

### 2. Add newsletter type: `content_type: inline`

Update `config/newsletters.yaml`:

```yaml
the batch:
  label: The Batch @ DeepLearning.AI
  query: from:thebatch_at_deeplearning.ai_duckduckyang@duck.com
  content_type: inline   # new: full content in email HTML
```

Keep `is_medium` for backward compat, add `content_type` enum: `medium_links` | `inline` | `plain_text`.

### 3. Extend pipeline to handle inline newsletters

In `src/knowledge/pipeline.py`, adjust the processing loop:

```
if content_type == "medium_links":
    # existing: parse article cards → fetch URLs → store
elif content_type == "inline":
    # new: parse_inline_newsletter(html) → store articles directly (no fetch needed)
else:
    # plain_text: store email body as single article
```

The key difference: **no fetcher needed** — the content is already in the email.

### 4. Handle tracking URL cleanup

The Batch wraps every link in HubSpot redirects:
```
https://info.deeplearning.ai/e3t/Ctc/LX+113/cJhC404/VVZ4df1G11K_W337szr3q...
```

Options:
- **a) Strip to anchor text only** — simplest, loses links but keeps readable text
- **b) Follow redirects to get real URLs** — slow, adds network calls
- **c) Use anchor text + mark as [link]** — e.g., `[Context Hub](link)` → `Context Hub`

**Recommendation:** Option (a) for pipeline storage. The voice agent doesn't need URLs.

### 5. Agent tool integration

In `src/agent/tools.py`, update `get_todays_newsletter()`:
- For `inline` type: query `raw_store` for articles from that newsletter date, return titles + snippets
- For `read_article` with `email:` prefix URLs: look up directly in `raw_store`

## Dependencies

- `beautifulsoup4` — already available (used by medium.py)
- `markitdown` — add to `pyproject.toml` ([Microsoft markitdown](https://github.com/microsoft/markitdown))

## Files to Change

1. **New:** `src/knowledge/newsletter.py` — `parse_inline_newsletter(html) -> list[Article]`
2. **Edit:** `config/newsletters.yaml` — add `content_type` field
3. **Edit:** `src/knowledge/pipeline.py` — handle `inline` content type
4. **Edit:** `src/agent/tools.py` — support `inline` newsletters in agent tools
5. **Edit:** `pyproject.toml` — add `markitdown`
6. **New:** `tests/knowledge/test_newsletter.py` — test with The Batch HTML sample
