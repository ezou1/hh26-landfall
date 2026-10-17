"""Check documentation text against the mechanical ASD-STE100 rules.

The linter reads README.md, the Markdown files in docs/, Python docstrings,
TypeScript JSDoc blocks, and the UI strings in web/src/i18n/en-ste.json.
It prints one line for each finding. It stops with exit code 1 if it finds an error.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MAX_DESCRIPTIVE = 25
MAX_PROCEDURAL = 20
MAX_PARAGRAPH_SENTENCES = 6

FORBIDDEN: dict[str, str] = {
    "utilize": "use",
    "utilizes": "uses",
    "utilized": "used",
    "utilizing": "use",
    "leverage": "use",
    "leverages": "uses",
    "leveraged": "used",
    "in order to": "to",
    "prior to": "before",
    "subsequent to": "after",
    "a number of": "some, or a digit",
    "ensure": "make sure",
    "ensures": "makes sure",
    "robust": "strong, or delete",
    "seamless": "delete",
    "seamlessly": "delete",
    "optimal": "best",
    "perform": "do",
    "performs": "does",
    "performed": "did",
    "commence": "start",
    "commences": "starts",
    "terminate": "stop",
    "terminates": "stops",
    "facilitate": "help",
    "facilitates": "helps",
    "approximately": "about",
    "additional": "more",
    "assist": "help",
    "assists": "helps",
    "indicate": "show",
    "indicates": "shows",
    "indicated": "showed",
}

BE_FORMS = {"is", "are", "was", "were", "be", "been", "being", "am", "isn't", "aren't"}

IRREGULAR_PARTICIPLES = {
    "built", "made", "done", "given", "taken", "shown", "known", "written", "read", "sent",
    "kept", "held", "found", "seen", "set", "put", "run", "drawn", "chosen", "broken", "brought",
    "bought", "caught", "cut", "driven", "fed", "felt", "forgotten", "frozen", "got", "gotten",
    "grown", "hidden", "hit", "hurt", "laid", "led", "left", "lost", "meant", "met", "paid",
    "said", "sold", "shut", "split", "spent", "spread", "stood", "struck", "taught", "thrown",
    "told", "thought", "understood", "won", "worn", "bound", "fit", "begun", "become", "come",
    "overridden", "rewritten", "undone",
}

# Words that end in "ed" or "ing" but are not participles in the usual sense.
ED_EXCEPTIONS = {"need", "speed", "seed", "feed", "red", "bed", "shed", "bred", "hundred", "indeed"}
ING_EXCEPTIONS = {
    "thing", "things", "string", "strings", "during", "nothing", "something", "anything",
    "everything", "ring", "rings", "king", "spring", "bring", "sing", "wing", "ceiling",
    "morning", "evening", "building", "buildings", "warning", "warnings", "routing",
    "landing", "heading", "spacing", "padding", "missing", "pending", "remaining",
}

# A small bundled noun dictionary for the noun-cluster check.
NOUNS = {
    "model", "track", "storm", "hurricane", "prediction", "output", "input", "data", "file",
    "zone", "release", "time", "clearance", "shelter", "depot", "asset", "task", "edge", "road",
    "network", "graph", "flow", "supply", "demand", "scenario", "advisory", "forecast", "error",
    "wind", "surge", "damage", "rescue", "team", "route", "truck", "boat", "helicopter", "county",
    "population", "census", "block", "group", "feature", "resolver", "frame", "layer", "globe",
    "panel", "view", "table", "map", "grid", "cell", "value", "speed", "intensity", "pressure",
    "fix", "server", "client", "token", "key", "cache", "test", "unit", "step", "plan", "cost",
    "capacity", "hour", "day", "evacuation", "medical", "kit", "fuel", "water", "food", "debris",
    "crew", "link", "bridge", "hospital", "bed", "user", "screen", "chart", "lead",
    "ensemble", "member", "residual", "bank", "baseline", "verification", "summary", "artifact",
    "pipeline", "stage", "batch", "sample", "seed", "timeline", "clock", "camera", "status",
}

PASSIVE_SKIP_AFTER = {"not", "also", "only", "then", "now", "always", "never", "still"}


@dataclass
class Unit:
    """One block of text that the linter checks."""

    path: Path
    line: int
    text: str
    procedural: bool = False
    paragraph: bool = True


@dataclass
class Finding:
    """One rule violation."""

    path: Path
    line: int
    level: str
    rule: str
    message: str

    def render(self) -> str:
        """Return the finding as one line of text."""
        try:
            rel = self.path.resolve().relative_to(ROOT)
        except ValueError:
            rel = self.path
        return f"{rel}:{self.line}: {self.level} [{self.rule}] {self.message}"


INLINE_CODE = re.compile(r"`[^`]*`")
MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
URL = re.compile(r"https?://\S+")
HTML_TAG = re.compile(r"<[^>]+>")
NUMBERED = re.compile(r"^\s*\d+[.)]\s+")
BULLET = re.compile(r"^\s*[-*+]\s+")


def clean(text: str) -> str:
    """Remove code spans, links, URLs, and markup from a text block."""
    text = INLINE_CODE.sub(" CODE ", text)
    text = MD_LINK.sub(r"\1", text)
    text = URL.sub(" URL ", text)
    text = HTML_TAG.sub(" ", text)
    text = text.replace("**", "").replace("__", "")
    return text


def split_sentences(text: str) -> list[str]:
    """Split text into sentences at a full stop, a question mark, or an exclamation mark."""
    text = re.sub(r"\b(e\.g|i\.e|etc|vs|approx|Fig|No|St|Dr|Blvd|Ave|Rd)\.", r"\1", text)
    text = re.sub(r"(\d)\.(\d)", r"\1\2", text)
    parts = re.split(r"(?<=[.!?:;])\s+", text.strip())
    return [p for p in parts if words(p)]


def words(sentence: str) -> list[str]:
    """Return the word tokens of a sentence."""
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-/%.]*", sentence)


def markdown_units(path: Path) -> list[Unit]:
    """Return the text units of a Markdown file. Skip code blocks and tables."""
    units: list[Unit] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    in_code = False
    buf: list[str] = []
    buf_start = 0

    def flush() -> None:
        nonlocal buf
        if buf:
            units.append(Unit(path, buf_start, " ".join(buf)))
        buf = []

    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith("<!--"):
            flush()
            continue
        if stripped.startswith("#"):
            flush()
            units.append(Unit(path, i, stripped.lstrip("#").strip(), paragraph=False))
            continue
        if stripped.startswith(">"):
            stripped = stripped.lstrip("> ").strip()
        if NUMBERED.match(line):
            flush()
            units.append(Unit(path, i, NUMBERED.sub("", line), procedural=True, paragraph=False))
            continue
        if BULLET.match(line):
            flush()
            units.append(Unit(path, i, BULLET.sub("", line), paragraph=False))
            continue
        if units and not buf and lines[i - 2].strip() and (
            NUMBERED.match(lines[i - 2]) or BULLET.match(lines[i - 2])
        ):
            # A continuation line of a list item.
            last = units[-1]
            last.text += " " + stripped
            continue
        if not buf:
            buf_start = i
        buf.append(stripped)
    flush()
    return units


def python_units(path: Path) -> list[Unit]:
    """Return the docstrings of a Python file as text units."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    units: list[Unit] = []
    nodes = [tree] + [
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    for node in nodes:
        doc = ast.get_docstring(node, clean=True)
        if not doc:
            continue
        body = getattr(node, "body", [])
        line = body[0].lineno if body else 1
        units.extend(docstring_units(path, line, doc))
    return units


def docstring_units(path: Path, line: int, doc: str) -> list[Unit]:
    """Split a docstring or a JSDoc block into paragraphs and list items."""
    units: list[Unit] = []
    buf: list[str] = []
    start = line
    in_code = False
    for offset, raw in enumerate(doc.splitlines()):
        stripped = raw.strip()
        if stripped.startswith("```") or stripped.startswith(">>>"):
            in_code = not in_code if stripped.startswith("```") else in_code
            continue
        if in_code or stripped.startswith("@") or stripped.startswith(":"):
            continue
        if not stripped:
            if buf:
                units.append(Unit(path, start, " ".join(buf)))
                buf = []
            continue
        if NUMBERED.match(stripped) or BULLET.match(stripped):
            if buf:
                units.append(Unit(path, start, " ".join(buf)))
                buf = []
            units.append(
                Unit(
                    path,
                    line + offset,
                    NUMBERED.sub("", BULLET.sub("", stripped)),
                    procedural=bool(NUMBERED.match(stripped)),
                    paragraph=False,
                )
            )
            continue
        if not buf:
            start = line + offset
        buf.append(stripped)
    if buf:
        units.append(Unit(path, start, " ".join(buf)))
    return units


JSDOC = re.compile(r"/\*\*(.*?)\*/", re.S)


def ts_units(path: Path) -> list[Unit]:
    """Return the JSDoc blocks of a TypeScript file as text units."""
    text = path.read_text(encoding="utf-8")
    units: list[Unit] = []
    for m in JSDOC.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        body = "\n".join(re.sub(r"^\s*\*\s?", "", ln) for ln in m.group(1).splitlines())
        units.extend(docstring_units(path, line, body.strip()))
    return units


def json_units(path: Path) -> list[Unit]:
    """Return every string value of a JSON file as a text unit."""
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    units: list[Unit] = []

    def find_line(value: str) -> int:
        needle = json.dumps(value)[1:-1][:40]
        for i, ln in enumerate(raw_lines, start=1):
            if needle in ln:
                return i
        return 1

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, str) and obj.strip():
            units.append(Unit(path, find_line(obj), obj, paragraph=False))

    walk(data)
    return units


def check_unit(unit: Unit) -> list[Finding]:
    """Apply the mechanical STE rules to one text unit."""
    findings: list[Finding] = []
    text = clean(unit.text)
    sentences = split_sentences(text)
    limit = MAX_PROCEDURAL if unit.procedural else MAX_DESCRIPTIVE
    for s in sentences:
        toks = words(s)
        if len(toks) > limit:
            kind = "procedural" if unit.procedural else "descriptive"
            findings.append(
                Finding(unit.path, unit.line, "ERROR", "sentence-length",
                        f"{kind} sentence has {len(toks)} words (max {limit}): '{s[:60]}...'")
            )
        lower = [t.lower().strip(".,'’") for t in toks]
        for i, w in enumerate(lower):
            if w in BE_FORMS:
                nxt = [x for x in lower[i + 1 : i + 3] if x]
                cands = [x for x in nxt if x not in PASSIVE_SKIP_AFTER][:2]
                for c in cands:
                    if (c.endswith("ed") and len(c) > 3 and c not in ED_EXCEPTIONS) or (
                        c in IRREGULAR_PARTICIPLES
                    ):
                        findings.append(
                            Finding(unit.path, unit.line, "WARNING", "passive-voice",
                                    f"possible passive voice: '{w} {c}'")
                        )
                        break
                if nxt and nxt[0].endswith("ing") and len(nxt[0]) > 4 and nxt[0] not in ING_EXCEPTIONS:
                    findings.append(
                        Finding(unit.path, unit.line, "WARNING", "present-participle",
                                f"present participle as a verb: '{w} {nxt[0]}'")
                    )
        run = 0
        for i, t in enumerate(toks):
            is_noun = t.lower() in NOUNS or (i > 0 and t[:1].isupper() and t.isalpha())
            run = run + 1 if is_noun else 0
            if run == 4:
                findings.append(
                    Finding(unit.path, unit.line, "WARNING", "noun-cluster",
                            f"noun cluster of 4 or more words near '{' '.join(toks[i - 3 : i + 1])}'")
                )
    low = " " + re.sub(r"\s+", " ", text.lower()) + " "
    for bad, good in FORBIDDEN.items():
        if re.search(r"(?<![a-z\-])" + re.escape(bad) + r"(?![a-z\-])", low):
            findings.append(
                Finding(unit.path, unit.line, "ERROR", "forbidden-word",
                        f"do not use '{bad}'; use '{good}'")
            )
    if unit.paragraph and len(sentences) > MAX_PARAGRAPH_SENTENCES:
        findings.append(
            Finding(unit.path, unit.line, "WARNING", "paragraph-length",
                    f"paragraph has {len(sentences)} sentences (max {MAX_PARAGRAPH_SENTENCES})")
        )
    return findings


def default_targets() -> list[Path]:
    """Return the default files in the linter scope."""
    targets: list[Path] = []
    readme = ROOT / "README.md"
    if readme.exists():
        targets.append(readme)
    targets += sorted((ROOT / "docs").rglob("*.md"))
    for folder in ("landfall", "chalk", "api", "scripts"):
        targets += sorted((ROOT / folder).rglob("*.py"))
    web_src = ROOT / "web" / "src"
    targets += sorted(p for p in web_src.rglob("*.ts*") if p.suffix in {".ts", ".tsx"})
    i18n = web_src / "i18n" / "en-ste.json"
    if i18n.exists():
        targets.append(i18n)
    return targets


def units_for(path: Path) -> list[Unit]:
    """Return the text units of one file, based on the file type."""
    if path.suffix == ".md":
        return markdown_units(path)
    if path.suffix == ".py":
        return python_units(path)
    if path.suffix in {".ts", ".tsx"}:
        return ts_units(path)
    if path.suffix == ".json":
        return json_units(path)
    return []


def lint(paths: list[Path]) -> list[Finding]:
    """Lint the given files and return all findings."""
    findings: list[Finding] = []
    for p in paths:
        for u in units_for(p):
            findings.extend(check_unit(u))
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run the linter from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--quiet-warnings", action="store_true", help="print errors only")
    args = parser.parse_args(argv)
    paths = args.paths or default_targets()
    findings = lint(paths)
    errors = [f for f in findings if f.level == "ERROR"]
    for f in findings:
        if f.level == "ERROR" or not args.quiet_warnings:
            print(f.render())
    print(f"ste_lint: {len(paths)} files, {len(errors)} errors, {len(findings) - len(errors)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
