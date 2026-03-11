import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],

  server: {
    port: 3000,
    open: false,  // main.py opens the browser after health-check — don't double-open

    proxy: {
      // ── WebSocket (live quotes, agent events) ────────────────────────────
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      // ── REST API endpoints served by FastAPI backend ─────────────────────
      '/quotes':     { target: 'http://localhost:8000', changeOrigin: true },
      '/signals':    { target: 'http://localhost:8000', changeOrigin: true },
      '/signal':     { target: 'http://localhost:8000', changeOrigin: true },
      '/indices':    { target: 'http://localhost:8000', changeOrigin: true },
      '/candles':    { target: 'http://localhost:8000', changeOrigin: true },
      '/portfolio':  { target: 'http://localhost:8000', changeOrigin: true },
      '/evaluation': { target: 'http://localhost:8000', changeOrigin: true },
      '/market':     { target: 'http://localhost:8000', changeOrigin: true },
      '/api':        { target: 'http://localhost:8000', changeOrigin: true },
    },
  },

  build: {
    // Output directly to dashboard/frontend/dist where backend.py serves from
    outDir: '../frontend/dist',
    emptyOutDir: true,
  },
})
