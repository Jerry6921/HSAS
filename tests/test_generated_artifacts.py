from pathlib import Path

from scripts.check_generated import main


def test_checked_in_generated_contracts_are_current() -> None:
    assert main() == 0


def test_ci_checks_the_served_asset_directory() -> None:
    workflow = Path(__file__).parents[1] / ".github/workflows/quality.yml"
    content = workflow.read_text(encoding="utf-8")
    assert "src/hsas/web/static/modern-assets" in content
    assert "src/hsas/ui/web/modern-assets" not in content


def test_generated_ui_contracts_are_consumed_by_the_ui() -> None:
    root = Path(__file__).parents[1] / "ui/src"
    consumers = [
        path
        for path in root.rglob("*.ts")
        if path.name != "contracts.ts"
        and 'from "./contracts"' in path.read_text(encoding="utf-8")
    ]

    assert consumers, "generated contracts are not imported by any UI type"


def test_generated_file_check_uses_the_generator_output() -> None:
    script = (Path(__file__).parents[1] / "scripts/check_generated.py").read_text(
        encoding="utf-8"
    )

    assert "render_ui_contracts" in script
    assert "render_model(name, schema)" not in script
