"""The layers import only downwards (AGENTS.md: Layers).

framework -> repositories -> capabilities -> interfaces. The framework does no I/O, so it must
not see the control-plane client.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "tokenops"

#: layer -> the tokenops packages it must NOT import
FORBIDDEN = {
    "framework": ("repositories", "capabilities", "interfaces"),
    "repositories": ("capabilities", "interfaces"),
    "capabilities": ("interfaces",),
    "interfaces": (),
}


def _tokenops_imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            if parts[0] == "tokenops" and len(parts) > 1:
                found.add(parts[1])
    return found


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_a_layer_imports_only_the_layers_below_it(layer: str) -> None:
    files = sorted((SRC / layer).rglob("*.py"))
    assert files, f"no files found for layer {layer}"
    offenders = []
    for path in files:
        bad = _tokenops_imports(path) & set(FORBIDDEN[layer])
        if bad:
            offenders.append(f"{path.relative_to(SRC)} imports {sorted(bad)}")
    assert not offenders, "\n".join(offenders)


def test_the_framework_package_has_no_network_client() -> None:
    """No ``httpx`` (or any HTTP client) in the framework: I/O lives in repositories."""
    for path in sorted((SRC / "framework").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for needle in ("import httpx", "import requests", "import urllib.request"):
            assert needle not in source, f"{path.relative_to(SRC)} uses {needle}"
