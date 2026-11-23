"""Архитектурные инварианты из ``docs/agent/SPEC.md`` §3.

Тесты решают задачу статически (AST), без импорта проверяемых модулей:
это позволяет ловить нарушения даже в коде, который не запускается в тестах.
"""

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "payment_service"
PROJECT_ROOT = PACKAGE_ROOT.parents[1]

DOMAIN = PACKAGE_ROOT / "domain"
APPLICATION = PACKAGE_ROOT / "application"
API = PACKAGE_ROOT / "entrypoints" / "api"
LEGACY_API = PACKAGE_ROOT / "api"

DOMAIN_FORBIDDEN_FRAMEWORKS = {
    "sqlalchemy",
    "fastapi",
    "pydantic",
    "faststream",
    "httpx",
}
TRANSPORT_FORBIDDEN_FRAMEWORKS = {"sqlalchemy"}


def python_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(path: Path) -> set[str]:
    """Все модули, импортированные файлом (включая resolve относительных)."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package_parts = module_name(path).split(".")[:-1]
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - (node.level - 1)]
                if node.module:
                    base = [*base, *node.module.split(".")]
                modules.add(".".join(base))
            elif node.module:
                modules.add(node.module)

    return modules


def is_framework_import(module: str, frameworks: set[str]) -> bool:
    return module.split(".")[0] in frameworks


def report(violations: list[str]) -> None:
    if violations:
        pytest.fail(
            "Нарушены архитектурные инварианты:\n" + "\n".join(violations),
        )


@pytest.mark.parametrize(
    "path",
    python_files(DOMAIN),
    ids=module_name,
)
def test_domain_has_no_framework_imports(path: Path) -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT)}: запрещённый импорт '{module}'"
        for module in imported_modules(path)
        if is_framework_import(module, DOMAIN_FORBIDDEN_FRAMEWORKS)
    ]
    report(violations)


@pytest.mark.parametrize(
    "path",
    python_files(DOMAIN),
    ids=module_name,
)
def test_domain_does_not_depend_on_outer_layers(path: Path) -> None:
    forbidden_prefixes = (
        "payment_service.application",
        "payment_service.infrastructure",
        "payment_service.entrypoints",
    )
    violations = [
        f"{path.relative_to(PROJECT_ROOT)}: домен зависит от '{module}'"
        for module in imported_modules(path)
        if module.startswith(forbidden_prefixes)
    ]
    report(violations)


@pytest.mark.parametrize(
    "path",
    [*python_files(APPLICATION), *python_files(API), *python_files(LEGACY_API)],
    ids=module_name,
)
def test_application_and_api_do_not_import_sqlalchemy(path: Path) -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT)}: запрещённый импорт '{module}'"
        for module in imported_modules(path)
        if is_framework_import(module, TRANSPORT_FORBIDDEN_FRAMEWORKS)
    ]
    report(violations)


@pytest.mark.parametrize(
    "path",
    python_files(APPLICATION),
    ids=module_name,
)
def test_application_does_not_depend_on_infrastructure(path: Path) -> None:
    forbidden_prefixes = (
        "payment_service.infrastructure",
        "payment_service.entrypoints",
    )
    violations = [
        f"{path.relative_to(PROJECT_ROOT)}: application зависит от '{module}'"
        for module in imported_modules(path)
        if module.startswith(forbidden_prefixes)
    ]
    report(violations)


def test_alembic_is_not_gitignored() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    ignored_lines = [
        line.strip()
        for line in gitignore.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert not any(
        "alembic" in line for line in ignored_lines
    ), f".gitignore не должен игнорировать alembic: {ignored_lines}"
