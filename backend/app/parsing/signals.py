"""Deterministic text signals: contact details, dates, quantified results, bullets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# --------------------------------------------------------------------------- contact

EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}(?![\w-])")
_PHONE_CANDIDATE = re.compile(r"(?<![\w/])\+?\(?\d[\d\s().-]{6,22}\d(?![\w/])")
_LINKEDIN = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w%-]+/?", re.IGNORECASE)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+/?", re.IGNORECASE)
_EXPLICIT_URL = re.compile(r"(?:https?://|www\.)[^\s|,;()<>]+", re.IGNORECASE)
_BARE_DOMAIN = re.compile(
    r"(?<![@\w.-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:dev|io|me|app|com|net|org|co|xyz|tech|site)(?:/[\w./-]*)?(?![\w@])",
    re.IGNORECASE,
)

LinkKind = Literal["linkedin", "github", "website"]


@dataclass(frozen=True)
class FoundLink:
    kind: LinkKind
    url: str


def find_emails(text: str) -> list[str]:
    return _unique(match.group(0) for match in EMAIL.finditer(text))


def find_phones(text: str) -> list[str]:
    phones = []
    for match in _PHONE_CANDIDATE.finditer(text):
        candidate = match.group(0).strip()
        digits = re.sub(r"\D", "", candidate)
        # 9-15 digits (E.164 max); excludes year ranges like "2018 - 2021" (8 digits).
        if 9 <= len(digits) <= 15 and not re.fullmatch(r"(?:19|20)\d{2}\s*[-\u2013]\s*(?:19|20)\d{2}", candidate):
            phones.append(candidate)
    return _unique(phones)


def find_links(text: str, *, header_text: str = "") -> list[FoundLink]:
    links: list[FoundLink] = []
    seen: set[str] = set()

    def add(kind: LinkKind, url: str) -> None:
        cleaned = url.rstrip("/.,;)")
        key = re.sub(r"^(?:https?://)?(?:www\.)?", "", cleaned.lower())
        if key and key not in seen:
            seen.add(key)
            links.append(FoundLink(kind=kind, url=cleaned))

    for match in _LINKEDIN.finditer(text):
        add("linkedin", match.group(0))
    for match in _GITHUB.finditer(text):
        add("github", match.group(0))
    for match in _EXPLICIT_URL.finditer(text):
        url = match.group(0)
        if "linkedin.com" not in url.lower() and "github.com" not in url.lower():
            add("website", url)
    # Bare domains (janedoe.dev) only in the header, where they are almost always a portfolio link.
    for match in _BARE_DOMAIN.finditer(header_text):
        url = match.group(0)
        lowered = url.lower()
        if "linkedin.com" in lowered or "github.com" in lowered:
            continue
        if any(lowered in email.lower() for email in find_emails(header_text)):
            continue
        add("website", url)
    return links


_NAME_TOKEN = re.compile(
    r"^[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff][A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff'\u2019.-]*$"
)


def guess_name(header_lines: list[str]) -> str | None:
    """The first header line that looks like a personal name (position-based inference)."""

    for raw in header_lines[:5]:
        line = re.sub(r"^#+\s*", "", raw).strip()
        if not line:
            continue
        candidate = re.split(r"\s[|•·,]\s|\s{2,}", line)[0].strip()
        words = candidate.split()
        if 2 <= len(words) <= 5 and all(_NAME_TOKEN.match(word) for word in words) and len(candidate) <= 60:
            return candidate
        return None  # only the first non-empty line is considered
    return None


# --------------------------------------------------------------------------- dates

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_YEAR = r"(?:19|20)\d{2}"
DATE_TOKEN = re.compile(
    rf"(?P<month_name>{_MONTH})\.?\s+(?P<y1>{_YEAR})"
    rf"|(?P<month_num>0?[1-9]|1[0-2])\s*[/.]\s*(?P<y2>{_YEAR})"
    rf"|(?<![\d/])(?P<y3>{_YEAR})(?![\d/])",
    re.IGNORECASE,
)
PRESENT = re.compile(r"\b(?:present|current(?:ly)?|now|to date|ongoing|till date)\b", re.IGNORECASE)

DateStyle = Literal["Mon YYYY", "Month YYYY", "MM/YYYY", "YYYY"]


def date_style(token: str) -> DateStyle | None:
    match = DATE_TOKEN.search(token)
    if match is None:
        return None
    if match.group("month_name"):
        name = match.group("month_name").rstrip(".")
        return "Mon YYYY" if len(name) <= 4 and name.lower() not in {"june", "july"} else "Month YYYY"
    if match.group("month_num"):
        return "MM/YYYY"
    return "YYYY"


_MONTH_INDEX = {
    name: index
    for index, name in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
    )
}


def parse_date(token: str | None) -> tuple[int, int] | None:
    """Return ``(year, month)`` (month 0 when unknown) for the first date in ``token``."""

    if not token:
        return None
    match = DATE_TOKEN.search(token)
    if match is None:
        return None
    if match.group("month_name"):
        return int(match.group("y1")), _MONTH_INDEX[match.group("month_name")[:3].lower()]
    if match.group("month_num"):
        return int(match.group("y2")), int(match.group("month_num"))
    return int(match.group("y3")), 0


def is_present(token: str | None) -> bool:
    return bool(token and PRESENT.search(token))


# --------------------------------------------------------------------------- quantified results

_METRIC = re.compile(
    r"[$€£¥₦₹]\s?\d[\d,.]*\s?(?:[kmb]|bn|million|billion|thousand)?\b"  # currency
    r"|\d[\d,.]*\s?%|\d[\d,.]*\s?(?:per\s?cent|percent)\b"  # percentages
    r"|\b\d+(?:\.\d+)?\s?x\b"  # multipliers (3x)
    r"|\b\d+(?:\.\d+)?\s?(?:k|m|bn)\+?(?=\W|$)"  # 10k, 2M
    r"|\b\d{1,3}(?:,\d{3})+\+?"  # 1,200,000
    r"|\b\d+(?:\.\d+)?\+?(?=\s+[a-z])",  # 40 services, 5 engineers
    re.IGNORECASE,
)


def find_metrics(text: str) -> list[str]:
    """Quantities in ``text`` that express scale or impact; years and dates are not metrics."""

    found = []
    for match in _METRIC.finditer(text):
        value = match.group(0).strip()
        digits = re.sub(r"\D", "", value)
        if re.fullmatch(r"(?:19|20)\d{2}", digits) and not re.search(r"[%$€£¥₦₹,xkmb]", value, re.IGNORECASE):
            continue  # a bare year
        found.append(value)
    return _unique(found)


# --------------------------------------------------------------------------- helpers


def bullet_lines(text: str) -> list[str]:
    return [line[2:].strip() for line in text.split("\n") if line.startswith("- ") and line[2:].strip()]


def _unique(values: object) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:  # type: ignore[attr-defined]
        key = str(value).lower()
        if key not in seen:
            seen.add(key)
            result.append(str(value))
    return result
