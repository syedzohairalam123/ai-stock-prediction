import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
        // Phase 17 streams over WebSocket, SSE and polling. `ws: true` lets the
        // dev server upgrade `/api/breaking-news/ws`; without it the client
        // would silently fall back to SSE on every reload.
        ws: true,
      }
    }
  },
  esbuild: {
    jsx: 'automatic',
  },
});
