import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // Dev: forward API calls to the FastAPI backend.
      '/api': 'http://localhost:8787',
    },
  },
})
