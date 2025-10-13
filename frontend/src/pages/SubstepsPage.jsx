// SubstepsPage.jsx
import React, { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

export function SubstepsPage() {
    const location = useLocation();
    const navigate = useNavigate();
    const state = location.state || {};
    const { step, ticket } = state;

    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [result, setResult] = useState(null);

    useEffect(() => {
        if (!step) return;
        const fetchSubsteps = async () => {
            const token = localStorage.getItem("token");
            if (!token) {
                window.location.href = "/login";
                return;
            }

            setLoading(true);
            setError("");
            try {
                const res = await fetch("http://127.0.0.1:5000/substeps", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: token,
                    },
                    body: JSON.stringify({ step: step, ticket: ticket }),
                });
                const data = await res.json();
                if (res.ok && data.result) {
                    setResult(data.result);
                } else {
                    setError(data.error || data.details || "Failed to generate substeps");
                }
            } catch (err) {
                setError("Network error when calling substeps API");
            } finally {
                setLoading(false);
            }
        };

        fetchSubsteps();
    }, [step, ticket]);

    // If page opened without state, show an instruction
    if (!step) {
        return (
            <div className="min-h-screen p-8 bg-gray-50 dark:bg-[#0f1724] text-slate-900 dark:text-slate-100">
                <button
                    onClick={() => navigate(-1)}
                    className="inline-flex items-center gap-2 px-3 py-1 rounded border mb-4"
                >
                    <ArrowLeft /> Back
                </button>
                <h2 className="text-xl font-semibold">No step selected</h2>
                <p className="mt-2 text-slate-500">
                    Open this page by clicking “Try this step” from the dashboard or suggest steps modal.
                </p>
            </div>
        );
    }

    const goToShare = () => {
        // pass down STEP, TICKET and SUBSTEPS so share page can render and use them
        navigate("/share", { state: { step, ticket, substeps: result?.recommendedSubsteps || [] } });
    };

    return (
        <div className="min-h-screen p-8 bg-gray-50 dark:bg-[#0f1724] text-slate-900 dark:text-slate-100">
            <button
                onClick={() => navigate(-1)}
                className="inline-flex items-center gap-2 px-3 py-1 rounded border mb-4"
            >
                <ArrowLeft /> Back
            </button>

            <div className="mb-6 p-4 bg-white dark:bg-slate-800 rounded-lg">
                <div className="flex items-start justify-between">
                    <div>
                        <div className="text-lg font-medium">{step}</div>
                        {ticket && (
                            <div className="text-sm text-slate-500 mt-1">
                                Context: {ticket.subject || ticket.displayId || ticket.ticketId} — requester: {ticket.requesterName || "N/A"}
                            </div>
                        )}
                    </div>

                    {/* Share screen button: navigates to dedicated Share page */}
                    <div>
                        <button
                            onClick={goToShare}
                            className="px-3 py-2 rounded-md bg-indigo-600 text-white shadow hover:bg-indigo-700"
                        >
                            Share screen
                        </button>
                    </div>
                </div>
            </div>

            <div className="grid gap-6 md:grid-cols-1">
                {loading ? (
                    <div className="p-4 bg-white dark:bg-slate-800 rounded-lg">Generating substeps…</div>
                ) : error ? (
                    <div className="p-4 bg-white dark:bg-slate-800 rounded-lg text-red-500">{error}</div>
                ) : result && result.recommendedSubsteps && result.recommendedSubsteps.length > 0 ? (
                    <div className="space-y-4">
                        {result.recommendedSubsteps.map((s) => (
                            <div key={s.id} className="p-4 bg-white dark:bg-slate-800 rounded-lg shadow-sm">
                                <div className="font-medium text-base mb-1">{s.title || `Step ${s.id}`}</div>
                                <div className="text-sm">{s.step}</div>
                                {s.whereToGo && <div className="text-xs text-slate-500 mt-2">Where: {s.whereToGo}</div>}
                                {s.commands && s.commands.length > 0 && (
                                    <div className="text-xs text-slate-500 mt-2">
                                        Commands:
                                        <pre className="bg-slate-100 dark:bg-slate-900 p-2 rounded mt-1 text-xs overflow-auto">
                                            {s.commands.join("\n")}
                                        </pre>
                                    </div>
                                )}
                                {s.notes && <div className="text-xs text-slate-500 mt-2">Notes: {s.notes}</div>}
                            </div>
                        ))}
                    </div>
                ) : (
                    <div className="p-4 bg-white dark:bg-slate-800 rounded-lg text-slate-500">No substeps returned for this step.</div>
                )}
            </div>
        </div>
    );
}
