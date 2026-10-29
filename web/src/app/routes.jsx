// 라우트 등록 (B1). 각 팀은 자기 기능의 페이지를 web/src/features/<기능>/에 만들고
// 아래 featureRoutes에 한 줄씩 추가한다(tasks.md 공통 규칙 1). 이 파일 변경은 B 리뷰.
//
// A: writing / B: resumes·share·pdf·interview·experiences(GitHub 소개 포함, 10/28)
// C: jobs·recommend·learning·applications / D: auth(로그인·MFA), admin
import Layout from './RoleNavLayout.jsx' // 역할 전용 메뉴를 거른 뒤 D의 Layout으로 넘긴다
import Home from './pages/Home.jsx'
import NotFound from './pages/NotFound.jsx'
import ResumesPage from '../features/resumes/ResumesPage.jsx'
import ResumeDetailPage from '../features/resumes/ResumeDetailPage.jsx'
import ExperiencesPage from '../features/experiences/ExperiencesPage.jsx'
import ExperienceEditPage from '../features/experiences/ExperienceEditPage.jsx'
import ExperienceDetailPage from '../features/experiences/ExperienceDetailPage.jsx'
import InterviewPage from '../features/interview/InterviewPage.jsx'
import WritingPage from '../features/writing/WritingPage.jsx'
import { AuthProvider } from '../features/auth/useAuth.jsx'
import LoginPage from '../features/auth/LoginPage.jsx'
import SignUpPage from '../features/auth/SignUpPage.jsx'
import ConfirmSignUpPage from '../features/auth/ConfirmSignUpPage.jsx'
import ForgotPasswordPage from '../features/auth/ForgotPasswordPage.jsx'
import MfaChallengePage from '../features/auth/MfaChallengePage.jsx'
import MfaSetupPage from '../features/auth/MfaSetupPage.jsx'
import MentorSharesPage from '../features/share/MentorSharesPage.jsx'
import MentorSharePage from '../features/share/MentorSharePage.jsx'
import TemplatesPage from '../features/templates/TemplatesPage.jsx'
import RequireAuth from '../features/auth/RequireAuth.jsx'
import AdminUsersPage from '../features/admin/AdminUsersPage.jsx'
// C: 공고 추천(C8)·학습 로드맵(C14)·지원 현황(C15) — nesumeC에서 이식(docs C-frontend-wiring.md 6절)
import RecommendPage from '../features/recommend/RecommendPage.jsx'
import LearningPage from '../features/learning/LearningPage.jsx'
import ApplicationsPage from '../features/applications/ApplicationsPage.jsx'

// nav: 상단 메뉴 노출 여부와 라벨. roles: 이 역할로 로그인했을 때만 메뉴에 보임(없으면 모두)
export const featureRoutes = [
  { path: 'resumes', element: <ResumesPage />, nav: '자소서' },
  { path: 'resumes/:resumeId', element: <ResumeDetailPage /> },
  { path: 'experiences', element: <ExperiencesPage />, nav: '경험' },
  // 작성·수정은 별도 주소 — 메뉴 '경험'을 누르면 목록(초기 화면)으로 돌아간다(10/28)
  { path: 'experiences/new', element: <ExperienceEditPage /> },
  { path: 'experiences/:experienceId/edit', element: <ExperienceEditPage /> },
  { path: 'experiences/:experienceId', element: <ExperienceDetailPage /> }, // 열람(행 클릭)
  { path: 'interview', element: <InterviewPage />, nav: '면접 연습' },
  { path: 'writing', element: <WritingPage />, nav: '글 다듬기' },
  // C 화면: 본인 데이터라 로그인 필요(백엔드도 토큰 강제 — 이중 방어)
  { path: 'recommend', element: <RequireAuth><RecommendPage /></RequireAuth>, nav: '공고 추천' },
  { path: 'learning', element: <RequireAuth><LearningPage /></RequireAuth>, nav: '학습 로드맵' },
  { path: 'applications', element: <RequireAuth><ApplicationsPage /></RequireAuth>, nav: '지원 현황' },
  // D7 인증 화면 (nav 없음). 보호 화면은 <RequireAuth> 로 감싼다(features/auth/RequireAuth.jsx).
  { path: 'login', element: <LoginPage /> },
  { path: 'signup', element: <SignUpPage /> },
  { path: 'confirm', element: <ConfirmSignUpPage /> },
  { path: 'forgot', element: <ForgotPasswordPage /> },
  { path: 'mfa/challenge', element: <MfaChallengePage /> },
  { path: 'mfa/setup', element: <MfaSetupPage /> },
  { path: 'mentor', element: <MentorSharesPage />, nav: '받은 공유', roles: ['mentor'] }, // B17 멘토 전용 — 메뉴도 멘토에게만
  { path: 'mentor/:shareId', element: <MentorSharePage /> },
  { path: 'templates', element: <TemplatesPage />, nav: '프롬프트 템플릿', roles: ['operator'] }, // B9 운영자 전용 — 메뉴도 운영자에게만
  // D6 역할 관리(운영자 전용). 운영자 부여·회수
  { path: 'admin/users', element: <RequireAuth roles={['operator']}><AdminUsersPage /></RequireAuth>, nav: '역할 관리', roles: ['operator'] },
]

export const routes = [
  {
    path: '/',
    // AuthProvider 가 Layout 을 감싼다: 토큰 공급·401 처리·/auth/me. 각 기능 페이지는 그대로 둔다(D7).
    element: (
      <AuthProvider>
        <Layout navItems={featureRoutes.filter((r) => r.nav)} />
      </AuthProvider>
    ),
    children: [
      { index: true, element: <Home /> },
      ...featureRoutes.map(({ path, element }) => ({ path, element })),
      { path: '*', element: <NotFound /> },
    ],
  },
]
