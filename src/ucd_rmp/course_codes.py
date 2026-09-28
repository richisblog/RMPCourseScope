"""UC Davis course-code parsing without inventing missing information."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ParsedCourseLabel:
    raw: str
    subject: Optional[str]
    number: Optional[str]
    suffix: Optional[str]
    comparison_key: str
    official_display: Optional[str]
    parse_status: str


_FULL = re.compile(r"^([A-Z]{2,4})(\d{1,3})([A-Z]{0,3})$")
_NUMBER = re.compile(r"^(\d{1,3})([A-Z]{0,3})$")


def _clean(raw: str) -> str:
    value = unicodedata.normalize("NFKC", str(raw or "")).upper().strip()
    return re.sub(r"[^A-Z0-9]", "", value)


def parse_course_label(raw: str) -> ParsedCourseLabel:
    original = str(raw or "")
    cleaned = _clean(original)
    full = _FULL.fullmatch(cleaned)
    if full:
        subject, number, suffix = full.groups()
        normalized_number = str(int(number)).zfill(3)
        return ParsedCourseLabel(original, subject, normalized_number, suffix or None,
                                 subject + str(int(number)) + (suffix or ""),
                                 f"{subject} {normalized_number}{suffix or ''}", "full")
    number_only = _NUMBER.fullmatch(cleaned)
    if number_only:
        number, suffix = number_only.groups()
        return ParsedCourseLabel(original, None, str(int(number)), suffix or None,
                                 str(int(number)) + (suffix or ""), None, "subject_missing")
    return ParsedCourseLabel(original, None, None, None, cleaned, None, "unparsed")
