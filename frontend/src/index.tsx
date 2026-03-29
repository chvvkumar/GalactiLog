/* @refresh reload */
import { render } from "solid-js/web";
import { Router, Route } from "@solidjs/router";
import "./index.css";
import App from "./App";
import DashboardPage from "./pages/DashboardPage";
import StatisticsPage from "./pages/StatisticsPage";
import TargetDetailPage from "./pages/TargetDetailPage";
import LoginPage from "./pages/LoginPage";
import { SettingsProvider } from "./components/SettingsProvider";
import { SettingsPage } from "./pages/SettingsPage";
import { AuthProvider } from "./components/AuthProvider";
import ProtectedRoute from "./components/ProtectedRoute";

const Protected = (Page: any) => () => (
  <ProtectedRoute><Page /></ProtectedRoute>
);

const root = document.getElementById("root");
render(
  () => (
    <AuthProvider>
      <SettingsProvider>
        <Router root={App}>
          <Route path="/login" component={LoginPage} />
          <Route path="/" component={Protected(DashboardPage)} />
          <Route path="/targets/:targetId" component={Protected(TargetDetailPage)} />
          <Route path="/statistics" component={Protected(StatisticsPage)} />
          <Route path="/settings" component={Protected(SettingsPage)} />
        </Router>
      </SettingsProvider>
    </AuthProvider>
  ),
  root!,
);
