/* @refresh reload */
import { render } from "solid-js/web";
import { lazy, Suspense } from "solid-js";
import { Router, Route } from "@solidjs/router";
import "./index.css";
import App from "./App";
import DashboardPage from "./pages/DashboardPage";
import { SettingsProvider } from "./components/SettingsProvider";
import { AuthProvider } from "./components/AuthProvider";
import ProtectedRoute from "./components/ProtectedRoute";

const LoginPage = lazy(() => import("./pages/LoginPage"));
const StatisticsPage = lazy(() => import("./pages/StatisticsPage"));
const TargetDetailPage = lazy(() => import("./pages/TargetDetailPage"));
const AnalysisPage = lazy(() => import("./pages/AnalysisPage"));
const MosaicsPage = lazy(() => import("./pages/MosaicsPage"));
const MosaicDetailPage = lazy(() => import("./pages/MosaicDetailPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then(m => ({ default: m.SettingsPage })));

const Protected = (Page: any) => () => (
  <ProtectedRoute><Page /></ProtectedRoute>
);

const root = document.getElementById("root");
render(
  () => (
    <AuthProvider>
      <SettingsProvider>
        <Suspense fallback={<div />}>
          <Router root={App}>
            <Route path="/login" component={LoginPage} />
            <Route path="/" component={Protected(DashboardPage)} />
            <Route path="/targets/:targetId" component={Protected(TargetDetailPage)} />
            <Route path="/statistics" component={Protected(StatisticsPage)} />
            <Route path="/analysis" component={Protected(AnalysisPage)} />
            <Route path="/mosaics" component={Protected(MosaicsPage)} />
            <Route path="/mosaics/:mosaicId" component={Protected(MosaicDetailPage)} />
            <Route path="/settings" component={Protected(SettingsPage)} />
          </Router>
        </Suspense>
      </SettingsProvider>
    </AuthProvider>
  ),
  root!,
);
