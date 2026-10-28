import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { mockApiPlugin } from './mock/server.js'

// 개발 서버(npm run dev)에서 /api 요청 처리:
// - API_PROXY_TARGET 가 있으면 실제 백엔드로 프록시(Phase 2). 단 /api/recommendations 는 계속 목(시드 필요).
// - 없으면 /api/* 를 전부 목으로 응답(Phase 1, 백엔드 없이 프론트 배선 확인).
// 호스트 주소는 코드에 두지 않고 환경변수로만 받는다.
//   예: API_PROXY_TARGET=http://localhost:8080 npm run dev
const proxyTarget = process.env.API_PROXY_TARGET
const hasProxy = Boolean(proxyTarget)

export default defineConfig({
  plugins: [react(), mockApiPlugin({ hasProxy })],
  // 프로덕션 nginx 와 동일하게 /api 접두사를 떼고 app 으로 보낸다(app 라우트는 /roadmaps 등 루트).
  server: hasProxy
    ? { proxy: { '/api': { target: proxyTarget, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') } } }
    : {},
})
