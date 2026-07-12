import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // /api への呼び出しはバックエンド(uvicorn, :8000)へプロキシする。
    // これによりフロント側は相対パス `/api/...` で fetch でき、CORS にも
    // ポート差にも煩わされない(server/app.py の CORS 許可は保険として維持)。
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
