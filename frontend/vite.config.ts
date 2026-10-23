import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api calls are proxied to FastAPI, so the browser sees one origin (no CORS needed).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.API_URL ?? "http://localhost:8000" },
  },
  preview: {
    port: 4173,
    proxy: { "/api": process.env.API_URL ?? "http://localhost:8000" },
  },
});
