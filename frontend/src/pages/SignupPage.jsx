import React, { useState } from "react";
import { Zap, Mail, Lock, User } from "lucide-react";

export function SignupPage() {
  const [showPassword, setShowPassword] = useState(false);
  const [formData, setFormData] = useState({ name: "", email: "", password: "" });
  const [message, setMessage] = useState("");

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage("");

    try {
      const res = await fetch("http://127.0.0.1:5000/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      });

      const data = await res.json();
      if (res.ok) {
        setMessage("✅ Signup successful! Redirecting to login...");
        setTimeout(() => (window.location.href = "/login"), 1500);
      } else {
        setMessage(`❌ ${data.error || "Signup failed"}`);
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
          <h1 className="text-xl font-semibold">Create your Fixella account</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm mb-1">Full Name</label>
            <div className="flex items-center gap-2 bg-slate-50 dark:bg-slate-900 p-3 rounded-lg">
              <User className="w-4 h-4 text-slate-400" />
              <input
                name="name"
                type="text"
                placeholder="John Doe"
                value={formData.name}
                onChange={handleChange}
                className="w-full bg-transparent focus:outline-none"
              />
            </div>
          </div>

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
                type={showPassword ? "text" : "password"}
                placeholder="••••••••"
                value={formData.password}
                onChange={handleChange}
                className="w-full bg-transparent focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="text-xs text-slate-400 hover:text-indigo-500"
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
          </div>

          <button
            type="submit"
            className="w-full mt-6 bg-indigo-600 hover:bg-indigo-700 text-white py-3 rounded-lg font-medium transition"
          >
            Sign Up
          </button>

          {message && (
            <p className="text-center text-sm mt-3">{message}</p>
          )}

          <p className="text-center text-sm text-slate-500 dark:text-slate-400 mt-3">
            Already have an account?{" "}
            <a href="/login" className="text-indigo-600 hover:underline">
              Login here
            </a>
          </p>
        </form>
      </div>
    </div>
  );
}
