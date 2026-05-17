import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Tauri-specific bits:
//   - clearScreen: false   so the cargo logs stay visible during dev
//   - server.port: 1420    matches the port Tauri expects
//   - server.strictPort    fail rather than fall through to another port
//   - envPrefix: ["VITE_", "TAURI_"]
export default defineConfig(async () => ({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: "127.0.0.1",
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  envPrefix: ["VITE_", "TAURI_ENV_"],
  build: {
    target: "es2022",
    sourcemap: true,
  },
}));
