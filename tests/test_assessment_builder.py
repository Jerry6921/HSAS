import json
from datetime import datetime, timezone
from pathlib import Path

from moodle_collector.transformation.assessment.builder import build_assessment_overview
from moodle_collector.transformation.assessment.schema import AssessmentItem
from moodle_collector.transformation.common.course_index import ArchiveIndex
from moodle_collector.transformation.common.course_mapper import build_course_archive
from moodle_collector.transformation.common.course_schema import StoredFile
from moodle_collector.transformation.course_materials.pdf_schema import PdfAnalysis


ROOT = Path(__file__).parents[1]


def test_legacy_course_rule_marker_is_migrated_on_read() -> None:
    item = AssessmentItem.model_validate(
        {
            "assessment_id": "legacy",
            "title": "Legacy Assessment",
            "assessment_type": "assignment",
            "extraction_methods": ["course_plugin"],
        }
    )

    assert item.extraction_methods == ["syllabus_text"]


def test_syllabus_confirms_and_enriches_assessment(tmp_path: Path) -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    state["course"]["id"] = "555001"
    state["course"]["baseurl"] = (
        "https://moodle.example.edu/course/view.php?id=555001"
    )
    state["section"].extend(
        [
            {
                "id": "102",
                "number": 2,
                "title": "Argument Analysis (9 Oct 17:00)",
                "rawtitle": "Argument Analysis (9 Oct 17:00)",
                "cmlist": [],
                "visible": False,
            },
            {
                "id": "103",
                "number": 3,
                "title": "Final Essay (Due 9 Dec 17:00)",
                "rawtitle": "Final Essay (Due 9 Dec 17:00)",
                "cmlist": [],
                "visible": False,
            },
        ]
    )
    archive = build_course_archive(
        state,
        course_title="Demo Course, 2026",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    text_relative = "courses/138907/analysis/text/syllabus.txt"
    text_path = tmp_path / text_relative
    text_path.parent.mkdir(parents=True)
    text_path.write_text(
        "--- Page 1 ---\nAssessment (100% Coursework)\n"
        "Tutorial participation (15%)\nTutorial attendance is mandatory.\n\n"
        "--- Page 2 ---\nFinal Essay (25%)\n"
        "You will write one 1000 word final essay. Final essay due 9 December at 17:00.\n"
        "Writing Portfolio (25% -- 15% argument analysis, 10% news report)\n"
        "The argument analysis (600 words) is due 9 October at 17:00.\n"
        "The news report (300 words) is due 4 December at 17:00.\n",
        encoding="utf-8",
    )
    syllabus_activity = archive.sections[0].activities[1]
    syllabus_activity.files.append(
        StoredFile(
            filename="syllabus.pdf",
            relative_path="courses/138907/files/syllabus.pdf",
            source_url="https://moodle.example.edu/pluginfile.php/syllabus.pdf",
            content_type="application/pdf",
            size_bytes=1,
            sha256="0" * 64,
            downloaded_at=datetime.now(timezone.utc),
            analysis=PdfAnalysis(
                status="complete",
                analyzed_at=datetime.now(timezone.utc),
                page_count=2,
                pages_with_text=2,
                word_count=20,
                character_count=100,
                estimated_reading_minutes=1,
                extracted_text_path=text_relative,
                extracted_text_sha256="1" * 64,
            ),
        )
    )

    overview = build_assessment_overview(ArchiveIndex(archive), storage_root=tmp_path)
    final = next(item for item in overview.items if item.assessment_type == "essay")

    assert final.status == "confirmed"
    assert final.weight_percent == 25
    assert final.word_limit == 1000
    assert final.due_at == datetime(2026, 12, 9, 17, 0, tzinfo=final.due_at.tzinfo)
    assert overview.grading_basis == "100% Coursework"
    assert overview.parser_version == "generic-v1"
    tutorial = next(
        item for item in overview.items if item.assessment_type == "participation"
    )
    assert tutorial.weight_percent == 15
    assert tutorial.extraction_methods == ["syllabus_text"]
    argument = next(
        item for item in overview.items if item.assessment_type == "argument_analysis"
    )
    assert argument.weight_percent == 15
    assert argument.word_limit == 600
    assert argument.group_id == "writing-portfolio"
    assert overview.groups[0].title == "Writing Portfolio"
    assert all(
        "course_plugin" not in item.extraction_methods for item in overview.items
    )


def test_generic_course_merges_moodle_and_syllabus_evidence(tmp_path: Path) -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    state["course"].update(
        {
            "id": "999001",
            "numsections": 1,
            "baseurl": "https://moodle.example.edu/course/view.php?id=999001",
        }
    )
    state["section"] = [
        {
            "id": "300",
            "number": 0,
            "title": "Assessments",
            "rawtitle": "Assessments",
            "cmlist": ["400", "401"],
            "visible": True,
        }
    ]
    state["cm"] = [
        {
            "id": "400",
            "name": "Research Project",
            "sectionid": "300",
            "module": "assign",
            "url": "https://moodle.example.edu/mod/assign/view.php?id=400",
            "visible": True,
            "uservisible": True,
            "accessvisible": True,
        },
        {
            "id": "401",
            "name": "Course Outline",
            "sectionid": "300",
            "module": "resource",
            "url": "https://moodle.example.edu/mod/resource/view.php?id=401",
            "visible": True,
            "uservisible": True,
            "accessvisible": True,
        },
    ]
    archive = build_course_archive(
        state,
        course_title="Generic Design Course, 2026",
        raw_state_path="courses/999001/raw/course-state.json",
    )
    text_relative = "courses/999001/analysis/text/course-outline.txt"
    text_path = tmp_path / text_relative
    text_path.parent.mkdir(parents=True)
    text_path.write_text(
        "--- Page 1 ---\nAssessment (100% Coursework)\n"
        "1. Research Project (40%)\n"
        "Submit a 2000-word research project by 15 November at 17:00.\n"
        "2. Group Presentation (20%)\n"
        "Present the team's findings in class.\n"
        "3. Final Examination (40%)\n"
        "The examination will be held on 9 December.\n",
        encoding="utf-8",
    )
    archive.sections[0].activities[1].files.append(
        StoredFile(
            filename="course-outline.pdf",
            relative_path="courses/999001/files/course-outline.pdf",
            source_url="https://moodle.example.edu/pluginfile.php/course-outline.pdf",
            content_type="application/pdf",
            size_bytes=1,
            sha256="2" * 64,
            downloaded_at=datetime.now(timezone.utc),
            analysis=PdfAnalysis(
                status="complete",
                analyzed_at=datetime.now(timezone.utc),
                page_count=1,
                pages_with_text=1,
                word_count=45,
                character_count=300,
                estimated_reading_minutes=1,
                extracted_text_path=text_relative,
                extracted_text_sha256="3" * 64,
            ),
        )
    )

    overview = build_assessment_overview(ArchiveIndex(archive), storage_root=tmp_path)
    by_title = {item.title: item for item in overview.items}

    assert overview.parser_version == "generic-v1"
    assert overview.total_weight_percent == 100
    assert overview.groups == []
    assert set(by_title) == {
        "Research Project",
        "Group Presentation",
        "Final Examination",
    }
    project = by_title["Research Project"]
    assert project.assessment_type == "project"
    assert project.word_limit == 2000
    assert project.weight_percent == 40
    assert project.due_at is not None
    assert set(project.extraction_methods) == {
        "moodle_activity",
        "syllabus_text",
    }
    assert any(source.activity_id == "400" for source in project.sources)
    assert by_title["Group Presentation"].scheduled_on is None
    assert by_title["Final Examination"].scheduled_on is not None


def test_generic_moodle_labels_extract_weights_dates_and_bonus(tmp_path: Path) -> None:
    state = {
        "course": {
            "id": "146267",
            "numsections": 4,
            "baseurl": "https://moodle.example.edu/course/view.php?id=146267",
        },
        "section": [
            {
                "id": "1",
                "number": 0,
                "title": "Course Information",
                "cmlist": ["10", "11"],
                "visible": True,
            },
            {"id": "2", "number": 1, "title": "Part I: Test", "cmlist": []},
            {"id": "3", "number": 2, "title": "Part II: Test", "cmlist": []},
            {"id": "4", "number": 3, "title": "Final Exam", "cmlist": []},
        ],
        "cm": [
            {
                "id": "10",
                "name": "Assessment Methods and Weighting...",
                "sectionid": "1",
                "module": "label",
                "visible": True,
                "uservisible": True,
                "accessvisible": True,
                "content_text": (
                    "Assessment and Weighting\n"
                    "Part I: 3 Assignments -- 5%\n"
                    "Part I: Test -- 15%\n"
                    "Part II: 3 Assignments -- 5%\n"
                    "Part II: Test -- 15%\n"
                    "Final Exam -- 60%\n"
                    "+3 BONUS percentage points for class participation!"
                ),
            },
            {
                "id": "11",
                "name": "Important Dates...",
                "sectionid": "1",
                "module": "label",
                "visible": True,
                "uservisible": True,
                "accessvisible": True,
                "content_text": (
                    "Important Dates\n"
                    "Part I: Test -- Friday, October 2nd (in-class)\n"
                    "Part II: Test -- TBD\nFinal Exam -- TBD"
                ),
            },
        ],
    }
    archive = build_course_archive(
        state,
        course_title="MATH1851 Calculus [2026]",
        raw_state_path="courses/146267/raw/course-state.json",
    )

    overview = build_assessment_overview(ArchiveIndex(archive), storage_root=tmp_path)
    by_title = {item.title: item for item in overview.items}

    assert overview.total_weight_percent == 100
    assert by_title["Part I: Test"].assessment_type == "exam"
    assert by_title["Part I: Test"].weight_percent == 15
    assert by_title["Part I: Test"].scheduled_on.isoformat() == "2026-10-02"
    assert by_title["Part II: Assignments"].weight_percent == 5
    assert by_title["Final Exam"].weight_percent == 60
    assert by_title["Class Participation Bonus"].bonus_percent == 3
    assert "Official date is TBD" in by_title["Part II: Test"].requirements
    assert not any("have no confirmed weight" in warning for warning in overview.warnings)
