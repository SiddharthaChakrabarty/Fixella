// SharePage.jsx
import React, { useRef, useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { io } from "socket.io-client";

export function SharePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { step, ticket } = location.state || {};

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-[#0f1724] text-slate-900 dark:text-slate-100 p-8">
      <div className="max-w-6xl mx-auto">
        <button
          onClick={() => navigate(-1)}
          className="inline-flex items-center gap-2 px-3 py-1 rounded border border-slate-700/30 dark:border-slate-600 text-sm mb-6 bg-transparent"
        >
          <ArrowLeft /> Back
        </button>

        <h1 className="text-3xl font-semibold mb-4">Screen Share</h1>

        {/* Info banner */}
        <div className="mb-6 rounded-xl p-4 bg-slate-800/60 dark:bg-slate-800 text-slate-200 shadow-sm">
          <div className="text-lg font-medium">Sharing for:</div>
          <div className="mt-2 text-sm text-slate-300">{step || "—"}</div>
          {ticket && (
            <div className="mt-1 text-sm text-slate-400">
              Context: {ticket.subject || ticket.displayId || ticket.ticketId} — requester: {ticket.requesterName || "N/A"}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Left column: video card */}
          <div className="md:col-span-2">
            <div className="bg-white dark:bg-slate-800 rounded-xl shadow p-4">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="text-sm font-medium text-slate-700 dark:text-slate-200">Share your screen</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                    Share to capture or stream your screen for troubleshooting.
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {/* Start / Stop Buttons */}
                  {/* Buttons style consistent with app: indigo for primary, subtle for secondary */}
                  <button
                    id="start-share-btn"
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm shadow-md"
                  >
                    Start
                  </button>
                  <button
                    id="stop-share-btn"
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-sm dark:bg-slate-700 dark:hover:bg-slate-600"
                  >
                    Stop
                  </button>
                </div>
              </div>

              {/* video preview */}
              <div className="border border-slate-100 dark:border-slate-700 rounded-lg overflow-hidden bg-black">
                <video
                  id="share-video"
                  ref={(el) => {
                    // intentionally left blank: child ScreenShare component will bind videoRef
                  }}
                  autoPlay
                  playsInline
                  muted
                  className="w-full h-72 md:h-96 object-contain bg-black"
                />
              </div>

              {/* controls area */}
              <div className="mt-4 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <button
                    id="snapshot-btn"
                    className="px-3 py-2 rounded-md bg-emerald-500 hover:bg-emerald-600 text-white text-sm shadow-sm"
                  >
                    Snapshot
                  </button>
                  <div className="text-sm text-slate-500">Not sharing</div>
                </div>

                <div className="text-xs text-slate-400">
                  Tip: Use the Snapshot button to download a local screenshot while sharing.
                </div>
              </div>
            </div>
          </div>

          {/* Right column: tips & connection status */}
          <aside className="space-y-4">
            <div className="bg-white dark:bg-slate-800 rounded-xl p-4 shadow-sm">
              <h3 className="font-medium text-sm text-slate-700 dark:text-slate-200 mb-2">Quick tips</h3>
              <ul className="text-sm text-slate-600 dark:text-slate-300 space-y-2">
                <li>– Choose a single window for privacy.</li>
                <li>– Close unrelated tabs to avoid accidental sharing.</li>
                <li>– Use Snapshot to save a local image while sharing.</li>
              </ul>
            </div>

            <div className="bg-white dark:bg-slate-800 rounded-xl p-4 shadow-sm">
              <h3 className="font-medium text-sm text-slate-700 dark:text-slate-200 mb-2">Connection</h3>
              <div className="text-sm text-slate-600 dark:text-slate-300">Status: <span className="inline-block ml-2 px-2 py-0.5 rounded bg-emerald-100 text-emerald-700 text-xs">Disconnected</span></div>
              <div className="text-xs text-slate-500 mt-3">Snapshots will be sent to the troubleshooting channel when connected.</div>
            </div>
          </aside>
        </div>
      </div>

      {/* Embed the interactive ScreenShare implementation at the bottom so it can manage videoRef and socket */}
      <ScreenShareBridge />
    </div>
  );
}

/**
 * ScreenShareBridge
 * - wires the DOM controls in the card above to the actual sharing logic.
 * - keeps the UI markup (in SharePage) tidy while still wiring to the same behavior.
 *
 * This component:
 *  - binds to #share-video element
 *  - listens to clicks on start/stop/snapshot buttons
 *  - manages socket connection and periodic snapshot sends
 */
function ScreenShareBridge() {
  const videoRef = useRef(null);
  const socketRef = useRef(null);
  const intervalRef = useRef(null);
  const [stream, setStream] = useState(null);
  const [sharing, setSharing] = useState(false);
  const [socketConnected, setSocketConnected] = useState(false);
  const [ssError, setSsError] = useState("");

  useEffect(() => {
    // find the video element placed in SharePage markup and attach ref
    const video = document.getElementById("share-video");
    if (video) videoRef.current = video;

    // wire buttons
    const startBtn = document.getElementById("start-share-btn");
    const stopBtn = document.getElementById("stop-share-btn");
    const snapshotBtn = document.getElementById("snapshot-btn");

    if (startBtn) startBtn.addEventListener("click", startSharing);
    if (stopBtn) stopBtn.addEventListener("click", stopSharing);
    if (snapshotBtn) snapshotBtn.addEventListener("click", downloadSnapshot);

    return () => {
      if (startBtn) startBtn.removeEventListener("click", startSharing);
      if (stopBtn) stopBtn.removeEventListener("click", stopSharing);
      if (snapshotBtn) snapshotBtn.removeEventListener("click", downloadSnapshot);
      stopSharing();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (videoRef.current) {
      try {
        videoRef.current.srcObject = stream || null;
      } catch (e) {
        // some browsers may throw if attaching null quickly; ignore
      }
    }
  }, [stream]);

  async function startSharing() {
    setSsError("");
    try {
      const s = await navigator.mediaDevices.getDisplayMedia({ video: true });
      setStream(s);
      setSharing(true);

      if (!socketRef.current) {
        // include auth token if needed: { auth: { token: localStorage.getItem('token') } }
        socketRef.current = io("ws://localhost:5001", { transports: ["websocket"], auth: {} });

        socketRef.current.on("connect", () => {
          setSocketConnected(true);
          if (intervalRef.current) clearInterval(intervalRef.current);
          intervalRef.current = setInterval(() => sendSnapshot(), 10000);
        });

        socketRef.current.on("disconnect", () => {
          setSocketConnected(false);
        });

        socketRef.current.on("connect_error", (err) => {
          console.error("Socket connect error", err);
          setSsError("WebSocket connection error");
        });
      }

      // stop sharing when the browser UI stops it
      s.getVideoTracks().forEach((track) => {
        track.onended = () => {
          stopSharing();
        };
      });
    } catch (err) {
      console.error(err);
      setSsError(err?.message || String(err));
    }
  }

  function stopSharing() {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (socketRef.current) {
      try {
        socketRef.current.disconnect();
      } catch (e) {
        // ignore
      }
      socketRef.current = null;
      setSocketConnected(false);
    }
    if (stream) {
      try {
        stream.getTracks().forEach((t) => t.stop());
      } catch (e) {
        // ignore
      }
      setStream(null);
    }
    setSharing(false);
  }

  function sendSnapshot() {
    if (!videoRef.current || !socketRef.current || socketRef.current.disconnected) return;
    const video = videoRef.current;
    if (!video.videoWidth || !video.videoHeight) return;

    // scale snapshot to reduce size (optional): set desired width (e.g., 1280)
    const maxWidth = 1280;
    const scale = Math.min(1, maxWidth / video.videoWidth);
    const w = Math.round(video.videoWidth * scale);
    const h = Math.round(video.videoHeight * scale);

    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, w, h);

    canvas.toBlob((blob) => {
      if (!blob) return;
      const reader = new FileReader();
      reader.onloadend = () => {
        try {
          socketRef.current.emit("snapshot", {
            image: reader.result,
            ticket_suggestion: document.querySelector(".text-lg")?.textContent || "",
            timestamp: new Date().toISOString(),
          });
        } catch (e) {
          console.error("Failed to emit snapshot", e);
        }
      };
      reader.readAsDataURL(blob);
    }, "image/jpeg", 0.7);
  }

  function downloadSnapshot() {
    if (!videoRef.current) return;
    const video = videoRef.current;
    if (!video.videoWidth || !video.videoHeight) return;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "screenshot.jpg";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }, "image/jpeg", 0.9);
  }

  return (
    <div className="sr-only" aria-hidden>
      {/* invisible helper element, UI is rendered in parent card. This component manages behavior only. */}
      <div>{ssError}</div>
    </div>
  );
}

export default SharePage;
