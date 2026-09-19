import { lazy } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ErrorBoundary } from "react-error-boundary";
import { QueryProvider } from "./lib/react-query";
import { ErrorFallback } from "./components/ErrorBoundary";
import Layout from "./Layout";

/*
 * Route-level code splitting (Phase 5).
 *
 * Pages are loaded on demand instead of shipping every screen (and all of
 * Plotly) in one initial bundle. `Layout` stays eagerly loaded so the terminal
 * shell — header, search, footer — is never torn down while a page chunk
 * arrives; it provides the Suspense boundary around <Outlet />.
 */
const HomePage = lazy(() => import("./pages/HomePage"));
const StockDashboard = lazy(() => import("./pages/StockDashboard"));
const ScreenerPage = lazy(() => import("./pages/ScreenerPage"));
const ComparePage = lazy(() => import("./pages/ComparePage"));
const MarketsPage = lazy(() => import("./pages/MarketsPage"));
const WatchlistPage = lazy(() => import("./pages/WatchlistPage"));
const AlertsOverviewPage = lazy(() => import("./pages/AlertsOverviewPage"));
const PopularStocksPage = lazy(() => import("./pages/PopularStocksPage"));
const PortfolioDashboardPage = lazy(() => import("./pages/PortfolioDashboardPage"));

// PSX financial terminal pages
const MarketPage = lazy(() => import("./pages/MarketPage"));
const NewsPage = lazy(() => import("./pages/NewsPage"));
const PortfolioPage = lazy(() => import("./pages/PortfolioPage"));
const IndexPage = lazy(() => import("./pages/IndexPage"));
// Phase 11: professional charting & technical-analysis workspace
const ChartWorkspacePage = lazy(() => import("./pages/ChartWorkspacePage"));
// Phase 12: customizable workspace & layout engine
const WorkspacePage = lazy(() => import("./pages/WorkspacePage"));
const AnnouncementPage = lazy(() => import("./pages/AnnouncementPage"));
const AnnouncementsPage = lazy(() => import("./pages/AnnouncementsPage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const SignupPage = lazy(() => import("./pages/SignupPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));

// Advanced analytics pages
const CommandCenter = lazy(() => import("./pages/CommandCenter"));
const Macro = lazy(() => import("./pages/Macro"));
const Events = lazy(() => import("./pages/Events"));
const Company = lazy(() => import("./pages/Company"));
const Screener = lazy(() => import("./pages/Screener"));
const Crypto = lazy(() => import("./pages/Crypto"));
const ForexCommoditiesPage = lazy(() => import("./pages/ForexCommoditiesPage"));
const Analytics = lazy(() => import("./pages/Analytics"));
const SentimentPage = lazy(() => import("./pages/SentimentPage"));
// Phase 14: non-monetary event probability forecasting
const ForecastMarketsPage = lazy(() => import("./pages/ForecastMarketsPage"));
const ForecastDetailPage = lazy(() => import("./pages/ForecastDetailPage"));

export default function App() {
  return (
    <ErrorBoundary FallbackComponent={ErrorFallback}>
      <QueryProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              {/* Dashboard */}
              <Route path="/" element={<HomePage />} />
              <Route path="/stock/:ticker" element={<StockDashboard />} />

              {/* Discovery & tools */}
              <Route path="/screener-classic" element={<ScreenerPage />} />
              <Route path="/screener" element={<Screener />} />
              <Route path="/compare" element={<ComparePage />} />
              <Route path="/markets" element={<MarketsPage />} />
              <Route path="/popular" element={<PopularStocksPage />} />
              <Route path="/watchlist" element={<WatchlistPage />} />
              <Route path="/alerts" element={<AlertsOverviewPage />} />
              <Route path="/analytics" element={<Analytics />} />

              {/* Phase 9: transaction-level portfolio dashboard */}
              <Route path="/portfolio/transactions" element={<PortfolioDashboardPage />} />

              {/* PSX terminal */}
              <Route path="/market" element={<MarketPage />} />
              <Route path="/index/:symbol" element={<IndexPage />} />
              <Route path="/charts" element={<ChartWorkspacePage />} />
              <Route path="/workspace" element={<WorkspacePage />} />
              <Route path="/news" element={<NewsPage />} />
              <Route path="/portfolio" element={<PortfolioPage />} />
              <Route path="/announcements" element={<AnnouncementsPage />} />
              <Route path="/announcements/:id" element={<AnnouncementPage />} />

              {/* Account & settings */}
              <Route path="/login" element={<LoginPage />} />
              <Route path="/signup" element={<SignupPage />} />
              <Route path="/settings" element={<SettingsPage />} />

              {/* Advanced analytics */}
              <Route path="/command-center" element={<CommandCenter />} />
              <Route path="/macro" element={<Macro />} />
              <Route path="/events" element={<Events />} />
              <Route path="/company" element={<Company />} />
              <Route path="/crypto" element={<Crypto />} />
              <Route path="/forex-commodities" element={<ForexCommoditiesPage />} />
              <Route path="/sentiment" element={<SentimentPage />} />
              <Route path="/forecasts" element={<ForecastMarketsPage />} />
              <Route path="/forecast/:id" element={<ForecastDetailPage />} />

              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryProvider>
    </ErrorBoundary>
  );
}
