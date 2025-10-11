import React, { useEffect, useState } from "react";
import { Zap } from "lucide-react";
import { features } from "../utils/Features";

export default function HomePage() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  useEffect(() => {
    // Check if token exists in localStorage
    const token = localStorage.getItem("token");
    setIsLoggedIn(!!token);
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("token"); // remove JWT token
    setIsLoggedIn(false);
    window.location.href = "/"; // redirect to homepage
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-[#0f1724] text-slate-900 dark:text-slate-100 transition-colors duration-300">
      <header className="max-w-7xl mx-auto px-6 py-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-indigo-500 to-sky-400 flex items-center justify-center shadow-lg">
            <Zap className="text-white w-6 h-6" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Fixella</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 -mt-0.5">
              AI-driven ticket resolution & escalation prevention
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {isLoggedIn ? (
            <button
              onClick={handleLogout}
              className="px-4 py-2 text-sm font-medium bg-red-600 text-white rounded-md hover:bg-red-700 transition"
            >
              Logout
            </button>
          ) : (
            <>
              <a
                href="/login"
                className="px-4 py-2 text-sm font-medium text-indigo-600 dark:text-indigo-300 hover:underline"
              >
                Login
              </a>
              <a
                href="/signup"
                className="px-4 py-2 text-sm font-medium bg-indigo-600 text-white rounded-md hover:bg-indigo-700 transition"
              >
                Sign Up
              </a>
            </>
          )}
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 pb-20">
        {/* Hero */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-center mt-6">
          <div>
            <h2 className="text-4xl sm:text-5xl font-extrabold leading-tight">
              Faster resolutions. Fewer escalations. Smarter billing.
            </h2>
            <p className="mt-4 text-slate-600 dark:text-slate-300 max-w-xl">
              Fixella connects to SuperOps and your toolchain to turn ticket
              data into actionable intelligence — powered by Bedrock AI, a
              tailored ML stack, and secure remote guidance.
            </p>

            <div className="mt-6 flex flex-wrap gap-3">
              <a
                className="inline-flex items-center gap-2 px-5 py-3 rounded-md bg-white dark:bg-slate-800 shadow hover:scale-[1.01] transition"
                href="#features"
              >
                Explore features
              </a>
            </div>

            <div className="mt-8 grid grid-cols-2 gap-4 max-w-md">
              <div className="p-4 bg-white dark:bg-slate-800 rounded-lg shadow-sm">
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  Avg. time to resolution
                </div>
                <div className="text-2xl font-bold">22m</div>
              </div>
              <div className="p-4 bg-white dark:bg-slate-800 rounded-lg shadow-sm">
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  Escalations reduced
                </div>
                <div className="text-2xl font-bold">48%</div>
              </div>
            </div>
          </div>

          <div className="relative">
            <div className="w-full rounded-2xl overflow-hidden shadow-2xl bg-gradient-to-br from-white to-slate-50 dark:from-slate-800 dark:to-slate-900">
              <div className="h-64 sm:h-80 lg:h-96 flex items-center justify-center">
                <svg
                  width="320"
                  height="200"
                  viewBox="0 0 320 200"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  className="opacity-90"
                >
                  <rect
                    x="0"
                    y="0"
                    width="320"
                    height="200"
                    rx="12"
                    fill="#E9F0FF"
                  />
                  <rect
                    x="18"
                    y="18"
                    width="284"
                    height="28"
                    rx="6"
                    fill="#fff"
                  />
                  <rect
                    x="18"
                    y="56"
                    width="284"
                    height="110"
                    rx="8"
                    fill="#fff"
                  />
                  <circle cx="44" cy="32" r="6" fill="#A3BFFA" />
                </svg>
              </div>
            </div>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="mt-16">
          <h3 className="text-2xl font-semibold">Core features</h3>
          <p className="mt-2 text-slate-600 dark:text-slate-300 max-w-2xl">
            A concise platform with built-in AI, telemetry, and secure guidance
            so L1 teams can resolve more, escalate less, and bill with
            confidence.
          </p>

          <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((f) => (
              <article
                key={f.title}
                className="group bg-white dark:bg-slate-800 p-5 rounded-2xl shadow hover:shadow-lg transition"
              >
                <div className="flex items-start gap-4">
                  <div className="p-3 rounded-lg bg-indigo-50 dark:bg-indigo-900/30">
                    <f.icon className="w-6 h-6 text-indigo-600 dark:text-indigo-300" />
                  </div>
                  <div>
                    <div className="text-xs text-indigo-600 dark:text-indigo-300 font-medium">
                      {f.tag}
                    </div>
                    <h4 className="mt-2 font-semibold">{f.title}</h4>
                    <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                      {f.desc}
                    </p>

                    <ul className="mt-3 text-sm text-slate-500 dark:text-slate-400 space-y-1">
                      {f.bullets.map((b) => (
                        <li key={b} className="flex items-center gap-2">
                          <span className="inline-block w-3 h-3 rounded-full bg-indigo-500/80" />
                          {b}
                        </li>
                      ))}
                    </ul>

                    <div className="mt-4 flex items-center gap-3">
                      <a
                        href="#contact"
                        className="text-sm font-medium text-indigo-600 dark:text-indigo-300"
                      >
                        Request integration
                      </a>
                      <span className="text-xs text-slate-400">•</span>
                      <a className="text-sm text-slate-500 dark:text-slate-400">
                        Learn more
                      </a>
                    </div>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>

        {/* How it works */}
        <section className="mt-16 grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
          <div className="lg:col-span-2">
            <h3 className="text-2xl font-semibold">How it works</h3>
            <p className="mt-2 text-slate-600 dark:text-slate-300 max-w-2xl">
              From SuperOps webhook to closed ticket — Fixella automates data
              collection, reasons over ticket history with AI, and produces
              actionable steps for technicians.
            </p>

            <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="p-4 bg-white dark:bg-slate-800 rounded-lg shadow-sm">
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  1
                </div>
                <h5 className="font-medium mt-2">Collect</h5>
                <p className="text-sm mt-1 text-slate-500 dark:text-slate-400">
                  Webhook captures ticket metadata & history.
                </p>
              </div>
              <div className="p-4 bg-white dark:bg-slate-800 rounded-lg shadow-sm">
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  2
                </div>
                <h5 className="font-medium mt-2">Analyze</h5>
                <p className="text-sm mt-1 text-slate-500 dark:text-slate-400">
                  AI creates embeddings, knowledge graph & scores.
                </p>
              </div>
              <div className="p-4 bg-white dark:bg-slate-800 rounded-lg shadow-sm">
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  3
                </div>
                <h5 className="font-medium mt-2">Act</h5>
                <p className="text-sm mt-1 text-slate-500 dark:text-slate-400">
                  Technician follows guided steps; time auto-recorded.
                </p>
              </div>
            </div>
          </div>

          <aside className="p-6 bg-gradient-to-br from-white to-slate-50 dark:from-slate-900 dark:via-slate-900 dark:to-slate-800 rounded-2xl shadow-lg">
            <div className="text-sm text-slate-500 dark:text-slate-400">
              Integration
            </div>
            <h4 className="mt-2 font-semibold">Connects to your stack</h4>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              SuperOps, ticketing API, Bedrock, secure WebRTC for screen
              sharing, and billing exports.
            </p>

            <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-slate-500 dark:text-slate-400">
              <div className="p-2 bg-white dark:bg-slate-800 rounded">
                SuperOps
              </div>
              <div className="p-2 bg-white dark:bg-slate-800 rounded">
                Amazon Bedrock
              </div>
              <div className="p-2 bg-white dark:bg-slate-800 rounded">
                Webhooks
              </div>
              <div className="p-2 bg-white dark:bg-slate-800 rounded">
                WebRTC
              </div>
            </div>
          </aside>
        </section>

        {/* Footer */}
        <footer
          id="contact"
          className="mt-12 text-sm text-slate-600 dark:text-slate-300"
        >
          <div className="mt-6 text-slate-400">
            © {new Date().getFullYear()} Fixella — Built for efficient support
            teams
          </div>
        </footer>
      </main>
    </div>
  );
}
