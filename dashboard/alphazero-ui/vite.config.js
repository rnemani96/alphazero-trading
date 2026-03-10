import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],

  server: {
    port: 3000,
    open: true, // auto-opens browser on npm run dev

    proxy: {
      // WebSocket — must use ws: true
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      // REST endpoints — proxy to FastAPI backend
      '/quotes':     { target: 'http://localhost:8000', changeOrigin: true },
      '/signals':    { target: 'http://localhost:8000', changeOrigin: true },
      '/indices':    { target: 'http://localhost:8000', changeOrigin: true },
      '/portfolio':  { target: 'http://localhost:8000', changeOrigin: true },
      '/candles':    { target: 'http://localhost:8000', changeOrigin: true },
      '/evaluation': { target: 'http://localhost:8000', changeOrigin: true },
      '/market':     { target: 'http://localhost:8000', changeOrigin: true },
      '/signal':     { target: 'http://localhost:8000', changeOrigin: true },
    }
  },

  build: {
    outDir: '../frontend/dist', // build output goes to dashboard/frontend/dist
    emptyOutDir: true,
  }
})
