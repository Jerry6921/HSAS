import json
from pathlib import Path

from hsas.infrastructure.storage.persist_data import write_bytes, write_json, write_text


def test_file_store_writes_json_text_and_bytes_atomically(tmp_path: Path) -> None:
    json_path = write_json(tmp_path / "nested/data.json", {"title": "哲学"})
    text_path = write_text(tmp_path / "nested/data.txt", "course text")
    bytes_path = write_bytes(tmp_path / "nested/data.bin", b"course bytes")

    assert json.loads(json_path.read_text(encoding="utf-8")) == {"title": "哲学"}
    assert text_path.read_text(encoding="utf-8") == "course text"
    assert bytes_path.read_bytes() == b"course bytes"
    assert not list((tmp_path / "nested").glob("*.tmp"))
