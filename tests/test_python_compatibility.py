"""Keep install-time imports and the OAuth helper parseable on Python 3.12+."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "custom_components/chatgpt_assist").rglob("*.py")) + [
    ROOT / "scripts/chatgpt_login.py"
]


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_python_312_syntax(source):
    ast.parse(source.read_text(), filename=str(source), feature_version=(3, 12))
