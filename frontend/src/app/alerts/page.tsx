"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { fetchAlert, fetchRCA, fetchFeedback, submitFeedback, fetchClassifierMatchLog } from "@/lib/api";

function AlertDetailContent() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");
  const [alert, setAlert] = useState<any>(null);
  const [rca, setRca] = useState<any>(null);
  const [feedback, setFeedbackList] = useState<any[]>([]);
  const [comment, setComment] = useState("");
  const [score, setScore] = useState(50);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");
  const [classifierMatch, setClassifierMatch] = useState<any>(null);

  useEffect(() => {
    if (!id) return;
    fetchAlert(id).then(setAlert).catch(() => setError("Alert not found"));
    fetchRCA(id).then((r) => r && setRca(r)).catch(() => {});
    fetchFeedback(id).then(setFeedbackList).catch(() => {});
    fetchClassifierMatchLog(id).then((cm) => setClassifierMatch(cm && Object.keys(cm).length > 0 ? cm : null)).catch(() => {});
  }, [id]);

  const handleSubmitFeedback = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id) return;
    setSubmitting(true);
    try {
      await submitFeedback(id, comment, score);
      setSubmitted(true);
      const updated = await fetchFeedback(id);
      setFeedbackList(updated);
      setComment("");
    } catch {
      setError("Failed to submit feedback");
    }
    setSubmitting(false);
  };

  if (!id) return <p className="text-[#888888]">No alert ID provided. Use ?id=...</p>;
  if (error && !alert) return <p className="text-red-600">{error}</p>;
  if (!alert) return <p className="text-[#888888]">Loading...</p>;

  return (
    <div className="space-y-8">
      {/* Alert Metadata */}
      <section>
        <h1 className="text-2xl font-bold text-[#032147] mb-4">Alert Details</h1>
        <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-2">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <span className="text-[#888888] text-sm">Application</span>
              <p className="font-medium">{alert.source_application}</p>
            </div>
            <div>
              <span className="text-[#888888] text-sm">Domain</span>
              <p className="font-medium">{alert.domain}</p>
            </div>
            <div>
              <span className="text-[#888888] text-sm">Category</span>
              <p className="font-medium">{alert.category}</p>
            </div>
            <div>
              <span className="text-[#888888] text-sm">Severity</span>
              <p>
                <span
                  className={`px-2 py-0.5 rounded text-sm font-medium ${
                    alert.severity === "critical"
                      ? "bg-red-100 text-red-700"
                      : alert.severity === "high"
                      ? "bg-orange-100 text-orange-700"
                      : "bg-yellow-100 text-yellow-700"
                  }`}
                >
                  {alert.severity}
                </span>
              </p>
            </div>
          </div>
          <div className="pt-2 border-t mt-3">
            <span className="text-[#888888] text-sm">Status</span>
            <p className="font-medium">{alert.status}</p>
          </div>
          <div>
            <span className="text-[#888888] text-sm">Alert ID</span>
            <p className="font-mono text-sm">{alert._id}</p>
          </div>
        </div>
      </section>

      {/* Dynamic Classifiers / Mapping Score */}
      {classifierMatch && (
        <section>
          <div className="flex items-center gap-3 mb-4">
            <h2 className="text-xl font-bold text-[#032147]">Dynamic Classifiers</h2>
            {classifierMatch.mapping_score != null && (
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                classifierMatch.mapping_score >= 70 ? "bg-green-100 text-green-700"
                  : classifierMatch.mapping_score >= 40 ? "bg-yellow-100 text-yellow-700"
                  : "bg-red-100 text-red-700"
              }`}>
                Score: {classifierMatch.mapping_score}%
              </span>
            )}
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-5">
            {classifierMatch.match_detail && classifierMatch.match_detail.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-[#888888] border-b border-gray-100">
                    <th className="text-left py-1.5 w-10">#</th>
                    <th className="text-left py-1.5">Field</th>
                    <th className="text-left py-1.5">Expected</th>
                    <th className="text-left py-1.5">Extracted</th>
                    <th className="text-left py-1.5 w-16">Match</th>
                  </tr>
                </thead>
                <tbody>
                  {classifierMatch.match_detail.map((md: any, idx: number) => (
                    <tr key={idx} className="border-t border-gray-50">
                      <td className="py-1.5 text-xs text-[#888888] font-mono">{md.label || idx + 1}</td>
                      <td className="py-1.5 text-sm font-medium">{md.field_name}</td>
                      <td className="py-1.5 text-sm">{md.expected || "\u2014"}</td>
                      <td className="py-1.5 text-sm">{md.actual || "\u2014"}</td>
                      <td className="py-1.5">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          md.match ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                        }`}>
                          {md.match ? "Yes" : "No"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : classifierMatch.dynamic_fields_extracted ? (
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(classifierMatch.dynamic_fields_extracted).map(([k, v]) => (
                  <div key={k}>
                    <span className="text-[#888888] text-xs">{k}</span>
                    <p className="text-sm font-medium">{String(v) || "\u2014"}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[#888888] text-sm">No classifier match data available.</p>
            )}
          </div>
        </section>
      )}

      {/* RCA Section */}
      {rca && (
        <section>
          <h2 className="text-xl font-bold text-[#032147] mb-4">Root Cause Analysis</h2>
          <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
            {rca.triaging_results && rca.triaging_results.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-[#888888] uppercase mb-2">Triaging Steps</h3>
                <div className="space-y-3">
                  {rca.triaging_results.map((step: any, i: number) => (
                    <div key={i} className="border-l-4 border-[#209dd7] pl-4 py-2">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs bg-[#209dd7] text-white px-2 py-0.5 rounded">
                          {step.tool}
                        </span>
                        <span className="font-medium text-sm">{step.action}</span>
                      </div>
                      <details className="text-xs text-[#888888]">
                        <summary className="cursor-pointer hover:text-[#209dd7]">View output</summary>
                        <pre className="mt-1 p-2 bg-gray-50 rounded overflow-x-auto text-xs">
                          {JSON.stringify(step.output, null, 2)}
                        </pre>
                      </details>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <h3 className="text-sm font-semibold text-[#888888] uppercase mb-1">Root Cause</h3>
              <p>{rca.root_cause}</p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[#888888] uppercase mb-1">Impact</h3>
              <p>{rca.impact}</p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[#888888] uppercase mb-1">Recommendation</h3>
              <p>{rca.recommendation}</p>
            </div>

            {rca.validation_assessment && (
              <div className="border-t pt-4 mt-4">
                <h3 className="text-sm font-semibold text-[#888888] uppercase mb-2">Validation</h3>
                <p>{rca.validation_assessment}</p>
                {rca.confidence_score != null && (
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-sm text-[#888888]">Confidence:</span>
                    <span className="px-3 py-1 bg-[#ecad0a] text-[#032147] font-bold rounded-full text-sm">
                      {rca.confidence_score}%
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Feedback Section */}
      <section>
        <h2 className="text-xl font-bold text-[#032147] mb-4">Feedback</h2>

        {feedback.length > 0 && (
          <div className="space-y-3 mb-6">
            {feedback.map((fb: any, i: number) => (
              <div key={i} className="bg-white border border-gray-200 rounded-lg p-4">
                <p>{fb.comment}</p>
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-sm text-[#888888]">Confidence:</span>
                  <span className="px-2 py-0.5 bg-[#ecad0a] text-[#032147] font-bold rounded text-sm">
                    {fb.confidence_score}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {submitted && (
          <p className="text-green-600 mb-4">Feedback submitted successfully.</p>
        )}
        <form onSubmit={handleSubmitFeedback} className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
          <div>
            <label className="block text-sm text-[#888888] mb-1">Assessment Comment</label>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={3}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#209dd7]"
              placeholder="Provide your assessment of the RCA..."
            />
          </div>
          <div>
            <label className="block text-sm text-[#888888] mb-1">
              Confidence Score: <span className="font-bold text-[#032147]">{score}</span>
            </label>
            <input
              type="range"
              min={0}
              max={100}
              value={score}
              onChange={(e) => setScore(Number(e.target.value))}
              className="w-full accent-[#753991]"
            />
            <div className="flex justify-between text-xs text-[#888888]">
              <span>0</span>
              <span>100</span>
            </div>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="px-6 py-2 bg-[#753991] text-white rounded-lg hover:bg-[#5e2d74] transition-colors disabled:opacity-50"
          >
            {submitting ? "Submitting..." : "Submit Feedback"}
          </button>
        </form>
      </section>
    </div>
  );
}

export default function AlertPage() {
  return (
    <Suspense fallback={<p className="text-[#888888]">Loading...</p>}>
      <AlertDetailContent />
    </Suspense>
  );
}
