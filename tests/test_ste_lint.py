"""Test the STE linter on a fixture with known violations."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ste_lint  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def _findings() -> list[ste_lint.Finding]:
    return ste_lint.lint([FIX / "ste_bad.md"])


def test_forbidden_words_are_errors() -> None:
    words = {f.message for f in _findings() if f.rule == "forbidden-word"}
    assert any("in order to" in w for w in words)
    assert any("'utilize'" in w for w in words)
    assert any("'leverage'" in w for w in words)
    assert any("'robust'" in w for w in words)


def test_sentence_length_rules() -> None:
    lengths = [f for f in _findings() if f.rule == "sentence-length"]
    assert any("descriptive" in f.message for f in lengths)
    assert any("procedural" in f.message for f in lengths)  # 21 words in a numbered step
    assert all(f.level == "ERROR" for f in lengths)


def test_warnings() -> None:
    rules = {f.rule for f in _findings() if f.level == "WARNING"}
    assert {"passive-voice", "present-participle", "paragraph-length"} <= rules


def test_tables_and_code_are_skipped() -> None:
    lines = {f.line for f in _findings()}
    text = (FIX / "ste_bad.md").read_text().splitlines()
    skipped = [i + 1 for i, ln in enumerate(text) if ln.startswith("|") or "code block" in ln]
    assert not lines & set(skipped)


def test_exit_code(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    good.write_text("# Good\n\nThe model predicts the track. Run the demo.\n")
    assert ste_lint.main([str(good)]) == 0
    assert ste_lint.main([str(FIX / "ste_bad.md")]) == 1


def test_docstrings_and_json(tmp_path: Path) -> None:
    py = tmp_path / "m.py"
    py.write_text('def f():\n    """In order to start, ensure that the file exists."""\n')
    js = tmp_path / "en-ste.json"
    js.write_text('{"a": "Select a scenario.", "b": "Please utilize the map."}')
    rules = [f.rule for f in ste_lint.lint([py, js])]
    assert rules.count("forbidden-word") == 3
