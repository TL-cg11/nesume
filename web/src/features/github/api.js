// B14 GitHub 프로젝트 소개. 공통 클라이언트(app/api/client.js)만 사용한다.
import { api } from '../../app/api/client.js'

export const githubApi = {
  // 결과의 experience_draft는 화면에서 고친 뒤 B5 POST /experiences 로 저장한다
  draft: (data) => api.post('/experiences/github/draft', data),
  saveExperience: (data) => api.post('/experiences', data),
}

export const errorText = (e) => {
  if (e.code === 'github_rate_limited') return 'GitHub 조회 한도를 넘었습니다. 잠시 후 다시 시도해 주세요.'
  if (e.code === 'github_unavailable') return 'GitHub에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'
  return e.message
}
