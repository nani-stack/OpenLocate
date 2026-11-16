import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Tauri expects a fixed dev server port (see devUrl in src-tauri/tauri.conf.json).
const DEV_PORT = 1420;

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: DEV_PORT,
    strictPort: true,
    // The app shows the repository's own TERMS.md, PRIVACY.md and notices (src/legal.ts).
    fs: { allow: [".."] },
    watch: { ignored: ["**/src-tauri/**"] },
  },
  build: {
    target: "es2022",
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
