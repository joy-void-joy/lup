// One workspace, one Vite build per surface. Which surface is being built
// arrives as Vite's own `--mode`, and where its bundle lands as `--outDir`,
// because the Python writer that materialises `lup.web`'s package data runs
// this once per surface into a directory it owns — the config declares the
// shape and never chooses a destination of its own.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig(({ mode }) => {
  const surface = mode === "production" || mode === "development" ? "explorer" : mode;
  return {
    root: resolve(__dirname, "src", surface),
    // Relative asset URLs, so a bundle serves from any prefix and an exported
    // single file needs no origin at all.
    base: "./",
    plugins: [react()],
    build: {
      outDir: resolve(__dirname, "out", surface),
      emptyOutDir: true,
      // Text only: the Python side materialises bundles as text artifacts
      // with an ownership manifest, and a binary asset would fail that gate.
      // Small assets are inlined as data URLs by this limit; nothing here
      // ships a large one.
      assetsInlineLimit: 1 << 20,
      sourcemap: false,
      // One script and one stylesheet per surface, so an export can carry a
      // surface whole: a chunk loaded by relative URL has no server to load
      // it from once the page is a file.
      rollupOptions: { output: { inlineDynamicImports: true } },
    },
  };
});
