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
    <div className="min-h-screen p-8 bg-gray-50 dark:bg-[#0f1724] text-slate-900 dark:text-slate-100">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-2 px-3 py-1 rounded border mb-4"
      >
        <ArrowLeft /> Back
      </button>

      <h2 className="text-2xl font-semibold mb-2">Screen Share</h2>
      <div className="mb-6 p-4 bg-white dark:bg-slate-800 rounded-lg">
        <div className="text-lg font-medium">Sharing for:</div>
        <div className="text-sm text-slate-500 mt-1">{step}</div>
        {ticket && (
          <div className="text-sm text-slate-500 mt-1">
            Context: {ticket.subject || ticket.displayId || ticket.ticketId} — requester: {ticket.requesterName || "N/A"}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-2">
          <div className="bg-white rounded-lg shadow p-3">
            <div className="border border-slate-100 rounded overflow-hidden">
              <ScreenShare ticketSuggestion={step} />
            </div>
          </div>
        </div>

        <aside className="space-y-3">
          <div className="bg-white rounded-lg shadow p-3 text-sm">
            <h3 className="font-medium">Quick tips</h3>
            <ul className="mt-2 space-y-1 text-slate-600 dark:text-slate-300">
              <li>- Choose a single window for privacy.</li>
              <li>- Close unrelated tabs to avoid accidental sharing.</li>
              <li>- Use Snapshot to save a local image while sharing.</li>
            </ul>
          </div>
        </aside>
      </div>
    </div>
  );
}

/**
 * ScreenShare component
 * - Starts/stops display capture
 * - Shows preview video
 * - Sends periodic snapshots to a socket.io server
 * - Allows manual snapshot download
 */
function ScreenShare({ ticketSuggestion }) {
  const videoRef = useRef(null);
  const socketRef = useRef(null);
  const intervalRef = useRef(null);

  const [stream, setStream] = useState(null);
  const [sharing, setSharing] = useState(false);
  const [ssError, setSsError] = useState("");
  const [socketConnected, setSocketConnected] = useState(false);

  useEffect(() => {
    // attach stream to video element
    if (videoRef.current) {
      videoRef.current.srcObject = stream || null;
    }
  }, [stream]);

  useEffect(() => {
    return () => {
      // cleanup on unmount
      stopSharing();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startSharing() {
    setSsError("");
    try {
      const s = await navigator.mediaDevices.getDisplayMedia({ video: true });
      setStream(s);
      setSharing(true);

      // connect socket.io
      if (!socketRef.current) {
        // update this URL if your websocket server is different
        socketRef.current = io("ws://localhost:5001", { transports: ["websocket"] });

        socketRef.current.on("connect", () => {
          setSocketConnected(true);
          // begin periodic snapshots
          if (intervalRef.current) clearInterval(intervalRef.current);
          intervalRef.current = setInterval(() => {
            sendSnapshot();
          }, 10000); // every 10s
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
    if (video.videoWidth === 0 || video.videoHeight === 0) return;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob((blob) => {
      if (!blob) return;
      const reader = new FileReader();
      reader.onloadend = () => {
        try {
          socketRef.current.emit("snapshot", {
            image: reader.result,
            ticket_suggestion: ticketSuggestion || "",
            timestamp: new Date().toISOString(),
          });
        } catch (e) {
          console.error("Failed to emit snapshot", e);
        }
      };
      reader.readAsDataURL(blob);
    }, "image/png");
  }

  function downloadSnapshot() {
    if (!videoRef.current) return;
    const video = videoRef.current;
    if (video.videoWidth === 0 || video.videoHeight === 0) return;

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
      a.download = "screenshot.png";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    });
  }

  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <div className="text-sm font-medium">Share your screen</div>
          <div className="text-xs text-slate-500">Share to capture or stream your screen for troubleshooting.</div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={startSharing}
            disabled={sharing}
            className="px-3 py-2 rounded-md bg-indigo-600 text-white shadow hover:opacity-95 disabled:opacity-50 text-sm"
          >
            Start
          </button>
          <button
            onClick={stopSharing}
            disabled={!sharing}
            className="px-3 py-2 rounded-md bg-slate-100 hover:bg-slate-200 disabled:opacity-50 text-sm"
          >
            Stop
          </button>
        </div>
      </div>

      <div className="bg-slate-50 dark:bg-slate-800 rounded-lg overflow-hidden border border-slate-100 dark:border-slate-700">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="w-full h-44 md:h-56 object-contain bg-black"
        />
      </div>

      <div className="flex items-center gap-2 mt-3">
        <button
          onClick={downloadSnapshot}
          disabled={!stream}
          className="px-3 py-2 rounded bg-emerald-500 text-white disabled:opacity-50 text-sm"
        >
          Snapshot
        </button>
        <div className="text-sm text-slate-500">
          {sharing ? (
            <span>Sharing {socketConnected ? "• connected" : "• connecting..."}</span>
          ) : (
            <span>Not sharing</span>
          )}
        </div>
      </div>

      {ssError && <div className="text-sm text-red-600 mt-2">{ssError}</div>}

      {stream && (
        <div className="text-xs text-slate-500 mt-2">
          <strong>Tracks:</strong> {stream.getTracks().length} • Video tracks: {stream.getVideoTracks().length}
        </div>
      )}
    </div>
  );
}

export default SharePage;
