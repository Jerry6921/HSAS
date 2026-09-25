from hsas.domain.courses.define_evidence import (
    LinkedPageEvidence,
    RecursiveCollectionReport,
)
from hsas.domain.courses.define_courses import CourseActivity
from hsas.domain.information import InformationUpdate
from hsas.infrastructure.moodle.download_files import (
    MoodleDiscoveryService,
    MoodleParseService,
    parse_html_evidence,
)
from hsas.interfaces.generate_typescript import schema_to_typescript


def test_evidence_contracts_validate_recursive_metadata() -> None:
    page = LinkedPageEvidence(url="https://moodle.hku.hk/course/view.php?id=1", depth=2)
    report = RecursiveCollectionReport(
        truncated=False,
        max_link_depth=6,
        max_linked_pages=100,
        max_linked_files=200,
        discovered_pages=2,
        discovered_files=3,
    )
    assert page.depth == 2
    assert report.discovered_files == 3


def test_legacy_activity_metadata_is_migrated_to_typed_evidence() -> None:
    activity = CourseActivity.model_validate({
        "module_id": "page-1",
        "name": "Week 1",
        "category": "resource",
        "module": "page",
        "metadata": {
            "content_text": "Hello",
            "linked_pages": [{"url": "https://moodle.hku.hk/mod/page/view.php?id=2", "depth": 1}],
            "recursive_collection_truncated": True,
            "recursive_collection_limits": {"max_link_depth": 2},
        },
    })
    assert activity.content_text == "Hello"
    assert activity.linked_pages[0].depth == 1
    assert activity.collection_report.truncated is True


def test_parse_stage_is_pure_and_returns_next_frontier() -> None:
    result = parse_html_evidence(
        '<html><title>Week 1</title><body><p>Hello</p><a href="/mod/page/view.php?id=2">Next</a></body></html>',
        "https://moodle.hku.hk/course/view.php?id=1",
        "https://moodle.hku.hk",
    )
    assert result.title == "Week 1"
    assert "Hello" in result.text
    assert result.discovered.page_urls == ("https://moodle.hku.hk/mod/page/view.php?id=2",)


def test_collection_stages_are_independently_callable() -> None:
    discovery = MoodleDiscoveryService()
    parser = MoodleParseService(discovery)
    result = parser.parse(
        '<a href="/mod/page/view.php?id=3">Next</a>',
        "https://moodle.hku.hk/mod/page/view.php?id=1",
        "https://moodle.hku.hk",
    )
    assert result.discovered == discovery.discover(
        '<a href="/mod/page/view.php?id=3">Next</a>',
        "https://moodle.hku.hk/mod/page/view.php?id=1",
        "https://moodle.hku.hk",
    )


def test_schema_to_typescript_is_deterministic() -> None:
    schema = InformationUpdate.model_json_schema()
    output = schema_to_typescript(schema)
    assert "export interface InformationUpdate" in output
    assert "export interface CourseRecord" in output
    assert output == schema_to_typescript(schema)
