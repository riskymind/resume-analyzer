"""Preview and PDF/DOCX export: latest edits, templates, links, page breaks, escaping, limits, failure modes and
the acknowledgement required before exporting claims that could not be verified.

PDF tests need WeasyPrint's system libraries (Pango). They are skipped when
those are missing (for example on a macOS host without Pango) and run in the
Docker/CI image, which installs them.
"""

from __future__ import annotations

import copy
import io
import re
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import RewriteExport
from app.documents import render
from app.documents.render import ExportUnavailableError, export_filename
from app.schemas.rewrite import DocBullet, ResumeDocument
from tests.fixtures.rewrite import sample_document
from tests.integration.test_rewrites_api import (
    REWRITES,
    create,
    freeze_rate_limit_clock,
    patch,
    submit_job,
    upload_resume,
)


def _pdf_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


PDF_AVAILABLE = _pdf_available()
needs_pdf = pytest.mark.skipif(
    not PDF_AVAILABLE, reason="WeasyPrint system libraries (Pango) are not installed; run in Docker/CI."
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ALL_TEMPLATES = ["modern", "minimal", "corporate", "technical", "graduate"]
HEADINGS = {"experience", "skills", "education", "projects"}
# Template -> DOCX body font and the order of the main sections present in the sample resume.
TEMPLATE_EXPECTATIONS = [
    ("modern", "Calibri", ["experience", "skills", "education"]),
    ("minimal", "Arial", ["experience", "skills", "education"]),
    ("corporate", "Times New Roman", ["experience", "education", "skills"]),
    ("technical", "Arial", ["skills", "experience", "education"]),
    ("graduate", "Cambria", ["education", "experience", "skills"]),
]


@pytest.fixture
def rewrite(client: TestClient) -> dict[str, Any]:
    return create(client, resume_id=upload_resume(client), job_id=submit_job(client))


def export(client: TestClient, rewrite: dict[str, Any], **body: Any) -> Any:
    return client.post(f"{REWRITES}/{rewrite['id']}/export", json=body)


def docx_text(data: bytes) -> str:
    document = Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return re.sub(r"\s+", " ", " ".join(page.extract_text() or "" for page in reader.pages))


def edit(client: TestClient, rewrite: dict[str, Any], change: Any) -> dict[str, Any]:
    content = copy.deepcopy(rewrite["content"])
    change(content)
    res = patch(client, rewrite, content=content)
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def long_resume(content: dict[str, Any]) -> None:
    """60 extra bullets across both roles (each role allows up to 40)."""

    for role, numbers in ((0, range(1, 31)), (1, range(31, 61))):
        content["experience"][role]["bullets"] += [
            {"id": f"u{i}", "text": f"Delivered improvement number {i} to the deployment platform for internal teams.",
             "source_ids": []}
            for i in numbers
        ]  # fmt: skip


class TestDocx:
    def test_docx_export(self, app: FastAPI, client: TestClient, rewrite: dict[str, Any]) -> None:
        res = export(client, rewrite, format="docx")
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == DOCX_MIME
        assert res.headers["content-disposition"] == 'attachment; filename="jane-doe-resume.docx"'
        assert res.headers["cache-control"] == "no-store"
        assert res.headers["x-content-type-options"] == "nosniff"
        text = docx_text(res.content)
        assert "Jane Doe" in text
        assert "Led the migration of 40 services to Kubernetes, reducing deploy time by 35%." in text
        assert "Senior Software Engineer, Acme Corp · " not in text  # no location -> no dangling separator
        document = Document(io.BytesIO(res.content))
        bullets = [p.text for p in document.paragraphs if p.style is not None and p.style.name == "List Bullet"]
        assert "Built FastAPI services that handle 2M requests per day." in bullets
        targets = {rel.target_ref for rel in document.part.rels.values() if rel.is_external}
        assert {"mailto:jane.doe@example.com", "https://janedoe.dev"} <= targets
        with app.state.db.session() as db:
            row = db.scalar(select(RewriteExport))
            assert row is not None
            assert (row.format, row.template, row.version_number) == ("docx", "modern", 1)
            assert row.size_bytes == len(res.content)

    def test_export_reflects_latest_edits(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        edited = edit(client, rewrite, lambda c: c.update(summary="UNIQUE-EDIT-7731 Python backend engineer."))
        res = export(client, edited, format="docx", acknowledge_unverified=True)
        assert "UNIQUE-EDIT-7731" in docx_text(res.content)
        # An explicit earlier version exports that version.
        assert "UNIQUE-EDIT-7731" not in docx_text(export(client, edited, format="docx", version=1).content)

    @pytest.mark.parametrize(("template", "font", "order"), TEMPLATE_EXPECTATIONS)
    def test_templates(
        self, client: TestClient, rewrite: dict[str, Any], template: str, font: str, order: list[str]
    ) -> None:
        res = export(client, rewrite, format="docx", template=template)
        assert res.status_code == 200, res.text
        document = Document(io.BytesIO(res.content))
        assert document.styles["Normal"].font.name == font
        headings = [p.text.lower() for p in document.paragraphs if p.text.lower() in HEADINGS]
        assert headings == order
        assert "Led the migration of 40 services to Kubernetes, reducing deploy time by 35%." in docx_text(res.content)

    def test_saved_template_is_the_default(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        patch(client, rewrite, template="minimal")
        document = Document(io.BytesIO(export(client, rewrite, format="docx").content))
        assert document.styles["Normal"].font.name == "Arial"

    def test_long_resume(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        edited = edit(client, rewrite, long_resume)
        text = docx_text(export(client, edited, format="docx", acknowledge_unverified=True).content)
        assert all(f"improvement number {i} " in text for i in range(1, 61))

    def test_empty_resume_cannot_be_exported(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        empty = patch(client, rewrite, content=ResumeDocument().model_dump()).json()
        res = export(client, empty, format="docx")
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "empty_resume"

    def test_invalid_requests(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        assert export(client, rewrite, format="txt").status_code == 422
        assert export(client, rewrite, format="docx", template="fancy").status_code == 422
        assert export(client, rewrite, format="docx", version=42).status_code == 404

    def test_export_rate_limit(self, app: FastAPI, client: TestClient, rewrite: dict[str, Any]) -> None:
        freeze_rate_limit_clock(app)
        app.state.settings = app.state.settings.model_copy(update={"export_max_per_minute": 2})
        assert export(client, rewrite, format="docx").status_code == 200
        assert export(client, rewrite, format="docx").status_code == 200
        res = export(client, rewrite, format="docx")
        assert res.status_code == 429
        assert "Retry-After" in res.headers


class TestPreview:
    def test_preview_matches_template_and_content(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        body = client.get(f"{REWRITES}/{rewrite['id']}/preview", params={"template": "corporate"}).json()
        assert body["template"] == "corporate"
        assert body["version"] == 1
        html = body["html"]
        assert "Liberation Serif" in html
        assert "text-align: center" in html
        assert "Led the migration of 40 services" in html
        assert html.index("Education") < html.index(">Skills<")
        assert '<a href="mailto:jane.doe@example.com">' in html

    def test_preview_escapes_document_content(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        def inject(content: dict[str, Any]) -> None:
            content["contact"]["name"] = '<script>alert("x")</script>'
            content["summary"] = '<img src="http://169.254.169.254/latest/meta-data" onerror="alert(1)">'

        edited = edit(client, rewrite, inject)
        html = client.get(f"{REWRITES}/{edited['id']}/preview").json()["html"]
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html
        assert "<img" not in html
        assert "&lt;img" in html

    def test_unknown_template(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        assert client.get(f"{REWRITES}/{rewrite['id']}/preview", params={"template": "x"}).status_code == 422


class TestPdf:
    def test_pdf_engine_missing_gives_clear_503(
        self, client: TestClient, rewrite: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "weasyprint", None)  # any import now raises ImportError
        res = export(client, rewrite, format="pdf")
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "export_unavailable"
        assert "DOCX export still works" in res.json()["detail"]

    def test_external_fetches_are_refused(self) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            render._refuse_fetch("file:///etc/passwd")

    @needs_pdf
    def test_pdf_export(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        res = export(client, rewrite, format="pdf")
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "application/pdf"
        assert res.headers["content-disposition"] == 'attachment; filename="jane-doe-resume.pdf"'
        assert (res.headers["cache-control"], res.headers["x-content-type-options"]) == ("no-store", "nosniff")
        assert res.content.startswith(b"%PDF")
        text = pdf_text(res.content)
        assert "Jane Doe" in text
        assert "Led the migration of 40 services to Kubernetes, reducing deploy time by 35%." in text
        uris = {
            annotation.get_object()["/A"]["/URI"]
            for page in PdfReader(io.BytesIO(res.content)).pages
            for annotation in page.get("/Annots", [])
            if "/A" in annotation.get_object()
        }
        assert {"mailto:jane.doe@example.com", "https://janedoe.dev"} <= uris

    @needs_pdf
    @pytest.mark.parametrize("template", ALL_TEMPLATES)
    def test_pdf_templates_and_latest_edits(self, client: TestClient, rewrite: dict[str, Any], template: str) -> None:
        edited = edit(client, rewrite, lambda c: c.update(summary="UNIQUE-EDIT-4410 Python backend engineer."))
        text = pdf_text(export(client, edited, format="pdf", template=template, acknowledge_unverified=True).content)
        assert "UNIQUE-EDIT-4410" in text
        assert "�" not in text

    @needs_pdf
    def test_long_resume_breaks_across_pages(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        edited = edit(client, rewrite, long_resume)
        data = export(client, edited, format="pdf", acknowledge_unverified=True).content
        assert len(PdfReader(io.BytesIO(data)).pages) >= 2
        text = pdf_text(data)
        assert all(f"improvement number {i} " in text for i in range(1, 61))


@pytest.fixture
def listener() -> Iterator[tuple[str, list[bytes]]]:
    """A local TCP server that records every connection attempt, to prove the PDF engine never connects."""
    hits: list[bytes] = []
    server = socket.create_server(("127.0.0.1", 0))
    server.settimeout(0.1)
    stop = threading.Event()

    def accept() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                continue
            with conn:
                conn.settimeout(1)
                try:
                    hits.append(conn.recv(200) or b"(no data)")
                except OSError:
                    hits.append(b"(no data)")

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.getsockname()[1]}", hits
    stop.set()
    thread.join(timeout=2)
    server.close()


def _hostile_cases(base: str, secret: Path) -> dict[str, str]:
    file_url = secret.as_uri()
    return {
        "stylesheet link": f'<link rel="stylesheet" href="{base}/a.css">',
        "css @import": f'<style>@import url("{base}/b.css");</style>',
        "web font": f"<style>@font-face{{font-family:x;src:url({base}/f.woff)}} p{{font-family:x}}</style>",
        "css background": f"<style>body{{background:url({base}/bg.png)}}</style>",
        "image (http)": f'<img src="{base}/i.png" alt="">',
        "image (https)": '<img src="https://example.com/i.png" alt="">',
        "iframe and object": f'<iframe src="{base}/f"></iframe><object data="{base}/o"></object>',
        "local file stylesheet": f'<link rel="stylesheet" href="{file_url}">',
        "local file image": f'<img src="{file_url}" alt=""><img src="file:///etc/passwd" alt="">',
        "data URI": '<link rel="stylesheet" href="data:text/css,p::after{content:%22DATA-URI-MARKER%22}">',
    }


@needs_pdf
class TestPdfResourceFetcher:
    """Regression for the WeasyPrint 70 fetcher interface: refused resources are skipped, never fetched."""

    def test_fetcher_uses_the_weasyprint_interface(self) -> None:
        import weasyprint

        fetcher = render._refusing_url_fetcher(weasyprint)
        assert isinstance(fetcher, weasyprint.URLFetcher)
        assert fetcher._fail_on_errors is False  # refusals are skipped with a warning, not fatal
        assert fetcher._allowed_protocols == ()  # even the base implementation would refuse every scheme

    @pytest.mark.parametrize(
        "url", ["http://127.0.0.1:9/x.png", "https://example.com/a.css", "file:///etc/passwd", "data:text/plain,hi"]
    )
    def test_every_url_is_refused_without_opening_it(self, url: str, monkeypatch: pytest.MonkeyPatch) -> None:
        import weasyprint
        from weasyprint.urls import URLFetchingError, fetch

        def no_open(*args: object, **kwargs: object) -> None:
            raise AssertionError("the fetcher must never open a URL")

        monkeypatch.setattr(weasyprint.URLFetcher, "open", no_open)
        monkeypatch.setattr("urllib.request.OpenerDirector.open", no_open)
        fetcher = render._refusing_url_fetcher(weasyprint)
        with pytest.raises(ValueError, match="not allowed"):
            fetcher.fetch(url)
        with pytest.raises(ValueError, match="not allowed"):
            fetcher(url)
        # WeasyPrint's own fetch path: a refusal becomes URLFetchingError (caught by WeasyPrint), not AttributeError.
        with pytest.raises(URLFetchingError, match="not allowed"), fetch(fetcher, url):
            pass

    def test_hostile_html_renders_without_any_fetch(
        self,
        listener: tuple[str, list[bytes]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        base, hits = listener
        secret = tmp_path / "secret.css"
        secret.write_text('p::after { content: "LOCAL-FILE-MARKER"; }', encoding="utf-8")
        refused: list[str] = []
        original = render._refuse_fetch

        def recording_refusal(url: str, *args: object, **kwargs: object) -> dict[str, Any]:
            refused.append(url)
            return original(url)

        monkeypatch.setattr(render, "_refuse_fetch", recording_refusal)
        for name, markup in _hostile_cases(base, secret).items():
            before = len(refused)
            html = f"<html><head></head><body>{markup}<p>CASE-OK {name}</p></body></html>"
            monkeypatch.setattr(render, "render_html", lambda document, template, html=html: html)
            data = render.render_pdf(sample_document(), "modern")  # must not raise (previously AttributeError)
            assert data.startswith(b"%PDF"), name
            text = pdf_text(data)
            assert f"CASE-OK {name}" in text, name
            assert "LOCAL-FILE-MARKER" not in text, name
            assert "root:" not in text, name
            assert "DATA-URI-MARKER" not in text, name
            assert len(refused) > before, f"{name}: the fetcher was not consulted"
        time.sleep(0.3)
        assert hits == [], f"the PDF engine connected to the network: {hits}"

    @pytest.mark.parametrize("template", ALL_TEMPLATES)
    def test_normal_exports_never_need_the_fetcher(self, template: str, monkeypatch: pytest.MonkeyPatch) -> None:
        refused: list[str] = []
        original = render._refuse_fetch

        def recording_refusal(url: str, *args: object, **kwargs: object) -> dict[str, Any]:
            refused.append(url)
            return original(url)

        monkeypatch.setattr(render, "_refuse_fetch", recording_refusal)
        data = render.render_pdf(sample_document(), template)
        assert data.startswith(b"%PDF")
        assert "Jane Doe" in pdf_text(data)
        assert refused == [], f"{template} references external resources: {refused}"


class TestRenderUnits:
    def test_export_filename_is_safe(self) -> None:
        document = sample_document()
        assert export_filename(document, "x", "pdf") == "jane-doe-resume.pdf"
        document.contact.name = '../../Ëvil "Name"\r\n'
        assert export_filename(document, "x", "docx") == "evil-name-resume.docx"
        document.contact.name = None
        assert export_filename(document, "", "pdf") == "resume.pdf"

    def test_broken_glyphs_are_cleaned(self) -> None:
        document = sample_document()
        document.experience[0].bullets = [DocBullet(id="b", text="\uf0b7 Built things\x07 well")]
        html = render.render_html(document, "minimal")
        assert "Built things well" in html
        assert "\uf0b7" not in html

    def test_empty_document_rejected(self) -> None:
        with pytest.raises(AppError):
            render.render_docx(ResumeDocument(), "modern")

    def test_weasyprint_import_failure_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "weasyprint", None)
        with pytest.raises(ExportUnavailableError):
            render.render_pdf(sample_document(), "modern")
