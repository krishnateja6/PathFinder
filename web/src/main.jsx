import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App.jsx";
import Landing from "./pages/Landing.jsx";
import AnalyzeFlow from "./pages/AnalyzeFlow.jsx";
import Workspace from "./pages/Workspace.jsx";
import ProfileScan from "./pages/ProfileScan.jsx";
import OverviewTab from "./tabs/OverviewTab.jsx";
import ArchitectureTab from "./tabs/ArchitectureTab.jsx";
import ExplorerChatTab from "./tabs/ExplorerChatTab.jsx";
import ImpactTab from "./tabs/ImpactTab.jsx";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Landing />} />
          <Route path="analyze" element={<AnalyzeFlow />} />
          <Route path="profile" element={<ProfileScan />} />
          <Route path="r/:owner/:repo" element={<Workspace />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<OverviewTab />} />
            <Route path="architecture" element={<ArchitectureTab />} />
            <Route path="explorer" element={<ExplorerChatTab />} />
            <Route path="impact" element={<ImpactTab />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
