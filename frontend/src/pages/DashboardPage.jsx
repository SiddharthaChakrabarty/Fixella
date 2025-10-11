import React, { useEffect, useState } from "react";
import { User, Clipboard, Calendar, AlertCircle, Zap } from "lucide-react";

export function DashboardPage() {
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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

  const handleAskAI = (ticket) => {
    alert(`Ask Fixella AI for ticket "${ticket.subject}"`);
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
                  <strong>Created:</strong> {new Date(ticket.createdAt).toLocaleString()}
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
    </div>
  );
}
