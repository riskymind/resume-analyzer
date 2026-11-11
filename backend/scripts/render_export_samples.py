"""Write every export template, for each fictional sample resume, as DOCX, PDF and preview HTML.

For manual quality checks (opening the DOCX files in Microsoft Word, viewing the PDFs) and for comparing PDF
output between macOS and the Linux container. No AI provider, database or network access is used.

    cd backend
    python -m scripts.render_export_samples ../export-samples        # PDF needs Pango; otherwise DOCX/HTML only

The output directory receives ``<sample>-<template>.{docx,pdf,html}`` plus ``manifest.txt``. Every person,
employer and institution in the samples is invented.
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from app.documents.render import ExportUnavailableError, render_docx, render_html, render_pdf
from app.documents.templates import TEMPLATES
from tests.fixtures.export_samples import SAMPLES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path, help="directory to write the samples to (created if missing)")
    parser.add_argument("--no-pdf", action="store_true", help="skip PDF even if the PDF engine is available")
    args = parser.parse_args(argv)

    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    lines = [f"platform: {platform.platform()}", f"python: {platform.python_version()}"]
    pdf_ok = not args.no_pdf
    for sample_name, build in SAMPLES.items():
        document = build()
        for key in TEMPLATES:
            stem = f"{sample_name}-{key}"
            (output / f"{stem}.docx").write_bytes(render_docx(document, key))
            (output / f"{stem}.html").write_text(render_html(document, key), encoding="utf-8")
            if pdf_ok:
                try:
                    (output / f"{stem}.pdf").write_bytes(render_pdf(document, key))
                except ExportUnavailableError as exc:
                    lines.append(f"pdf: unavailable ({exc})")
                    pdf_ok = False
            lines.append(f"{stem}: docx, html{', pdf' if pdf_ok else ''}")
    (output / "manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
