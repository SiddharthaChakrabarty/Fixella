import React from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home";
import Share from "./pages/Share";
import NotFound from "./pages/NotFound";
import { SignupPage } from "./pages/SignupPage";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { SubstepsPage } from "./pages/SubstepsPage";

export default function App() {
  return (
    <div>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/share" element={<Share />} />
        <Route path="*" element={<NotFound />} />
        <Route path="/substeps" element={<SubstepsPage />} />
      </Routes>
    </div>
  );
}
