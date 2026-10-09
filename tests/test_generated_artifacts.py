from pathlib import Path

from scripts.check_generated import main


def test_checked_in_generated_contracts_are_current() -> None:
    assert main() == 0


def test_ci_checks_the_served_asset_directory() -> None:
    workflow = Path(__file__).parents[1] / ".github/workflows/quality.yml"
    content = workflow.read_text(encoding="utf-8")
    assert "src/hsas/web/static/modern-assets" in content
    assert "src/hsas/ui/web/modern-assets" not in content
