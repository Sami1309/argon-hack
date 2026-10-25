import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev: vite on :5173 proxies data + API to the FastAPI server on :8787 (python dashboard/server.py)
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8787", "/bundle": "http://127.0.0.1:8787", "/runs": "http://127.0.0.1:8787" } },
  build: { outDir: "dist", emptyOutDir: true },
});
