const API = process.env.NEXT_PUBLIC_API_URL || "";

export interface AlertFilters {
  application?: string;
  domain?: string;
  category?: string;
  severity?: string;
  sop_id?: string;
  processing_status?: string;
  feedback_received?: boolean;
  root_cause?: string;
  date_from?: string;
  date_to?: string;
  alert_id?: string;
  skip?: number;
  limit?: number;
}

export async function fetchAlerts(filters: AlertFilters = {}) {
  const params = new URLSearchParams();
  if (filters.skip != null) params.set("skip", String(filters.skip));
  if (filters.limit != null) params.set("limit", String(filters.limit));
  if (filters.application) params.set("application", filters.application);
  if (filters.domain) params.set("domain", filters.domain);
  if (filters.category) params.set("category", filters.category);
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.sop_id) params.set("sop_id", filters.sop_id);
  if (filters.processing_status) params.set("processing_status", filters.processing_status);
  if (filters.feedback_received != null) params.set("feedback_received", String(filters.feedback_received));
  if (filters.root_cause) params.set("root_cause", filters.root_cause);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (filters.alert_id) params.set("alert_id", filters.alert_id);
  const res = await fetch(`${API}/api/alerts?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch alerts");
  return res.json();
}

function buildStatsParams(filters: AlertFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.application) params.set("application", filters.application);
  if (filters.domain) params.set("domain", filters.domain);
  if (filters.category) params.set("category", filters.category);
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.sop_id) params.set("sop_id", filters.sop_id);
  if (filters.processing_status) params.set("processing_status", filters.processing_status);
  if (filters.feedback_received != null) params.set("feedback_received", String(filters.feedback_received));
  if (filters.root_cause) params.set("root_cause", filters.root_cause);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (filters.alert_id) params.set("alert_id", filters.alert_id);
  return params;
}

export interface AlertStats {
  total: number;
  success: number;
  failed: number;
  incomplete: number;
  mean_processing_time_seconds: number | null;
  total_alerts?: number;
}

export async function fetchAlertStats(filters: AlertFilters = {}): Promise<AlertStats> {
  const params = buildStatsParams(filters);
  const res = await fetch(`${API}/api/alerts/stats?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch alert stats");
  return res.json();
}

export async function fetchRetryStats(filters: AlertFilters = {}): Promise<AlertStats> {
  const params = new URLSearchParams();
  if (filters.alert_id) params.set("alert_id", filters.alert_id);
  if (filters.application) params.set("application", filters.application);
  if (filters.domain) params.set("domain", filters.domain);
  if (filters.category) params.set("category", filters.category);
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  const res = await fetch(`${API}/api/retries/stats?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch retry stats");
  return res.json();
}

export async function fetchAlert(id: string) {
  const res = await fetch(`${API}/api/alerts/${id}`);
  if (!res.ok) throw new Error("Alert not found");
  return res.json();
}

export async function fetchRCA(alertId: string) {
  const res = await fetch(`${API}/api/rca/${alertId}`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchFeedback(alertId: string) {
  const res = await fetch(`${API}/api/feedback/${alertId}`);
  if (!res.ok) return [];
  return res.json();
}

export async function fetchClassifierMatchLog(alertId: string) {
  const res = await fetch(`${API}/api/alerts/${alertId}/classifier-match`);
  if (!res.ok) return null;
  return res.json();
}

export async function submitFeedback(alertId: string, comment: string, confidenceScore: number) {
  const res = await fetch(`${API}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ alert_id: alertId, comment, confidence_score: confidenceScore }),
  });
  if (!res.ok) throw new Error("Failed to submit feedback");
  return res.json();
}

// Retry APIs

export type RetryLevel = "level1" | "level2" | "level3" | "level4";

export async function submitRetry(alertIds: string[], retryLevel: RetryLevel, reason?: string) {
  const res = await fetch(`${API}/api/retries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ alert_ids: alertIds, retry_level: retryLevel, reason }),
  });
  if (!res.ok) throw new Error("Failed to submit retry");
  return res.json();
}

export async function fetchAlertRetryHistory(alertId: string) {
  const res = await fetch(`${API}/api/alerts/${alertId}/retries`);
  if (!res.ok) return { alert_id: alertId, retries: [] };
  return res.json();
}

export async function fetchRetryBatch(batchId: string) {
  const res = await fetch(`${API}/api/retries/${batchId}`);
  if (!res.ok) throw new Error("Retry batch not found");
  return res.json();
}

export async function fetchRetryRunOutput(alertId: string, batchId: string) {
  const res = await fetch(`${API}/api/retries/${batchId}/run-output?alert_id=${encodeURIComponent(alertId)}`);
  if (!res.ok) return null;
  return res.json();
}

// SOP Management

export async function fetchSopMappings(): Promise<any[]> {
  const res = await fetch(`${API}/api/sop-management/mappings`);
  if (!res.ok) throw new Error("Failed to fetch SOP mappings");
  return res.json();
}

export async function fetchSopWorkflow(sopId: string): Promise<any> {
  const res = await fetch(`${API}/api/sop-management/mappings/${encodeURIComponent(sopId)}/workflow`);
  if (!res.ok) throw new Error("Workflow not found");
  return res.json();
}

export async function createSopMapping(formData: FormData): Promise<any> {
  const res = await fetch(`${API}/api/sop-management/mappings`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to create SOP mapping");
  }
  return res.json();
}

export async function updateClassifier(sopId: string, data: Record<string, any>): Promise<any> {
  const res = await fetch(`${API}/api/sop-management/mappings/${encodeURIComponent(sopId)}/classifier`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to update classifier");
  }
  return res.json();
}

export async function updateWorkflow(sopId: string, workflowJson: object): Promise<void> {
  const res = await fetch(`${API}/api/sop-management/mappings/${encodeURIComponent(sopId)}/workflow`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(workflowJson),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to update workflow");
  }
}

export async function updateDocFile(sopId: string, file: File): Promise<void> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${API}/api/sop-management/mappings/${encodeURIComponent(sopId)}/doc-file`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to update doc file");
  }
}

// Tool Registry

export interface ToolParam {
  name: string;
  description: string;
  required: boolean;
  default: string | null;
}

export interface ToolDef {
  tool: string;
  tool_version: string;
  tool_tech: "python_script" | "shell_script" | "mcp_client" | string;
  description: string;
  tool_params: ToolParam[];
  source_file: string;
  change_type?: string;
  changed_by?: string;
  version_created_at?: string;
  created_at?: string;
}

export interface ToolHistoryEntry {
  tool: string;
  tool_version: string;
  archived_at: string;
  change_type: string;
  changed_by: string;
  snapshot: ToolDef;
}

export async function fetchTools(): Promise<ToolDef[]> {
  const res = await fetch(`${API}/api/tools`);
  if (!res.ok) throw new Error("Failed to fetch tools");
  return res.json();
}

export async function fetchToolSource(toolName: string): Promise<{ tool: string; tool_version: string; source_code: string }> {
  const res = await fetch(`${API}/api/tools/${encodeURIComponent(toolName)}/source`);
  if (!res.ok) throw new Error("Source not found");
  return res.json();
}

export async function fetchToolHistory(toolName: string): Promise<ToolHistoryEntry[]> {
  const res = await fetch(`${API}/api/tools/${encodeURIComponent(toolName)}/history`);
  if (!res.ok) return [];
  return res.json();
}

// Pending Actions

export interface PendingAction {
  _id: string;
  alert_id: string;
  step_id: number;
  section: string;
  tool: string;
  action: string;
  tool_params: Record<string, unknown>;
  status: string;
  result?: unknown;
}

export async function fetchPendingActions(alertId: string): Promise<PendingAction[]> {
  const res = await fetch(`${API}/api/alerts/${encodeURIComponent(alertId)}/pending-actions`);
  if (!res.ok) return [];
  return res.json();
}

export async function approvePendingAction(alertId: string, stepId: number): Promise<unknown> {
  const res = await fetch(
    `${API}/api/alerts/${encodeURIComponent(alertId)}/pending-actions/${stepId}/approve`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to approve action");
  return res.json();
}
