import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 개발 서버(npm run dev)에서 /api 요청을 넘길 대상. 호스트 주소를 코드에 두지 않고 환경변수로만 받는다.
// 예: API_PROXY_TARGET=http://localhost:8080 npm run dev  (nginx 경유, /api 접두사 유지)
const proxyTarget = process.env.API_PROXY_TARGET

export default defineConfig({
  plugins: [react()],
  server: proxyTarget ? { proxy: { '/api': { target: proxyTarget, changeOrigin: true } } } : {},
})
