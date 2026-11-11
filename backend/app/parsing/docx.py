"""DOCX text extraction with the standard library only.

A .docx file is a ZIP package of XML parts. We read ``word/document.xml``
(plus page header parts, where many resumes keep contact details) and emit
markdown-flavoured text: styled headings become ``## Heading`` and list
paragraphs become ``- item``.

Hardening against malicious files:
- the ZIP directory is inspected before anything is decompressed: entry count
  and total *declared* uncompressed size are capped (zip bombs);
- each part is read with a hard byte cap, so a lying header cannot inflate it;
- XML containing a DTD (``<!DOCTYPE``/``<!ENTITY``) is rejected, which rules
  out entity-expansion attacks; WordprocessingML never needs a DTD.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from app.core.errors import InvalidFileError

logger = logging.getLogger(__name__)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # password-protected Office files and legacy .doc
ZIP_MAGIC = b"PK\x03\x04"

MAX_ENTRIES = 1000
MAX_TOTAL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_PART_BYTES = 20 * 1024 * 1024

_HEADING_STYLE = re.compile(r"^(?:heading\s?(?P<level>\d)|(?P<title>title|subtitle))$", re.IGNORECASE)
_CORRUPT = "Could not read DOCX file. It may be corrupted."


@dataclass
class DocxContent:
    text: str
    heading_count: int = 0
    list_item_count: int = 0
    table_count: int = 0
    header_text_found: bool = False
    page_header_text: str = ""
    body_text: str = ""
    warnings: list[str] = field(default_factory=list)


def looks_like_docx(data: bytes) -> bool:
    return data.startswith(ZIP_MAGIC) or data.startswith(OLE_MAGIC)


def extract_docx(data: bytes) -> DocxContent:
    if data.startswith(OLE_MAGIC):
        raise InvalidFileError(
            "This Word file is password-protected or in the old .doc format. "
            "Remove the password or save it as .docx, then upload it again."
        )
    try:
        package = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise InvalidFileError(_CORRUPT) from exc

    with package:
        infos = package.infolist()
        if len(infos) > MAX_ENTRIES or sum(info.file_size for info in infos) > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise InvalidFileError("DOCX file is too large when uncompressed.")
        if any(info.flag_bits & 0x1 for info in infos):
            raise InvalidFileError("DOCX file is password-protected. Remove the password and upload it again.")

        names = {info.filename for info in infos}
        if "word/document.xml" not in names:
            raise InvalidFileError("File content does not look like a valid Word (.docx) document.")

        content = DocxContent(text="")
        header_lines: list[str] = []
        for name in sorted(n for n in names if re.fullmatch(r"word/header\d*\.xml", n)):
            for line in _paragraph_lines(_parse_part(package, name), content):
                if line and line not in header_lines:
                    header_lines.append(line)
        content.header_text_found = bool(header_lines)
        content.heading_count = content.list_item_count = content.table_count = 0  # count body only

        body = _parse_part(package, "word/document.xml").find(f"{W}body")
        if body is None:
            raise InvalidFileError(_CORRUPT)
        body_lines = _paragraph_lines(body, content)

    content.page_header_text = "\n".join(header_lines)
    content.body_text = "\n".join(body_lines)
    content.text = "\n".join([*header_lines, *([""] if header_lines else []), *body_lines])
    if not content.text.strip():
        raise InvalidFileError("No extractable text found in DOCX file. Text inside images is not supported.")
    return content


def _parse_part(package: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        with package.open(name) as handle:
            raw = handle.read(MAX_PART_BYTES + 1)
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as exc:
        raise InvalidFileError(_CORRUPT) from exc
    if len(raw) > MAX_PART_BYTES:
        raise InvalidFileError("DOCX file is too large when uncompressed.")
    head = raw[:4096]
    if b"<!DOCTYPE" in head or b"<!ENTITY" in raw:
        raise InvalidFileError("DOCX file contains unsupported XML constructs.")
    try:
        return ET.fromstring(raw)  # noqa: S314 - DTDs rejected above; input size capped
    except ET.ParseError as exc:
        logger.info("docx_xml_parse_failed", extra={"part": name})
        raise InvalidFileError(_CORRUPT) from exc


def _paragraph_lines(container: ET.Element, content: DocxContent) -> list[str]:
    lines: list[str] = []
    for child in container:
        tag = child.tag
        if tag == f"{W}p":
            line = _paragraph_text(child, content)
            if line is not None:
                lines.append(line)
        elif tag == f"{W}tbl":
            content.table_count += 1
            for row in child.iter(f"{W}tr"):
                cells = []
                for cell in row.findall(f"{W}tc"):
                    cell_lines = [ln for ln in _paragraph_lines(cell, content) if ln.strip()]
                    if cell_lines:
                        cells.append(" ".join(cell_lines))
                if cells:
                    lines.append(" | ".join(cells))
        elif tag in (f"{W}sdt", f"{W}sdtContent", f"{W}customXml", f"{W}hdr", f"{W}ftr"):
            lines.extend(_paragraph_lines(child, content))
    return lines


def _paragraph_text(paragraph: ET.Element, content: DocxContent) -> str | None:
    parts: list[str] = []
    for node in paragraph.iter():
        tag = node.tag
        if tag == f"{W}t" and node.text:
            parts.append(node.text)
        elif tag == f"{W}tab":
            parts.append("\t")
        elif tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
        # w:delText (tracked deletions) and w:instrText (field codes) are skipped on purpose.
    text = "".join(parts).strip()
    if not text:
        return ""

    properties = paragraph.find(f"{W}pPr")
    style = properties.find(f"{W}pStyle") if properties is not None else None
    style_name = style.get(f"{W}val", "") if style is not None else ""
    heading = _HEADING_STYLE.match(style_name)
    if heading and "\n" not in text:
        content.heading_count += 1
        # Mirror markdown levels: Title/Heading 1 -> "#", Heading 2 -> "##", deeper -> "###".
        level = 1 if heading.group("title") else min(int(heading.group("level")), 3)
        return f"{'#' * max(level, 1)} {text}"
    if properties is not None and (properties.find(f"{W}numPr") is not None or "list" in style_name.lower()):
        content.list_item_count += 1
        return f"- {text}"
    return text
