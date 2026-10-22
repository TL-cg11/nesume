# 프론트엔드 개발 가이드

작성: B (자소서 관리·문서) · 2026-10-22
대상: `web/` 아래에서 화면을 만드는 A·B·C·D 전원
짝 문서: `docs/dev/backend-guide.md` (D3)

이 문서의 표기
- ✅ **현재 구현됨**: 지금 코드가 이렇게 되어 있다. 그대로 따르면 된다.
- 📝 **제안**: 통일을 위해 B가 제안하는 규칙. **팀 합의 후 ✅로 바꾼다.** 합의 전에도 새 코드는 이 제안을 따르는 것을 권장한다.

---

## 1. 기술 스택 ✅

| 항목 | 버전 | 비고 |
|---|---|---|
| React | 19.3.0 | |
| react-router | 7.18.4 | v8(2026-06 출시)은 1년 미만이라 쓰지 않음 |
| Vite | 8.3.3 | 빌드·개발 서버 |
| Node(빌드) | 22.23.3 | Docker 빌드 단계 |
| nginx | nginx-unprivileged 1.30.5 | 운영 서빙, 비루트 |

- TypeScript·상태관리 라이브러리·UI 프레임워크는 **쓰지 않는다.** 지금 규모에서는 React 기본 기능(`useState`, `useEffect`)으로 충분하다.
- 📝 **패키지 추가 규칙**
  - 버전은 `--save-exact`로 고정한다(`^` 금지). `package-lock.json`도 함께 커밋한다.
  - 출시 1년 미만 패키지는 넣지 않는다(프로젝트 원칙).
  - 추가 전에 팀 채널에 이유를 공유한다. 화면 하나를 위해 큰 라이브러리를 넣지 않는다.

---

## 2. 폴더 구조와 소유 ✅

```
web/
├─ index.html
├─ vite.config.js           개발 서버 /api 프록시(환경변수 API_PROXY_TARGET)
├─ nginx.conf.template      운영: /api → app 프록시, SPA 라우팅, 보안 헤더
├─ Dockerfile               node 빌드 → nginx 서빙
└─ src/
   ├─ main.jsx              진입점(수정 불필요)
   ├─ app/                  ★ 공통 골격 — B 소유, 변경은 B 리뷰
   │  ├─ App.jsx            라우터 생성
   │  ├─ routes.jsx         라우트 등록표 (각 팀이 한 줄씩 추가)
   │  ├─ Layout.jsx         상단 메뉴 + 본문 영역
   │  ├─ layout.css         색·글꼴 변수(디자인 토큰), 기본 버튼·입력 스타일
   │  ├─ api/client.js      공통 API 호출 함수 (모든 화면이 이것만 사용)
   │  ├─ pages/             Home, NotFound
   │  └─ dev/               개발 서버 전용 도구(DevTokenPanel)
   └─ features/             ★ 기능별 화면 — 각 팀 소유
      ├─ resumes/  share/  pdf/  interview/  github/  experiences/   B
      ├─ writing/                                                    A
      ├─ jobs/  recommend/  learning/  applications/                 C
      └─ auth/  admin/                                               D
```

- 소유 기준은 `plan/tasks.md` "디렉터리 소유" 표와 같다.
- 다른 팀 폴더의 파일은 고치지 않는다. 필요하면 그 팀에 요청한다.

### 기능 폴더 안 구성 📝

```
features/<기능>/
├─ <기능>Page.jsx       라우트에 연결되는 화면(페이지) 컴포넌트
├─ <이름>.jsx           페이지 안에서 쓰는 하위 컴포넌트
├─ api.js               이 기능의 API 호출 함수 모음 (client.js만 사용)
├─ <순수 함수>.js       화면과 무관한 계산(예: experiences/summary.js)
└─ <기능>.css           이 기능 전용 스타일
```

현재 B 화면이 이 구성을 따른다. 예: `features/resumes/` = `ResumesPage.jsx`, `ResumeDetailPage.jsx`, `QuestionEditor.jsx`, `DiffView.jsx`, `api.js`, `resumes.css`.

---

## 3. 실행·빌드·배포 흐름 ✅

| 상황 | 방법 | /api 처리 |
|---|---|---|
| 화면 개발 | `cd web && npm ci && API_PROXY_TARGET=http://localhost:8080 npm run dev` → http://localhost:5173 | Vite 개발 서버가 nginx로 프록시 |
| 로컬 통합 | `docker compose up -d` → http://localhost:8080 | nginx가 `/api/*`를 app의 `/*`로 전달(접두사 제거) |
| 운영 | Docker 이미지(정적 파일 + nginx) | 같은 출처 `/api` |

- **코드에 호스트 주소(localhost 등)를 쓰지 않는다.** 모든 호출은 같은 출처 `/api`로 간다. CORS 설정이 필요 없다.
- 개발 서버는 `docker compose up -d`로 백엔드가 떠 있어야 한다.
- nginx 보안 헤더: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`. 다른 사이트에 iframe으로 삽입되지 않는다.

---

## 4. 라우팅 규칙

### 등록 방법 ✅

`web/src/app/routes.jsx`의 `featureRoutes`에 한 줄 추가한다.

```jsx
import JobsPage from '../features/jobs/JobsPage.jsx'

export const featureRoutes = [
  // ...
  { path: 'jobs', element: <JobsPage />, nav: '공고' },        // 상단 메뉴에 표시
  { path: 'jobs/:jobId', element: <JobDetailPage /> },          // nav 없음 = 메뉴 미표시
]
```

- `routes.jsx` 변경은 B 리뷰를 받는다(여러 팀이 같은 파일을 고치므로 충돌 조정).
- 없는 주소는 `NotFound` 화면이 처리한다.

### 경로 이름 📝

| 규칙 | 예 |
|---|---|
| 소문자, 단어 구분은 하이픈 | `learning-roadmap` |
| 목록은 복수형 | `/resumes`, `/experiences`, `/jobs` |
| 상세는 `목록/:<단수>Id` | `/resumes/:resumeId` |
| 하위 화면은 상세 아래 | `/resumes/:resumeId/share` |
| 운영자 화면은 `/admin/` 아래(D) | `/admin/audit-logs` |

- 메뉴 라벨(`nav`)은 2~5자 명사로 한다. 예: 자소서, 경험, 면접 연습, 공고, 추천

---

## 5. API 호출 규칙

### 공통 클라이언트만 쓴다 ✅

```js
// features/<기능>/api.js
import { api } from '../../app/api/client.js'

export const jobsApi = {
  list: (params) => api.get(`/jobs?${new URLSearchParams(params)}`),
  get: (id) => api.get(`/jobs/${id}`),
  apply: (id, body) => api.post(`/jobs/${id}/applications`, body),
}
```

- `fetch`를 화면에서 직접 부르지 않는다. 토큰·에러·401 처리가 `client.js`에 모여 있다.
- 경로는 `/`로 시작하고 `/api`는 붙이지 않는다(클라이언트가 붙임).
- 쿼리 문자열은 `URLSearchParams`로 만든다. 문자열을 직접 이어 붙이면 한글·특수문자가 깨진다.
- 배열 파라미터는 같은 키를 반복한다: `tags=a&tags=b` (예: `features/experiences/api.js`)

### 로그인 토큰 ✅

- 토큰은 인증 모듈(D7, `features/auth`)이 `setTokenProvider(fn)`으로 넣는다. 각 화면은 토큰을 다루지 않는다.
- 401이 오면 `setUnauthorizedHandler`에 등록된 동작(로그인 화면 이동 등, D7)이 실행된다.
- D7 로그인 화면 전까지는 개발 서버 상단 **DEV 토큰** 입력란을 쓴다(10절).

### 에러 응답 형식 (백엔드 D3) ✅

```json
{"detail": "자소서를 찾을 수 없습니다.", "code": "not_found", "request_id": "3f2a...", "errors": null}
```

- 어떤 오류든 `detail`이 있다. 화면에 보여줄 문구는 `detail`.
- `code`로 분기한다(문구로 분기하지 않는다). 예: `not_found`, `forbidden`, `validation_error`, `rate_limited`
- `request_id`는 문의·디버깅용. 사용자가 오류를 신고할 때 함께 받는다.

### 📝 제안: `ApiError`에 `code`·`requestId` 추가

현재 `ApiError`는 `status`·`detail`만 담는다. D3 형식에 맞춰 아래처럼 넓히자(B가 `client.js` 수정, 기존 화면 호환).

```js
// 사용 예
try { await resumesApi.get(id) }
catch (e) {
  if (e.status === 404) showNotFound()
  else if (e.code === 'rate_limited') showRetryLater()
  else showError(e.message, e.requestId)
}
```

### 요청 취소 ✅

화면을 떠날 때 진행 중인 요청을 취소한다(`AbortController`). 예: `app/pages/Home.jsx`

```jsx
useEffect(() => {
  const ctrl = new AbortController()
  api.get('/health', { signal: ctrl.signal }).then(...).catch((e) => e.name !== 'AbortError' && setError(e))
  return () => ctrl.abort()
}, [])
```

---

## 6. 화면 상태 처리 📝

모든 데이터 화면은 **네 가지 상태**를 빠짐없이 그린다.

| 상태 | 표시 | 현재 예 |
|---|---|---|
| 불러오는 중 | `<p className="muted">불러오는 중...</p>` | `ResumeDetailPage` |
| 비어 있음 | `<li className="muted">자소서가 없습니다.</li>` | `ResumesPage` |
| 오류 | `<p className="error">불러오지 못했습니다: {메시지}</p>` | `ResumesPage` |
| 정상 | 데이터 | |

- 404는 "찾을 수 없습니다"로 따로 보여준다. 다른 사용자 데이터도 404가 오므로 "권한이 없습니다"라고 쓰지 않는다(존재 노출 방지).
- 저장 중에는 버튼을 `disabled`로 두어 중복 저장을 막는다.
- 저장 성공 후에는 서버 응답 값으로 화면을 갱신한다(서버가 바꾼 값 반영. 예: 버전 번호, 등급).

---

## 7. 폼·입력 규칙

### 서버 전용 값은 보내지 않는다 ✅

`grade`(등급), `owner_id`, `deleted_at`, `source` 같은 값은 서버가 정한다. 보내면 422로 거부된다.

### 📝 입력 규칙

| 규칙 | 이유 |
|---|---|
| `maxLength`를 백엔드 스키마와 같게 | 제출 후에 422가 나는 것을 막음. 예: 자소서 제목 200, 태그 50 |
| 앞뒤 공백은 `trim()` 후 전송, 빈 문자열은 `null` | 백엔드 선택 필드 규칙과 맞춤 |
| 쉼표 목록 입력은 배열로 변환 | 예: `ExperienceForm`의 `split()` |
| 날짜는 `<input type="date">` → `YYYY-MM-DD` 그대로 전송 | |
| 삭제는 `window.confirm`으로 한 번 확인, 문구에 "30일 후 완전히 삭제" 명시 | 소프트 삭제 정책 안내(B4·B5) |
| 글자 수 표시는 공백 포함 기준 | 백엔드 `char_count`와 같음 |

### 민감정보 입력 ✅

주민번호·계좌번호가 들어가면 서버가 422로 거부하고 안내 문구(spec 9.1)를 `detail`로 준다. 화면은 그 문구를 그대로 보여준다.

---

## 8. 스타일 규칙

### 디자인 토큰 ✅ (`app/layout.css`)

| 변수 | 용도 |
|---|---|
| `--bg` | 배경 |
| `--fg` | 본문 글자 |
| `--muted` | 보조 글자(날짜, 설명) |
| `--border` | 테두리 |
| `--accent` | 강조(기본 버튼, 활성 메뉴) |

- 다크 모드는 운영체제 설정을 따라 자동으로 바뀐다. **색은 반드시 변수로 쓴다.** `#fff` 같은 값을 직접 쓰면 다크 모드에서 깨진다.
- 글꼴: 시스템 글꼴 + Apple SD Gothic Neo + Noto Sans KR

### 기본 요소 ✅

| 요소 | 사용 |
|---|---|
| `<button>` | 기본 동작(저장, 만들기) — 파란 배경 |
| `<button className="secondary">` | 보조 동작(취소, 삭제, 비교) — 테두리만 |
| `input`, `textarea`, `select` | 별도 클래스 없이 기본 스타일 적용 |
| `.error` | 오류 문구(빨강) |

### 📝 공용 유틸 클래스를 `app/layout.css`로 이동

지금은 `.row`, `.stack`, `.muted`, `.notice`가 `features/resumes/resumes.css`에 있고, 경험 화면이 그 파일을 가져다 쓴다. 다른 팀도 쓰도록 `app/layout.css`로 옮기자(B 작업).

| 클래스 | 의미 |
|---|---|
| `.row` | 가로 배치, 간격 8px, 줄바꿈 허용 |
| `.stack` | 세로 배치, 간격 6px |
| `.muted` | 보조 글자, 13px |
| `.notice` | 주의 안내(노랑 계열) |

### 📝 클래스 이름 규칙

- 기능 전용 클래스는 **기능 접두사**를 붙인다: `exp-form`, `exp-list`, `resume-list` (다른 팀 CSS와 충돌 방지)
- 전역 요소 선택자(`button {}`, `p {}`)는 `app/layout.css`에서만 쓴다.

### 📝 간격·크기·반응형

| 항목 | 값 |
|---|---|
| 간격 | 4 / 8 / 12 / 16 / 24px 중에서 |
| 모서리 | 6px(입력·버튼), 8px(카드·폼 박스), 999px(태그 칩) |
| 본문 최대 폭 | 1080px (`.app-main`) |
| 모바일 전환 | **720px 하나로 통일** (현재 640px·720px 혼재 → 720px로 맞춤) |
| 좁은 화면 | 가로 스크롤이 생기지 않게 `flex-wrap: wrap` |

---

## 9. 보안 규칙 (필수)

| 규칙 | 상태 | 근거 |
|---|---|---|
| **`dangerouslySetInnerHTML` 사용 금지.** 서버·외부 텍스트는 항상 텍스트로 렌더링 | 📝 | 공유 문서 "응답 내 HTML·이미지 렌더링 금지", XSS 방지 |
| 외부 링크는 `target="_blank" rel="noopener noreferrer"` + "외부 사이트" 표시 | 📝 | 공유 문서(C) |
| 고용24 링크는 `https`이면서 `work24.go.kr` 도메인만 허용 | 📝 | 공유 문서(C) |
| 서울시 공고 화면은 "서울특별시 공공데이터" 출처 표시, AI 분석 결과는 원문과 구분 표시 | 📝 | 공유 문서(C), 출처 표시 의무 |
| **토큰을 `localStorage`·`sessionStorage`에 저장하지 않는다** | ✅ (DEV 토큰도 메모리만) | 탈취 위험 |
| `console.log`에 자소서 본문·개인정보·토큰을 찍지 않는다 | 📝 | 브라우저 로그 유출 방지 |
| 개인정보 가림(마스킹)은 서버가 한다. 화면에서 다시 풀거나 가공하지 않는다 | ✅ | spec 6.3 (멘토·운영자는 가린 값만 받음) |
| 파일 다운로드는 `fetch`(로그인 헤더 포함)로 받아 저장한다. 링크로 직접 열지 않는다 | ✅ | B6 1회용 토큰, 발급자 본인만 |
| 오류 화면에 "권한이 없다"·"존재하지 않는다"를 구분해서 노출하지 않는다 | ✅ | spec 9.1 (존재 노출 금지) |

---

## 10. 문구·접근성 📝

- 차단·권한 안내 문구는 **spec 9.1 문구를 그대로** 쓴다. 서버가 `detail`로 주면 그대로 표시한다.
  - 권한: "요청하신 자료는 현재 권한으로 열람할 수 없습니다."
  - 민감정보: "주민번호·계좌번호 등 민감정보는 제공하지 않습니다. 입력 시에도 자동 차단됩니다."
  - 탈취 차단: "해당 요청은 처리할 수 없습니다."
  - 마스킹: "일부 개인정보는 보호를 위해 가려졌습니다."
- 버튼 문구는 동사로: "새 버전으로 저장", "본문에 추가", "연결 해제"
- 라벨이 없는 입력에는 `aria-label`을 단다(현재 B 화면 적용).
- 색만으로 상태를 구분하지 않는다. 비교 화면도 삭제는 취소선, 추가는 강조로 모양을 함께 다르게 한다(`DiffView`).

---

## 11. 개발 도구: DEV 토큰 ✅

- `app/dev/DevTokenPanel.jsx`: 개발 서버(`npm run dev`)에서만 상단에 보인다. **운영 빌드에는 포함되지 않는다**(빌드 결과물에 해당 코드 없음 확인).
- cognito-local 토큰 발급 방법은 루트 `README.md`의 "프론트엔드 개발 서버" 절 참고.
- D7 로그인 화면이 들어오면 삭제한다(B).

---

## 12. 이름 규칙 📝

| 대상 | 규칙 | 예 |
|---|---|---|
| 컴포넌트 파일 | PascalCase + `.jsx` | `QuestionEditor.jsx` |
| 페이지 컴포넌트 | `~Page.jsx` | `ResumesPage.jsx`, `ResumeDetailPage.jsx` |
| 일반 JS 파일 | camelCase + `.js` | `summary.js` |
| API 모음 | 기능 폴더마다 `api.js`, 객체 이름은 `<기능>Api` | `resumesApi`, `experiencesApi` |
| CSS 파일 | `<기능>.css` | `experiences.css` |
| 이벤트 함수 | 동사로 시작 | `save`, `restore`, `pullExperience` |
| 상태 이름 | 명사, 불리언은 `is`/`has` | `versions`, `isSaving` |

---

## 13. 새 화면 추가 체크리스트

1. `features/<기능>/`에 `<기능>Page.jsx`, `api.js`, `<기능>.css` 만들기
2. `api.js`는 `app/api/client.js`의 `api`만 사용
3. 네 가지 상태(불러오는 중·비어 있음·오류·정상) 처리
4. 색은 CSS 변수, 클래스는 기능 접두사
5. 서버 전용 필드 보내지 않기, `maxLength`는 백엔드와 같게
6. `dangerouslySetInnerHTML` 없음, 외부 링크 `noopener`
7. `routes.jsx`에 한 줄 등록 → B 리뷰
8. `npm run build` 통과 확인

---

## 14. 팀 합의 필요 목록

| # | 제안 | 담당 |
|---|---|---|
| 1 | `ApiError`에 `code`·`requestId` 추가 (5절) | B 구현 |
| 2 | 공용 유틸 클래스를 `app/layout.css`로 이동, 모바일 기준 720px 통일 (8절) | B 구현 |
| 3 | 상태 처리 4종·입력 규칙 (6·7절) | 전원 |
| 4 | 보안 규칙 중 📝 항목 (9절) | 전원 |
| 5 | 경로·이름 규칙 (4·12절) | 전원 |
| 6 | 패키지 추가 규칙 (1절) | 전원 |

합의되면 이 문서의 📝를 ✅로 바꾸고, B는 1·2번을 반영한다.
