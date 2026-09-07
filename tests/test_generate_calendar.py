from datetime import datetime, timezone

from hsas.domain.information import InformationStore
from hsas.domain.information.generate_calendar import build_ics


def test_ics_exports_recurrence_exclusions_additions_and_changed_instance() -> None:
    store = InformationStore.model_validate(
        {
            "updated_at": "2026-09-07T08:00:00+00:00",
            "courses": [{"course_id": "1", "code": "DEMO1001", "title": "Demo"}],
            "items": [
                {
                    "item_id": "demo-class",
                    "course_id": "1",
                    "title": "Lecture",
                    "category": "class",
                    "date_status": "confirmed",
                    "location": "Room A",
                    "recurrence": {
                        "weekdays": [0],
                        "valid_from": "2026-09-01",
                        "valid_until": "2026-11-30",
                        "start_time": "09:00:00",
                        "end_time": "09:50:00",
                        "excluded_dates": ["2026-10-05"],
                        "additional_dates": ["2026-10-06"],
                        "exceptions": [
                            {"date": "2026-10-12", "status": "cancelled"},
                            {
                                "date": "2026-10-19",
                                "status": "changed",
                                "start_time": "10:00:00",
                                "end_time": "10:50:00",
                                "location": "Room B",
                            },
                        ],
                    },
                }
            ],
        }
    )

    content = build_ics(store)

    assert "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261130T155959Z" in content
    assert "20261005T090000" in content
    assert "20261012T090000" in content
    assert "20261019T090000" in content
    assert "RDATE;TZID=Asia/Hong_Kong:20261006T090000" in content
    assert "DTSTART;TZID=Asia/Hong_Kong:20261019T100000" in content
    assert "LOCATION:Room B" in content
    assert content.endswith("END:VCALENDAR\r\n")


def test_ics_exports_exact_and_date_only_items() -> None:
    store = InformationStore.model_validate(
        {
            "updated_at": datetime(2026, 9, 7, tzinfo=timezone.utc),
            "courses": [{"course_id": "1", "code": "DEMO1001", "title": "Demo"}],
            "items": [
                {
                    "item_id": "test",
                    "course_id": "1",
                    "title": "Test",
                    "category": "exam",
                    "starts_at": "2026-10-02T10:00:00+08:00",
                    "ends_at": "2026-10-02T11:00:00+08:00",
                },
                {
                    "item_id": "deadline",
                    "course_id": "1",
                    "title": "Deadline",
                    "category": "deadline",
                    "due_on": "2026-10-03",
                },
            ],
        }
    )
    content = build_ics(store)
    assert "DTSTART;TZID=Asia/Hong_Kong:20261002T100000" in content
    assert "DTEND;TZID=Asia/Hong_Kong:20261002T110000" in content
    assert "DTSTART;VALUE=DATE:20261003" in content
