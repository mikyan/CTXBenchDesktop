import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 43173,
    strictPort: true,
    proxy: { "/worker": { target: "http://127.0.0.1:48173", rewrite: (path) => path.replace(/^\/worker/, "/v1") } },
  },
  envPrefix: ["VITE_", "TAURI_ENV_*"],
  build: {
    target: "esnext",
    sourcemap: false,
  },
});
