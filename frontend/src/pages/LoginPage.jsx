import React, { useState } from "react";
import { Zap, Mail, Lock } from "lucide-react";

export function LoginPage() {
  const [formData, setFormData] = useState({ email: "", password: "" });
  const [message, setMessage] = useState("");

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage("");

    try {
      const res = await fetch("http://127.0.0.1:5000/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      });

      const data = await res.json();
      if (res.ok) {
        localStorage.setItem("token", data.token);
        setMessage("✅ Login successful! Redirecting...");
        setTimeout(() => (window.location.href = "/dashboard"), 1500);
      } else {
        setMessage(`❌ ${data.error || "Login failed"}`);
      }
    } catch (err) {
      setMessage("⚠️ Server error. Please try again later.");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-[#0f1724] text-slate-900 dark:text-slate-100">
      <div className="w-full max-w-md bg-white dark:bg-slate-800 rounded-2xl shadow-xl p-8">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-sky-400 flex items-center justify-center shadow-md">
            <Zap className="text-white w-5 h-5" />
          </div>
          <h1 className="text-xl font-semibold">Fixella Login</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm mb-1">Email</label>
            <div className="flex items-center gap-2 bg-slate-50 dark:bg-slate-900 p-3 rounded-lg">
              <Mail className="w-4 h-4 text-slate-400" />
              <input
                name="email"
                type="email"
                placeholder="you@company.com"
                value={formData.email}
                onChange={handleChange}
                className="w-full bg-transparent focus:outline-none"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm mb-1">Password</label>
            <div className="flex items-center gap-2 bg-slate-50 dark:bg-slate-900 p-3 rounded-lg">
              <Lock className="w-4 h-4 text-slate-400" />
              <input
                name="password"
                type="password"
                placeholder="••••••••"
                value={formData.password}
                onChange={handleChange}
                className="w-full bg-transparent focus:outline-none"
              />
            </div>
          </div>

          <button
            type="submit"
            className="w-full mt-6 bg-indigo-600 hover:bg-indigo-700 text-white py-3 rounded-lg font-medium transition"
          >
            Login
          </button>

          {message && (
            <p className="text-center text-sm mt-3">{message}</p>
          )}
        </form>
      </div>
    </div>
  );
}
