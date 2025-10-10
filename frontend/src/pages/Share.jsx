import React, { useRef, useState, useEffect } from "react";
import { io } from "socket.io-client"; // <-- add this

export default function Share() {
  const videoRef = useRef(null);
  const [stream, setStream] = useState(null);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState(null);
  const socketRef = useRef(null);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = stream || null;
    }
  }, [stream]);

  useEffect(() => {
    return () => {
      stopSharing();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startSharing() {
    setError(null);
    try {
      const s = await navigator.mediaDevices.getDisplayMedia({ video: true });
      setStream(s);
      setSharing(true);

      // Use socket.io-client
      if (!socketRef.current) {
        socketRef.current = io("ws://localhost:5001", {
          transports: ["websocket"],
        });
        socketRef.current.on("connect", () => {
          intervalRef.current = setInterval(sendSnapshot, 10000);
        });
        socketRef.current.on("connect_error", () =>
          setError("WebSocket error")
        );
      }

      // Stop sharing if user ends from browser UI
      s.getVideoTracks().forEach((track) => {
        track.onended = () => {
          stopSharing();
        };
      });
    } catch (err) {
      setError(err.message || String(err));
    }
  }

  function stopSharing() {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      setStream(null);
    }
    setSharing(false);
  }

  function sendSnapshot() {
    if (
      !videoRef.current ||
      !socketRef.current ||
      socketRef.current.disconnected
    )
      return;
    const video = videoRef.current;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        socketRef.current.emit("snapshot", {
          image: reader.result,
          ticket_suggestion:
            "Open the Settings app and go to Network & Internet > Wi-Fi.",
        });
      };
      reader.readAsDataURL(blob);
    }, "image/png");
  }

  function downloadSnapshot() {
    if (!videoRef.current) return;
    const video = videoRef.current;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
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
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <div className="flex-1">
          <h2 className="text-2xl font-semibold">Screen Sharing</h2>
          <p className="text-sm text-slate-600">
            Use the controls to start/stop sharing. The browser will prompt
            which screen/window/tab to share.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={startSharing}
            disabled={sharing}
            className="px-4 py-2 rounded-md bg-sky-600 text-white shadow hover:opacity-95 disabled:opacity-50"
          >
            Start
          </button>
          <button
            onClick={stopSharing}
            disabled={!sharing}
            className="px-4 py-2 rounded-md bg-slate-200 hover:bg-slate-300 disabled:opacity-50"
          >
            Stop
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-2">
          <div className="bg-white rounded-lg shadow p-3">
            <div className="border border-slate-100 rounded overflow-hidden">
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="w-full h-72 md:h-[480px] object-contain bg-black"
              />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={downloadSnapshot}
                disabled={!stream}
                className="px-3 py-2 rounded bg-emerald-500 text-white disabled:opacity-50"
              >
                Snapshot
              </button>
              <span className="text-sm text-slate-500">
                {sharing ? "Sharing..." : "Not sharing"}
              </span>
            </div>
            {error && (
              <div className="mt-3 text-sm text-red-600">Error: {error}</div>
            )}
            {stream && (
              <div className="mt-3 text-xs text-slate-500">
                <strong>Tracks:</strong> {stream.getTracks().length} • Video
                tracks: {stream.getVideoTracks().length}
              </div>
            )}
          </div>
        </div>
        <aside className="space-y-3">
          <div className="bg-white rounded-lg shadow p-3 text-sm">
            <h3 className="font-medium">Quick tips</h3>
            <ul className="mt-2 space-y-1 text-slate-600">
              <li>- Use a single monitor for simpler capture selection.</li>
              <li>- Browser UI will allow sharing a tab, window, or screen.</li>
            </ul>
          </div>
        </aside>
      </div>
    </div>
  );
}
