import ast
from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
SOURCE_ROOT = ROOT / "src/hsas"
LEGACY_ACTION_PREFIXES = {
    "build",
    "calculate",
    "define",
    "detect",
    "display",
    "download",
    "expose",
    "fetch",
    "generate",
    "handle",
    "index",
    "implement",
    "load",
    "map",
    "manage",
    "migrate",
    "orchestrate",
    "parse",
    "persist",
    "publish",
    "query",
    "record",
    "resolve",
    "retrieve",
    "run",
    "synchronize",
    "update",
}
SPECIAL_MODULES = {"__init__", "__main__"}
OUTER_LAYER_PREFIXES = (
    "hsas.application",
    "hsas.core",
    "hsas.infrastructure",
    "hsas.cli",
    "hsas.codegen",
    "hsas.mcp",
    "hsas.web",
)


def test_source_modules_use_responsibility_oriented_snake_case_names() -> None:
    invalid = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        if path.stem in SPECIAL_MODULES:
            continue
        prefix = path.stem.split("_", 1)[0]
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", path.stem):
            invalid.append(path.relative_to(ROOT).as_posix())
        elif prefix in LEGACY_ACTION_PREFIXES:
            invalid.append(path.relative_to(ROOT).as_posix())

    assert invalid == []


def test_top_level_packages_express_architecture_layers() -> None:
    layers = {
        path.name
        for path in SOURCE_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }

    assert layers == {
        "application",
        "cli",
        "codegen",
        "core",
        "domain",
        "infrastructure",
        "mcp",
        "web",
    }


def test_domain_does_not_import_outer_layers() -> None:
    violations: list[str] = []
    for path in sorted((SOURCE_ROOT / "domain").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.startswith(OUTER_LAYER_PREFIXES):
                    violations.append(
                        f"{path.relative_to(ROOT).as_posix()}:{node.lineno} -> {module}"
                    )

    assert violations == []


def test_application_does_not_import_outer_adapters_or_ui_frameworks() -> None:
    forbidden_prefixes = (
        "hsas.infrastructure",
        "hsas.cli",
        "hsas.web",
        "playwright",
        "typer",
    )
    violations: list[str] = []
    for path in sorted((SOURCE_ROOT / "application").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.startswith(forbidden_prefixes):
                    violations.append(
                        f"{path.relative_to(ROOT).as_posix()}:{node.lineno} -> {module}"
                    )

    assert violations == []


def test_core_does_not_depend_on_delivery_adapters() -> None:
    violations = _import_violations(
        SOURCE_ROOT / "core",
        forbidden_prefixes=("hsas.cli", "hsas.codegen", "hsas.mcp", "hsas.web", "typer"),
    )
    assert violations == []


def test_infrastructure_does_not_depend_on_composition_or_delivery_layers() -> None:
    violations = _import_violations(
        SOURCE_ROOT / "infrastructure",
        forbidden_prefixes=("hsas.cli", "hsas.codegen", "hsas.core", "hsas.mcp", "hsas.web"),
    )
    assert violations == []


def test_mcp_and_web_depend_on_core_port_not_internal_layers() -> None:
    forbidden_prefixes = (
        "hsas.application",
        "hsas.domain",
        "hsas.infrastructure",
        "hsas.cli",
    )
    violations = [
        *_import_violations(SOURCE_ROOT / "mcp", forbidden_prefixes=forbidden_prefixes),
        *_import_violations(SOURCE_ROOT / "web", forbidden_prefixes=forbidden_prefixes),
    ]
    assert violations == []


def _import_violations(
    root: Path,
    *,
    forbidden_prefixes: tuple[str, ...],
) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.startswith(forbidden_prefixes):
                    violations.append(
                        f"{path.relative_to(ROOT).as_posix()}:{node.lineno} -> {module}"
                    )
    return violations
