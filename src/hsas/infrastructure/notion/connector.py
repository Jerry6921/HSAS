"""Convert the same projection into Notion connector property arguments."""

from hsas.infrastructure.notion.export import plain_property


def connector_properties(record: dict, course_pages: dict[str, str],
                         item_pages: dict[str, str] | None = None) -> dict:
    result = {}
    for name, prop in record["properties"].items():
        if "date" in prop:
            value = prop["date"]
            if value:
                result[f"date:{name}:start"] = value["start"]
                if value.get("end"):
                    result[f"date:{name}:end"] = value["end"]
                result[f"date:{name}:is_datetime"] = int("T" in value["start"])
        elif "checkbox" in prop:
            result[name] = "__YES__" if prop["checkbox"] else "__NO__"
        else:
            value = plain_property(prop)
            # The connector interprets a syntactically valid JSON object/array
            # string as a structured property value. Keep source JSON as text.
            if "rich_text" in prop and value.lstrip().startswith(("{", "[")):
                value = "HIQS data:\n" + value
            if value is not None:
                result[name] = value
    if record.get("course_id"):
        result["课程" if record["kind"] == "materials" else "Course"] = [course_pages[record["course_id"]]]
    if record["kind"] == "calendar" and item_pages:
        result["Item"] = [item_pages[record["item_id"]]]
    return result
