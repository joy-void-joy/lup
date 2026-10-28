// The page's build: written into the dashboard's package, which its server serves
// (`lup_dashboard/layout.py`), and which git ignores. `pnpm exec vite` serves it with
// reloading, the API passed on to a dashboard running on 8766.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
    plugins: [react()],
    build: {
        outDir: "../src/lup_dashboard/page",
        emptyOutDir: true,
    },
    server: {
        proxy: { "/api": "http://127.0.0.1:8766" },
    },
    test: {
        include: ["src/**/*.test.ts"],
    },
});
