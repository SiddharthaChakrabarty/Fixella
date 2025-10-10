import React from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home";
import Share from "./pages/Share";
import NotFound from "./pages/NotFound";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="bg-white shadow-sm">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <h1 className="text-lg font-semibold">ScreenShare — React</h1>
          <nav className="space-x-3">
            <NavLink
              to="/"
              className={({ isActive }) =>
                isActive ? "text-sky-600 font-medium" : "text-slate-600"
              }
            >
              Home
            </NavLink>
            <NavLink
              to="/share"
              className={({ isActive }) =>
                isActive ? "text-sky-600 font-medium" : "text-slate-600"
              }
            >
              Share
            </NavLink>
          </nav>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-8">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/share" element={<Share />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>

      <footer className="mt-8 py-6 text-center text-sm text-slate-500">
        Built with ❤️ • Uses the Screen Capture API
        (navigator.mediaDevices.getDisplayMedia)
      </footer>
    </div>
  );
}
