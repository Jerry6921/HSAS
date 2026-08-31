import json
from pathlib import Path

import pytest

from hku_moodle_collector.acquisition.moodle_api import MoodleAjaxError, decode_ajax_response


ROOT = Path(__file__).parents[1]


def fixture_state() -> dict:
    return json.loads((ROOT / "tests/fixtures/course_state.json").read_text())


def test_decode_ajax_response_with_json_string_data() -> None:
    state = fixture_state()
    payload = [{"error": False, "data": json.dumps(state)}]
    assert decode_ajax_response(payload)["course"]["id"] == "138907"


def test_decode_double_encoded_result() -> None:
    state = fixture_state()
    assert decode_ajax_response(json.dumps(json.dumps(state)))["cm"][0]["id"] == "200"


def test_decode_ajax_error() -> None:
    with pytest.raises(MoodleAjaxError, match="Not allowed"):
        decode_ajax_response(
            [{"error": True, "exception": {"message": "Not allowed"}}]
        )
