// DashboardPage.jsx
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { User, Clipboard, Calendar, AlertCircle, Zap, X } from "lucide-react";

export function DashboardPage() {
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // AI modal state (for recommended resolution steps)
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState("");
  const [aiResult, setAiResult] = useState(null);
  const [showAiModal, setShowAiModal] = useState(false);

  const [showChat, setShowChat] = useState(false);
  const [chatMessages, setChatMessages] = useState([]); // {sender: "user"|"ai", text: string}
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  const navigate = useNavigate();

  useEffect(() => {
    const fetchTickets = async () => {
      const token = localStorage.getItem("token");
      if (!token) {
        window.location.href = "/login";
        return;
      }

      try {
        const res = await fetch("http://127.0.0.1:5000/tickets", {
          headers: { Authorization: token },
        });
        const data = await res.json();

        if (res.ok) {
          setTickets(data.tickets);
        } else {
          setError(data.error || "Failed to fetch tickets");
        }
      } catch (err) {
        setError("Server error. Please try again later.");
      } finally {
        setLoading(false);
      }
    };

    fetchTickets();
  }, []);

  const handleAskAI = async (ticket) => {
    const token = localStorage.getItem("token");
    if (!token) {
      window.location.href = "/login";
      return;
    }

    const payload = {
      ticket: {
        ticketId: ticket.ticketId,
        displayId: ticket.displayId,
        subject: ticket.title,
        requesterName: ticket.requesterName,
        ticketType: ticket.ticketType,
        priority: ticket.priority,
        description: ticket.description || "",
      },
    };

    setAiLoading(true);
    setAiError("");
    setAiResult(null);
    setShowAiModal(true);

    try {
      const res = await fetch("http://127.0.0.1:5000/ask_ai", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: token,
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.ok && data.result) {
        setAiResult(data.result);
      } else {
        setAiError(
          data.error || data.details || "Agent failed to return suggestions"
        );
      }
    } catch (err) {
      setAiError("AI request failed. Try again.");
    } finally {
      setAiLoading(false);
    }
  };

  // When user clicks Try this step, navigate to Substeps page and pass state
  const goToSubsteps = (stepText, ticket) => {
    // Build minimal ticket object for context
    const ticketForCall = {
      ticketId: ticket.ticketId,
      displayId: ticket.displayId,
      subject: ticket.title,
      requesterName: ticket.requesterName,
      priority: ticket.priority,
      description: ticket.description || "",
    };

    navigate("/substeps", { state: { step: stepText, ticket: ticketForCall } });
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-[#0f1724] text-slate-900 dark:text-slate-100 p-8">
      <h1 className="text-3xl font-bold mb-8">Your Tickets</h1>

      {loading ? (
        <p className="text-slate-500">Loading tickets...</p>
      ) : error ? (
        <p className="text-red-500">{error}</p>
      ) : tickets.length === 0 ? (
        <p className="text-slate-500">No tickets found.</p>
      ) : (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {tickets.map((ticket) => (
            <div
              key={ticket.ticketId}
              className="p-6 bg-white dark:bg-slate-800 rounded-2xl shadow-md hover:shadow-xl transition-shadow"
            >
              <div className="flex justify-between items-start mb-4">
                <h2 className="font-semibold text-xl">{ticket.title}</h2>
                <span
                  className={`text-xs px-3 py-1 rounded-full font-medium ${
                    ticket.status === "Open"
                      ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
                      : "bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-300"
                  }`}
                >
                  {ticket.status}
                </span>
              </div>

              <div className="space-y-2 mb-4 text-sm text-slate-600 dark:text-slate-300">
                <div className="flex items-center gap-2">
                  <User className="w-4 h-4 text-indigo-500" />{" "}
                  <strong>Client:</strong> {ticket.clientName}
                </div>
                <div className="flex items-center gap-2">
                  <Clipboard className="w-4 h-4 text-indigo-500" />{" "}
                  <strong>Site:</strong> {ticket.siteName}
                </div>
                <div className="flex items-center gap-2">
                  <User className="w-4 h-4 text-indigo-500" />{" "}
                  <strong>Requester:</strong> {ticket.requesterName}
                </div>
                <div className="flex items-center gap-2">
                  <User className="w-4 h-4 text-indigo-500" />{" "}
                  <strong>Technician:</strong> {ticket.technicianName}
                </div>
                <div className="flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 text-red-500" />{" "}
                  <strong>Priority:</strong> {ticket.priority || "Normal"}
                </div>
                <div className="flex items-center gap-2">
                  <Zap className="w-4 h-4 text-yellow-500" />{" "}
                  <strong>Impact:</strong> {ticket.impact || "N/A"}
                </div>
                <div className="flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-indigo-500" />{" "}
                  <strong>Created:</strong>{" "}
                  {new Date(ticket.createdAt).toLocaleString()}
                </div>
              </div>

              {ticket.status === "Open" && (
                <button
                  onClick={() => handleAskAI(ticket)}
                  className="w-full mt-2 flex justify-center items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition"
                >
                  <Zap className="w-4 h-4" /> Ask Fixella AI
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* AI Modal: shows recommended resolution steps; Try this navigates to /substeps */}
      {showAiModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-3xl bg-white dark:bg-slate-900 rounded-2xl p-6 relative max-h-[85vh] overflow-auto">
            <button
              className="absolute top-4 right-4 p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-800"
              onClick={() => {
                setShowAiModal(false);
                setAiResult(null);
                setAiError("");
              }}
            >
              <X />
            </button>

            <h3 className="text-xl font-semibold mb-3">
              AI Suggested Resolution
            </h3>

            {aiLoading ? (
              <p>Generating steps…</p>
            ) : aiError ? (
              <p className="text-red-500">{aiError}</p>
            ) : aiResult ? (
              <>
                {aiResult.recommendedSteps &&
                aiResult.recommendedSteps.length > 0 ? (
                  <ol className="list-decimal pl-5 space-y-4">
                    {aiResult.recommendedSteps.map((s, idx) => (
                      <li key={idx} className="text-sm">
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <div className="font-medium">{s.step}</div>
                            {s.supportingDisplayIds &&
                              s.supportingDisplayIds.length > 0 && (
                                <div className="text-xs text-slate-500">
                                  Supporting:{" "}
                                  {s.supportingDisplayIds.join(", ")}
                                </div>
                              )}
                            {s.notes && (
                              <div className="text-xs text-slate-500 mt-1">
                                {s.notes}
                              </div>
                            )}
                          </div>

                          <div className="flex items-center gap-2">
                            <button
                              onClick={() =>
                                goToSubsteps(s.step, {
                                  ticketId:
                                    aiResult.ticketId ||
                                    aiResult.displayId ||
                                    aiResult.ticket?.ticketId,
                                  displayId: aiResult.displayId,
                                  title: aiResult.subject,
                                  requesterName:
                                    aiResult.requester?.name ||
                                    aiResult.requesterName,
                                  priority: aiResult.priority,
                                  description:
                                    aiResult.description || aiResult.body,
                                })
                              }
                              className="text-sm px-3 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-700"
                            >
                              Try this step
                            </button>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-sm text-slate-600">
                    No recommended steps returned.
                  </p>
                )}

                {aiResult.sources && aiResult.sources.length > 0 && (
                  <div className="mt-4 text-xs text-slate-500">
                    Sources:{" "}
                    {aiResult.sources
                      .map((s) => s.displayId || s.ticketId)
                      .join(", ")}
                  </div>
                )}
              </>
            ) : (
              <p>No result yet.</p>
            )}
          </div>
        </div>
      )}
      <button
        onClick={() => setShowChat(true)}
        className="fixed bottom-6 right-6 flex items-center gap-2 px-4 py-3 rounded-full bg-indigo-600 text-white font-medium shadow-lg hover:bg-indigo-700 transition-all"
      >
        <Zap className="w-5 h-5" />
        Chat with Fixella AI
      </button>

      {/* Fixella AI Chat Modal */}
      {showChat && (
        <div className="fixed bottom-20 right-6 w-96 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden z-50">
          {/* Header */}
          <div className="flex justify-between items-center p-3 bg-indigo-600 text-white">
            <h4 className="font-semibold text-sm">Chat with Fixella AI</h4>
            <button
              onClick={() => setShowChat(false)}
              className="p-1 rounded hover:bg-indigo-500"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Chat messages area */}
          <div className="flex-1 p-3 space-y-3 overflow-y-auto max-h-80 text-sm">
            {chatMessages.length === 0 && (
              <p className="text-center text-slate-500">
                Start asking Fixella AI your questions...
              </p>
            )}
            {chatMessages.map((msg, idx) => (
              <div
                key={idx}
                className={`flex ${
                  msg.sender === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`px-3 py-2 rounded-lg max-w-[80%] ${
                    msg.sender === "user"
                      ? "bg-indigo-600 text-white"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100"
                  }`}
                >
                  {msg.text}
                </div>
              </div>
            ))}
            {chatLoading && (
              <div className="text-slate-500 text-xs text-center">
                Fixella is typing...
              </div>
            )}
          </div>

          {/* Input area */}
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (!chatInput.trim()) return;
              const userMsg = { sender: "user", text: chatInput.trim() };
              setChatMessages((prev) => [...prev, userMsg]);
              setChatInput("");
              setChatLoading(true);

              try {
                const token = localStorage.getItem("token");
                const res = await fetch("http://127.0.0.1:5000/ai/chat", {
                  method: "POST",
                  headers: {
                    "Content-Type": "application/json",
                    Authorization: token,
                  },
                  body: JSON.stringify({ question: userMsg.text }),
                });

                const data = await res.json();
                if (res.ok && data.result) {
                  const aiMsg = {
                    sender: "ai",
                    text:
                      typeof data.result === "string"
                        ? data.result
                        : data.result.answer || JSON.stringify(data.result),
                  };
                  setChatMessages((prev) => [...prev, aiMsg]);
                } else {
                  setChatMessages((prev) => [
                    ...prev,
                    {
                      sender: "ai",
                      text: data.error || "Sorry, I couldn't process that.",
                    },
                  ]);
                }
              } catch (err) {
                setChatMessages((prev) => [
                  ...prev,
                  { sender: "ai", text: "Network error. Please try again." },
                ]);
              } finally {
                setChatLoading(false);
              }
            }}
            className="flex items-center border-t border-slate-200 dark:border-slate-700 p-2"
          >
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder="Ask a question..."
              className="flex-1 px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-slate-800"
            />
            <button
              type="submit"
              disabled={chatLoading}
              className="ml-2 px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
            >
              Send
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
