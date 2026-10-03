/**
 * In-browser PDF text extraction.
 *
 * The file never leaves the browser. The panel reads the PDF with PDF.js and
 * hands the resulting *text* to the background worker, which forwards it to
 * `POST /extract_resume`. Two consequences are worth stating plainly:
 *
 * * the backend needs no file-upload surface at all, which is what lets it stay
 *   stateless without an exception carved out for uploads - the H3 constraint
 *   the rest of the assistant holds to;
 * * "the document is not uploaded anywhere" is literally true rather than
 *   approximately true, which is the promise the panel makes to the user.
 *
 * The worker script is shipped inside the extension as `dist/pdf.worker.js` and
 * registered by its extension URL (`vite.config.ts` copies it; the manifest needs
 * no `web_accessible_resources` entry, because the panel loads it as its own
 * origin's resource). PDF.js checks that URL against `window.location` and, when
 * they match, loads the module directly instead of wrapping it in a blob. That
 * matters: the wrapper it would otherwise use is a classic script, and the v6
 * worker is an ES module.
 */

import * as pdfjs from "pdfjs-dist";

pdfjs.GlobalWorkerOptions.workerSrc = chrome.runtime.getURL("pdf.worker.js");

/**
 * Refuse an obviously oversized file before spending time parsing it.
 *
 * Not a security boundary - the text still crosses the loopback and the server
 * caps its own input length - just a courtesy, so a 200 MB scan does not lock
 * the panel while the user wonders whether it has hung.
 */
export const MAX_PDF_BYTES = 8 * 1024 * 1024;

/**
 * A PDF that could not be turned into text.
 *
 * `key` is a label key, not a message. The panel is bilingual, so the sentence
 * has to be rendered by whichever language is selected at the time, and this
 * module has no business knowing which that is.
 */
export class PdfTextError extends Error {
  readonly key: string;

  constructor(key: string) {
    super(key);
    this.name = "PdfTextError";
    this.key = key;
  }
}

/**
 * The text of a PDF, one line per page, in reading order.
 *
 * Nothing is written anywhere and no URL is fetched: the bytes come from the
 * `File` the user chose. A parse failure is reported as `PdfTextError` rather
 * than leaking PDF.js's own exception, because "this is not a resume I can read"
 * is the only part of that error a user can act on.
 */
export async function extractPdfText(file: File): Promise<string> {
  if (file.size > MAX_PDF_BYTES) throw new PdfTextError("resumeTooLarge");

  const data = new Uint8Array(await file.arrayBuffer());

  // Teardown lives on the loading task in v6, not on the document proxy, so the
  // task is kept rather than discarded - otherwise the worker it spawns would
  // outlive every parse.
  const task = pdfjs.getDocument({ data });
  let doc: pdfjs.PDFDocumentProxy;
  try {
    doc = await task.promise;
  } catch {
    throw new PdfTextError("resumeParseFailed");
  }

  try {
    const pages: string[] = [];
    for (let number = 1; number <= doc.numPages; number += 1) {
      const page = await doc.getPage(number);
      const content = await page.getTextContent();
      const line = content.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
      if (line) pages.push(line);
      // Release the page's operator list as we go: a long CV would otherwise
      // hold every page's parsed content in memory until the loop ends.
      page.cleanup();
    }
    return pages.join("\n");
  } catch {
    throw new PdfTextError("resumeParseFailed");
  } finally {
    await task.destroy().catch(() => undefined);
  }
}
