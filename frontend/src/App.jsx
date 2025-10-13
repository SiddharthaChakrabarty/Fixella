import React, { Suspense, lazy } from "react";
import { Routes, Route } from "react-router-dom";
import Home from "./pages/Home";
import Share from "./pages/Share";
import NotFound from "./pages/NotFound";
import { SignupPage } from "./pages/SignupPage";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { SubstepsPage } from "./pages/SubstepsPage";

// Lazy-load the knowledge graph page (default export)
const KnowledgeGraph = lazy(() => import("./pages/Knowledge_Graph"));

export default function App() {
  return (
    <div>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/share" element={<Share />} />
        <Route path="/substeps" element={<SubstepsPage />} />
        <Route path="/knowledge-graph" element={
          <Suspense fallback={<div className="p-4 text-center">Loading graph…</div>}>
            <KnowledgeGraph />
          </Suspense>
        } />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </div>
  );
}
