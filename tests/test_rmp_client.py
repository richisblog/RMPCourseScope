import json
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rmp_client import RMPAPI, RMPAPIError


class RMPClientTests(unittest.TestCase):
    def make_response(self, payload, status=200):
        response = Mock()
        response.status_code = status
        response.ok = status < 400
        response.raise_for_status.side_effect = None if response.ok else Exception("http")
        response.json.return_value = payload
        return response

    def test_session_has_public_rmp_authorization(self):
        client = RMPAPI()
        self.assertEqual(client.session.headers["Authorization"], "Basic dGVzdDp0ZXN0")

    def test_search_teachers_sends_school_id_and_returns_all_candidates(self):
        client = RMPAPI()
        payload = {"data": {"newSearch": {"teachers": {"resultCount": 1, "edges": [{"node": {
                "id": "VGVhY2hlci0x", "legacyId": 1, "firstName": "Ada", "lastName": "Lovelace",
                "school": {"id": "school", "name": "UC Davis"}, "avgRating": 4.5,
                "avgDifficulty": 2.0, "numRatings": 3, "wouldTakeAgainPercent": 90,
                "department": "CS"
            }}]}}}}
        client.session.post = Mock(return_value=self.make_response(payload))
        result = client.search_teachers("Ada Lovelace", school_id="school")
        sent = client.session.post.call_args.kwargs["json"]
        self.assertEqual(sent["variables"]["query"]["schoolID"], "school")
        self.assertEqual(result[0]["legacyId"], 1)

    def test_reviews_use_class_as_course_code_and_support_cursor_pagination(self):
        client = RMPAPI()
        client.session.post = Mock(side_effect=[
            self.make_response({"data": {"node": {"ratings": {"edges": [{"cursor": "c1", "node": {
                "id": "r1", "class": "ECS36B", "courseType": 3, "comment": "Great",
                "qualityRating": 5, "difficultyRatingRounded": 2, "date": "2026-01-01"
            }}], "pageInfo": {"hasNextPage": True, "endCursor": "c1"}}}}}),
            self.make_response({"data": {"node": {"ratings": {"edges": [{"cursor": "c2", "node": {
                "id": "r2", "class": "ECS36C", "courseType": 3, "comment": "Good",
                "qualityRating": 4, "difficultyRatingRounded": 3, "date": "2026-01-02"
            }}], "pageInfo": {"hasNextPage": False, "endCursor": "c2"}}}}}),
        ])
        result = list(client.iter_teacher_reviews("teacher", page_size=1))
        self.assertEqual([r["course_code"] for r in result], ["ECS36B", "ECS36C"])
        self.assertEqual(client.session.post.call_count, 2)

    def test_graphql_errors_raise_structured_error(self):
        client = RMPAPI()
        client.session.post = Mock(return_value=self.make_response({"errors": [{"message": "bad field"}]}))
        with self.assertRaises(RMPAPIError):
            client.search_teachers("Ada")


if __name__ == "__main__":
    unittest.main()
