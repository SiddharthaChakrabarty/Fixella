import React, { useRef, useState, useEffect } from "react";

export default function Share() {
  const videoRef = useRef(null);
  const [stream, setStream] = useState(null);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState(null);
  const [constraint, setConstraint] = useState({
    video: { cursor: "always" },
    audio: false,
  });

  useEffect(() => {
    // attach stream to video element
    if (videoRef.current) {
      videoRef.current.srcObject = stream || null;
    }
  }, [stream]);

  useEffect(() => {
    // stop tracks when component unmounts
    return () => {
      if (stream) stopSharing();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startSharing() {
    setError(null);
    try {
      // request display media
      const s = await navigator.mediaDevices.getDisplayMedia(constraint);
      setStream(s);
      setSharing(true);

      // when the user stops sharing using browser UI, update state
      s.getVideoTracks().forEach((track) => {
        track.onended = () => {
          // the user clicked "Stop sharing" in the browser
          setSharing(false);
          setStream(null);
        };
      });
    } catch (err) {
      setError(err.message || String(err));
    }
  }

  function stopSharing() {
    if (!stream) return;
    stream.getTracks().forEach((t) => t.stop());
    setStream(null);
    setSharing(false);
  }

  function toggleAudio() {
    setConstraint((prev) => ({ ...prev, audio: !prev.audio }));
  }

  function setCursor(mode) {
    setConstraint((prev) => ({
      ...prev,
      video: { ...(prev.video || {}), cursor: mode },
    }));
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
                muted // keep muted for preview to avoid feedback
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
                tracks: {stream.getVideoTracks().length} • Audio tracks:{" "}
                {stream.getAudioTracks().length}
              </div>
            )}
          </div>
        </div>

        <aside className="space-y-3">
          <div className="bg-white rounded-lg shadow p-3">
            <h3 className="font-medium">Options</h3>
            <div className="mt-2 space-y-2 text-sm">
              <label className="flex items-center justify-between">
                <span>Capture audio</span>
                <input
                  type="checkbox"
                  checked={constraint.audio}
                  onChange={toggleAudio}
                />
              </label>

              <div>
                <div className="text-xs text-slate-500 mb-1">Cursor</div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setCursor("always")}
                    className={`px-2 py-1 rounded ${
                      constraint.video?.cursor === "always"
                        ? "bg-sky-600 text-white"
                        : "bg-slate-100"
                    }`}
                  >
                    Always
                  </button>
                  <button
                    onClick={() => setCursor("motion")}
                    className={`px-2 py-1 rounded ${
                      constraint.video?.cursor === "motion"
                        ? "bg-sky-600 text-white"
                        : "bg-slate-100"
                    }`}
                  >
                    Motion
                  </button>
                  <button
                    onClick={() => setCursor("never")}
                    className={`px-2 py-1 rounded ${
                      constraint.video?.cursor === "never"
                        ? "bg-sky-600 text-white"
                        : "bg-slate-100"
                    }`}
                  >
                    Never
                  </button>
                </div>
              </div>

              <div className="pt-2 border-t border-slate-100">
                <div className="text-xs text-slate-500">Stream controls</div>
                <div className="mt-2 text-sm space-y-1">
                  <button
                    className="w-full py-2 rounded bg-slate-100"
                    onClick={() => {
                      if (!stream) return;
                      stream
                        .getVideoTracks()
                        .forEach((t) => (t.enabled = !t.enabled));
                    }}
                  >
                    Toggle Video Track
                  </button>

                  <button
                    className="w-full py-2 rounded bg-slate-100"
                    onClick={() => {
                      if (!stream) return;
                      stream
                        .getAudioTracks()
                        .forEach((t) => (t.enabled = !t.enabled));
                    }}
                  >
                    Toggle Audio Track
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-3 text-sm">
            <h3 className="font-medium">Quick tips</h3>
            <ul className="mt-2 space-y-1 text-slate-600">
              <li>- Use a single monitor for simpler capture selection.</li>
              <li>- Browser UI will allow sharing a tab, window, or screen.</li>
              <li>- Audio capture depends on the browser and OS.</li>
            </ul>
          </div>
        </aside>
      </div>
    </div>
  );
}
