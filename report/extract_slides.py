"""Extract text from every PE6201 study-slide PDF.

Writes one .txt per deck (with page markers) into report/slides_text/ and a
single combined file. Page markers matter: the final report has to cite where a
requirement came from, so "deck C4 page 7" has to survive the extraction.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

BASE = Path(__file__).resolve().parent
SLIDES = BASE.parent / "study slides"
OUT = BASE / "slides_text"


def clean(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(SLIDES.glob("*.pdf"))
    if not pdfs:
        print("no PDFs found under", SLIDES)
        return 1

    index: list[dict] = []
    combined: list[str] = []

    for pdf in pdfs:
        reader = PdfReader(str(pdf))
        pages: list[str] = []
        empty_pages: list[int] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                raw = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001
                raw = ""
                print(f"  ! page {i} of {pdf.name} failed: {type(exc).__name__}")
            body = clean(raw)
            if not body:
                empty_pages.append(i)
            pages.append(f"\n===== PAGE {i} =====\n{body}")

        text = "".join(pages).strip()
        (OUT / (pdf.stem + ".txt")).write_text(
            f"### DECK: {pdf.name}\n{text}\n", encoding="utf-8"
        )

        index.append(
            {
                "deck": pdf.name,
                "stem": pdf.stem,
                "pages": len(reader.pages),
                "chars": len(text),
                "empty_pages": empty_pages,
            }
        )
        combined.append(f"\n\n########## DECK: {pdf.name} ##########\n{text}")

    (OUT / "_ALL_DECKS.txt").write_text("\n".join(combined).strip(), encoding="utf-8")
    (OUT / "_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"=== decks: {len(index)} | total chars: {sum(i['chars'] for i in index)}")
    thin = [i for i in index if i["chars"] < 800]
    if thin:
        print("=== THIN / SUSPECT DECKS:")
        for i in thin:
            print(f"    {i['deck']}: {i['chars']} chars, empty pages {i['empty_pages']}")
    else:
        print("=== all decks yielded text")
    print("=== per-deck:")
    for i in index:
        flag = " <-- THIN" if i["chars"] < 800 else ""
        print(f"    {i['chars']:>7} chars  {i['pages']:>3}p  {i['deck']}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
