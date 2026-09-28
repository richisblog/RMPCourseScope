import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ucd_rmp.course_codes import parse_course_label


def test_official_ucdavis_format_keeps_suffix_and_padding():
    parsed = parse_course_label("mat 21a")
    assert parsed.comparison_key == "MAT21A"
    assert parsed.official_display == "MAT 021A"


def test_missing_subject_is_not_invented():
    parsed = parse_course_label("21A")
    assert parsed.comparison_key == "21A"
    assert parsed.official_display is None
