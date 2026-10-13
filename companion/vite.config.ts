// SPDX-License-Identifier: AGPL-3.0-or-later
// Builds the extension into dist/: background.js and content.js as single
// files, popup.html and options.html with their hashed assets, manifest.json
// with the package version injected, and the generated icons.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import { SIZES, iconFileName, renderIcon } from "./scripts/icons.mjs";

const root = fileURLToPath(new URL(".", import.meta.url));
const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as {
  version: string;
};

/** Chrome accepts up to four dot-separated integers; "0.8.0-dev" -> "0.8.0". */
function manifestVersion(version: string): string {
  const base = version.split("-")[0] ?? version;
  return base
    .split(".")
    .map((part) => part.replace(/[^0-9]/g, "") || "0")
    .slice(0, 4)
    .join(".");
}

const SINGLE_FILE_ENTRIES = new Set(["background.js", "content.js"]);

function extensionPlugin(): Plugin {
  return {
    name: "veyra-extension",
    enforce: "post",
    generateBundle(_options, bundle) {
      // Move the HTML pages to the dist root (Vite keeps the src/… path).
      for (const [key, item] of Object.entries(bundle)) {
        if (item.type === "asset" && key.endsWith(".html")) {
          const base = key.slice(key.lastIndexOf("/") + 1);
          if (base !== key) {
            // Rolldown forbids reassigning bundle entries: re-emit instead.
            const source = item.source;
            delete bundle[key];
            this.emitFile({ type: "asset", fileName: base, source });
          }
        }
      }
      // The service worker and the content script must not depend on chunks.
      for (const [key, item] of Object.entries(bundle)) {
        if (item.type === "chunk" && SINGLE_FILE_ENTRIES.has(key)) {
          if (item.imports.length > 0 || item.dynamicImports.length > 0) {
            throw new Error(
              `${key} must be a single file but imports ${[...item.imports, ...item.dynamicImports].join(", ")}; ` +
                "keep its modules out of the pages' runtime imports.",
            );
          }
          if (key === "content.js" && item.exports.length > 0) {
            throw new Error("content.js must not export anything (classic script).");
          }
        }
      }
      const manifest = JSON.parse(readFileSync(`${root}manifest.json`, "utf8")) as Record<string, unknown>;
      manifest.version = manifestVersion(pkg.version);
      manifest.version_name = pkg.version;
      this.emitFile({
        type: "asset",
        fileName: "manifest.json",
        source: `${JSON.stringify(manifest, null, 2)}\n`,
      });
      for (const size of SIZES) {
        this.emitFile({ type: "asset", fileName: iconFileName(size), source: renderIcon(size) });
      }
    },
  };
}

export default defineConfig({
  root,
  base: "/",
  plugins: [extensionPlugin()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    minify: false,
    sourcemap: false,
    modulePreload: { polyfill: false },
    cssCodeSplit: true,
    rolldownOptions: {
      input: {
        background: `${root}src/background.ts`,
        content: `${root}src/content.ts`,
        popup: `${root}src/popup/popup.html`,
        options: `${root}src/options/options.html`,
      },
      output: {
        format: "es",
        entryFileNames: (chunk) =>
          chunk.name === "background" || chunk.name === "content"
            ? "[name].js"
            : "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});
