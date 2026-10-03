# -*- coding: utf-8 -*-
"""Verify every course quotation in report/final_report_v8.md against report/slides_text/.

For each quote found the script reports the deck + page where it actually occurs.
Exit 1 if any quote is missing or its cited page differs from the observed page.

`report/slides_text/` is the extracted text of the instructor's decks, and is not
part of the submitted repository - it is the instructor's material. Regenerate it
with `report/extract_slides.py`, pointed at `study slides/`, before running this.
"""
import re, sys, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # script lives in report/, root is one up
SL = ROOT / "report" / "slides_text"
REPORT = ROOT / "report" / "final_report_v8.md"

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    # every quote glyph collapses to one marker, so a nested straight quote in the
    # report is not judged different from the deck's curly quote
    for a in ("\u201c", "\u201d", "\u2018", "\u2019", '"', "'", "\u00ab", "\u00bb"):
        s = s.replace(a, "'")
    for a, b in (("\u2014", "-"), ("\u2013", "-"), ("\u2212", "-"), ("\u2026", "...")):
        s = s.replace(a, b)
    return re.sub(r"\s+", "", s).lower()

# deck stem -> file
DECKS = {}
for p in SL.glob("*.txt"):
    DECKS[p.stem] = p

def pages_of(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    pg = [None] * len(lines)
    cur = None
    for i, l in enumerate(lines):
        m = re.match(r"===== PAGE (\d+) =====", l)
        if m:
            cur = int(m.group(1))
        pg[i] = cur
    return lines, pg

# (deck stem fragment, quoted text, cited page)
QUOTES = [
 ("C1_Your_intuition", "This is why A1 makes you compare two approaches empirically instead of arguing about them.", 10),
 ("C1_Your_intuition", "AI capability does not track how hard a task looks to a human", 9),
 ("C2_Sorting_vs_making", "returns a calibrated probability for every class", 11),
 ("C2_Sorting_vs_making", "returns the word 'positive', with no honest confidence attached", 11),
 ("C2_Sorting_vs_making", "Because it will not tell you when it is wrong.", 4),
 ("Class5_C2", "Cost per SUCCESSFUL task. Always.", 26),
 ("Class2_C3_RAG", "RAG is one tool. Knowing when NOT to use it is the senior skill.", 9),
 ("Class6_Close", "A prompt asks. A permission enforces.", 6),
 ("A1_FAQ", "L1 checks the shape of the answer, L2 checks whether it is true", 4),
 ("A1_FAQ", "Reading ten outputs yourself is a perfectly good L2", 5),
 ("Class2_C4", "An unaligned judge just launders bias.", 13),
 ("Class5_C2", "Cost per successful task = layer 1 + layer 2, plus layer 3 spread over volume.", 21),
 ("Class3_C2", "Change three things at once and you cannot tell which one helped", 13),
 ("A1_FAQ", "did it write or rewrite something that ended up in your submission, or did it change a decision you made? If yes, it counts", 5),
 ("A1_FAQ", "the subject of the assignment, not assistance with it", 5),
 ("A1_FAQ", "tells a reader nothing", 5),
 ("A1_FAQ", "An unexplained deviation looks like a mistake; an explained one looks like judgement.", 7),
 ("Class6_Close", "Carry the method. The facts have a shelf life; the questions do not.", 6),
 ("Watchouts", "Give your system a way to say 'I don't know'", 3),
 ("Watchouts", "Every risk needs its mitigation on the same line.", 3),
 ("Watchouts", "A date is not a version. Describe the slice, not the deadline.", 3),
 ("Watchouts", "accuracy without the majority-class baseline", 3),
 ("Watchouts", "the library, the model, the service. Not 'an API'", 2),
 ("Watchouts", "Commit the script or prompt that produced it so a reader can regenerate it", 2),
 ("Watchouts", "in a file before you run anything, never after you have seen results", 2),
 ("Watchouts", "it broke on Y, so I built Z", 2),
]

report_text = REPORT.read_text(encoding="utf-8")

def find_deck(frag):
    hits = [p for stem, p in DECKS.items() if frag.lower().replace("_", "").replace("/", "") in stem.lower().replace("_", "").replace("/", "")]
    return hits

fails = []
for frag, quote, page in QUOTES:
    decks = find_deck(frag)
    if not decks:
        fails.append((frag, quote, page, "DECK NOT FOUND", None)); continue
    observed = []
    for d in decks:
        lines, pg = pages_of(d)
        n = norm(quote)
        for i in range(len(lines)):
            joined = norm(" ".join(lines[i:i + 4]))
            if n in joined:
                observed.append((d.name, pg[i]))
    if not observed:
        fails.append((frag, quote, page, "QUOTE NOT FOUND", None))
    elif page not in [p for _, p in observed]:
        fails.append((frag, quote, page, "PAGE MISMATCH", observed))
    else:
        d, p = observed[0]
        print(f"ok   p.{page:<3} {d[:46]:48s} :: {quote[:64]}")

# quotes that live in the report must be verbatim: re-check the report contains them
print("\n--- report contains each quote verbatim? ---")
for frag, quote, page in QUOTES:
    if norm(quote) not in norm(report_text):
        print(f"NOT IN REPORT: {quote[:70]}")

print("\n--- failures ---")
if not fails:
    print("none")
else:
    for f in fails:
        print("FAIL:", f)
sys.exit(1 if fails else 0)
