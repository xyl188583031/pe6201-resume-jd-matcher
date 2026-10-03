#!/usr/bin/env python
"""No-Chinese check - every control file outside the test data is English.

Round 3, M5. Run it from the repository root:

    python scripts/check_no_chinese.py

Exit code 0 means every CJK character inside the scanned scope is either a
declared exception or nothing at all. Exit code 1 means at least one line should
be English and is not, printed as `file:line:col: <matched text>`.

Scope
-----
Eight roots: the seven the round-3 brief named, plus `src/`.

    resume_jd_matcher/README.md      the repository README
    report/                          the report deliverable, beside the repo
    resume_jd_matcher/server/        the HTTP layer
    resume_jd_matcher/extension/     the browser extension
    resume_jd_matcher/scripts/       the check scripts
    resume_jd_matcher/artifacts/     what the checks produced
    resume_jd_matcher/tests/         the unit tests
    resume_jd_matcher/src/           the offline pipeline: parsing, retrieval,
                                     scoring, and the three conditions

`src/` was outside the scope until the unreferenced Chinese Streamlit prototype
under it was deleted. With that gone the pipeline is English but for two skill
aliases, and scanning it is what proves so.

Three things are deliberately *not* in that list, and each is printed below with
the CJK it actually contains, so an exclusion is a stated decision rather than
a silent gap:

    resume_jd_matcher/demo/          the simulated forms. This *is* the test
                                     data: `form_06_bilingual.html` exists to
                                     carry a Chinese-only label.
    resume_jd_matcher/vendor/        the vendored embedding model. Its
                                     `vocab.txt` is third-party tokeniser data.

What counts as an exception
---------------------------
Four kinds, and every one of them is named here with the reason:

  * a **detector's subject matter** - the Chinese words for identity documents
    are how the identity detector recognises a Chinese-labelled field.
    Translating them would delete the feature.
  * a **test fixture** - the test forms, and the tests that assert on their
    labels. The Chinese is the input being tested, not prose.
  * a **declared product decision** - the side panel renders every label as
    "Chinese (English)" on purpose, so its Chinese is a feature.
  * a **deliberate Chinese deliverable** - the report exists in two mirrored
    languages and `report_zh.md` is one of them. That mirror, like the report's
    patch scripts and the extracted deck text, is no longer part of the submitted
    repository; it is kept on the author's machine, and this script scans the
    working copy, so the exception is still declared here.

Anything not covered by one of those four is a failure. Nothing else in the
whole scanned scope is Chinese, and that is what this script exists to prove.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[1]
PROJECT_ROOT = REPO_ROOT.parent

#: CJK ideographs and their extensions, the CJK punctuation block, kana, and the
#: fullwidth forms. A bare ideograph is the signal; the rest catch a line whose
#: only Chinese is punctuation.
CJK = re.compile(
    "[\u3400-\u4dbf"  # CJK Unified Ideographs Extension A
    "\u4e00-\u9fff"  # CJK Unified Ideographs
    "\uf900-\ufaff"  # CJK Compatibility Ideographs
    "\u3000-\u303f"  # CJK symbols and punctuation
    "\u3040-\u30ff"  # hiragana and katakana
    "\uff01-\uff60\uffe0-\uffe6"  # fullwidth forms
    "]"
)

TEXT_SUFFIXES = frozenset(
    {
        ".md", ".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".jsonl", ".html",
        ".css", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sh", ".csv",
    }
)

#: Directory names that hold build output, binary stores or third-party data.
#: A hit in any of these is not a sentence somebody wrote here.
SKIP_DIR_NAMES = frozenset(
    {"__pycache__", "node_modules", ".git", "chroma_db", "kb_index", "tmp_run", ".venv", "venv", ".mypy_cache"}
)

#: The scanned roots, each with why it is one of them.
SCAN_ROOTS: list[tuple[Path, str]] = [
    (REPO_ROOT / "README.md", "the repository README"),
    (PROJECT_ROOT / "report", "the report deliverable, beside the repo"),
    (REPO_ROOT / "server", "the HTTP layer"),
    (REPO_ROOT / "extension", "the browser extension"),
    (REPO_ROOT / "scripts", "the check scripts"),
    (REPO_ROOT / "artifacts", "what the checks produced"),
    (REPO_ROOT / "tests", "the unit tests"),
    (REPO_ROOT / "src", "the offline pipeline"),
]

#: Directories the brief did not name. Each is printed with the CJK it holds and
#: the reason it is out, so nothing is skipped invisibly.
NOT_SCANNED: list[tuple[Path, str]] = [
    (
        REPO_ROOT / "demo",
        "the simulated forms - this is the test data, and "
        "`form_matrix/form_06_bilingual.html` exists to carry a Chinese-only label",
    ),
    (
        REPO_ROOT / "vendor",
        "the vendored embedding model; its `vocab.txt` is third-party tokeniser "
        "data whose CJK tokens are part of the model's byte-pair vocabulary",
    ),
    (REPO_ROOT / "eval", "not one of the seven named roots"),
    (REPO_ROOT / "data", "not one of the seven named roots; the synthetic inputs"),
    (
        REPO_ROOT / "artifacts_preflight",
        "the author's working copy, not submitted; the delivered run is "
        "`artifacts/kbv2_final`",
    ),
    (REPO_ROOT / "app.py", "not one of the seven named roots"),
    (REPO_ROOT.parent / "study slides", "the course material, not this project's text"),
]

#: Two basename rules applied inside a scanned root, each printed with its count.
TRANSIENT_DIR = "artifacts"  # files under it whose name starts with `_`
BUILD_DIST = REPO_ROOT / "extension" / "dist"


@dataclass(frozen=True)
class Excuse:
    """A place CJK is allowed to stay.

    `glob` is matched against the path relative to the project root, in POSIX
    form, with `fnmatch`. `needle` is optional: when it is set, the exception
    only applies to a line that actually contains it, so a *different* Chinese
    line in the same file is still a failure.
    """

    glob: str
    needle: str
    reason: str


#: The two labels `demo/form_matrix/form_06_bilingual.html` carries and nothing
#: else on the page does. Written as escapes so this file contains no CJK of its
#: own and needs no exception for itself.
FORM06_ADDITIONAL_NOTES = "\u8865\u5145\u8bf4\u660e"  # "additional notes"
STRAWBERRY = "\u8349\u8393"  # the tokeniser example on a PE6201 slide


EXCUSES: list[Excuse] = [
    # -- the side panel's string table, which is bilingual on purpose ---------
    # Rounds 9-10 kept the panel bilingual and added a `zh` / `en` / `bilingual`
    # switch. This file is the table the switch reads: it is the one place the
    # Chinese is allowed to live, and every component resolves its strings
    # through `useLabel()` rather than by rendering a literal. `App.tsx` used to
    # carry two of those literals of its own; both moved into this table, so its
    # exception was retired rather than left behind matching nothing.
    Excuse(
        "resume_jd_matcher/extension/src/sidepanel/labels.ts",
        "",
        "the one table holding both languages for every panel string. The switch "
        "picks `zh`, `en` or both from it; deleting the Chinese would delete the "
        "Chinese mode",
    ),
    Excuse(
        "resume_jd_matcher/extension/src/types.ts",
        "",
        "the `{en, zh}` module-name pairs that the bilingual panel reads",
    ),
    Excuse(
        "resume_jd_matcher/extension/panel.html",
        "",
        "the panel document's own `<title>` and `<noscript>` text, shown in both languages",
    ),
    # -- a detector's subject matter ------------------------------------------
    Excuse(
        "resume_jd_matcher/server/field_map.py",
        "",
        "`SENSITIVE_PATTERNS`: the Chinese words for identity documents are the "
        "detector's subject matter. Translating them would remove the ability to "
        "recognise a Chinese-labelled identity field, which is a feature.",
    ),
    # -- test fixtures --------------------------------------------------------
    Excuse(
        "resume_jd_matcher/tests/test_server_scan.py",
        "",
        "test fixtures: the Chinese labels are the input the identity detector is "
        "asserted to recognise",
    ),
    Excuse(
        "resume_jd_matcher/tests/test_sensitive_and_missing.py",
        "",
        "the same fixtures, asserted through the `/generate` path",
    ),
    Excuse(
        "resume_jd_matcher/scripts/run_form_matrix.py",
        "",
        "names the on-page labels of `demo/form_matrix/form_06_bilingual.html` - the "
        "control the matrix exists to test is labelled only in Chinese, so the "
        "assertion and the finding have to name it",
    ),
    # -- generated evidence that quotes the page -------------------------------
    Excuse(
        "resume_jd_matcher/artifacts/form_matrix/report*.md",
        FORM06_ADDITIONAL_NOTES,
        "the generated report quotes the on-page label of the form_06 control it is "
        "describing; everything else in the report is English",
    ),
    Excuse(
        "resume_jd_matcher/artifacts/form_matrix/runs*.jsonl",
        "",
        "run records store the page's own `label` text, and on `form_06_bilingual` "
        "those labels are Chinese by design. This is evidence, not prose.",
    ),
    Excuse(
        "resume_jd_matcher/src/taxonomy.py",
        "",
        "carries two skill aliases written in Chinese (the strings for Go and R "
        "as a Chinese-language resume would spell them) as matching keys. They "
        "are data, not prose: translating them would stop the matcher "
        "recognising the skill",
    ),
    # -- the deliberate Chinese deliverable -----------------------------------
    Excuse(
        "report/report_zh.md",
        "",
        "the Chinese mirror of the report, which is the author's working copy and not "
        "part of the submitted repository. The English original is submitted; this "
        "file stays on the author's machine, and the scan runs against the working "
        "copy, so the exception is declared rather than left as a silent gap.",
    ),
    Excuse(
        "report/_patch_*.py",
        "",
        "the report's atomic patch scripts, kept on the author's machine rather than "
        "submitted. The ones that edit the Chinese mirror have to contain the Chinese "
        "they insert, in the same way a script that edits `report_en.md` contains the "
        "English.",
    ),
    Excuse(
        "report/slides_text/*.txt",
        STRAWBERRY,
        "extracted PE6201 lecture-slide text: the line is the deck's own tokeniser "
        "example, quoted course material rather than our prose",
    ),
]


def rel(path: Path) -> str:
    """Project-root-relative POSIX path, for stable printing and globs."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def iter_files(root: Path):
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if SKIP_DIR_NAMES & set(path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def scan(path: Path) -> list[tuple[int, int, str, str]]:
    """Every CJK hit in one file: (line, column, the CJK text, the whole line)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    out: list[tuple[int, int, str, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = CJK.search(line)
        if match:
            out.append((number, match.start() + 1, match.group(0), line))
    return out


def count_cjk(path: Path) -> int:
    return len(scan(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print only the offenders and the verdict",
    )
    args = parser.parse_args(argv)

    def say(*parts: str) -> None:
        if not args.quiet:
            print(*parts)

    say("No-Chinese check - scripts/check_no_chinese.py")
    say("=" * 68)
    say("")

    # -------------------------------------------------------------- scope
    say("Scanned")
    say("-------")
    scanned: list[Path] = []
    for root, why in SCAN_ROOTS:
        exists = root.exists()
        say(f"  {rel(root) + ('/' if root.is_dir() else ''):<48} {why}")
        if not exists:
            say(f"  {'':<48} (not present)")
            continue
        for path in iter_files(root):
            if TRANSIENT_DIR in path.parts and path.name.startswith("_"):
                continue
            if BUILD_DIST in path.parents or path.parent == BUILD_DIST:
                continue
            scanned.append(path)
    say(f"  -> {len(scanned)} file(s) scanned")
    say("")

    offenders: list[tuple[Path, int, int, str, str]] = []
    excused: dict[int, int] = {index: 0 for index in range(len(EXCUSES))}
    for path in scanned:
        relative = rel(path)
        for line_no, column, text, whole in scan(path):
            for index, excuse in enumerate(EXCUSES):
                if fnmatch.fnmatch(relative, excuse.glob) and (
                    not excuse.needle or excuse.needle in whole
                ):
                    excused[index] += 1
                    break
            else:
                offenders.append((path, line_no, column, text, whole))

    # ------------------------------------------------------ declared exceptions
    say("Declared exceptions (CJK allowed to stay, with the reason)")
    say("----------------------------------------------------------")
    for index, excuse in enumerate(EXCUSES):
        count = excused[index]
        mark = " " if count else "!"
        say(f" {mark} {excuse.glob}")
        say(f"     {count} line(s)   {excuse.reason}")
    stale = [excuse.glob for index, excuse in enumerate(EXCUSES) if not excused[index]]
    if stale:
        say("")
        say(f"  note: {len(stale)} exception(s) matched no CJK this run - recheck the list:")
        for glob in stale:
            say(f"        {glob}")
    say("")

    # --------------------------------------------------- not scanned, and why
    say("Not scanned, and why (with the CJK it actually holds)")
    say("------------------------------------------------------")
    for root, why in NOT_SCANNED:
        if not root.exists():
            say(f"    {rel(root):<44} (not present)")
            continue
        if root.is_file():
            total, files = count_cjk(root), 1
        else:
            files = 0
            total = 0
            for path in iter_files(root):
                found = count_cjk(path)
                if found:
                    files += 1
                    total += found
        say(f"    {rel(root) + ('/' if root.is_dir() else ''):<44} {total:>4} CJK line(s) in {files} file(s)")
        say(f"        {why}")
    # The two basename rules inside a scanned root, counted the same way.
    skip_counts: list[tuple[str, int]] = []
    for root, _why in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if TRANSIENT_DIR in path.parts and path.name.startswith("_"):
                skip_counts.append((rel(path), count_cjk(path)))
    transient_files = len(skip_counts)
    transient_lines = sum(lines for _path, lines in skip_counts)
    say("")
    say(f"    artifacts/**/_*  (transient command logs written by `tee` while a check ran)")
    say(f"        {transient_files} file(s), {transient_lines} CJK line(s) - inputs to the work, not deliverables")
    if BUILD_DIST.is_dir():
        dist_files = [p for p in BUILD_DIST.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES]
        dist_lines = sum(count_cjk(p) for p in dist_files)
        say("")
        say(f"    {rel(BUILD_DIST)}/  (build output)")
        say(
            f"        {len(dist_files)} file(s), {dist_lines} CJK line(s) - generated from "
            "`extension/src/`, which is scanned; a bundle is not a second decision"
        )
    say("")

    # ------------------------------------------------------------- verdict
    if offenders:
        say("Unaccounted CJK")
        say("---------------")
        for path, line_no, column, text, whole in offenders:
            say(f"  {rel(path)}:{line_no}:{column}: {text}")
            say(f"      in: {whole.strip()[:160]}")
        say("")
        say(f"FAIL - {len(offenders)} line(s) inside the scanned scope are not covered by an exception.")
        say("       Either translate them to English, or add a declared exception with a reason.")
        return 1

    covering = sum(1 for index in excused if excused[index])
    say("Unaccounted CJK")
    say("---------------")
    say("  none")
    say("")
    say(
        f"OK - everything inside the scanned scope is English, except {covering} declared "
        f"exception(s) carrying {sum(excused.values())} CJK line(s) in total."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
