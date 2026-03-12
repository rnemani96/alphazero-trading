// dashboard/alphazero-ui/vite.config.js
// FIX: proxy target changed from :8000 to :8000 (explicit, matches settings.py)
// This was already correct but made explicit here.

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend port must match DASHBOARD_PORT in config/settings.py (default: 8000)
const BACKEND_PORT = parseInt(process.env.VITE_BACKEND_PORT || '8000')
const BACKEND_URL  = `http://localhost:${BACKEND_PORT}`
const WS_URL       = `ws://localhost:${BACKEND_PORT}`

export default defineConfig({
  plugins: [react()],

  // Inject backend URL so React can use it at runtime
  define: {
    __BACKEND_URL__: JSON.stringify(BACKEND_URL),
  },

  server: {
    port: 3000,
    open: false,   // main.py opens the browser after health-check

    proxy: {
      // WebSocket — live quotes and agent events
      '/ws': {
        target:       WS_URL,
        ws:           true,
        changeOrigin: true,
      },
      // REST API — all routed to FastAPI backend
      '/quotes':      { target: BACKEND_URL, changeOrigin: true },
      '/quote':       { target: BACKEND_URL, changeOrigin: true },
      '/signals':     { target: BACKEND_URL, changeOrigin: true },
      '/signal':      { target: BACKEND_URL, changeOrigin: true },
      '/indices':     { target: BACKEND_URL, changeOrigin: true },
      '/candles':     { target: BACKEND_URL, changeOrigin: true },
      '/portfolio':   { target: BACKEND_URL, changeOrigin: true },
      '/evaluation':  { target: BACKEND_URL, changeOrigin: true },
      '/market':      { target: BACKEND_URL, changeOrigin: true },
      '/api':         { target: BACKEND_URL, changeOrigin: true },
      '/health':      { target: BACKEND_URL, changeOrigin: true },
      '/fundamentals':{ target: BACKEND_URL, changeOrigin: true },
    },
  },

  build: {
    // Build output goes to dashboard/frontend/dist (served by backend.py)
    outDir:     '../frontend/dist',
    emptyOutDir: true,
  },
})
