from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_development_app_uses_stable_python_module_entrypoint() -> None:
    launcher = (PROJECT_ROOT / "packaging/macos/HIQSApp.swift").read_text(encoding="utf-8")
    build_script = (PROJECT_ROOT / "scripts/build_macos_app.sh").read_text(encoding="utf-8")

    assert '.venv/bin/python' in launcher
    assert '["-m", "hsas"]' in launcher
    assert '.venv/bin/hsas' not in launcher
    assert 'HSAS_BIN=' not in build_script
