// The page's build, written into the core's environment side, which the shell's
// server serves, and which git ignores.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
    plugins: [react()],
    build: {
        outDir: "../src/lup/environment/page",
        emptyOutDir: true,
    },
    test: {
        include: ["src/**/promises.ts"],
        environment: "happy-dom",
    },
});
