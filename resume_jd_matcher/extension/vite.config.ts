import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const here = dirname(fileURLToPath(import.meta.url));

/**
 * Copy `manifest.json` into `dist/` after the bundle is written.
 *
 * `manifest.json` lives at the extension root (as the task's file layout
 * specifies) rather than in Vite's `public/` folder, so the copy is explicit and
 * a missing manifest fails the build instead of producing a silently unusable
 * extension.
 */
function copyManifest(): Plugin {
  return {
    name: "rjd-copy-manifest",
    closeBundle() {
      const source = resolve(here, "manifest.json");
      const out = resolve(here, "dist");
      if (!existsSync(source)) {
        this.error(`manifest.json not found at ${source}`);
        return;
      }
      mkdirSync(out, { recursive: true });
      copyFileSync(source, resolve(out, "manifest.json"));
    },
  };
}


/**
 * Copy PDF.js's worker into `dist/` as `pdf.worker.js`.
 *
 * `pdf.ts` registers that path with PDF.js. Shipping the worker inside the
 * extension rather than pointing at a CDN is what keeps resume reading offline:
 * a candidate's CV must not be fetched from a third party, and the panel has no
 * business needing the network to read a file the user already has.
 *
 * The file is copied verbatim, and it has to be. PDF.js v6 always constructs the
 * worker with `{ type: "module" }`, so the copy must stay an ES module; naming it
 * `.js` is fine, because the extension origin serves it with a JavaScript MIME
 * type. The manifest needs no `web_accessible_resources` entry either - the
 * panel loads it as its own origin's resource, which is also what makes PDF.js
 * skip the blob wrapper it uses for cross-origin workers.
 */
function copyPdfWorker(): Plugin {
  return {
    name: "rjd-copy-pdf-worker",
    closeBundle() {
      const source = resolve(here, "node_modules", "pdfjs-dist", "build", "pdf.worker.min.mjs");
      const out = resolve(here, "dist");
      if (!existsSync(source)) {
        this.error(`pdf.worker.min.mjs not found at ${source}. Run "npm install" first.`);
        return;
      }
      mkdirSync(out, { recursive: true });
      copyFileSync(source, resolve(out, "pdf.worker.js"));
    },
  };
}

export default defineConfig({
  plugins: [react(), copyManifest(), copyPdfWorker()],
  // Relative asset URLs: an extension page is served from chrome-extension://,
  // where absolute paths happen to resolve, but relative ones survive being
  // loaded unpacked from any directory.
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "chrome114",
    // Readable output: this is a prototype that must be reviewable, and the
    // reviewer may well be reading the built file.
    minify: false,
    sourcemap: true,
    rollupOptions: {
      input: {
        panel: resolve(here, "panel.html"),
        background: resolve(here, "src/background.ts"),
        content: resolve(here, "src/content.ts"),
      },
      output: {
        // Stable names for the two files the manifest points at by name; the
        // panel keeps a hashed name so a stale cached page cannot survive a
        // rebuild.
        entryFileNames: (chunk) =>
          chunk.name === "panel" ? "assets/[name]-[hash].js" : "[name].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
  server: { port: 5173 },
});
