import React from "react";
import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="text-center py-20">
      <h2 className="text-3xl font-bold">404</h2>
      <p className="mt-2 text-slate-600">Page not found.</p>
      <Link to="/" className="mt-4 inline-block text-sky-600">
        Go home
      </Link>
    </div>
  );
}
