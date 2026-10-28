// 라우트 등록 (프론트 가이드 4절). 기능 페이지는 src/features/<기능>/에 두고 아래에 한 줄씩 추가.
import Layout from './Layout.jsx'
import Home from './pages/Home.jsx'
import NotFound from './pages/NotFound.jsx'
import RecommendPage from '../features/recommend/RecommendPage.jsx'
import LearningPage from '../features/learning/LearningPage.jsx'
import ApplicationsPage from '../features/applications/ApplicationsPage.jsx'

// nav: 상단 메뉴 노출 여부와 라벨(2~5자 명사)
export const featureRoutes = [
  { path: 'recommend', element: <RecommendPage />, nav: '공고 추천' },
  { path: 'learning', element: <LearningPage />, nav: '학습 로드맵' },
  { path: 'applications', element: <ApplicationsPage />, nav: '지원 현황' },
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
