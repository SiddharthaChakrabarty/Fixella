import React from "react";
import { Link } from "react-router-dom";

export default function Home() {
  return (
    <div className="prose max-w-none">
      <h2>Welcome to ScreenShare</h2>
      <p>
        This small demo shows how to implement browser screen sharing
        (getDisplayMedia) on the client side and preview the shared screen
        locally. It does not include signaling / WebRTC peer wiring — only the
        local UI and media handling. Use{" "}
        <Link to="/share" className="text-sky-600">
          Share
        </Link>{" "}
        to start.
      </p>

      <h3>Notes</h3>
      <ul>
        <li>Screen sharing requires a secure context (HTTPS) or localhost.</li>
        <li>
          Browsers will prompt the user to choose which screen/window/tab to
          share.
        </li>
        <li>Audio capture from the system may be browser-dependent.</li>
      </ul>
    </div>
  );
}
