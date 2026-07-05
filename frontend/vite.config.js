import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API paths to the FastAPI backend so the frontend can
// call same-origin paths during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/research": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/portfolio": "http://localhost:8000",
      "/preferences": "http://localhost:8000",
      "/watchlist": "http://localhost:8000",
      "/summaries": "http://localhost:8000",
      "/alerts": "http://localhost:8000",
      "/notifications": "http://localhost:8000",
      "/digest": "http://localhost:8000",
      "/recommendations": "http://localhost:8000",
    },
  },
});
