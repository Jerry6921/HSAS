"""Portable Notion import package, including unchanged original files."""

from __future__ import annotations

import csv
from io import StringIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from hsas.infrastructure.storage.json_store import atomic_write, safe_filename


def plain_property(value: dict):
    for key in ("title", "rich_text"):
        if key in value:
            return "".join(v.get("text", {}).get("content", "") for v in value[key])
    if "date" in value:
        return (value["date"] or {}).get("start", "")
    if "select" in value:
        return (value["select"] or {}).get("name", "")
    if "number" in value:
        return value["number"]
    if "checkbox" in value:
        return value["checkbox"]
    return ""


def export_package(projection: dict, calendar: bytes | None, destination: Path,
                   *, include_files: bool = True) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    atomic_write(destination / "notion-plan.json", json.dumps(projection, ensure_ascii=False, indent=2))
    library = projection.get("scope") == "library"
    if library:
        for retired in ("HIQS-calendar.ics", "items.csv", "calendar.csv"):
            (destination / retired).unlink(missing_ok=True)
    if calendar is not None and not library:
        atomic_write(destination / "HIQS-calendar.ics", calendar)
    kinds = ("courses", "materials") if library else ("courses", "items", "calendar", "materials")
    for kind in kinds:
        rows = [r for r in projection["records"] if r["kind"] == kind]
        keys = list(dict.fromkeys(k for row in rows for k in row["properties"]))
        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: plain_property(v) for k, v in row["properties"].items()})
        atomic_write(destination / f"{kind}.csv", "\ufeff" + output.getvalue())
    for course in (r for r in projection["records"] if r["kind"] == "courses"):
        details = course["details"]
        lines = [f"# {details['code']} · {details['title']}", "",
                 details.get("overview") or "", "", "## 课程资料"]
        for row in projection["records"]:
            if row["kind"] != "materials" or row["course_id"] != course["identity"]:
                continue
            value = row["file"]
            target = f"materials/{row['identity'].split(':')[0]}/{value.get('sha256', 'link')}/{value['title']}"
            lines.append(f"- {value['section']}: [{value['title']}]({target if value.get('path') else value.get('url', '')})")
        if not library:
            lines.extend(["", "## 课程事项"])
        for row in projection["records"]:
            if row["kind"] == "items" and row["course_id"] == course["identity"]:
                d = row["details"]
                lines.extend([f"### {d['title']}", d.get("description") or "",
                    f"分数占比：{d['weight_percent']}%" if d.get("weight_percent") is not None else "",
                    f"日期确认状态：{d['date_status']}"])
        atomic_write(destination / f"{safe_filename(details['code'])}.md", "\n".join(lines))
    atomic_write(destination / "README.md", """# HIQS → Notion Course Library

Notion 保存课程、课程档案、原文件与笔记。待办与日程由 Apple 提醒事项和日历管理。
CSV 可导入课程与资料数据库；Markdown 可导入课程页面。原文件保留原始字节。
本包包含私人课程内容，不要提交到公开仓库。
""" if library else """# HIQS → Notion

CSV 可导入为数据库；课程 Markdown 可导入为页面。HIQS-calendar.ics 保留
重复规则、排除日期和例外，供支持 iCalendar 的日历使用。Notion 原生日历
使用 calendar.csv 中展开的每次活动。关系、公式、彩色视图由 API 适配器
配置，CSV 导入不能自动创建这些设置。HIQS-originals.zip 保留原文件字节。
本包包含私人课程内容，不要提交到公开仓库。
""")
    archived = 0
    if include_files:
        temporary = destination / ".HIQS-originals.zip.tmp"
        try:
            with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
                for file in destination.iterdir():
                    if file.suffix in {".md", ".csv", ".ics", ".json"}:
                        archive.write(file, file.name)
                for row in projection["records"]:
                    value = row.get("file", {})
                    if not value.get("path"):
                        continue
                    name = f"materials/{row['course_id']}/{value['sha256']}/{value['title']}"
                    archive.write(value["path"], name)
                    archived += 1
            temporary.replace(destination / "HIQS-originals.zip")
        finally:
            temporary.unlink(missing_ok=True)
    return {"destination": str(destination.resolve()), "counts": projection["counts"],
            "original_files": archived, "warnings": projection["warnings"]}
