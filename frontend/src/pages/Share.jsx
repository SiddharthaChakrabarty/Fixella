// SharePage.jsx (fixed: avoid stale activeId in interval by using a ref)
import React, { useRef, useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { io } from "socket.io-client";

/**
 * SharePage
 * location.state expected: { step, ticket, substeps: [ { id, title, step, whereToGo, commands, notes } ] }
 */
export function SharePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { step, ticket, substeps: initialSubsteps } = location.state || {};

  const [substeps, setSubsteps] = useState(() =>
    (initialSubsteps || []).map((s) => ({ ...s, done: !!s.done }))
  );

  // Initialize activeId to the first incomplete substep (if any).
  const firstId = (initialSubsteps && initialSubsteps.length)
    ? initialSubsteps[0].id
    : null;
  const [activeId, setActiveId] = useState(firstId);

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

        {/* info banner */}
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
          {/* Left column: video + controls */}
          <div className="md:col-span-2">
            <ScreenShare
              step={step}
              ticket={ticket}
              substeps={substeps}
              activeId={activeId}
              setActiveId={setActiveId}
              setSubsteps={setSubsteps}
            />
          </div>

          {/* Right column: substeps list + tips */}
          <aside className="space-y-4">
            <div className="bg-white dark:bg-slate-800 rounded-xl p-4 shadow-sm max-h-[60vh] overflow-auto">
              <h3 className="font-medium text-sm text-slate-700 dark:text-slate-200 mb-3">Substeps</h3>

              {substeps.length === 0 && <div className="text-sm text-slate-500">No substeps available.</div>}

              <ul className="space-y-2">
                {substeps.map((s) => {
                  const isActive = String(activeId) === String(s.id);
                  return (
                    <li
                      key={s.id}
                      className={`p-3 rounded-lg border ${isActive ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20" : "border-slate-100 dark:border-slate-700"} cursor-pointer`}
                      onClick={() => {
                        // allow user to manually focus a substep (optional)
                        setActiveId(s.id);
                      }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1">
                          <div className="text-sm font-medium">{s.title || `Step ${s.id}`}</div>
                          <div className="text-xs text-slate-500 mt-1">{s.step}</div>
                        </div>

                        <div className="flex flex-col items-end gap-2">
                          <label className="inline-flex items-center gap-2 text-xs">
                            <input
                              type="checkbox"
                              checked={!!s.done}
                              onChange={(e) => {
                                const checked = e.target.checked;
                                setSubsteps((prev) => {
                                  const updated = prev.map((x) =>
                                    String(x.id) === String(s.id) ? { ...x, done: checked } : x
                                  );

                                  if (checked) {
                                    // find next incomplete after this index
                                    const idx = updated.findIndex((x) => String(x.id) === String(s.id));
                                    let next = null;
                                    for (let i = idx + 1; i < updated.length; i++) {
                                      if (!updated[i].done) {
                                        next = updated[i].id;
                                        break;
                                      }
                                    }
                                    if (next === null) {
                                      // wrap: pick first incomplete (if any)
                                      const firstIncomplete = updated.find((x) => !x.done && String(x.id) !== String(s.id));
                                      next = firstIncomplete ? firstIncomplete.id : null;
                                    }
                                    setActiveId(next);
                                  }

                                  return updated;
                                });
                              }}
                            />
                            <span className="text-xs text-slate-500">Done</span>
                          </label>

                          <div className="text-xs text-slate-400">Select</div>
                        </div>
                      </div>

                      {s.whereToGo && <div className="text-xs text-slate-400 mt-2">Where: {s.whereToGo}</div>}
                    </li>
                  );
                })}
              </ul>
            </div>

            <div className="bg-white dark:bg-slate-800 rounded-xl p-4 shadow-sm">
              <h3 className="font-medium text-sm text-slate-700 dark:text-slate-200 mb-2">Quick tips</h3>
              <ul className="text-sm text-slate-600 dark:text-slate-300 space-y-2">
                <li>– The app automatically sends the current substep context with each snapshot.</li>
                <li>– When the server confirms a substep is complete, it will be auto-checked and we’ll advance to the next one for you.</li>
                <li>– You can still manually check a step to mark it done and advance.</li>
              </ul>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

/**
 * ScreenShare component (internal to SharePage)
 */
function ScreenShare({ step, ticket, substeps, activeId, setActiveId, setSubsteps }) {
  const videoRef = useRef(null);
  const socketRef = useRef(null);
  const intervalRef = useRef(null);

  const [stream, setStream] = useState(null);
  const [sharing, setSharing] = useState(false);
  const [socketConnected, setSocketConnected] = useState(false);
  const [ssError, setSsError] = useState("");

  // NEW: a ref that always holds the latest activeId (fixes stale closure)
  const activeIdRef = useRef(activeId);
  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  useEffect(() => {
    // attach videoRef to the rendered <video> element once mounted
    const videoEl = document.querySelector("#share-video");
    if (videoEl) videoRef.current = videoEl;
  }, []);

  useEffect(() => {
    if (videoRef.current) {
      try {
        videoRef.current.srcObject = stream || null;
      } catch (e) {
        // ignore attach errors
      }
    }
  }, [stream]);

  useEffect(() => {
    // cleanup on unmount
    return () => {
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

      if (!socketRef.current) {
        const token = localStorage.getItem("token");
        socketRef.current = io("ws://localhost:5001", {
          transports: ["websocket"],
          auth: token ? { token } : {},
        });

        socketRef.current.on("connect", () => {
          setSocketConnected(true);

          // immediately send one snapshot for the current active substep,
          // then start periodic snapshots every 10s.
          sendSnapshot();
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

        // Listen for snapshot acknowledgements from the server and mark substeps done only on YES.
        socketRef.current.on("snapshot_ack", (payload) => {
          try {
            const id = payload?.substep_id;
            const decision = (payload?.decision || "").toUpperCase();

            if (id !== null && id !== undefined && decision === "YES") {
              // Mark this substep done and advance to the next incomplete substep.
              setSubsteps((prev) => {
                const updated = prev.map((s) => (String(s.id) === String(id) ? { ...s, done: true } : s));

                // find index of current substep
                const idx = updated.findIndex((s) => String(s.id) === String(id));
                let next = null;
                if (idx >= 0) {
                  for (let i = idx + 1; i < updated.length; i++) {
                    if (!updated[i].done) {
                      next = updated[i].id;
                      break;
                    }
                  }
                }
                if (next === null) {
                  // wrap: find first incomplete
                  const firstIncomplete = updated.find((s) => !s.done && String(s.id) !== String(id));
                  next = firstIncomplete ? firstIncomplete.id : null;
                }

                // update activeId to next (if any)
                setActiveId(next);
                // also update ref immediately so the interval uses the new value
                activeIdRef.current = next;

                // If there are no more incomplete steps, stop the periodic snapshots
                if (next === null && intervalRef.current) {
                  clearInterval(intervalRef.current);
                  intervalRef.current = null;
                }

                return updated;
              });

              // Immediately request a new snapshot for the new active substep (if any).
              // Small delay to allow state to settle; we also read the ref inside sendSnapshot.
              setTimeout(() => {
                if (activeIdRef.current != null && socketRef.current && socketRef.current.connected) {
                  sendSnapshot();
                }
              }, 200);
            } else {
              // decision != YES: do nothing special
              console.log("snapshot_ack (NO or undecided):", payload);
            }
          } catch (e) {
            console.error("Error handling snapshot_ack:", e);
          }
        });
      }

      // attach video element
      if (videoRef.current) {
        try {
          videoRef.current.srcObject = s;
        } catch (e) { }
      }

      // stop sharing when browser UI ends it
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

  function buildSubstepContext(sub) {
    // Format: Title, step, whereToGo, commands, notes (each on separate lines)
    if (!sub) return "";
    const parts = [];
    if (sub.title) parts.push(`${sub.title}`);
    if (sub.step) parts.push(`${sub.step}`);
    if (sub.whereToGo) parts.push(`Where: ${sub.whereToGo}`);
    if (sub.commands && sub.commands.length) parts.push(`Commands: ${sub.commands.join(" ; ")}`);
    if (sub.notes) parts.push(`Notes: ${sub.notes}`);
    return parts.join("\n");
  }

  function getActiveContextFromRef() {
    const active = (substeps || []).find((s) => String(s.id) === String(activeIdRef.current));
    if (active) return buildSubstepContext(active);
    return step || "";
  }

  function sendSnapshot() {
    // Use the ref for activeId so interval doesn't use stale closure
    const curActiveId = activeIdRef.current;

    if (curActiveId == null) {
      // nothing to check
      return;
    }
    if (!videoRef.current || !socketRef.current || socketRef.current.disconnected) return;
    const video = videoRef.current;
    if (!video.videoWidth || !video.videoHeight) return;

    // scale for bandwidth (optional)
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
          const contextText = getActiveContextFromRef();
          // include activeIdRef explicitly so backend can ack the correct substep
          socketRef.current.emit("snapshot", {
            image: reader.result,
            ticket_suggestion: contextText,
            active_id: curActiveId,
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
    <div className="bg-white dark:bg-slate-800 rounded-xl shadow p-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="text-sm font-medium text-slate-700 dark:text-slate-200">Share your screen</div>
          <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">Share to capture or stream your screen for troubleshooting.</div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={startSharing}
            disabled={sharing}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm shadow-md disabled:opacity-50"
          >
            Start
          </button>
          <button
            onClick={stopSharing}
            disabled={!sharing}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-sm dark:bg-slate-700 dark:hover:bg-slate-600 disabled:opacity-50"
          >
            Stop
          </button>
        </div>
      </div>

      <div className="border border-slate-100 dark:border-slate-700 rounded-lg overflow-hidden bg-black">
        <video id="share-video" ref={videoRef} autoPlay playsInline muted className="w-full h-72 md:h-96 object-contain bg-black" />
      </div>

      <div className="mt-4 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              // immediate snapshot + emit with active substep content
              if (sharing) sendSnapshot();
              else {
                downloadSnapshot();
              }
            }}
            disabled={!stream && !sharing && !videoRef.current?.videoWidth}
            className="px-3 py-2 rounded-md bg-emerald-500 hover:bg-emerald-600 text-white text-sm shadow-sm disabled:opacity-50"
          >
            Snapshot
          </button>

          <div className="text-sm text-slate-500">{sharing ? (socketConnected ? "Sharing • connected" : "Sharing • connecting...") : "Not sharing"}</div>
        </div>

        <div className="text-xs text-slate-400">
          Selected context: <span className="font-medium">{substeps.find(s => String(s.id) === String(activeId))?.title || step || "None"}</span>
        </div>
      </div>

      {ssError && <div className="mt-3 text-sm text-red-600">{ssError}</div>}

      {stream && (
        <div className="mt-3 text-xs text-slate-500">
          <strong>Tracks:</strong> {stream.getTracks().length} • Video tracks: {stream.getVideoTracks().length}
        </div>
      )}
    </div>
  );
}

export default SharePage;
