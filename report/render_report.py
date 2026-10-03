# -*- coding: utf-8 -*-
"""render_report.py -- render the PE6201 final report to HTML (A1 layout),
then print it to PDF with headless Edge.

Read-only with respect to the markdown: the source .md is never modified.

    python report/render_report.py [source.md]

Defaults to report/final_report_v8.md and writes, next to it:
    final_report_v8.html   (self-contained, CSS inlined)
    final_report_v8.pdf    (via _print_pdf.mjs, Edge + CDP)

WeasyPrint was the first choice but is unavailable on this machine's package
index, so the Edge path is used -- see the brief's fallback.
"""
import io
import os
import subprocess
import sys

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, "final_report_v8.md")
CSS_PATH = os.path.join(HERE, "report_style.css")
NODE = r"C:\Users\xyl18\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
CDP_DRIVER = os.path.join(HERE, "_print_pdf.mjs")

# markdown extensions actually needed by this document:
#   tables     -> the 7 pipe tables (6 data tables + the AI-disclosure table)
#   sane_lists -> predictable list nesting
MD_EXTENSIONS = ["tables", "sane_lists"]

HTML_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Graduate Resume\u2013JD Matcher \u2014 PE6201 Final Report</title>
<style>
{css}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def render(source=DEFAULT_SRC, make_pdf=True):
    src_path = os.path.abspath(source)
    stem = os.path.splitext(os.path.basename(src_path))[0]
    html_path = os.path.join(os.path.dirname(src_path), stem + ".html")
    pdf_path = os.path.join(os.path.dirname(src_path), stem + ".pdf")

    text = io.open(src_path, encoding="utf-8").read()
    css = io.open(CSS_PATH, encoding="utf-8").read()

    body = markdown.markdown(text, extensions=MD_EXTENSIONS, output_format="html5")
    html = HTML_SHELL.format(css=css, body=body)

    io.open(html_path, "w", encoding="utf-8", newline="\n").write(html)
    print("html  : %s  (%d bytes)" % (html_path, len(html.encode("utf-8"))))

    if not make_pdf:
        return html_path, None

    res = subprocess.run(
        [NODE, CDP_DRIVER, html_path, pdf_path],
        capture_output=True, text=True,
    )
    sys.stdout.write(res.stdout)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        raise SystemExit("PDF step failed (exit %d)" % res.returncode)
    print("pdf   : %s  (%d bytes)" % (pdf_path, os.path.getsize(pdf_path)))
    return html_path, pdf_path


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC)
