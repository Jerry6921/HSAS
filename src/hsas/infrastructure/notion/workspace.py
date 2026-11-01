"""Resumable stable-ID upserts into an existing Notion learning workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hsas.application.notion_projection import rich_text, select
from hsas.infrastructure.notion.client import NotionAPIError, NotionClient
from hsas.infrastructure.notion.export import plain_property
from hsas.infrastructure.storage.json_store import read_json, write_json


IDENTITY_PROPERTIES = {"courses": "HIQS Course ID", "items": "HIQS Item ID",
                       "calendar": "HIQS Occurrence ID", "materials": "资料 ID"}


def _equivalent(first: dict, second: dict) -> bool:
    if "date" in first:
        # API normalizes offsets and timestamps. Compare values as instants.
        a, b = first.get("date"), second.get("date")
        if not a or not b:
            return a == b
        def moment(value):
            if value and "T" in value:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value
        return all(moment(a.get(k)) == moment(b.get(k)) for k in ("start", "end"))
    if "relation" in first:
        return {v["id"].replace("-", "") for v in first["relation"]} == {
            v["id"].replace("-", "") for v in second.get("relation", [])}
    return plain_property(first) == plain_property(second)


class NotionWorkspaceAdapter:
    def __init__(self, client: NotionClient, config: dict, state_path: Path):
        self.client, self.config, self.state_path = client, config, state_path
        self.identities = {k: v for k, v in IDENTITY_PROPERTIES.items()
                           if config.get("include_execution", False) or k in {"courses", "materials"}}
        try:
            self.state = read_json(state_path) if state_path.exists() else {"files": {}}
            if not isinstance(self.state, dict) or not isinstance(self.state.get("files"), dict):
                self.state = {"files": {}}
        except (OSError, ValueError):
            # Derived checkpoints can be rebuilt from stable page identities
            # and attached file markers; canonical facts are never repaired.
            self.state = {"files": {}}

    def check_connection(self) -> dict:
        self.client.request("GET", "/users/me")
        sources = self.config.get("data_sources", {})
        missing = [kind for kind in self.identities if kind not in sources]
        if missing:
            raise ValueError("Notion data source IDs are missing: " + ", ".join(missing))
        for kind, source in sources.items():
            if kind in self.identities:
                schema = self.client.request("GET", f"/data_sources/{source}")
                if self.identities[kind] not in schema["properties"]:
                    raise ValueError(f"{kind} identity property is missing")
        return {"connected": True, "data_sources": sources,
                "workspace_url": "https://www.notion.so/" + self.config["parent_page_id"].replace("-", "")}

    def _ensure_schema(self, projection: dict) -> None:
        for kind, source in self.config["data_sources"].items():
            if kind not in self.identities:
                continue
            schema = self.client.request("GET", f"/data_sources/{source}")
            requested = {}
            for row in projection["records"]:
                if row["kind"] == kind:
                    for name, prop in row["properties"].items():
                        prop_type = next(iter(prop))
                        if name not in schema["properties"]:
                            requested[name] = {prop_type: {}}
            relation = "课程" if kind == "materials" else "Course"
            if kind != "courses" and relation not in schema["properties"]:
                requested[relation] = {"relation": {
                    "data_source_id": self.config["data_sources"]["courses"],
                    "type": "single_property", "single_property": {}}}
            if kind == "calendar" and "Item" not in schema["properties"]:
                requested["Item"] = {"relation": {
                    "data_source_id": self.config["data_sources"]["items"],
                    "type": "single_property", "single_property": {}}}
            if kind == "materials":
                if "同步状态" not in schema["properties"]:
                    requested["同步状态"] = {"select": {"options": [
                        {"name": n, "color": c} for n, c in (
                            ("已上传", "green"), ("等待上传", "yellow"),
                            ("超过上传限制", "orange"), ("上传失败", "red"))]}}
                if "HIQS Present" not in schema["properties"]:
                    requested["HIQS Present"] = {"checkbox": {}}
            if requested:
                self.client.request("PATCH", f"/data_sources/{source}", {"properties": requested})

    def synchronize(self, projection: dict) -> dict[str, Any]:
        """Reconcile before every write; do not delete pages or personal fields."""
        unsupported = {row["kind"] for row in projection["records"]} - self.identities.keys()
        if unsupported:
            raise ValueError("Notion library cannot publish execution records: " + ", ".join(sorted(unsupported)))
        self.check_connection()
        self._ensure_schema(projection)
        sources = self.config["data_sources"]
        indexes = {}
        for kind in self.identities:
            index = {}
            for row in self.client.rows(sources[kind]):
                identity = plain_property(row["properties"].get(self.identities[kind], {}))
                if not identity:
                    continue  # User drafts have no HIQS identity.
                if identity in index:
                    raise ValueError(f"Duplicate stable ID in Notion {kind}: {identity}")
                index[identity] = row
            indexes[kind] = index
        report = {"started_at": datetime.now(UTC).isoformat(), "status": "running",
            "source_updated_at": projection["source_updated_at"],
            "counts": projection["counts"], "created": 0, "updated": 0,
            "unchanged": 0, "uploaded": 0, "blocked": [], "errors": [],
            "warnings": projection["warnings"]}
        self._save(report)
        current = {kind: set() for kind in self.identities}
        for record in projection["records"]:
            kind, identity = record["kind"], record["identity"]
            current[kind].add(identity)
            try:
                properties = dict(record["properties"])
                if record.get("course_id"):
                    course = indexes["courses"].get(record["course_id"])
                    if not course:
                        raise ValueError("Course sync failed; relation cannot be resolved")
                    properties["课程" if kind == "materials" else "Course"] = {
                        "relation": [{"id": course["id"]}]}
                if kind == "calendar":
                    item = indexes["items"].get(record["item_id"])
                    if not item:
                        raise ValueError("Item sync failed; relation cannot be resolved")
                    properties["Item"] = {"relation": [{"id": item["id"]}]}
                if kind == "materials":
                    properties["HIQS Present"] = {"checkbox": True}
                old = indexes[kind].get(identity)
                if old is None:
                    if kind == "items" and record.get("initial_status"):
                        properties["Personal Status"] = select(record["initial_status"])
                    old = self.client.request("POST", "/pages", {
                        "parent": {"type": "data_source_id", "data_source_id": sources[kind]},
                        "properties": properties})
                    indexes[kind][identity] = old
                    report["created"] += 1
                else:
                    changed = {k: v for k, v in properties.items()
                        if not _equivalent(v, old["properties"].get(k, {}))}
                    if changed:
                        self.client.request("PATCH", f"/pages/{old['id']}", {"properties": changed})
                        report["updated"] += 1
                    else:
                        report["unchanged"] += 1
                if kind == "materials" and record["file"].get("path"):
                    self._upload(record, old, report)
            except (NotionAPIError, ValueError, OSError) as exc:
                # Never put API messages, auth headers or source contents in logs.
                report["errors"].append({"kind": kind, "identity": identity,
                    "reason": str(exc) if isinstance(exc, NotionAPIError) else type(exc).__name__})
            self._save(report)
        # Only derived presence is changed. Personal task states/notes survive.
        if not report["errors"]:
            for kind, rows in indexes.items():
                for identity in rows.keys() - current[kind]:
                    prop = {"HIQS Present": {"checkbox": False}} if kind == "materials" else {
                        "Sync State": select("removed")}
                    try:
                        self.client.request("PATCH", f"/pages/{rows[identity]['id']}", {"properties": prop})
                    except (NotionAPIError, ValueError, OSError) as exc:
                        report["errors"].append({"kind": kind, "identity": identity,
                                                 "reason": "removal_failed", "error_type": type(exc).__name__})
        self._verify_projection(projection, report)
        report["status"] = "partial" if report["errors"] or report["blocked"] or report["warnings"] else "complete"
        report["finished_at"] = datetime.now(UTC).isoformat()
        self._save(report)
        return report

    def _verify_projection(self, projection: dict, report: dict) -> None:
        """Read back every projected row; an HTTP write response is not a receipt."""
        verification = {"status": "verified", "expected": len(projection["records"]),
                        "matched": 0, "failures": []}
        try:
            observed = {}
            for kind, key in self.identities.items():
                rows = {}
                for row in self.client.rows(self.config["data_sources"][kind]):
                    identity = plain_property(row["properties"].get(key, {}))
                    if not identity:
                        continue
                    if identity in rows:
                        verification["failures"].append({"kind": kind, "identity": identity,
                                                            "reason": "duplicate_identity"})
                    rows[identity] = row
                observed[kind] = rows
            for record in projection["records"]:
                kind, identity = record["kind"], record["identity"]
                actual = observed[kind].get(identity)
                expected = dict(record["properties"])
                relations = {"课程" if kind == "materials" else "Course":
                             ("courses", record.get("course_id"))}
                if kind == "calendar":
                    relations["Item"] = ("items", record["item_id"])
                for name, (parent_kind, parent_identity) in relations.items():
                    if parent_identity:
                        parent = observed[parent_kind].get(parent_identity)
                        expected[name] = {"relation": [{"id": parent["id"]}] if parent else []}
                if kind == "materials":
                    expected["HIQS Present"] = {"checkbox": True}
                mismatched = [name for name, value in expected.items()
                              if actual is None or not _equivalent(value, actual["properties"].get(name, {}))]
                if mismatched:
                    verification["failures"].append({"kind": kind, "identity": identity,
                        "reason": "missing_or_mismatched_properties", "properties": mismatched})
                else:
                    verification["matched"] += 1
            expected_ids = {kind: {row["identity"] for row in projection["records"] if row["kind"] == kind}
                            for kind in self.identities}
            for kind, rows in observed.items():
                for identity in rows.keys() - expected_ids[kind]:
                    properties = rows[identity]["properties"]
                    removed = (properties.get("HIQS Present", {}).get("checkbox") is False
                               if kind == "materials" else
                               plain_property(properties.get("Sync State", {})) == "removed")
                    if not removed:
                        verification["failures"].append({"kind": kind, "identity": identity,
                                                        "reason": "stale_row_still_current"})
        except (NotionAPIError, ValueError, OSError) as exc:
            verification["failures"].append({"reason": "readback_failed", "error_type": type(exc).__name__})
        if verification["failures"]:
            verification["status"] = "failed"
            report["errors"].append({"kind": "verification", "reason": "projection_readback_failed"})
        report["verification"] = verification

    def _upload(self, record: dict, page: dict, report: dict) -> None:
        identity, file = record["identity"], record["file"]
        completed = self.state.setdefault("files", {}).get(identity)
        if completed and completed["page_id"] == page["id"]:
            # Confirm the attachment still exists; a user may have removed it.
            children = self.client.children(page["id"])
            if any(v["id"] == completed.get("block_id") for v in children):
                return
        children = self.client.children(page["id"])
        # An append can have committed before a network timeout. Reconcile the
        # content hash marker before retrying; never duplicate that attachment.
        for block in children:
            content = block.get(block.get("type", ""), {})
            caption = "".join(v.get("plain_text") or v.get("text", {}).get("content", "")
                              for v in content.get("caption", []))
            if caption == "HIQS SHA256:" + file["sha256"]:
                self.state["files"][identity] = {"page_id": page["id"], "block_id": block["id"]}
                self.client.request("PATCH", f"/pages/{page['id']}", {
                    "properties": {"同步状态": select("已上传")}})
                return
        # Adopt verified uploads made by the existing Codex connection.
        if plain_property(page["properties"].get("同步状态", {})) == "已上传":
            attached = next((v for v in children if v["type"] in {"pdf", "file", "video"}), None)
            if attached:
                self.state["files"][identity] = {"page_id": page["id"], "block_id": attached["id"]}
                return
        limit = int(self.config.get("upload_limit_bytes", 5 * 1024 * 1024))
        if file["bytes"] > limit:
            report["blocked"].append({"identity": identity, "reason": "workspace_file_size_limit",
                "bytes": file["bytes"], "limit_bytes": limit})
            self.client.request("PATCH", f"/pages/{page['id']}", {
                "properties": {"同步状态": select("超过上传限制")}})
            return
        # Revalidate byte identity immediately before transmission.
        from hashlib import sha256
        path = Path(file["path"])
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != file["sha256"]:
            raise ValueError("Material changed after projection; rebuild the plan")
        try:
            upload_id = self.client.upload(path)
            block_type = "pdf" if path.suffix.lower() == ".pdf" else "file"
            block = {"object": "block", "type": block_type,
                block_type: {"type": "file_upload", "file_upload": {"id": upload_id},
                             "caption": rich_text("HIQS SHA256:" + file["sha256"])["rich_text"]}}
            result = self.client.request("PATCH", f"/blocks/{page['id']}/children", {"children": [block]})
            self.state["files"][identity] = {"page_id": page["id"],
                "block_id": result["results"][0]["id"], "file_upload_id": upload_id}
            self._save(report)  # Persist attachment before a status update can fail.
            self.client.request("PATCH", f"/pages/{page['id']}", {"properties": {"同步状态": select("已上传")}})
            report["uploaded"] += 1
        except (NotionAPIError, OSError):
            self.client.request("PATCH", f"/pages/{page['id']}", {"properties": {"同步状态": select("上传失败")}})
            raise

    def _save(self, report: dict) -> None:
        self.state["report"] = report
        write_json(self.state_path, self.state)
