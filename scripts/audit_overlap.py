"""Measure how much of this repository's text also occurs in reference code.

Purpose: show that the code here was written independently of the projects
it once started from. Two measures per file, each against the union of all
reference sources:

* shared lines  - non-trivial lines that occur verbatim (after whitespace
                  normalisation) in a reference, and "blocks": runs of three
                  or more such lines in a row, the stronger sign of copying
* shared shingles - share of the file's 8-token sequences that also occur in
                  a reference; catches copied code that was merely
                  re-wrapped or re-indented

References are given as ``name=git:<rev>`` (a commit in this repository) or
``name=dir:<path>`` (a checked-out directory).

    python scripts/audit_overlap.py \
        --ref template=git:bc174a1 --ref upstream=git:origin/main \
        --ref ahujasid=dir:../refs/ahujasid --ref jpoindexter=dir:../refs/jpoindexter         --notes scripts/audit_notes.md --out docs/TEMPLATE_AUDIT.md
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from typing import Dict, Iterable, List, Set, Tuple

TEXT_SUFFIXES = (".py", ".md", ".toml", ".txt", ".json", ".js", ".bat", ".cfg", ".yml",
                 ".yaml", ".example", ".maxpat")
SKIP_PARTS = ("__pycache__", ".git", "node_modules", ".venv", "uv.lock")
MIN_LINE = 24          # characters after normalisation
MIN_WORDS = 3          # identifier-like words a line must contain to count
BLOCK = 3              # consecutive shared lines that make a block
SHINGLE = 8            # tokens per shingle

# Lines every project using these APIs has to contain. They are counted and
# listed separately instead of being hidden.
INTERFACE_LINES = {
    "def create_instance(c_instance):":
        "entry point name and signature required by Ableton Live",
    "from _Framework.ControlSurface import ControlSurface":
        "import of Ableton's control surface base class",
    "ControlSurface.__init__(self, c_instance)":
        "base class constructor call required by Ableton's framework",
    "def __init__(self, c_instance):":
        "constructor signature: Live passes exactly this one argument",
    "ControlSurface.disconnect(self)":
        "base class shutdown call required by Ableton's framework",
    "[project.optional-dependencies]":
        "table name defined by the pyproject.toml standard",
    'build-backend = "setuptools.build_meta"':
        "the standard way to name the setuptools build backend",
    "from mcp.server.fastmcp import FastMCP":
        "import of the MCP SDK's server class",
    "from mcp.server.fastmcp import FastMCP, Context":
        "import of the MCP SDK's server class",
}

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|\S")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def normalise(line: str) -> str:
    return " ".join(line.strip().split())


def is_trivial(line: str) -> bool:
    if len(line) < MIN_LINE:
        return True
    if len(_WORD.findall(line)) < MIN_WORDS:
        return True
    if re.match(r"^(import |from \S+ import )", line):
        return True
    return False


def tokens(text: str) -> List[str]:
    return _TOKEN.findall(text)


def shingles(text: str) -> Set[Tuple[str, ...]]:
    stream = tokens(text)
    return {tuple(stream[i:i + SHINGLE]) for i in range(len(stream) - SHINGLE + 1)}


def wanted(path: str) -> bool:
    lowered = path.replace("\\", "/").lower()
    if any(part in lowered.split("/") or lowered.endswith(part) for part in SKIP_PARTS):
        return False
    return lowered.endswith(TEXT_SUFFIXES)


def git(*args: str) -> str:
    return subprocess.run(("git",) + args, check=True, capture_output=True).stdout.decode(
        "utf-8", errors="replace")


def read_git_tree(rev: str) -> Dict[str, str]:
    files = {}
    for path in git("ls-tree", "-r", "--name-only", rev).splitlines():
        if wanted(path):
            files[path] = git("show", f"{rev}:{path}")
    return files


def read_directory(root: str) -> Dict[str, str]:
    files = {}
    for folder, subfolders, names in os.walk(root):
        subfolders[:] = [s for s in subfolders if s not in SKIP_PARTS]
        for name in names:
            full = os.path.join(folder, name)
            relative = os.path.relpath(full, root).replace(os.sep, "/")
            if wanted(relative):
                with open(full, "r", encoding="utf-8", errors="replace") as handle:
                    files[relative] = handle.read()
    return files


def own_files() -> Dict[str, str]:
    files = {}
    for path in git("ls-files").splitlines():
        if wanted(path) and os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                files[path] = handle.read()
    return files


class Reference:
    def __init__(self, name: str, source: str, files: Dict[str, str]):
        self.name, self.source, self.files = name, source, files
        self.lines: Dict[str, str] = {}
        self.shingles: Set[Tuple[str, ...]] = set()
        for path, text in files.items():
            for line in text.splitlines():
                clean = normalise(line)
                if clean and clean not in self.lines:
                    self.lines[clean] = path
            self.shingles |= shingles(text)


def audit_file(text: str, references: List[Reference]) -> dict:
    rows = [normalise(line) for line in text.splitlines()]
    counted = [(number, line) for number, line in enumerate(rows, 1) if not is_trivial(line)]
    shared, interface = [], []
    shared_numbers = set()
    for number, line in counted:
        hits = [ref.name for ref in references if line in ref.lines]
        if not hits:
            continue
        if line in INTERFACE_LINES:
            interface.append((number, line, hits))
            continue
        shared.append((number, line, hits))
        shared_numbers.add(number)
    # Blocks: consecutive *counted* lines that are all shared.
    blocks, run = [], []
    for number, _line in counted:
        if number in shared_numbers:
            run.append(number)
        else:
            if len(run) >= BLOCK:
                blocks.append((run[0], run[-1], len(run)))
            run = []
    if len(run) >= BLOCK:
        blocks.append((run[0], run[-1], len(run)))
    own = shingles(text)
    common = set()
    per_reference = {}
    for ref in references:
        overlap = own & ref.shingles
        common |= overlap
        per_reference[ref.name] = {
            "lines": sum(1 for _n, _l, hits in shared if ref.name in hits),
            "shingles": len(overlap),
        }
    return {
        "per_reference": per_reference,
        "lines_total": len(rows),
        "lines_counted": len(counted),
        "shared": shared,
        "interface": interface,
        "blocks": blocks,
        "shingles_total": len(own),
        "shingles_shared": len(common),
    }


def percent(part: int, whole: int) -> str:
    return "0.0 %" if not whole else f"{100.0 * part / whole:.1f} %"


def build_report(results: Dict[str, dict], references: List[Reference], head: str,
                 notes: str = "") -> str:
    total_counted = sum(r["lines_counted"] for r in results.values())
    total_shared = sum(len(r["shared"]) for r in results.values())
    total_blocks = sum(len(r["blocks"]) for r in results.values())
    total_shingles = sum(r["shingles_total"] for r in results.values())
    shared_shingles = sum(r["shingles_shared"] for r in results.values())
    out = [
        "# Overlap audit against reference code",
        "",
        f"Generated {datetime.date.today().isoformat()} by `scripts/audit_overlap.py` "
        f"from the files tracked on top of commit `{head}`.",
        "",
        "## What was compared",
        "",
        "| Reference | Source | Text files |",
        "|---|---|---|",
    ]
    for ref in references:
        out.append(f"| {ref.name} | `{ref.source}` | {len(ref.files)} |")
    out += [
        "",
        f"Own files examined: {len(results)} (all tracked text files except this report).",
        "",
        "## Method",
        "",
        f"- A line counts if, after trimming and collapsing whitespace, it has at least "
        f"{MIN_LINE} characters and {MIN_WORDS} identifier-like words and is not an import.",
        "- **Shared line**: a counted line that occurs verbatim in any reference file.",
        f"- **Block**: {BLOCK} or more counted lines in a row that are all shared.",
        f"- **Shared shingles**: share of a file's {SHINGLE}-token sequences that occur in "
        "any reference (independent of line breaks and indentation).",
        "- Lines that an API dictates (Live's entry point, SDK imports) are listed "
        "separately as interface lines.",
        "",
        "## Result",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Counted lines | {total_counted} |",
        f"| Shared lines | {total_shared} ({percent(total_shared, total_counted)}) |",
        f"| Blocks of {BLOCK}+ shared lines | {total_blocks} |",
        f"| Shared {SHINGLE}-token shingles | {shared_shingles} of {total_shingles} "
        f"({percent(shared_shingles, total_shingles)}) |",
        "",
        "Against each reference on its own:",
        "",
        "| Reference | Shared lines | Shared shingles |",
        "|---|---:|---:|",
    ]
    for ref in references:
        ref_lines = sum(r["per_reference"][ref.name]["lines"] for r in results.values())
        ref_shingles = sum(r["per_reference"][ref.name]["shingles"] for r in results.values())
        out.append(f"| {ref.name} | {ref_lines} ({percent(ref_lines, total_counted)}) | "
                   f"{ref_shingles} ({percent(ref_shingles, total_shingles)}) |")
    out += [
        "",
    ]
    if notes:
        out += [notes.strip(), ""]
    out += [
        "## Per file",
        "",
        "| File | Counted lines | Shared | Blocks | Shared shingles |",
        "|---|---:|---:|---:|---:|",
    ]
    for path in sorted(results):
        r = results[path]
        out.append(f"| `{path}` | {r['lines_counted']} | {len(r['shared'])} | "
                   f"{len(r['blocks'])} | {percent(r['shingles_shared'], r['shingles_total'])} |")
    out += ["", "## Every shared line", ""]
    any_shared = False
    for path in sorted(results):
        r = results[path]
        if not r["shared"]:
            continue
        any_shared = True
        out.append(f"### `{path}`")
        out.append("")
        for number, line, hits in r["shared"]:
            out.append(f"- line {number} ({', '.join(hits)}): `{line[:160]}`")
        out.append("")
    if not any_shared:
        out += ["None.", ""]
    out += ["## Interface lines", ""]
    seen = defaultdict(list)
    for path in sorted(results):
        for number, line, _hits in results[path]["interface"]:
            seen[line].append(f"{path}:{number}")
    if seen:
        for line, places in seen.items():
            out.append(f"- `{line}` - {INTERFACE_LINES[line]} ({', '.join(places)})")
    else:
        out.append("None.")
    out.append("")
    return "\n".join(out)


def main(argv: Iterable[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ref", action="append", required=True,
                        help="name=git:<rev> or name=dir:<path>; repeatable")
    parser.add_argument("--out", help="write the Markdown report here")
    parser.add_argument("--json", help="write raw numbers here")
    parser.add_argument("--notes", help="Markdown file inserted after the result tables")
    parser.add_argument("--max-shared-percent", type=float, default=None,
                        help="exit with status 1 if the shared-line share is above this")
    args = parser.parse_args(argv)

    references = []
    for spec in args.ref:
        name, _eq, source = spec.partition("=")
        kind, _colon, location = source.partition(":")
        if kind == "git":
            files = read_git_tree(location)
        elif kind == "dir":
            files = read_directory(location)
        else:
            parser.error(f"bad --ref '{spec}'")
        shown = source if kind == "git" else f"dir:{os.path.basename(os.path.normpath(location))}"
        references.append(Reference(name, shown, files))

    own = own_files()
    if args.out:  # the report quotes shared lines; do not audit the report itself
        own.pop(os.path.relpath(args.out).replace(os.sep, "/"), None)
    results = {path: audit_file(text, references) for path, text in own.items()}
    head = git("rev-parse", "--short", "HEAD").strip()
    notes = ""
    if args.notes:
        with open(args.notes, "r", encoding="utf-8") as handle:
            notes = handle.read()
    report = build_report(results, references, head, notes)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(report)
    else:
        sys.stdout.write(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({path: {k: v for k, v in r.items()} for path, r in results.items()},
                      handle, indent=1)
    counted = sum(r["lines_counted"] for r in results.values())
    shared = sum(len(r["shared"]) for r in results.values())
    share = 100.0 * shared / counted if counted else 0.0
    print(f"shared lines: {shared} of {counted} ({share:.2f} %), "
          f"blocks: {sum(len(r['blocks']) for r in results.values())}", file=sys.stderr)
    if args.max_shared_percent is not None and share > args.max_shared_percent:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
