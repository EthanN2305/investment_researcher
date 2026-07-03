import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /research and /health to the FastAPI backend so the
// frontend can call same-origin paths during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/research": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
