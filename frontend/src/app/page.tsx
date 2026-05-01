"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  fetchAlerts,
  fetchAlert,
  fetchRCA,
  fetchFeedback,
  submitFeedback,
  fetchClassifierMatchLog,
  fetchPendingActions,
  approvePendingAction,
  submitRetry,
  fetchAlertRetryHistory,
  fetchRetryBatch,
  fetchRetryRunOutput,
  fetchAlertStats,
  fetchRetryStats,
  AlertFilters,
  AlertStats,
  RetryLevel,
  PendingAction,
} from "@/lib/api";
import SopManagementPanel from "@/app/SopManagementPanel";

const PROCESSING_STATUSES = [
  { value: "", label: "All" },
  { value: "ingested", label: "Ingested" },
  { value: "processedSuccessfully", label: "Processed Successfully" },
  { value: "SOPNotFound", label: "SOP Not Found" },
  { value: "RCANotFound", label: "RCA Not Found" },
  { value: "RCANotValidated", label: "RCA Not Validated" },
  { value: "sop_workflow_processfailed", label: "Workflow Process Failed" },
  { value: "pending_actions", label: "Pending Actions" },
];

const SEVERITIES = [
  { value: "", label: "All" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

function statusBadge(status: string) {
  const map: Record<string, string> = {
    processedSuccessfully: "bg-green-100 text-green-700",
    SOPNotFound: "bg-red-100 text-red-700",
    RCANotFound: "bg-orange-100 text-orange-700",
    RCANotValidated: "bg-yellow-100 text-yellow-700",
    sop_workflow_processfailed: "bg-red-100 text-red-700",
    ingested: "bg-gray-100 text-gray-600",
    pending_actions: "bg-orange-100 text-orange-700",
  };
  return map[status] || "bg-gray-100 text-gray-600";
}

function severityBadge(severity: string) {
  const map: Record<string, string> = {
    critical: "bg-red-100 text-red-700",
    high: "bg-orange-100 text-orange-700",
    medium: "bg-yellow-100 text-yellow-700",
    low: "bg-blue-100 text-blue-700",
  };
  return map[severity] || "bg-gray-100 text-gray-600";
}

function toText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if (typeof obj.description === "string") return obj.description;
    return JSON.stringify(value);
  }
  return String(value ?? "");
}

function pickFirstNonEmpty(...values: unknown[]): string {
  for (const v of values) {
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

function resolveAlertSourceLabel(alert: any): string {
  const sourceType = String(alert?.source_type || "").toLowerCase();
  const sourceRef = pickFirstNonEmpty(alert?.source_ref);
  const filename = pickFirstNonEmpty(alert?.raw_payload?.filename);

  if (sourceType === "file") return sourceRef || filename || "unknown-file";
  if (sourceType === "webhook" || sourceType === "api") {
    return sourceRef || "unknown-endpoint";
  }

  // Backward-compatible fallback for historical records.
  if (filename) return filename;
  if (sourceRef) return sourceRef;
  return "unknown-endpoint";
}

function buildAlertDisplayName(alert: any): string {
  const sourceLabel = resolveAlertSourceLabel(alert);
  const classifiers = [
    pickFirstNonEmpty(alert?.source_application),
    pickFirstNonEmpty(alert?.domain),
    pickFirstNonEmpty(alert?.category),
  ].filter(Boolean);

  return [sourceLabel, ...classifiers].join(" | ");
}

function formatLoggedAt(value: unknown): string {
  if (!value) return "-";
  const d = new Date(String(value));
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

type Tab = "alerts" | "retry" | "sop-management";

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("alerts");

  // Filters
  const [filters, setFilters] = useState<AlertFilters>({ limit: 50 });
  const [showFilters, setShowFilters] = useState(false);

  // Alert list
  const [alerts, setAlerts] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  // Selected alert detail
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [alertDetail, setAlertDetail] = useState<any>(null);
  const [rca, setRca] = useState<any>(null);
  const [feedback, setFeedbackList] = useState<any[]>([]);
  const [classifierMatch, setClassifierMatch] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Pending actions
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);
  const [approveResults, setApproveResults] = useState<Record<number, unknown>>({});
  const [approvingStep, setApprovingStep] = useState<number | null>(null);

  // Feedback form
  const [comment, setComment] = useState("");
  const [score, setScore] = useState(50);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  // Retry tab filters + alert list (independent from Alert Analysis)
  const [retryFilters, setRetryFilters] = useState<AlertFilters>({ limit: 50 });
  const [retryShowFilters, setRetryShowFilters] = useState(false);
  const [retryAlerts, setRetryAlerts] = useState<any[]>([]);
  const [retryTotal, setRetryTotal] = useState(0);
  const [retryLoading, setRetryLoading] = useState(true);

  // Retry tab state
  const [selectedRetryIds, setSelectedRetryIds] = useState<string[]>([]);
  const [retryLevel, setRetryLevel] = useState<RetryLevel>("level1");
  const [retryReason, setRetryReason] = useState("");
  const [retrySubmitting, setRetrySubmitting] = useState(false);
  const [retryResults, setRetryResults] = useState<any[]>([]);
  const [currentBatchId, setCurrentBatchId] = useState<string | null>(null);
  const [currentBatch, setCurrentBatch] = useState<any>(null);
  const [retryHistory, setRetryHistory] = useState<any[]>([]);
  const [retryHistoryAlertId, setRetryHistoryAlertId] = useState<string | null>(null);
  const [retryHistoryLoading, setRetryHistoryLoading] = useState(false);
  const [retryRunPopup, setRetryRunPopup] = useState<{ alertId: string; batchId: string; level: string; completedAt: string | null; data: any } | null>(null);
  const [retryRunPopupLoading, setRetryRunPopupLoading] = useState(false);

  // KPI stats for each tab's bar
  const [alertStats, setAlertStats] = useState<AlertStats | null>(null);
  const [retryStats, setRetryStats] = useState<AlertStats | null>(null);

  const loadAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchAlerts(filters);
      if (Array.isArray(data)) {
        setAlerts(data);
        setTotal(data.length);
      } else {
        setAlerts(data.alerts || []);
        setTotal(data.total || 0);
      }
    } catch {
      setAlerts([]);
      setTotal(0);
    }
    setLoading(false);
    fetchAlertStats(filters).then(setAlertStats).catch(() => {});
  }, [filters]);

  const loadRetryAlerts = useCallback(async () => {
    setRetryLoading(true);
    try {
      const data = await fetchAlerts(retryFilters);
      if (Array.isArray(data)) {
        setRetryAlerts(data);
        setRetryTotal(data.length);
      } else {
        setRetryAlerts(data.alerts || []);
        setRetryTotal(data.total || 0);
      }
    } catch {
      setRetryAlerts([]);
      setRetryTotal(0);
    }
    setRetryLoading(false);
    fetchRetryStats(retryFilters).then(setRetryStats).catch(() => {});
  }, [retryFilters]);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  useEffect(() => {
    loadRetryAlerts();
  }, [loadRetryAlerts]);

  // Load detail when alert selected
  useEffect(() => {
    if (!selectedId) {
      setAlertDetail(null);
      setRca(null);
      setFeedbackList([]);
      setClassifierMatch(null);
      setPendingActions([]);
      setApproveResults({});
      setApprovingStep(null);
      return;
    }
    setDetailLoading(true);
    setSubmitted(false);
    setApproveResults({});
    setApprovingStep(null);
    Promise.all([
      fetchAlert(selectedId).catch(() => null),
      fetchRCA(selectedId).catch(() => null),
      fetchFeedback(selectedId).catch(() => []),
      fetchClassifierMatchLog(selectedId).catch(() => null),
      fetchPendingActions(selectedId).catch(() => []),
    ]).then(([a, r, f, cm, pa]) => {
      setAlertDetail(a);
      setRca(r);
      setFeedbackList(Array.isArray(f) ? f : []);
      setClassifierMatch(cm && Object.keys(cm).length > 0 ? cm : null);
      setPendingActions(Array.isArray(pa) ? pa : []);
      setDetailLoading(false);
    });
  }, [selectedId]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadAlerts();
  };

  const updateFilter = (key: string, value: string | boolean | undefined) => {
    setFilters((prev) => {
      const next = { ...prev, [key]: value, skip: 0 };
      if (value === "" || value === undefined) delete next[key as keyof AlertFilters];
      return next;
    });
  };

  const updateRetryFilter = (key: string, value: string | boolean | undefined) => {
    setRetryFilters((prev) => {
      const next = { ...prev, [key]: value, skip: 0 };
      if (value === "" || value === undefined) delete next[key as keyof AlertFilters];
      return next;
    });
  };

  const handleApprove = async (stepId: number) => {
    if (!selectedId) return;
    setApprovingStep(stepId);
    try {
      const result = await approvePendingAction(selectedId, stepId);
      setApproveResults((prev) => ({ ...prev, [stepId]: result }));
      setPendingActions((prev) =>
        prev.map((a) => (a.step_id === stepId ? { ...a, status: "executed" } : a))
      );
    } catch {
      setApproveResults((prev) => ({ ...prev, [stepId]: { error: "Failed to execute" } }));
    }
    setApprovingStep(null);
  };

  const handleSubmitFeedback = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedId) return;
    setSubmitting(true);
    try {
      await submitFeedback(selectedId, comment, score);
      setSubmitted(true);
      const updated = await fetchFeedback(selectedId);
      setFeedbackList(Array.isArray(updated) ? updated : []);
      setComment("");
      loadAlerts();
      const a = await fetchAlert(selectedId);
      setAlertDetail(a);
    } catch {
      // ignore
    }
    setSubmitting(false);
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "alerts", label: "Alert Analysis" },
    { id: "retry", label: "Retry" },
    { id: "sop-management", label: "SOP Management" },
  ];

  const toggleRetryAlert = (alertId: string) => {
    setSelectedRetryIds((prev) =>
      prev.includes(alertId) ? prev.filter((id) => id !== alertId) : [...prev, alertId]
    );
  };

  const loadBatch = async (batchId: string) => {
    try {
      const batch = await fetchRetryBatch(batchId);
      setCurrentBatch(batch);
    } catch {
      setCurrentBatch(null);
    }
  };

  const loadRetryHistory = async (alertId: string) => {
    setRetryHistoryLoading(true);
    setRetryHistoryAlertId(alertId);
    try {
      const history = await fetchAlertRetryHistory(alertId);
      setRetryHistory(history?.retries || []);
    } catch {
      setRetryHistory([]);
    }
    setRetryHistoryLoading(false);
  };

  const openRetryRunPopup = async (alertId: string, batchId: string, level: string, completedAt: string | null) => {
    setRetryRunPopupLoading(true);
    setRetryRunPopup({ alertId, batchId, level, completedAt, data: null });
    try {
      const data = await fetchRetryRunOutput(alertId, batchId);
      setRetryRunPopup({ alertId, batchId, level, completedAt, data });
    } catch {
      setRetryRunPopup({ alertId, batchId, level, completedAt, data: null });
    }
    setRetryRunPopupLoading(false);
  };

  const handleRunRetry = async () => {
    if (selectedRetryIds.length === 0) return;
    setRetrySubmitting(true);
    try {
      const results = await submitRetry(selectedRetryIds, retryLevel, retryReason || undefined);
      setRetryResults(Array.isArray(results) ? results : []);

      const firstAccepted = (Array.isArray(results) ? results : []).find((r: any) => r.accepted && r.batch_id);
      if (firstAccepted?.batch_id) {
        setCurrentBatchId(firstAccepted.batch_id);
        await loadBatch(firstAccepted.batch_id);
      }

      const firstSelected = selectedRetryIds[0];
      if (firstSelected) {
        await loadRetryHistory(firstSelected);
      }

      await loadRetryAlerts();
    } catch {
      setRetryResults([]);
      setCurrentBatch(null);
      setCurrentBatchId(null);
    }
    setRetrySubmitting(false);
  };

  const renderKpiBar = (stats: AlertStats, label: string, icon: React.ReactNode) => {
    const total = stats.total || 0;
    const pctSuccess = total > 0 ? (stats.success / total) * 100 : 0;
    const pctFailed  = total > 0 ? (stats.failed  / total) * 100 : 0;
    const pctIncomplete = total > 0 ? (stats.incomplete / total) * 100 : 0;
    const meanSec = stats.mean_processing_time_seconds;
    const meanLabel = meanSec == null ? "—"
      : meanSec < 60 ? `${meanSec}s`
      : `${Math.floor(meanSec / 60)}m ${Math.round(meanSec % 60)}s`;
    return (
      <div className="ml-auto flex items-center gap-3 py-2 text-xs text-[#888888] select-none">
        <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-100 text-[#032147] font-semibold text-[10px] uppercase tracking-wide whitespace-nowrap">
          {icon}
          {label}
        </span>
        {stats.total_alerts != null && (
          <span className="text-[#209dd7] font-semibold">{stats.total_alerts} alerts</span>
        )}
        <div className="flex h-1 w-24 rounded overflow-hidden bg-gray-200">
          <span style={{ width: `${pctSuccess}%` }}    className="bg-green-500" />
          <span style={{ width: `${pctFailed}%` }}     className="bg-red-500" />
          <span style={{ width: `${pctIncomplete}%` }} className="bg-[#ecad0a]" />
        </div>
        <span>{total} {stats.total_alerts != null ? "attempts" : "total"}</span>
        <span className="text-green-600 font-medium">{stats.success}✓</span>
        <span className="text-red-600 font-medium">{stats.failed}✗</span>
        <span className="text-[#ecad0a] font-medium">{stats.incomplete}~</span>
        <span>{meanLabel} avg</span>
      </div>
    );
  };

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]">
      {/* Tab bar */}
      <div className="flex border-b border-gray-200 bg-white px-4">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-[#209dd7] text-[#209dd7]"
                : "border-transparent text-[#888888] hover:text-[#032147]"
            }`}
          >
            {tab.label}
          </button>
        ))}
        {activeTab === "alerts" && alertStats && renderKpiBar(
          alertStats,
          "Ingested",
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
        )}
        {activeTab === "retry" && retryStats && renderKpiBar(
          retryStats,
          "Retry Attempts",
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="1 4 1 10 7 10"/>
            <path d="M3.51 15a9 9 0 1 0 .49-4.5"/>
          </svg>
        )}
      </div>

      {/* SOP Management tab */}
      {activeTab === "sop-management" && <SopManagementPanel />}

      {/* Retry tab */}
      {activeTab === "retry" && (
        <div className="flex flex-1 gap-0 overflow-hidden">
          <div className="w-1/3 flex flex-col min-w-[320px] border-r border-gray-200">
            <div className="p-4 border-b border-gray-200 bg-white">
              <div className="flex items-center justify-between mb-3">
                <h1 className="text-lg font-bold text-[#032147]">Retry Alerts</h1>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[#888888]">{retryTotal} total</span>
                  <button
                    onClick={() => setRetryShowFilters(!retryShowFilters)}
                    className={`px-3 py-1 text-xs rounded border transition-colors ${
                      retryShowFilters
                        ? "bg-[#209dd7] text-white border-[#209dd7]"
                        : "border-gray-300 text-[#888888] hover:border-[#209dd7]"
                    }`}
                  >
                    Filters
                  </button>
                </div>
              </div>

              {retryShowFilters && (
                <form onSubmit={(e) => { e.preventDefault(); loadRetryAlerts(); }} className="space-y-2 text-sm mb-3">
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      type="text"
                      placeholder="Alert ID"
                      value={retryFilters.alert_id || ""}
                      onChange={(e) => updateRetryFilter("alert_id", e.target.value)}
                      className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                    />
                    <input
                      type="text"
                      placeholder="Application"
                      value={retryFilters.application || ""}
                      onChange={(e) => updateRetryFilter("application", e.target.value)}
                      className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                    />
                    <input
                      type="text"
                      placeholder="Domain"
                      value={retryFilters.domain || ""}
                      onChange={(e) => updateRetryFilter("domain", e.target.value)}
                      className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                    />
                    <input
                      type="text"
                      placeholder="Category"
                      value={retryFilters.category || ""}
                      onChange={(e) => updateRetryFilter("category", e.target.value)}
                      className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                    />
                    <select
                      value={retryFilters.severity || ""}
                      onChange={(e) => updateRetryFilter("severity", e.target.value)}
                      className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                    >
                      {SEVERITIES.map((s) => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                    <select
                      value={retryFilters.processing_status || ""}
                      onChange={(e) => updateRetryFilter("processing_status", e.target.value)}
                      className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                    >
                      {PROCESSING_STATUSES.map((s) => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                    <input
                      type="text"
                      placeholder="SOP ID"
                      value={retryFilters.sop_id || ""}
                      onChange={(e) => updateRetryFilter("sop_id", e.target.value)}
                      className="col-span-2 px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="submit"
                      className="flex-1 px-3 py-1.5 bg-[#753991] text-white rounded text-xs hover:bg-[#5e2d74] transition-colors"
                    >
                      Apply
                    </button>
                    <button
                      type="button"
                      onClick={() => setRetryFilters({ limit: 50 })}
                      className="px-3 py-1.5 border border-gray-300 rounded text-xs text-[#888888] hover:border-[#209dd7] transition-colors"
                    >
                      Clear
                    </button>
                  </div>
                </form>
              )}

              <div className="flex gap-2">
                <button
                  onClick={() => setSelectedRetryIds(retryAlerts.map((a: any) => a._id))}
                  className="px-3 py-1.5 border border-gray-300 rounded text-xs text-[#888888] hover:border-[#209dd7]"
                >
                  Select All
                </button>
                <button
                  onClick={() => setSelectedRetryIds([])}
                  className="px-3 py-1.5 border border-gray-300 rounded text-xs text-[#888888] hover:border-[#209dd7]"
                >
                  Clear
                </button>
                <span className="ml-auto text-xs text-[#888888] self-center">{selectedRetryIds.length} selected</span>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              {retryLoading ? (
                <p className="text-[#888888] p-4 text-sm">Loading...</p>
              ) : retryAlerts.length === 0 ? (
                <p className="text-[#888888] p-4 text-sm">No alerts found.</p>
              ) : (
                <div className="divide-y divide-gray-100">
                  {retryAlerts.map((alert: any) => {
                    const checked = selectedRetryIds.includes(alert._id);
                    const displayName = buildAlertDisplayName(alert);
                    const status = alert.processing_status || alert.status;
                    const loggedAt = formatLoggedAt(alert.logged_at || alert.created_at);
                    return (
                      <label
                        key={alert._id}
                        className={`flex gap-3 px-4 py-3 cursor-pointer hover:bg-blue-50 ${checked ? "bg-blue-50" : ""}`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleRetryAlert(alert._id)}
                          className="mt-1 accent-[#753991]"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center justify-between mb-1">
                            <span className="font-medium text-sm text-[#209dd7] truncate">{displayName}</span>
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${severityBadge(alert.severity)}`}>
                              {alert.severity}
                            </span>
                          </div>
                          <div className="mt-1 flex items-center justify-between">
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${statusBadge(status)}`}>
                              {status}
                            </span>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                loadRetryHistory(alert._id);
                              }}
                              className="text-[10px] text-[#209dd7] hover:underline"
                            >
                              History
                            </button>
                          </div>
                          <p className="text-[10px] text-[#888888] mt-1 font-mono truncate">{alert._id}</p>
                          <p className="text-[10px] text-[#888888] mt-1 truncate">{loggedAt}</p>
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="w-2/3 overflow-y-auto p-6 space-y-6">
            <section className="bg-white border border-gray-200 rounded-lg p-5">
              <h2 className="text-lg font-bold text-[#032147] mb-4">Run Retry</h2>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-[#888888] mb-1">Retry Level</label>
                  <select
                    value={retryLevel}
                    onChange={(e) => setRetryLevel(e.target.value as RetryLevel)}
                    className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                  >
                    <option value="level1">Level 1 (Re-ingest alert)</option>
                    <option value="level2">Level 2 (Re-identify SOP)</option>
                    <option value="level3">Level 3 (Re-execute SOP)</option>
                    <option value="level4">Level 4 (Re-validate RCA)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-[#888888] mb-1">Selected Alerts</label>
                  <div className="px-3 py-2 border border-gray-200 rounded text-sm text-[#032147] bg-gray-50">
                    {selectedRetryIds.length}
                  </div>
                </div>
              </div>
              <div className="mt-4">
                <label className="block text-xs text-[#888888] mb-1">Reason (optional)</label>
                <textarea
                  value={retryReason}
                  onChange={(e) => setRetryReason(e.target.value)}
                  rows={3}
                  placeholder="Reason for retry request"
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                />
              </div>
              <div className="mt-4">
                <button
                  onClick={handleRunRetry}
                  disabled={retrySubmitting || selectedRetryIds.length === 0}
                  className="px-5 py-2 bg-[#753991] text-white rounded text-sm hover:bg-[#5e2d74] transition-colors disabled:opacity-50"
                >
                  {retrySubmitting ? "Submitting..." : "Run Retry"}
                </button>
              </div>
            </section>

            {(retryResults.length > 0 || currentBatch) && (
              <section className="bg-white border border-gray-200 rounded-lg p-5">
                <h2 className="text-lg font-bold text-[#032147] mb-3">Latest Retry Run</h2>
                {currentBatchId && (
                  <p className="text-xs text-[#888888] mb-3">Batch ID: <span className="font-mono">{currentBatchId}</span></p>
                )}
                {currentBatch && (
                  <p className="text-sm mb-3">
                    Status: <span className="font-semibold text-[#032147]">{currentBatch.overall_status}</span>
                  </p>
                )}
                {retryResults.length > 0 && (
                  <div className="space-y-2">
                    {retryResults.map((res: any, idx: number) => (
                      <div key={idx} className="border border-gray-100 rounded p-3 text-sm">
                        <p className="font-mono text-xs text-[#888888] mb-1">{res.alert_id}</p>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${res.accepted ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                          {res.accepted ? "accepted" : "rejected"}
                        </span>
                        {res.reason && <p className="text-xs text-[#888888] mt-2">{res.reason}</p>}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}

            <section className="bg-white border border-gray-200 rounded-lg p-5">
              <h2 className="text-lg font-bold text-[#032147] mb-3">Alert Retry History</h2>
              {retryHistoryAlertId && (
                <p className="text-xs text-[#888888] mb-3">
                  Alert ID: <span className="font-mono">{retryHistoryAlertId}</span>
                </p>
              )}
              {retryHistoryLoading ? (
                <p className="text-sm text-[#888888]">Loading history...</p>
              ) : retryHistory.length === 0 ? (
                <p className="text-sm text-[#888888]">No retry history loaded. Click "History" on an alert.</p>
              ) : (
                <div className="space-y-2">
                  {retryHistory.map((item: any, idx: number) => (
                    <div key={idx} className="border border-gray-100 rounded p-3">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-xs font-mono text-[#888888]">{item.batch_id}</span>
                        <span className="text-xs text-[#032147] font-semibold">{item.retry_level}</span>
                      </div>
                      <div className="flex items-center justify-between mt-1">
                        <p className="text-xs text-[#888888]">State: {item.state}</p>
                        {item.state === "completed" && retryHistoryAlertId && (
                          <button
                            onClick={() => openRetryRunPopup(retryHistoryAlertId, item.batch_id, item.retry_level, item.completed_at || null)}
                            className="text-[10px] px-2 py-0.5 rounded bg-[#209dd7] text-white hover:bg-[#1a7faf] transition-colors"
                          >
                            View Details
                          </button>
                        )}
                      </div>
                      {item.completed_at && (
                        <p className="text-[10px] text-[#888888] mt-0.5">{new Date(item.completed_at).toLocaleString()}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        </div>
      )}

      {/* Alert Analysis tab */}
      {activeTab === "alerts" && (
      <div className="flex flex-1 gap-0 overflow-hidden">
      {/* LEFT PANEL - Alert List (1/3 width) */}
      <div className="w-1/3 flex flex-col min-w-[320px] border-r border-gray-200">
        <div className="p-4 border-b border-gray-200 bg-white">
          <div className="flex items-center justify-between mb-3">
            <h1 className="text-lg font-bold text-[#032147]">Alerts</h1>
            <div className="flex items-center gap-2">
              <span className="text-xs text-[#888888]">{total} total</span>
              <button
                onClick={() => setShowFilters(!showFilters)}
                className={`px-3 py-1 text-xs rounded border transition-colors ${
                  showFilters
                    ? "bg-[#209dd7] text-white border-[#209dd7]"
                    : "border-gray-300 text-[#888888] hover:border-[#209dd7]"
                }`}
              >
                Filters
              </button>
            </div>
          </div>

          {/* Filter Panel */}
          {showFilters && (
            <form onSubmit={handleSearch} className="space-y-2 text-sm">
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="text"
                  placeholder="Alert ID"
                  value={filters.alert_id || ""}
                  onChange={(e) => updateFilter("alert_id", e.target.value)}
                  className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                />
                <input
                  type="text"
                  placeholder="Application"
                  value={filters.application || ""}
                  onChange={(e) => updateFilter("application", e.target.value)}
                  className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                />
                <input
                  type="text"
                  placeholder="Domain"
                  value={filters.domain || ""}
                  onChange={(e) => updateFilter("domain", e.target.value)}
                  className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                />
                <input
                  type="text"
                  placeholder="Category"
                  value={filters.category || ""}
                  onChange={(e) => updateFilter("category", e.target.value)}
                  className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                />
                <select
                  value={filters.severity || ""}
                  onChange={(e) => updateFilter("severity", e.target.value)}
                  className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                >
                  {SEVERITIES.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
                <select
                  value={filters.processing_status || ""}
                  onChange={(e) => updateFilter("processing_status", e.target.value)}
                  className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                >
                  {PROCESSING_STATUSES.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
                <input
                  type="text"
                  placeholder="SOP ID"
                  value={filters.sop_id || ""}
                  onChange={(e) => updateFilter("sop_id", e.target.value)}
                  className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                />
                <input
                  type="text"
                  placeholder="Root Cause search"
                  value={filters.root_cause || ""}
                  onChange={(e) => updateFilter("root_cause", e.target.value)}
                  className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                />
                <input
                  type="date"
                  value={filters.date_from || ""}
                  onChange={(e) => updateFilter("date_from", e.target.value)}
                  className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                />
                <input
                  type="date"
                  value={filters.date_to || ""}
                  onChange={(e) => updateFilter("date_to", e.target.value)}
                  className="px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                />
              </div>
              <div className="flex gap-2">
                <button
                  type="submit"
                  className="flex-1 px-3 py-1.5 bg-[#753991] text-white rounded text-xs hover:bg-[#5e2d74] transition-colors"
                >
                  Apply Filters
                </button>
                <button
                  type="button"
                  onClick={() => { setFilters({ limit: 50 }); }}
                  className="px-3 py-1.5 border border-gray-300 rounded text-xs text-[#888888] hover:border-[#209dd7] transition-colors"
                >
                  Clear
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Alert List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <p className="text-[#888888] p-4 text-sm">Loading...</p>
          ) : alerts.length === 0 ? (
            <p className="text-[#888888] p-4 text-sm">No alerts found.</p>
          ) : (
            <div className="divide-y divide-gray-100">
              {alerts.map((alert: any) => {
                const displayName = buildAlertDisplayName(alert);
                const status = alert.processing_status || alert.status;
                const loggedAt = formatLoggedAt(alert.logged_at || alert.created_at);

                return (
                  <button
                    key={alert._id}
                    onClick={() => setSelectedId(alert._id)}
                    className={`w-full text-left px-4 py-3 hover:bg-blue-50 transition-colors ${
                      selectedId === alert._id ? "bg-blue-50 border-l-4 border-[#209dd7]" : ""
                    } ${alert.feedback_received ? "bg-green-50" : ""}`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-sm text-[#209dd7] truncate">{displayName}</span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${severityBadge(alert.severity)}`}>
                        {alert.severity}
                      </span>
                    </div>
                    <div className="flex items-center justify-between mt-1">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${statusBadge(status)}`}>
                        {status}
                      </span>
                      {alert.feedback_received && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#ecad0a] text-[#032147] font-medium">
                          Feedback
                        </span>
                      )}
                      {alert.processing_status === "pending_actions" && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 font-medium">
                          Pending
                        </span>
                      )}
                    </div>
                    <p className="text-[10px] text-[#888888] mt-1 font-mono truncate">{alert._id}</p>
                    <p className="text-[10px] text-[#888888] mt-1 truncate">{loggedAt}</p>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* RIGHT PANEL - Alert Detail (2/3 width) */}
      <div className="w-2/3 overflow-y-auto p-6">
        {!selectedId ? (
          <div className="flex items-center justify-center h-full text-[#888888]">
            <p>Select an alert from the list to view details</p>
          </div>
        ) : detailLoading ? (
          <p className="text-[#888888]">Loading details...</p>
        ) : !alertDetail ? (
          <p className="text-red-600">Alert not found</p>
        ) : (
          <div className="space-y-6">
            {/* Alert Metadata */}
            <section>
              <div className="flex items-center justify-between mb-4">
                <h1 className="text-xl font-bold text-[#032147]">Alert Details</h1>
                {alertDetail.feedback_received && (
                  <span className="px-3 py-1 rounded-full text-xs font-medium bg-[#ecad0a] text-[#032147]">
                    Feedback Received
                  </span>
                )}
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-2">
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <span className="text-[#888888] text-xs">Application</span>
                    <p className="font-medium text-sm">{alertDetail.source_application}</p>
                  </div>
                  <div>
                    <span className="text-[#888888] text-xs">Domain</span>
                    <p className="font-medium text-sm">{alertDetail.domain}</p>
                  </div>
                  <div>
                    <span className="text-[#888888] text-xs">Category</span>
                    <p className="font-medium text-sm">{alertDetail.category}</p>
                  </div>
                  <div>
                    <span className="text-[#888888] text-xs">Severity</span>
                    <p>
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${severityBadge(alertDetail.severity)}`}>
                        {alertDetail.severity}
                      </span>
                    </p>
                  </div>
                  <div>
                    <span className="text-[#888888] text-xs">Processing Status</span>
                    <p>
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusBadge(alertDetail.processing_status || alertDetail.status)}`}>
                        {alertDetail.processing_status || alertDetail.status}
                      </span>
                    </p>
                  </div>
                  <div>
                    <span className="text-[#888888] text-xs">Alert ID</span>
                    <p className="font-mono text-xs">{alertDetail._id}</p>
                  </div>
                </div>
                {alertDetail.sop_id && (
                    <div className="pt-2 border-t mt-3">
                      <span className="text-[#888888] text-xs">SOP ID</span>
                      <p className="font-mono text-xs">{alertDetail.sop_id}</p>
                    </div>
                  )}
                  {alertDetail.sop_document_id && !alertDetail.sop_id && (
                  <div className="pt-2 border-t mt-3">
                    <span className="text-[#888888] text-xs">SOP Document ID</span>
                    <p className="font-mono text-xs">{alertDetail.sop_document_id}</p>
                  </div>
                )}
                  {alertDetail.latest_retry_level && (
                    <div className="pt-2 border-t mt-3">
                      <span className="text-[#888888] text-xs">Latest retry run</span>
                      <p className="text-xs font-medium text-[#032147]">
                        Level {String(alertDetail.latest_retry_level).replace("level", "")}
                        {alertDetail.retry_requested_at ? ` - ${new Date(alertDetail.retry_requested_at).toLocaleString()}` : ""}
                      </p>
                    </div>
                  )}
              </div>
            </section>

            {/* Dynamic Classifiers / Mapping Score */}
            {classifierMatch && (
              <section>
                <div className="flex items-center gap-3 mb-3">
                  <h2 className="text-lg font-bold text-[#032147]">Dynamic Classifiers</h2>
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
                <h2 className="text-lg font-bold text-[#032147] mb-3">Root Cause Analysis</h2>
                <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
                  {rca.triaging_results && rca.triaging_results.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold text-[#888888] uppercase mb-2">Triaging Steps</h3>
                      <div className="space-y-2">
                        {rca.triaging_results.map((step: any, i: number) => (
                          <div key={i} className="border-l-4 border-[#209dd7] pl-3 py-1">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-[10px] bg-[#209dd7] text-white px-1.5 py-0.5 rounded">
                                {step.tool}
                              </span>
                              <span className="font-medium text-xs">{step.action}</span>
                            </div>
                            <details className="text-xs text-[#888888]">
                              <summary className="cursor-pointer hover:text-[#209dd7]">View output</summary>
                              <pre className="mt-1 p-2 bg-gray-50 rounded overflow-x-auto text-[10px]">
                                {JSON.stringify(step.output, null, 2)}
                              </pre>
                            </details>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div>
                    <h3 className="text-xs font-semibold text-[#888888] uppercase mb-1">Root Cause</h3>
                    <p className="text-sm">{toText(rca.root_cause)}</p>
                  </div>
                  <div>
                    <h3 className="text-xs font-semibold text-[#888888] uppercase mb-1">Impact</h3>
                    <p className="text-sm">{toText(rca.impact)}</p>
                  </div>
                  <div>
                    <h3 className="text-xs font-semibold text-[#888888] uppercase mb-1">Recommendation</h3>
                    <p className="text-sm">{toText(rca.recommendation)}</p>
                  </div>
                  {rca.validation_assessment && (
                    <div className="border-t pt-3 mt-3">
                      <h3 className="text-xs font-semibold text-[#888888] uppercase mb-1">Validation</h3>
                      <p className="text-sm">{rca.validation_assessment}</p>
                      {rca.confidence_score != null && (
                        <div className="mt-2 flex items-center gap-2">
                          <span className="text-xs text-[#888888]">Confidence:</span>
                          <span className="px-2 py-0.5 bg-[#ecad0a] text-[#032147] font-bold rounded-full text-xs">
                            {rca.confidence_score}%
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Pending Actions Section */}
            {pendingActions.length > 0 && (
              <section>
                <h2 className="text-lg font-bold text-[#032147] mb-3">Pending Actions</h2>
                <div className="space-y-2">
                  {pendingActions.map((pa) => {
                    const sectionColors: Record<string, string> = {
                      triaging: "bg-[#209dd7] text-white",
                      remediation: "bg-[#ecad0a] text-[#032147]",
                      communication: "bg-[#753991] text-white",
                      escalation: "bg-red-600 text-white",
                    };
                    const sectionColor = sectionColors[pa.section] || "bg-gray-200 text-gray-700";
                    const isDone = pa.status === "executed" || pa.status in approveResults;
                    const result = approveResults[pa.step_id];
                    return (
                      <div key={pa.step_id} className="bg-white border border-gray-200 rounded-lg p-3">
                        <div className="flex items-start gap-2">
                          <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium ${sectionColor}`}>
                            {pa.section}
                          </span>
                          <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-700">
                            {pa.tool}
                          </span>
                          <span className="text-xs flex-1">{pa.action}</span>
                          <button
                            onClick={() => handleApprove(pa.step_id)}
                            disabled={isDone || approvingStep === pa.step_id}
                            className="shrink-0 px-2 py-0.5 text-[10px] font-medium rounded bg-[#753991] text-white hover:bg-[#5e2d74] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                          >
                            {approvingStep === pa.step_id
                              ? "Executing..."
                              : isDone
                              ? "Executed"
                              : "Approve & Execute"}
                          </button>
                        </div>
                        {result != null && (
                          <details className="mt-2 text-xs text-[#888888]" open>
                            <summary className="cursor-pointer hover:text-[#209dd7]">Result</summary>
                            <pre className="mt-1 p-2 bg-gray-50 rounded overflow-x-auto text-[10px]">
                              {JSON.stringify(result, null, 2)}
                            </pre>
                          </details>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* Feedback Section */}
            <section>
              <h2 className="text-lg font-bold text-[#032147] mb-3">Feedback</h2>
              {feedback.length > 0 && (
                <div className="space-y-2 mb-4">
                  {feedback.map((fb: any, i: number) => (
                    <div key={i} className="bg-white border border-gray-200 rounded-lg p-3">
                      <p className="text-sm">{fb.comment}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-[#888888]">Confidence:</span>
                        <span className="px-2 py-0.5 bg-[#ecad0a] text-[#032147] font-bold rounded text-xs">
                          {fb.confidence_score}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {submitted && (
                <p className="text-green-600 mb-3 text-sm">Feedback submitted successfully.</p>
              )}
              <form onSubmit={handleSubmitFeedback} className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
                <div>
                  <label className="block text-xs text-[#888888] mb-1">Assessment Comment</label>
                  <textarea
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    rows={3}
                    required
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#209dd7]"
                    placeholder="Provide your assessment of the RCA..."
                  />
                </div>
                <div>
                  <label className="block text-xs text-[#888888] mb-1">
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
                  <div className="flex justify-between text-[10px] text-[#888888]">
                    <span>0</span>
                    <span>100</span>
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-5 py-2 bg-[#753991] text-white rounded-lg text-sm hover:bg-[#5e2d74] transition-colors disabled:opacity-50"
                >
                  {submitting ? "Submitting..." : "Submit Feedback"}
                </button>
              </form>
            </section>
          </div>
        )}
      </div>
      </div>
      )}

      {/* Retry Run Details Popup */}
      {retryRunPopup && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto mx-4">
            {/* Popup Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-[#032147] rounded-t-xl">
              <div>
                <h2 className="text-base font-bold text-white">Retry Run Details</h2>
                <p className="text-xs text-[#209dd7] mt-0.5">
                  {retryRunPopup.level}
                  {retryRunPopup.completedAt ? ` — ${new Date(retryRunPopup.completedAt).toLocaleString()}` : ""}
                </p>
              </div>
              <button
                onClick={() => setRetryRunPopup(null)}
                className="text-white/70 hover:text-white text-lg font-bold leading-none px-2"
                aria-label="Close"
              >
                &times;
              </button>
            </div>

            <div className="p-6 space-y-5">
              {retryRunPopupLoading ? (
                <p className="text-[#888888] text-sm">Loading run details...</p>
              ) : !retryRunPopup.data ? (
                <p className="text-[#888888] text-sm">No run output available for this retry. The run may not have completed all stages yet.</p>
              ) : (
                <>
                  {/* SOP Matched */}
                  {retryRunPopup.data.sop_id && (
                    <section>
                      <h3 className="text-sm font-bold text-[#032147] mb-2">SOP Matched</h3>
                      <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                        <span className="text-xs text-[#888888]">SOP ID</span>
                        <p className="font-mono text-sm mt-0.5">{retryRunPopup.data.sop_id}</p>
                      </div>
                    </section>
                  )}

                  {/* Classifier Match */}
                  {retryRunPopup.data.classifier_match && (
                    <section>
                      <div className="flex items-center gap-3 mb-2">
                        <h3 className="text-sm font-bold text-[#032147]">Dynamic Classifiers</h3>
                        {retryRunPopup.data.classifier_match.mapping_score != null && (
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            retryRunPopup.data.classifier_match.mapping_score >= 70 ? "bg-green-100 text-green-700"
                              : retryRunPopup.data.classifier_match.mapping_score >= 40 ? "bg-yellow-100 text-yellow-700"
                              : "bg-red-100 text-red-700"
                          }`}>
                            Score: {retryRunPopup.data.classifier_match.mapping_score}%
                          </span>
                        )}
                      </div>
                      <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                        {retryRunPopup.data.classifier_match.match_detail?.length > 0 ? (
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="text-[#888888] border-b border-gray-100">
                                <th className="text-left py-1">Field</th>
                                <th className="text-left py-1">Expected</th>
                                <th className="text-left py-1">Extracted</th>
                                <th className="text-left py-1 w-12">Match</th>
                              </tr>
                            </thead>
                            <tbody>
                              {retryRunPopup.data.classifier_match.match_detail.map((md: any, i: number) => (
                                <tr key={i} className="border-t border-gray-50">
                                  <td className="py-1 font-medium">{md.field_name}</td>
                                  <td className="py-1">{md.expected || "\u2014"}</td>
                                  <td className="py-1">{md.actual || "\u2014"}</td>
                                  <td className="py-1">
                                    <span className={`px-1 py-0.5 rounded text-[9px] font-medium ${md.match ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                                      {md.match ? "Yes" : "No"}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        ) : (
                          <p className="text-xs text-[#888888]">No classifier detail available.</p>
                        )}
                      </div>
                    </section>
                  )}

                  {/* RCA Output */}
                  <section>
                    <h3 className="text-sm font-bold text-[#032147] mb-2">Root Cause Analysis</h3>
                    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-3">
                      {retryRunPopup.data.root_cause && (
                        <div>
                          <span className="text-[10px] font-semibold text-[#888888] uppercase">Root Cause</span>
                          <p className="text-sm mt-0.5">{toText(retryRunPopup.data.root_cause)}</p>
                        </div>
                      )}
                      {retryRunPopup.data.impact && (
                        <div>
                          <span className="text-[10px] font-semibold text-[#888888] uppercase">Impact</span>
                          <p className="text-sm mt-0.5">{toText(retryRunPopup.data.impact)}</p>
                        </div>
                      )}
                      {retryRunPopup.data.recommendation && (
                        <div>
                          <span className="text-[10px] font-semibold text-[#888888] uppercase">Recommendation</span>
                          <p className="text-sm mt-0.5">{toText(retryRunPopup.data.recommendation)}</p>
                        </div>
                      )}
                      {!retryRunPopup.data.root_cause && !retryRunPopup.data.impact && !retryRunPopup.data.recommendation && (
                        <p className="text-xs text-[#888888]">RCA output not yet available for this run.</p>
                      )}
                    </div>
                  </section>

                  {/* Validation */}
                  {(retryRunPopup.data.validation_assessment || retryRunPopup.data.confidence_score != null) && (
                    <section>
                      <h3 className="text-sm font-bold text-[#032147] mb-2">Validation</h3>
                      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-2">
                        {retryRunPopup.data.validation_assessment && (
                          <p className="text-sm">{retryRunPopup.data.validation_assessment}</p>
                        )}
                        {retryRunPopup.data.confidence_score != null && (
                          <div className="flex items-center gap-2 mt-1">
                            <span className="text-xs text-[#888888]">Confidence Score:</span>
                            <span className="px-3 py-0.5 bg-[#ecad0a] text-[#032147] font-bold rounded-full text-sm">
                              {retryRunPopup.data.confidence_score}%
                            </span>
                          </div>
                        )}
                      </div>
                    </section>
                  )}
                </>
              )}
            </div>

            <div className="px-6 py-4 border-t border-gray-100 flex justify-end">
              <button
                onClick={() => setRetryRunPopup(null)}
                className="px-5 py-2 bg-[#753991] text-white rounded text-sm hover:bg-[#5e2d74] transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
