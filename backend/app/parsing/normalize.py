"""Text normalisation shared by every document format.

The output is "markdown-flavoured plain text": one logical line per paragraph
or bullet, list items prefixed with ``- ``, headings from styled formats
(DOCX) prefixed with ``## ``. Every downstream step (section detection,
extraction evidence checks, scoring) works on this single representation.
"""

from __future__ import annotations

import re
import unicodedata

# Characters used as bullets by word processors, PDF exporters and icon fonts.
_BULLET_CHARS = "•●▪■◦‣∙·○◆◇►▸▹➢➤➔→✓✔✗☐❖⦿\u2043"  # \u2043 = hyphen bullet
_BULLET_LINE = re.compile(rf"^\s*(?:[{re.escape(_BULLET_CHARS)}]|[*+]\s|[\u2013\u2014]\s)\s*")
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
_HORIZONTAL_SPACE = re.compile(r"[ \t\u00a0\u2000-\u200a\u202f\u205f\u3000]+")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def _strip_control_chars(text: str) -> str:
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")


def normalize_text(text: str) -> str:
    """Return consistently normalised text (idempotent)."""

    text = unicodedata.normalize("NFKC", text)  # ligatures (ﬁ → fi), full-width forms, compatibility spaces
    text = text.replace("\r\n", "\n").replace("\r", "\n").translate(_INVISIBLE)
    text = _strip_control_chars(text)

    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = _HORIZONTAL_SPACE.sub(" ", raw_line).strip()
        if _BULLET_LINE.match(line):
            line = "- " + _BULLET_LINE.sub("", line, count=1).strip()
            if line == "- ":
                continue  # a bullet glyph on its own line
        lines.append(line)

    return _EXCESS_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def alnum_count(text: str) -> int:
    return sum(1 for ch in text if ch.isalnum())


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][\w'\u2019+#.-]*", text))
