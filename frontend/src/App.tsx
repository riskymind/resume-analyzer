import { Navigate, Route, Routes } from 'react-router'
import RequireAuth from './auth/RequireAuth'
import AppLayout from './components/layout/AppLayout'
import AccountPage from './pages/AccountPage'
import DashboardPage from './pages/DashboardPage'
import JobDetailPage from './pages/JobDetailPage'
import LoginPage from './pages/LoginPage'
import MatchDetailPage from './pages/MatchDetailPage'
import MatchesPage from './pages/MatchesPage'
import MatchNewPage from './pages/MatchNewPage'
import NotFoundPage from './pages/NotFoundPage'
import ResumeAnalysisPage from './pages/ResumeAnalysisPage'
import ResumesPage from './pages/ResumesPage'
import ReviewDetailPage from './pages/ReviewDetailPage'
import ReviewNewPage from './pages/ReviewNewPage'
import ReviewsPage from './pages/ReviewsPage'
import RewriteDetailPage from './pages/RewriteDetailPage'
import RewriteNewPage from './pages/RewriteNewPage'
import RewritesPage from './pages/RewritesPage'
import UploadPage from './pages/UploadPage'

/**
 * Routes. Everything except /login requires a session (<RequireAuth>); unknown paths show a not-found page.
 *
 *   /                      Dashboard
 *   /upload                Upload a resume (→ /resumes/:id)
 *   /resumes[/:id]         Resume quality analysis
 *   /match                 New job match (?resume=&job= preselect) (→ /matches/:id)
 *   /matches[/:id]         Saved match reports and job descriptions
 *   /jobs/:id              One job description's verified requirements
 *   /rewrite               New AI rewrite (?resume=&job= preselect) (→ /rewrites/:id)
 *   /rewrites[/:id]        Saved rewrites and the rewrite workspace
 *   /reviews[/new|/:id]    Quick reviews (resume + job in one step; the original flow)
 *   /account               Sign out and account deletion
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route index element={<DashboardPage />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="resumes" element={<ResumesPage />} />
          <Route path="resumes/:resumeId" element={<ResumeAnalysisPage />} />
          <Route path="match" element={<MatchNewPage />} />
          <Route path="matches" element={<MatchesPage />} />
          <Route path="matches/:matchId" element={<MatchDetailPage />} />
          <Route path="jobs" element={<Navigate to="/matches" replace />} />
          <Route path="jobs/:jobId" element={<JobDetailPage />} />
          <Route path="rewrite" element={<RewriteNewPage />} />
          <Route path="rewrites" element={<RewritesPage />} />
          <Route path="rewrites/:rewriteId" element={<RewriteDetailPage />} />
          <Route path="reviews" element={<ReviewsPage />} />
          <Route path="reviews/new" element={<ReviewNewPage />} />
          <Route path="reviews/:analysisId" element={<ReviewDetailPage />} />
          <Route path="account" element={<AccountPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
