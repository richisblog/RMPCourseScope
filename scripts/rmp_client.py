"""A defensive Python client for RateMyProfessors' public GraphQL API.

The client keeps RMP's course code (``class``) separate from an optional
catalog title. RMP supplies codes such as ``ECS36B``; it does not reliably
provide official catalog titles.
"""

from __future__ import annotations

import base64
import difflib
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Mapping, Optional

try:
    import requests
except ImportError:  # pragma: no cover - keeps the client usable in stdlib-only environments
    import json
    from urllib.request import Request, urlopen

    class _Response:
        def __init__(self, raw):
            self._raw = raw
        def raise_for_status(self):
            if not (200 <= self._raw.status < 300):
                raise OSError(f"HTTP {self._raw.status}")
        def json(self):
            return json.loads(self._raw.read().decode("utf-8"))

    class _Session:
        def __init__(self):
            self.headers = {}
        def post(self, url, json=None, timeout=None):
            request = Request(url, data=__import__("json").dumps(json).encode(),
                              headers=self.headers, method="POST")
            return _Response(urlopen(request, timeout=timeout))

    class _RequestsCompat:
        Session = _Session
        RequestException = OSError
    requests = _RequestsCompat()


class RMPAPIError(RuntimeError):
    """Raised for HTTP, GraphQL, or malformed RMP responses."""


@dataclass(frozen=True)
class RMPConfig:
    timeout: float = 15.0
    retries: int = 2
    backoff_seconds: float = 0.4
    user_agent: str = "rmp-client/1.0"


class RMPAPI:
    BASE_URL = "https://www.ratemyprofessors.com/graphql"
    AUTHORIZATION = "Basic dGVzdDp0ZXN0"

    def __init__(self, config: Optional[RMPConfig] = None, session: Optional[requests.Session] = None):
        self.config = config or RMPConfig()
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": self.AUTHORIZATION,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.config.user_agent,
        })

    def _post(self, query: str, variables: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        payload = {"query": query, "variables": dict(variables or {})}
        last_error: Optional[Exception] = None
        for attempt in range(self.config.retries + 1):
            try:
                response = self.session.post(self.BASE_URL, json=payload, timeout=self.config.timeout)
                response.raise_for_status()
                body = response.json()
                if body.get("errors"):
                    messages = "; ".join(str(e.get("message", e)) for e in body["errors"])
                    raise RMPAPIError(f"RMP GraphQL error: {messages}")
                if not isinstance(body.get("data"), dict):
                    raise RMPAPIError("RMP response did not contain a data object")
                return body["data"]
            except RMPAPIError:
                raise
            except (requests.RequestException, ValueError, TypeError) as exc:
                last_error = exc
                if attempt < self.config.retries:
                    time.sleep(self.config.backoff_seconds * (2 ** attempt))
        raise RMPAPIError(f"RMP request failed after retries: {last_error}") from last_error

    def search_school(self, name: str, first: int = 20) -> List[Dict[str, Any]]:
        query = """query($q: SchoolSearchQuery!, $first: Int!) {
          newSearch { schools(query: $q, first: $first) {
            edges { node { id legacyId name city state } }
          }}
        }"""
        data = self._post(query, {"q": {"text": name}, "first": first})
        return [edge["node"] for edge in data.get("newSearch", {}).get("schools", {}).get("edges", [])]

    def search_teachers(self, name: str, school_id: Optional[str] = None,
                        first: int = 50) -> List[Dict[str, Any]]:
        query = """query($query: TeacherSearchQuery!, $first: Int!) {
          newSearch { teachers(query: $query, first: $first) {
            resultCount edges { cursor node {
              id legacyId firstName lastName department avgRating avgDifficulty
              numRatings wouldTakeAgainPercent school { id legacyId name city state }
            }}
          }}
        }"""
        search_query: Dict[str, Any] = {"text": name}
        if school_id:
            search_query["schoolID"] = school_id
        data = self._post(query, {"query": search_query, "first": first})
        return [edge["node"] for edge in data.get("newSearch", {}).get("teachers", {}).get("edges", [])]

    def find_teacher(self, first_name: str, last_name: str, school_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        candidates = self.search_teachers(f"{first_name} {last_name}", school_id=school_id)
        if not candidates:
            return None
        wanted = f"{first_name} {last_name}".strip().casefold()
        def score(node: Dict[str, Any]) -> tuple:
            actual = f"{node.get('firstName', '')} {node.get('lastName', '')}".strip().casefold()
            return (actual == wanted, difflib.SequenceMatcher(None, wanted, actual).ratio(), node.get("numRatings") or 0)
        return max(candidates, key=score)

    def get_teacher_profile(self, teacher_id: str) -> Dict[str, Any]:
        query = """query($id: ID!) { node(id: $id) { ... on Teacher {
          id legacyId firstName lastName department avgRating avgDifficulty numRatings
          wouldTakeAgainPercent school { id legacyId name city state }
          ratingsDistribution { r1 r2 r3 r4 r5 total }
          teacherRatingTags { tagName tagCount }
          courseCodes { courseName courseCount }
        }}}"""
        data = self._post(query, {"id": teacher_id})
        profile = data.get("node")
        if not profile:
            raise RMPAPIError(f"Teacher not found: {teacher_id}")
        profile["profile_url"] = self.get_teacher_url(profile.get("legacyId") or self.numeric_id(teacher_id))
        return profile

    def iter_teacher_reviews(self, teacher_id: str, page_size: int = 50,
                             limit: Optional[int] = None, course_name: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        query = """query($id: ID!, $first: Int!, $after: String) { node(id: $id) { ... on Teacher {
          ratings(first: $first, after: $after) { edges { cursor node {
            adminReviewedAt id class courseType comment grade ratingTags qualityRating
            difficultyRatingRounded clarityRatingRounded helpfulRatingRounded iWouldTakeAgain
            date createdByUser flagStatus isForOnlineClass isForCredit attendanceMandatory
            textbookIsUsed legacyId maskCount teacherVisible thumbsDownTotal thumbsUpTotal
          }} pageInfo { hasNextPage endCursor } }
        }}}"""
        after = None
        yielded = 0
        while True:
            data = self._post(query, {"id": teacher_id, "first": max(1, min(page_size, 100)), "after": after})
            ratings = data.get("node", {}).get("ratings")
            if not ratings:
                return
            for edge in ratings.get("edges", []):
                node = edge.get("node", {})
                code = node.get("class")
                if course_name and (code or "").casefold() != course_name.casefold():
                    continue
                yield {"review_id": node.get("id"), "course_code": code,
                       "raw": dict(node), "course_title": None, "course_type": node.get("courseType"),
                       "comment": (node.get("comment") or "").replace("\r", " ").replace("\n", " ").strip(),
                       "grade": node.get("grade"), "rating": node.get("qualityRating"),
                       "difficulty": node.get("difficultyRatingRounded"),
                       "clarity": node.get("clarityRatingRounded"),
                       "helpfulness": node.get("helpfulRatingRounded"),
                       "rating_tags": node.get("ratingTags"),
                       "would_take_again": node.get("iWouldTakeAgain"), "date": node.get("date"),
                       "is_online_class": node.get("isForOnlineClass"),
                       "is_for_credit": node.get("isForCredit"),
                       "attendance_mandatory": node.get("attendanceMandatory"),
                       "textbook_used": node.get("textbookIsUsed")}
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            page = ratings.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                return
            after = page.get("endCursor")
            if not after:
                raise RMPAPIError("RMP indicated another page but returned no endCursor")

    def get_teacher_reviews(self, teacher_id: str, first_name: str = "", last_name: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        return list(self.iter_teacher_reviews(teacher_id, limit=limit))

    @staticmethod
    def numeric_id(relay_id: str) -> str:
        try:
            decoded = base64.b64decode(relay_id).decode("utf-8")
            return decoded.rsplit("-", 1)[-1]
        except Exception:
            return relay_id

    @classmethod
    def get_teacher_url(cls, teacher_id: Any) -> str:
        return f"https://www.ratemyprofessors.com/professor/{teacher_id}"

    def get_ucdavis_search_url(self, first_name: str, last_name: str) -> str:
        from urllib.parse import quote
        return f"https://www.ratemyprofessors.com/search/professors/?q={quote(f'{first_name} {last_name}')}"

    get_search_url = get_ucdavis_search_url
