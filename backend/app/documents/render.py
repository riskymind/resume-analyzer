"""Resume export rendering: HTML (preview and PDF source), PDF via WeasyPrint, DOCX via python-docx.

Exports are generated on demand from the saved document and streamed; nothing
is written to disk. All document text is escaped by Jinja's autoescaping, link
targets are restricted to http(s) and mailto, and WeasyPrint is given a URL
fetcher that refuses every request, so a document cannot make the server fetch
anything (no SSRF, no local file reads).
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.errors import AppError
from app.documents.templates import SECTION_TITLES, get_template
from app.schemas.rewrite import DocContact, DocEducation, ResumeDocument
from app.services.rewriting.document import certification_line, date_range

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ExportUnavailableError(AppError):
    status_code = 503
    code = "export_unavailable"


class EmptyDocumentError(AppError):
    code = "empty_resume"


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(enabled_extensions=("j2", "html"), default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )


@dataclass(frozen=True)
class ContactPart:
    text: str
    href: str | None = None


def contact_parts(contact: DocContact) -> list[ContactPart]:
    parts: list[ContactPart] = []
    if contact.email:
        parts.append(ContactPart(contact.email, f"mailto:{contact.email}"))
    if contact.phone:
        parts.append(ContactPart(contact.phone))
    if contact.location:
        parts.append(ContactPart(contact.location))
    for link in contact.links:
        display = re.sub(r"^https?://(www\.)?", "", link.url).rstrip("/")
        parts.append(ContactPart(display, link.url))
    return parts


def degree_line(entry: DocEducation) -> str:
    return " ".join(part for part in (entry.qualification, entry.field_of_study) if part)


def _clean_typography(text: str) -> str:
    """Normalise characters that commonly render as broken symbols (private-use bullets, control chars)."""

    text = unicodedata.normalize("NFC", text)
    text = re.sub("[\\uf000-\\uf8ff\\u25aa\\u25cf\\u2022\\u2023\\u2043\\u2219]\\s*", "", text)  # stray bullet glyphs
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def _sanitised(document: ResumeDocument) -> ResumeDocument:
    data = document.model_dump(mode="json")

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return _clean_typography(value)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    return ResumeDocument.model_validate(walk(data))


def ensure_exportable(document: ResumeDocument) -> None:
    if document.is_empty():
        raise EmptyDocumentError("This resume is empty. Add some content before exporting.")


# --------------------------------------------------------------------------- HTML / PDF


def render_html(document: ResumeDocument, template_key: str) -> str:
    template = get_template(template_key)
    doc = _sanitised(document)
    return (
        _environment()
        .get_template("resume.html.j2")
        .render(
            doc=doc,
            t=template,
            title=f"{doc.contact.name or 'Resume'}",
            sections=template.sections,
            titles=SECTION_TITLES,
            footer_text=_css_string(doc.contact.name or "Resume"),
            contact_parts=contact_parts(doc.contact),
            dates=date_range,
            degree=degree_line,
            cert_line=certification_line,
        )
    )


def _css_string(text: str) -> str:
    """Text safe inside a double-quoted CSS string in a <style> element, where HTML escaping would show literally."""

    cleaned = re.sub(r"\s+", " ", re.sub(r"[^\w .,'()&-]", "", text, flags=re.UNICODE))[:80].strip()
    return cleaned or "Resume"


def _refuse_fetch(url: str, *args: object, **kwargs: object) -> dict[str, Any]:
    raise ValueError(f"External resources are not allowed in exports ({url[:40]}).")


def _refusing_url_fetcher(weasyprint: Any) -> Any:
    """A WeasyPrint 70 ``URLFetcher`` that refuses every URL (network, ``file:``, ``data:``, anything).

    WeasyPrint requires a ``URLFetcher`` instance: its error path reads ``url_fetcher._fail_on_errors``, which a
    plain function lacks, so a refusal used to crash rendering with ``AttributeError``. With
    ``fail_on_errors=False`` a refusal is reported as a warning and the resource is skipped. ``fetch`` never calls
    the base implementation, and ``allowed_protocols=()`` would refuse every scheme even if it did.
    """

    class RefusingURLFetcher(weasyprint.URLFetcher):  # type: ignore[misc]  # weasyprint ships no type information
        def fetch(self, url: str, headers: object = None) -> Any:
            return _refuse_fetch(url)

    return RefusingURLFetcher(allowed_protocols=(), allow_redirects=False, fail_on_errors=False)


def _weasyprint() -> Any:
    try:
        import weasyprint  # heavy optional native dependency, loaded on first use
    except (ImportError, OSError) as exc:
        logger.warning("pdf_export_unavailable", extra={"error_type": type(exc).__name__})
        raise ExportUnavailableError(
            "PDF export is not available on this server (the PDF engine's system libraries are missing). "
            "DOCX export still works."
        ) from exc
    return weasyprint


def render_pdf(document: ResumeDocument, template_key: str) -> bytes:
    ensure_exportable(document)
    weasyprint = _weasyprint()
    html = render_html(document, template_key)
    fetcher = _refusing_url_fetcher(weasyprint)
    pdf: bytes = weasyprint.HTML(string=html, base_url=None, url_fetcher=fetcher).write_pdf()
    return pdf


# --------------------------------------------------------------------------- DOCX


def render_docx(document: ResumeDocument, template_key: str) -> bytes:
    from app.documents.docx_builder import build_docx  # keeps python-docx off the API import path

    ensure_exportable(document)
    output = io.BytesIO()
    build_docx(_sanitised(document), get_template(template_key)).save(output)
    return output.getvalue()


# --------------------------------------------------------------------------- filenames


def export_filename(document: ResumeDocument, fallback: str, extension: str) -> str:
    """A safe, predictable ASCII filename such as ``jane-doe-resume.pdf``."""

    base = document.contact.name or fallback or "resume"
    ascii_name = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60] or "resume"
    if not slug.endswith("resume"):
        slug = f"{slug}-resume"
    return f"{slug}.{extension}"
