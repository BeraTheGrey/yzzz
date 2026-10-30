import ast
from pathlib import Path

from switchlib import i18n

ROOT = Path(__file__).resolve().parent.parent / "switchlib"


def _literal_calls():
    for f in ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_" \
                    and node.args and isinstance(node.args[0], ast.Constant):
                yield node.args[0].value


def _runtime_strings():
    """Strings that are translated through a variable."""
    import pytest

    pytest.importorskip("PySide6")
    from switchlib.gui import detail, main_window

    yield from detail.KIND_LABELS.values()
    yield from detail.SOURCE_LABELS.values()
    yield from (label for _key, label in main_window.FILTERS)
    yield from (c for c in main_window.MainWindow.COLUMNS if c)
    src = (ROOT / "gui" / "main_window.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "action":
            yield node.args[0].value
            for kw in node.keywords:
                if kw.arg == "tip":
                    yield kw.value.value
            if len(node.args) > 3:
                yield node.args[3].value


def test_all_strings_translated():
    missing = sorted({s for s in [*_literal_calls(), *_runtime_strings()] if s not in i18n.TR})
    assert not missing, missing


def test_placeholders_match():
    import string

    fmt = string.Formatter()
    for en, tr in i18n.TR.items():
        en_fields = {f for _, f, _, _ in fmt.parse(en) if f}
        tr_fields = {f for _, f, _, _ in fmt.parse(tr) if f}
        assert en_fields == tr_fields, en


def test_switch_language():
    i18n.set_language("tr")
    try:
        assert i18n._("Scan") == "Tara"
        assert i18n._("not in table") == "not in table"
    finally:
        i18n.set_language("en")
    assert i18n._("Scan") == "Scan"
