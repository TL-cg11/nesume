// 라우트 등록 (B1). 각 팀은 자기 기능의 페이지를 web/src/features/<기능>/에 만들고
// 아래 featureRoutes에 한 줄씩 추가한다(tasks.md 공통 규칙 1). 이 파일 변경은 B 리뷰.
//
// A: writing / B: resumes·share·pdf·interview·github·experiences
// C: jobs·recommend·learning·applications / D: auth(로그인·MFA), admin
import Layout from './Layout.jsx'
import Home from './pages/Home.jsx'
import NotFound from './pages/NotFound.jsx'
import ResumesPage from '../features/resumes/ResumesPage.jsx'
import ResumeDetailPage from '../features/resumes/ResumeDetailPage.jsx'
import ExperiencesPage from '../features/experiences/ExperiencesPage.jsx'
import InterviewPage from '../features/interview/InterviewPage.jsx'
import GithubPage from '../features/github/GithubPage.jsx'
import WritingPage from '../features/writing/WritingPage.jsx'
import { AuthProvider } from '../features/auth/useAuth.jsx'
import LoginPage from '../features/auth/LoginPage.jsx'
import SignUpPage from '../features/auth/SignUpPage.jsx'
import ConfirmSignUpPage from '../features/auth/ConfirmSignUpPage.jsx'
import ForgotPasswordPage from '../features/auth/ForgotPasswordPage.jsx'
import MfaChallengePage from '../features/auth/MfaChallengePage.jsx'
import MfaSetupPage from '../features/auth/MfaSetupPage.jsx'

// nav: 상단 메뉴 노출 여부와 라벨
export const featureRoutes = [
  { path: 'resumes', element: <ResumesPage />, nav: '자소서' },
  { path: 'resumes/:resumeId', element: <ResumeDetailPage /> },
  { path: 'experiences', element: <ExperiencesPage />, nav: '경험' },
  { path: 'interview', element: <InterviewPage />, nav: '면접 연습' },
  { path: 'github', element: <GithubPage />, nav: 'GitHub 소개' },
  { path: 'writing', element: <WritingPage />, nav: '글 다듬기' },
  // D7 인증 화면 (nav 없음). 보호 화면은 <RequireAuth> 로 감싼다(features/auth/RequireAuth.jsx).
  { path: 'login', element: <LoginPage /> },
  { path: 'signup', element: <SignUpPage /> },
  { path: 'confirm', element: <ConfirmSignUpPage /> },
  { path: 'forgot', element: <ForgotPasswordPage /> },
  { path: 'mfa/challenge', element: <MfaChallengePage /> },
  { path: 'mfa/setup', element: <MfaSetupPage /> },
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
