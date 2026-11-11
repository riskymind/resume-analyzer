# Export Quality Assurance (PDF and DOCX)

_Milestone 6 · audience: developers and reviewers · code in `backend/app/documents/`, tests in
`backend/tests/integration/test_export_quality.py` and `test_rewrite_exports.py`._

This records what has been checked automatically, what has been checked by rendering and looking at the
output, and what still needs a person with Microsoft Word.

## 1. Templates

All five templates are single column, use standard section headings, real text, real hyperlinks and Word's
built-in list style, and contain no tables, text boxes or images, so each stays ATS-readable. One definition
per template (`documents/templates.py`) drives the HTML preview, the PDF and the DOCX.

| Key | Name | Section order (after the summary) | DOCX font / PDF font in Docker | Distinctive |
|---|---|---|---|---|
| `modern` | Modern professional | experience, projects, skills, education, certifications, languages | Calibri / Carlito | Teal accent, ruled uppercase headings |
| `minimal` | Minimalist | same as modern | Arial / Liberation Sans | Black only, no rules |
| `corporate` | Traditional corporate | experience, education, certifications, skills, projects, languages | Times New Roman / Liberation Serif | Centred header, serif |
| `technical` | Technical | **skills**, experience, projects, certifications, education, languages | Arial / Liberation Sans | Compact (10 pt), project "Tech stack:" line shown before the description |
| `graduate` | Graduate | **education** (with relevant coursework), **projects**, experience, skills, certifications, languages | Cambria / Caladea | Centred header, title-case headings |

Continuation pages (page 2 onwards) carry a small footer, "_Name_ — page _n_ of _N_", in both formats. The
first page has none. Contact details always stay in the body, because some ATS parsers skip headers and
footers.

**Relevant coursework.** The AI extraction does not capture coursework, so it is not filled in
automatically. Users add it per education entry in the editor. Each course is checked against the
original resume text. A course that the resume does not mention is flagged as an unverified claim made by
the user, and it is never shown as verified.

## 2. Automated checks

| Area | Check | Formats | Where it runs |
|---|---|---|---|
| Content | Latest edits are exported; an explicit older version exports that version; long resumes keep every bullet | both | all environments (PDF needs Pango) |
| Templates | DOCX body font and section order for each of the five templates; preview HTML for each template; coursework rendered in every template | both | all |
| Structure | No tables, text boxes, drawings or multi-column sections; A4, 16 mm margins; only `Normal` and `List Bullet` styles; bullets use Word numbering (real hanging indent) and carry no typed bullet glyphs | DOCX | all |
| Headings and dates | Headings keep with next; dated entries use exactly one right-aligned tab stop at 178 mm; every role's start date appears | DOCX | all |
| Links | Only `http(s)`/`mailto` targets; each `w:hyperlink` has a relationship; e-mail is a `mailto:` link | DOCX, PDF | all |
| Characters | No control characters or U+FFFD; stray bullet glyphs (private-use, `•`) are removed before rendering | both | all |
| Footer | `PAGE` and `NUMPAGES` fields, different first page, name present and contact details absent; CSS footer text cannot break out of the stylesheet | both | all |
| Fonts | Every font in every PDF is embedded (subset) | PDF | Pango |
| Pagination | A long resume runs to 3+ pages, the footer reads "page n of N" on pages 2+ and not on page 1, no bullet text lost | PDF | Pango |
| Wrapping | A 140-character unbroken token wraps across lines instead of overflowing | PDF | Pango |
| Security | Content is HTML-escaped; WeasyPrint gets a refusing `URLFetcher` subclass, so every URL (`http(s)`, `file`, `data`) is refused and skipped, never fetched (no SSRF, no local file reads). End-to-end tests render hostile HTML with a listening socket and a secret file (`TestPdfResourceFetcher`, Milestone 9) | PDF | Pango |
| Response | `Content-Disposition: attachment` with an ASCII slug filename, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` | both | all |

## 3. PDF results (rendered and inspected)

| Environment | Engine | Result |
|---|---|---|
| macOS 15.8 (Intel) with Homebrew Pango 1.58.2 | WeasyPrint 70.0 | All 84 export tests pass. 20 sample PDFs generated, all fonts embedded. |
| Linux container (`python:3.12-slim`, Debian bookworm) with the packages listed in §5 | WeasyPrint 70.0 | All 84 export tests pass. 20 sample PDFs generated, all fonts embedded, rasterised with `pdftoppm` and inspected. |

Inspected pages: standard, graduate, long (3–5 pages) and edge-case samples for several templates on both
platforms. Bullets have a hanging indent, dates align right, headings stay with their first entry, the
footer sits bottom-right on continuation pages only, and long URLs and tokens wrap inside the margins. No
overlap or clipping was seen.

**Differences between platforms (expected):** macOS has no Carlito or Caladea, so the Modern template
falls back to Arial and Graduate to Georgia. Arial is wider than Carlito, so the long sample is 5 pages on
macOS and 3 in Linux. **Production PDFs are rendered in the Linux image, which has the metric-compatible
fonts.** Local macOS PDFs are for development only.

**Known gap: CJK text.** Chinese, Japanese and Korean characters render as empty boxes in the Linux image,
because it has no CJK font. Greek, accented Latin, €, ±, °, en/em dashes and curly quotes render correctly.
macOS renders CJK through its system fonts.

_Milestone 8 decision (approved):_ `fonts-noto-cjk` is available as an **opt-in** build argument
(`docker build --build-arg INSTALL_CJK_FONTS=true backend`), not installed by default. Measured: +169 MB
(542 → 712 MB, +31%). With it, the edge-case sample renders 日本語 correctly (Noto Sans CJK JP embedded);
without it, the glyphs are empty boxes. The PDF text layer contains the right characters in both cases, which helps text extraction, but it does **not** fix the visual rendering: without the fonts, PDFs do not visually support CJK. Details: [milestone-8-completion-report.md §12](milestone-8-completion-report.md#12-image-sizes-and-the-cjk-font-decision).

## 4. DOCX: what is and is not verified

Automated structural checks pass for all five templates and all four samples (`test_docx_structure`, 20
cases). **The DOCX files have not been opened in Microsoft Word**, because Word is not available in this
environment, so Word's own layout (line breaks, page breaks, field updates) is unverified. LibreOffice is
not installed either.

### Manual Word inspection checklist

Open each file in `backend/data/export-samples/linux/*.docx` (regenerate with the command in §6) in Word
for Windows or Mac. Start with `standard-*` and `long-*` for each template, then `graduate-graduate.docx`
and `edge-cases-minimal.docx`.

1. The file opens without a repair prompt or compatibility warning.
2. Fonts: Modern uses Calibri, Minimalist and Technical use Arial, Corporate uses Times New Roman, and
   Graduate uses Cambria. No font is substituted (check the font box when the cursor is in body text).
3. Bullets are real Word bullets (the Home ▸ Bullets button is highlighted) with a hanging indent:
   wrapped lines align with the text, not with the bullet.
4. Dates sit flush right on the same line as the job title, including long titles. No date wraps onto
   its own line.
5. Headings are never the last line on a page (keep-with-next), and no entry heading is separated from
   its first bullet.
6. `long-*.docx`: page 1 has no footer. Pages 2+ show "Jane Doe — page n of N" with correct numbers
   (press F9 or print preview if a field shows "1").
7. Ctrl/Cmd-click the e-mail and website links: they open `mailto:` / the browser.
8. `edge-cases-*.docx`: the long URL and the long token wrap within the margins. Accented names, €, ±,
   °, curly quotes and dashes look right. Japanese text shows (Word substitutes a font).
9. `graduate-*.docx`: the "Relevant coursework:" line appears under the degree. In `graduate-graduate.docx`,
   Education comes first, then Projects, then Experience.
10. `technical-*`: Skills come before Experience, and each project shows "Tech stack:" before its
    description.
11. Save as PDF from Word and compare with the server PDF of the same template. Small line-break
    differences are expected; missing text or overlaps are not.
12. Optional: paste the document text into a plain-text editor. The reading order should match the
    visual order.

Record the Word version and platform, and any failures with the file name, in the Milestone 6 review.

## 5. System packages (Linux / Docker)

```
libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0
fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea fonts-dejavu-core
```

`fonts-crosextra-caladea` is new in Milestone 6 (Graduate template). `backend/Dockerfile` (Milestone 8)
installs exactly this list; CI installs it too. On macOS: `brew install pango`. On an Intel Mac
with outdated Command Line Tools, Homebrew builds several dependencies from source, which took about 40
minutes here.

Without Pango, PDF export returns `503 export_unavailable` and DOCX still works (tested by forcing the
import to fail).

## 6. Reproducing

```bash
cd backend
python -m scripts.render_export_samples data/export-samples/local   # every template × sample, DOCX/PDF/HTML
pytest tests/integration/test_export_quality.py tests/integration/test_rewrite_exports.py
```

The samples are invented people (`tests/fixtures/export_samples.py`): standard, graduate (coursework,
internship, projects), long (6 roles × 9 wrapping bullets, 3 projects), and edge cases (non-ASCII name,
symbols, CJK and Greek, a long URL and a 140-character unbroken token).
