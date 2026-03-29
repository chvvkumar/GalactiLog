/* @refresh reload */
import { render } from "solid-js/web";
import { Router, Route } from "@solidjs/router";
import "./index.css";
import App from "./App";
import DashboardPage from "./pages/DashboardPage";
import StatisticsPage from "./pages/StatisticsPage";
import TargetDetailPage from "./pages/TargetDetailPage";
import { SettingsProvider } from "./components/SettingsProvider";
import { SettingsPage } from "./pages/SettingsPage";

const root = document.getElementById("root");
render(
  () => (
    <SettingsProvider>
      <Router root={App}>
        <Route path="/" component={DashboardPage} />
        <Route path="/targets/:targetId" component={TargetDetailPage} />
        <Route path="/statistics" component={StatisticsPage} />
        <Route path="/settings" component={SettingsPage} />
      </Router>
    </SettingsProvider>
  ),
  root!,
);
