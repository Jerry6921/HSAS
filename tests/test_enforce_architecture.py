import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]
SOURCE_ROOT = ROOT / "src/hsas"
ACTION_PREFIXES = {
    "analyze",
    "build",
    "calculate",
    "define",
    "detect",
    "display",
    "download",
    "expose",
    "extract",
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
    "validate",
}
SPECIAL_MODULES = {"__init__", "__main__"}
OUTER_LAYER_PREFIXES = (
    "hsas.application",
    "hsas.infrastructure",
    "hsas.interfaces",
)


def test_source_module_names_start_with_actions() -> None:
    invalid = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        if path.stem in SPECIAL_MODULES:
            continue
        action = path.stem.split("_", 1)[0]
        if action not in ACTION_PREFIXES:
            invalid.append(path.relative_to(ROOT).as_posix())

    assert invalid == []


def test_top_level_packages_express_architecture_layers() -> None:
    layers = {
        path.name
        for path in SOURCE_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }

    assert layers == {"application", "domain", "infrastructure", "interfaces"}


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
        "hsas.interfaces",
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
