import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Builds straight into ../public (the repo root's static-assets directory,
// already served by Vercel's zero-config static+Python-functions model —
// see the top-level README's "Try it live" section and webdemo's old
// approach for why we deliberately avoid a root-level package.json /
// framework auto-detection here). `emptyOutDir` replaces the old
// hand-written public/index.html wholesale, as Phase 4 intends.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../public",
    emptyOutDir: true,
  },
});
