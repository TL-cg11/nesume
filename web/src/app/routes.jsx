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
import MentorSharesPage from '../features/share/MentorSharesPage.jsx'
import MentorSharePage from '../features/share/MentorSharePage.jsx'

// nav: 상단 메뉴 노출 여부와 라벨
export const featureRoutes = [
  { path: 'resumes', element: <ResumesPage />, nav: '자소서' },
  { path: 'resumes/:resumeId', element: <ResumeDetailPage /> },
  { path: 'experiences', element: <ExperiencesPage />, nav: '경험' },
  { path: 'interview', element: <InterviewPage />, nav: '면접 연습' },
  { path: 'github', element: <GithubPage />, nav: 'GitHub 소개' },
  { path: 'writing', element: <WritingPage />, nav: '글 다듬기' },
  { path: 'mentor', element: <MentorSharesPage />, nav: '받은 공유' }, // B17 멘토 전용(그 외 역할은 안내 문구)
  { path: 'mentor/:shareId', element: <MentorSharePage /> },
]

export const routes = [
  {
    path: '/',
    element: <Layout navItems={featureRoutes.filter((r) => r.nav)} />,
    children: [
      { index: true, element: <Home /> },
      ...featureRoutes.map(({ path, element }) => ({ path, element })),
      { path: '*', element: <NotFound /> },
    ],
  },
]
