"""PDF text extraction with a documented fallback chain.

PS section 4 names PyPDF2 and classifies this as the *rule-based* part of the
system. PyPDF2 is now `pypdf`, so this module tries, in order:

1. `pypdf`
2. `PyPDF2`   (same codebase, older distribution name)
3. a minimal built-in extractor that decompresses FlateDecode streams and pulls
   the text-showing operators out of the content stream.

(3) exists because the demo must run in an environment where neither package is
installed. It handles the common case - a PDF with Flate-compressed content and
simple Tj/TJ text operators - and returns whatever it found, plus a warning, for
anything more exotic. It never pretends to have parsed a scanned page: if no
text comes out, that is reported as an extraction failure, not as an empty
resume.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field

MIN_USABLE_CHARS = 30


@dataclass
class PdfExtraction:
    text: str
    engine: str
    pages: int = 0
    warnings: list[str] = field(default_factory=list)
    ok: bool = False


def _extract_with(module_name: str, data: bytes) -> PdfExtraction:
    import io

    module = __import__(module_name)
    reader = module.PdfReader(io.BytesIO(data))
    pages = len(reader.pages)
    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page must not kill the file
            chunks.append("")
    return PdfExtraction(text="\n".join(chunks), engine=module_name, pages=pages)


def _unfence_cid(text: str) -> str:
    """Undo the \\( \\) \\[ \\] escapes that appear in PDF string literals."""
    replacements = {
        r"\(": "(",
        r"\)": ")",
        r"\[": "[",
        r"\]": "]",
        r"\\": "\\",
        r"\n": "\n",
        r"\r": "\r",
        r"\t": "\t",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _decode_pdf_literal(raw: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            mapping = {"n": "\n", "r": "\r", "t": "\t", "(": "(", ")": ")", "\\": "\\"}
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
                continue
            octal = re.match(r"[0-7]{1,3}", raw[i + 1 :])
            if octal:
                out.append(chr(int(octal.group(0), 8)))
                i += 1 + len(octal.group(0))
                continue
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# Tokens that only appear in PDF structure, never in a human-readable line.
_PDF_SYNTAX = re.compile(
    rb"(obj\b|endobj|xref|trailer|/Type|/Font|/BaseFont|/MediaBox|stream\b|endstream|%%EOF)"
)


def _looks_like_pdf(data: bytes) -> bool:
    """A file that is not a PDF cannot yield resume text, and guessing is worse
    than failing."""
    head = data[:1024]
    return b"%PDF" in head or b"%PDF" in data


def _plausible_text_lines(blob: bytes) -> str:
    """Keep ASCII runs that do not look like PDF structure."""
    kept: list[str] = []
    for run in re.findall(rb"[ -~]{6,}", blob):
        if _PDF_SYNTAX.search(run):
            continue
        candidate = run.decode("latin-1").strip()
        if not candidate:
            continue
        letters = sum(1 for ch in candidate if ch.isalpha())
        # Prose is mostly letters and spaces; structure is mostly punctuation.
        if letters >= max(6, int(0.5 * len(candidate))):
            kept.append(candidate)
    return " ".join(kept)


def _extract_builtin(data: bytes) -> PdfExtraction:
    warnings: list[str] = []
    if not _looks_like_pdf(data):
        return PdfExtraction(
            text="",
            engine="builtin-minimal",
            pages=0,
            warnings=["input does not start with %PDF - refusing to guess at text"],
            ok=False,
        )
    text_parts: list[str] = []

    # 1. content streams, usually Flate-compressed
    streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S)
    decoded: list[str] = []
    for stream in streams:
        payload: bytes | None = None
        try:
            payload = zlib.decompress(stream)
        except Exception:
            try:
                payload = zlib.decompressobj().decompress(stream)
            except Exception:
                payload = None
        if payload:
            decoded.append(payload.decode("latin-1", errors="ignore"))
        else:
            # Uncompressed content streams are legal PDF and common in small
            # generated files. Skipping them entirely meant a plain-text PDF
            # fell through to the raw-ASCII scan and got flagged as unreliable.
            decoded.append(stream.decode("latin-1", errors="ignore"))

    for content in decoded:
        for match in re.finditer(r"\((?:\\.|[^\\()])*\)", content):
            literal = match.group(0)[1:-1]
            piece = _decode_pdf_literal(literal).strip()
            if piece:
                text_parts.append(piece)
        if re.search(r"\bTJ\b|\bTj\b", content) and not text_parts:
            warnings.append("content stream used text operators this extractor did not decode")

    text = " ".join(text_parts)
    # 2. last resort: readable ASCII runs from the raw file (uncompressed PDFs)
    if len(text) < MIN_USABLE_CHARS:
        candidate = re.sub(r"\s+", " ", _plausible_text_lines(data)).strip()
        if len(candidate) > len(text):
            text = candidate
            warnings.append(
                "fell back to raw ASCII runs; layout and text order are unreliable"
            )

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) < MIN_USABLE_CHARS:
        warnings.append(
            "no usable text found - the PDF is likely scanned or uses an "
            "unsupported encoding (this is a reportable failure, not an empty resume)"
        )

    return PdfExtraction(
        text=text,
        engine="builtin-minimal",
        pages=len(re.findall(rb"/Type\s*/Page[^s]", data)),
        warnings=warnings,
        ok=len(text) >= MIN_USABLE_CHARS,
    )


def extract_pdf_text(data: bytes) -> PdfExtraction:
    """Try pypdf, then PyPDF2, then the built-in extractor."""
    errors: list[str] = []
    for module_name in ("pypdf", "PyPDF2"):
        try:
            result = _extract_with(module_name, data)
        except ImportError:
            errors.append(f"{module_name} not installed")
            continue
        except Exception as exc:  # noqa: BLE001 - try the next engine
            errors.append(f"{module_name} failed: {type(exc).__name__}: {exc}")
            continue

        if len(result.text.strip()) >= MIN_USABLE_CHARS:
            result.ok = True
            result.text = result.text.strip()
            return result
        errors.append(f"{module_name} extracted only {len(result.text.strip())} chars")

    fallback = _extract_builtin(data)
    fallback.warnings = errors + fallback.warnings
    return fallback


def extract_pdf_text_from_path(path: str) -> PdfExtraction:
    with open(path, "rb") as fh:
        return extract_pdf_text(fh.read())
