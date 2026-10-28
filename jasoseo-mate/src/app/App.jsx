import { createBrowserRouter, RouterProvider } from 'react-router'
import { routes } from './routes.jsx'
import './theme.css'
import './layout.css'

const router = createBrowserRouter(routes)

export default function App() {
  return <RouterProvider router={router} />
}
