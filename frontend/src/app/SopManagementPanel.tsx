"use client";

import { useState, useEffect, useRef } from "react";
import {
  fetchSopMappings,
  fetchSopWorkflow,
  createSopMapping,
  updateClassifier,
  updateWorkflow,
  updateDocFile,
  fetchTools,
  fetchToolSource,
  fetchToolHistory,
  type ToolDef,
  type ToolHistoryEntry,
} from "@/lib/api";

// ──────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────
interface DynamicClassifier {
  label: string;
  field_name: string;
  field_value: string;
}

interface SopMapping {
  sop_id: string;
  name: string;
  application: string;
  domain: string;
  category: string;
  severity: string;
  sop_document_file: string;
  workflow_file: string;
  sop_document_id?: string;
  workflow_id?: string;
  seeded?: boolean;
  dynamic_classifiers?: DynamicClassifier[];
}

interface SectionMsg {
  type: "success" | "error";
  text: string;
}

// ──────────────────────────────────────────────────────────────
// SectionHeader — title + Edit / Save / Cancel controls
// ──────────────────────────────────────────────────────────────
function SectionHeader({
  title,
  editing,
  saving,
  onEdit,
  onSave,
  onCancel,
}: {
  title: string;
  editing: boolean;
  saving: boolean;
  onEdit: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-sm font-semibold text-[#032147] uppercase tracking-wide">{title}</h3>
      <div className="flex gap-2">
        {!editing ? (
          <button
            onClick={onEdit}
            className="px-3 py-1 text-xs border border-[#209dd7] text-[#209dd7] rounded hover:bg-[#209dd7] hover:text-white transition-colors"
          >
            Edit
          </button>
        ) : (
          <>
            <button
              onClick={onSave}
              disabled={saving}
              className="px-3 py-1 text-xs bg-[#753991] text-white rounded hover:bg-[#5e2d74] transition-colors disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              onClick={onCancel}
              disabled={saving}
              className="px-3 py-1 text-xs border border-gray-300 text-[#888888] rounded hover:border-[#209dd7] transition-colors"
            >
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// MessageBanner
// ──────────────────────────────────────────────────────────────
function MessageBanner({ msg }: { msg: SectionMsg | null }) {
  if (!msg) return null;
  return (
    <p
      className={`text-xs px-3 py-2 rounded mb-3 ${
        msg.type === "success"
          ? "bg-green-50 text-green-700 border border-green-200"
          : "bg-red-50 text-red-700 border border-red-200"
      }`}
    >
      {msg.text}
    </p>
  );
}

// ──────────────────────────────────────────────────────────────
// Section 1 — SOP File Mapping
// ──────────────────────────────────────────────────────────────
function FileMappingSection({
  mapping,
  onWorkflowFileContent,
  onSaved,
}: {
  mapping: SopMapping;
  onWorkflowFileContent: (content: string) => void;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<SectionMsg | null>(null);
  const [docFile, setDocFile] = useState<File | null>(null);
  const docInputRef = useRef<HTMLInputElement>(null);
  const wfInputRef = useRef<HTMLInputElement>(null);

  function reset() {
    setDocFile(null);
    if (docInputRef.current) docInputRef.current.value = "";
    if (wfInputRef.current) wfInputRef.current.value = "";
  }

  function handleCancel() {
    reset();
    setEditing(false);
    setMsg(null);
  }

  async function handleSave() {
    if (!docFile) {
      setMsg({ type: "error", text: "Please select a new SOP document file to upload." });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      await updateDocFile(mapping.sop_id, docFile);
      setMsg({ type: "success", text: "SOP document file updated successfully." });
      setEditing(false);
      reset();
      onSaved();
    } catch (e: any) {
      setMsg({ type: "error", text: e.message || "Failed to update doc file." });
    }
    setSaving(false);
  }

  function handleWfFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      onWorkflowFileContent(text);
    };
    reader.readAsText(file);
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
      <SectionHeader
        title="SOP File Mapping"
        editing={editing}
        saving={saving}
        onEdit={() => { setEditing(true); setMsg(null); }}
        onSave={handleSave}
        onCancel={handleCancel}
      />
      <MessageBanner msg={msg} />
      {!editing ? (
        <div className="space-y-2">
          <div>
            <span className="text-[#888888] text-xs">SOP Document File</span>
            <p className="text-sm font-mono">{mapping.sop_document_file || "—"}</p>
          </div>
          <div>
            <span className="text-[#888888] text-xs">Workflow File</span>
            <p className="text-sm font-mono">{mapping.workflow_file || "—"}</p>
          </div>
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <div>
            <label className="block text-xs text-[#888888] mb-1">
              New SOP Document File <span className="text-[#888888]">(txt / pdf / docx)</span>
            </label>
            <input
              ref={docInputRef}
              type="file"
              accept=".txt,.pdf,.docx"
              onChange={(e) => setDocFile(e.target.files?.[0] ?? null)}
              className="block w-full text-xs text-[#032147] file:mr-3 file:py-1 file:px-3 file:border file:border-[#209dd7] file:rounded file:text-xs file:text-[#209dd7] file:bg-white hover:file:bg-blue-50"
            />
          </div>
          <div>
            <label className="block text-xs text-[#888888] mb-1">
              New Workflow JSON File{" "}
              <span className="text-[#888888]">(selecting fills the JSON editor below — save via Section 2.2)</span>
            </label>
            <input
              ref={wfInputRef}
              type="file"
              accept=".json"
              onChange={handleWfFileSelect}
              className="block w-full text-xs text-[#032147] file:mr-3 file:py-1 file:px-3 file:border file:border-[#209dd7] file:rounded file:text-xs file:text-[#209dd7] file:bg-white hover:file:bg-blue-50"
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Section 2 — Workflow JSON Editor
// ──────────────────────────────────────────────────────────────
function WorkflowEditorSection({
  sopId,
  preloadContent,
  onClearPreload,
}: {
  sopId: string;
  preloadContent: string | null;
  onClearPreload: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<SectionMsg | null>(null);
  const [workflow, setWorkflow] = useState<object | null>(null);
  const [loadingWf, setLoadingWf] = useState(true);
  const [editorText, setEditorText] = useState("");

  useEffect(() => {
    setLoadingWf(true);
    fetchSopWorkflow(sopId)
      .then((data) => {
        setWorkflow(data);
        setEditorText(JSON.stringify(data, null, 2));
      })
      .catch(() => {
        setWorkflow(null);
        setEditorText("");
      })
      .finally(() => setLoadingWf(false));
  }, [sopId]);

  // When a workflow file is selected in Section 1, pre-populate the editor
  useEffect(() => {
    if (preloadContent !== null) {
      setEditorText(preloadContent);
      setEditing(true);
      onClearPreload();
    }
  }, [preloadContent, onClearPreload]);

  function handleCancel() {
    setEditorText(workflow ? JSON.stringify(workflow, null, 2) : "");
    setEditing(false);
    setMsg(null);
  }

  async function handleSave() {
    let parsed: object;
    try {
      parsed = JSON.parse(editorText);
    } catch {
      setMsg({ type: "error", text: "Invalid JSON — please fix syntax errors before saving." });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      await updateWorkflow(sopId, parsed);
      setWorkflow(parsed);
      setMsg({ type: "success", text: "Workflow JSON saved successfully." });
      setEditing(false);
    } catch (e: any) {
      setMsg({ type: "error", text: e.message || "Failed to save workflow." });
    }
    setSaving(false);
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
      <SectionHeader
        title="Workflow JSON Editor"
        editing={editing}
        saving={saving}
        onEdit={() => { setEditing(true); setMsg(null); }}
        onSave={handleSave}
        onCancel={handleCancel}
      />
      <MessageBanner msg={msg} />
      {loadingWf ? (
        <p className="text-xs text-[#888888]">Loading workflow…</p>
      ) : !editing ? (
        <pre className="bg-gray-50 rounded p-3 text-[11px] font-mono overflow-x-auto max-h-72 overflow-y-auto border border-gray-100">
          {workflow ? JSON.stringify(workflow, null, 2) : "No workflow found."}
        </pre>
      ) : (
        <textarea
          value={editorText}
          onChange={(e) => setEditorText(e.target.value)}
          rows={20}
          spellCheck={false}
          className="w-full font-mono text-[11px] p-3 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-[#209dd7] bg-gray-50 resize-y"
        />
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Section 3 — Alert Classifier
// ──────────────────────────────────────────────────────────────
const EMPTY_DCS: DynamicClassifier[] = Array.from({ length: 7 }, (_, i) => ({
  label: String(i + 1),
  field_name: "",
  field_value: "",
}));

function ensureDcs(dcs?: DynamicClassifier[]): DynamicClassifier[] {
  if (!dcs || dcs.length === 0) return EMPTY_DCS.map((d) => ({ ...d }));
  const result = dcs.map((d) => ({ ...d }));
  while (result.length < 7) result.push({ label: String(result.length + 1), field_name: "", field_value: "" });
  return result.slice(0, 7);
}

function ClassifierSection({
  mapping,
  onSaved,
}: {
  mapping: SopMapping;
  onSaved: (updated: Partial<SopMapping>) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<SectionMsg | null>(null);
  const [form, setForm] = useState({
    name: mapping.name,
    application: mapping.application,
    domain: mapping.domain,
    category: mapping.category,
    severity: mapping.severity,
  });
  const [dynForm, setDynForm] = useState<DynamicClassifier[]>(ensureDcs(mapping.dynamic_classifiers));

  useEffect(() => {
    setForm({
      name: mapping.name,
      application: mapping.application,
      domain: mapping.domain,
      category: mapping.category,
      severity: mapping.severity,
    });
    setDynForm(ensureDcs(mapping.dynamic_classifiers));
  }, [mapping]);

  function handleCancel() {
    setForm({
      name: mapping.name,
      application: mapping.application,
      domain: mapping.domain,
      category: mapping.category,
      severity: mapping.severity,
    });
    setDynForm(ensureDcs(mapping.dynamic_classifiers));
    setEditing(false);
    setMsg(null);
  }

  async function handleSave() {
    setSaving(true);
    setMsg(null);
    try {
      await updateClassifier(mapping.sop_id, { ...form, dynamic_classifiers: dynForm });
      setMsg({ type: "success", text: "Classifier metadata saved successfully." });
      setEditing(false);
      onSaved({ ...form, dynamic_classifiers: dynForm });
    } catch (e: any) {
      setMsg({ type: "error", text: e.message || "Failed to save classifier." });
    }
    setSaving(false);
  }

  function updateDyn(idx: number, field: "field_name" | "field_value", value: string) {
    setDynForm((prev) => prev.map((d, i) => (i === idx ? { ...d, [field]: value } : d)));
  }

  const fields: { key: keyof typeof form; label: string }[] = [
    { key: "name", label: "Alert Name" },
    { key: "application", label: "Application" },
    { key: "domain", label: "Domain" },
    { key: "category", label: "Category" },
    { key: "severity", label: "Severity" },
  ];

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
      <SectionHeader
        title="Alert Classifier"
        editing={editing}
        saving={saving}
        onEdit={() => { setEditing(true); setMsg(null); }}
        onSave={handleSave}
        onCancel={handleCancel}
      />
      <MessageBanner msg={msg} />

      {/* Static classifiers */}
      <div className="grid grid-cols-2 gap-3">
        {fields.map(({ key, label }) => (
          <div key={key}>
            <span className="block text-xs text-[#888888] mb-1">{label}</span>
            {!editing ? (
              <p className="text-sm font-medium">{form[key] || "\u2014"}</p>
            ) : (
              <input
                type="text"
                value={form[key]}
                onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
              />
            )}
          </div>
        ))}
      </div>

      {/* Dynamic classifiers */}
      <div className="mt-4 pt-3 border-t border-gray-100">
        <h4 className="text-xs font-semibold text-[#032147] uppercase tracking-wide mb-2">Dynamic Classifiers</h4>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-[#888888]">
              <th className="text-left py-1 w-10">#</th>
              <th className="text-left py-1">Field Name</th>
              <th className="text-left py-1">Field Value</th>
            </tr>
          </thead>
          <tbody>
            {dynForm.map((dc, idx) => (
              <tr key={dc.label} className="border-t border-gray-50">
                <td className="py-1.5 text-xs text-[#888888] font-mono">{dc.label}</td>
                {!editing ? (
                  <>
                    <td className="py-1.5 text-sm">{dc.field_name || "\u2014"}</td>
                    <td className="py-1.5 text-sm">{dc.field_value || "\u2014"}</td>
                  </>
                ) : (
                  <>
                    <td className="py-1 pr-2">
                      <input
                        type="text"
                        value={dc.field_name}
                        onChange={(e) => updateDyn(idx, "field_name", e.target.value)}
                        placeholder="field name"
                        className="w-full px-2 py-1 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                      />
                    </td>
                    <td className="py-1">
                      <input
                        type="text"
                        value={dc.field_value}
                        onChange={(e) => updateDyn(idx, "field_value", e.target.value)}
                        placeholder="field value"
                        className="w-full px-2 py-1 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                      />
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Add New SOP Panel
// ──────────────────────────────────────────────────────────────
function AddSopPanel({
  onCreated,
  onCancel,
}: {
  onCreated: (sopId: string) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({
    sop_id: "",
    name: "",
    application: "",
    domain: "",
    category: "",
    severity: "",
  });
  const [docFile, setDocFile] = useState<File | null>(null);
  const [wfFile, setWfFile] = useState<File | null>(null);
  const [dynForm, setDynForm] = useState<DynamicClassifier[]>(EMPTY_DCS.map((d) => ({ ...d })));
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<SectionMsg | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!docFile || !wfFile) {
      setMsg({ type: "error", text: "Both SOP document file and workflow JSON file are required." });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const fd = new FormData();
      Object.entries(form).forEach(([k, v]) => fd.append(k, v));
      fd.append("doc_file", docFile);
      fd.append("workflow_file", wfFile);
      fd.append("dynamic_classifiers", JSON.stringify(dynForm));
      await createSopMapping(fd);
      setMsg({ type: "success", text: `SOP '${form.sop_id}' created successfully.` });
      setTimeout(() => onCreated(form.sop_id), 600);
    } catch (e: any) {
      setMsg({ type: "error", text: e.message || "Failed to create SOP." });
    }
    setSaving(false);
  }

  const textFields: { key: keyof typeof form; label: string; required?: boolean }[] = [
    { key: "sop_id", label: "SOP ID", required: true },
    { key: "name", label: "SOP Name", required: true },
    { key: "application", label: "Application" },
    { key: "domain", label: "Domain" },
    { key: "category", label: "Category" },
    { key: "severity", label: "Severity" },
  ];

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-lg font-bold text-[#032147]">Add New SOP</h2>
        <button
          onClick={onCancel}
          className="px-3 py-1 text-xs border border-gray-300 text-[#888888] rounded hover:border-[#209dd7] transition-colors"
        >
          Cancel
        </button>
      </div>
      <MessageBanner msg={msg} />
      <form onSubmit={handleCreate} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          {textFields.map(({ key, label, required }) => (
            <div key={key}>
              <label className="block text-xs text-[#888888] mb-1">
                {label} {required && <span className="text-red-500">*</span>}
              </label>
              <input
                type="text"
                required={required}
                value={form[key]}
                onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
              />
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-[#888888] mb-1">
              SOP Document File <span className="text-red-500">*</span>{" "}
              <span className="text-[#888888]">(txt / pdf / docx)</span>
            </label>
            <input
              type="file"
              required
              accept=".txt,.pdf,.docx"
              onChange={(e) => setDocFile(e.target.files?.[0] ?? null)}
              className="block w-full text-xs text-[#032147] file:mr-3 file:py-1 file:px-3 file:border file:border-[#209dd7] file:rounded file:text-xs file:text-[#209dd7] file:bg-white hover:file:bg-blue-50"
            />
          </div>
          <div>
            <label className="block text-xs text-[#888888] mb-1">
              Workflow JSON File <span className="text-red-500">*</span>
            </label>
            <input
              type="file"
              required
              accept=".json"
              onChange={(e) => setWfFile(e.target.files?.[0] ?? null)}
              className="block w-full text-xs text-[#032147] file:mr-3 file:py-1 file:px-3 file:border file:border-[#209dd7] file:rounded file:text-xs file:text-[#209dd7] file:bg-white hover:file:bg-blue-50"
            />
          </div>
        </div>

        {/* Dynamic Classifiers */}
        <div className="border border-gray-200 rounded-lg p-3">
          <h4 className="text-xs font-semibold text-[#032147] uppercase tracking-wide mb-2">Dynamic Classifiers</h4>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-[#888888]">
                <th className="text-left py-1 w-10">#</th>
                <th className="text-left py-1">Field Name</th>
                <th className="text-left py-1">Field Value</th>
              </tr>
            </thead>
            <tbody>
              {dynForm.map((dc, idx) => (
                <tr key={dc.label} className="border-t border-gray-50">
                  <td className="py-1 text-xs text-[#888888] font-mono">{dc.label}</td>
                  <td className="py-1 pr-2">
                    <input
                      type="text"
                      value={dc.field_name}
                      onChange={(e) => setDynForm((prev) => prev.map((d, i) => (i === idx ? { ...d, field_name: e.target.value } : d)))}
                      placeholder="field name"
                      className="w-full px-2 py-1 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                    />
                  </td>
                  <td className="py-1">
                    <input
                      type="text"
                      value={dc.field_value}
                      onChange={(e) => setDynForm((prev) => prev.map((d, i) => (i === idx ? { ...d, field_value: e.target.value } : d)))}
                      placeholder="field value"
                      className="w-full px-2 py-1 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex gap-3 pt-2">
          <button
            type="submit"
            disabled={saving}
            className="px-5 py-2 bg-[#753991] text-white rounded-lg text-sm hover:bg-[#5e2d74] transition-colors disabled:opacity-50"
          >
            {saving ? "Creating…" : "Create SOP"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="px-5 py-2 border border-gray-300 text-[#888888] rounded-lg text-sm hover:border-[#209dd7] transition-colors"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Source Code Modal
// ──────────────────────────────────────────────────────────────
function SourceModal({
  tool,
  version,
  source,
  onClose,
}: {
  tool: string;
  version: string;
  source: string;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-[80vw] max-w-4xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200">
          <div>
            <span className="font-mono text-sm font-semibold text-[#209dd7]">{tool}</span>
            <span className="ml-2 text-xs px-2 py-0.5 rounded bg-[#032147] text-white font-mono">
              v{version}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-[#888888] hover:text-[#032147] text-xl leading-none"
          >
            &times;
          </button>
        </div>
        <pre className="flex-1 overflow-auto p-4 text-[11px] font-mono bg-gray-950 text-green-300 rounded-b-xl">
          {source || "// No source code stored."}
        </pre>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Tool Registry Panel
// ──────────────────────────────────────────────────────────────
const TECH_COLORS: Record<string, string> = {
  python_script: "bg-blue-100 text-blue-700",
  shell_script: "bg-yellow-100 text-yellow-800",
  mcp_client: "bg-purple-100 text-purple-700",
};

function techBadge(tech: string) {
  return TECH_COLORS[tech] || "bg-gray-100 text-gray-600";
}

function ToolRegistryPanel() {
  const [tools, setTools] = useState<ToolDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [selectedTool, setSelectedTool] = useState<ToolDef | null>(null);
  const [history, setHistory] = useState<ToolHistoryEntry[]>([]);
  const [histLoading, setHistLoading] = useState(false);
  const [modal, setModal] = useState<{ source: string; tool: string; version: string } | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchTools()
      .then(setTools)
      .catch(() => setTools([]))
      .finally(() => setLoading(false));
  }, []);

  function selectTool(tool: ToolDef) {
    setSelectedTool(tool);
    setHistory([]);
    setHistLoading(true);
    fetchToolHistory(tool.tool)
      .then(setHistory)
      .catch(() => setHistory([]))
      .finally(() => setHistLoading(false));
  }

  async function openSource(toolName: string, version: string) {
    setSourceLoading(true);
    try {
      const data = await fetchToolSource(toolName);
      setModal({ source: data.source_code, tool: toolName, version });
    } catch {
      setModal({ source: "// Failed to load source.", tool: toolName, version });
    }
    setSourceLoading(false);
  }

  const filtered = tools.filter(
    (t) =>
      t.tool.toLowerCase().includes(filter.toLowerCase()) ||
      t.description.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="flex h-[calc(100vh-104px)] gap-0">
      {/* LEFT — tool list */}
      <div className="w-1/3 min-w-[260px] flex flex-col border-r border-gray-200 bg-white">
        <div className="p-4 border-b border-gray-200">
          <h3 className="text-sm font-bold text-[#032147] mb-3 uppercase tracking-wide">
            Registered Tools
          </h3>
          <input
            type="text"
            placeholder="Filter tools…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
          />
        </div>
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <p className="text-[#888888] p-4 text-sm">Loading…</p>
          ) : filtered.length === 0 ? (
            <p className="text-[#888888] p-4 text-sm">No tools found.</p>
          ) : (
            <div className="divide-y divide-gray-100">
              {filtered.map((t) => (
                <button
                  key={t.tool}
                  onClick={() => selectTool(t)}
                  className={`w-full text-left px-4 py-3 hover:bg-blue-50 transition-colors ${
                    selectedTool?.tool === t.tool ? "bg-blue-50 border-l-4 border-[#209dd7]" : ""
                  }`}
                >
                  <p className="font-mono text-sm font-semibold text-[#209dd7]">{t.tool}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[10px] font-mono text-[#888888]">v{t.tool_version}</span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${techBadge(t.tool_tech)}`}
                    >
                      {t.tool_tech}
                    </span>
                  </div>
                  <p className="text-xs text-[#888888] mt-0.5 truncate">{t.description}</p>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* RIGHT — tool detail */}
      <div className="w-2/3 overflow-y-auto bg-[#f8f9fb] p-6">
        {!selectedTool ? (
          <div className="flex items-center justify-center h-full text-[#888888]">
            <p>Select a tool from the list to view details</p>
          </div>
        ) : (
          <>
            {/* Header */}
            <div className="flex items-start justify-between mb-5">
              <div>
                <h2 className="text-xl font-bold text-[#032147] font-mono">{selectedTool.tool}</h2>
                <p className="text-sm text-[#888888] mt-1">{selectedTool.description}</p>
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-xs font-mono bg-[#032147] text-white px-2 py-0.5 rounded">
                    v{selectedTool.tool_version}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${techBadge(selectedTool.tool_tech)}`}>
                    {selectedTool.tool_tech}
                  </span>
                </div>
              </div>
              <button
                disabled={sourceLoading}
                onClick={() => openSource(selectedTool.tool, selectedTool.tool_version)}
                className="px-4 py-2 text-sm bg-[#209dd7] text-white rounded-lg hover:bg-[#1a7fb0] transition-colors disabled:opacity-50"
              >
                {sourceLoading ? "Loading…" : "View Source"}
              </button>
            </div>

            {/* Source file */}
            {selectedTool.source_file && (
              <div className="bg-white border border-gray-200 rounded-lg px-4 py-3 mb-4">
                <span className="text-xs text-[#888888]">Source File</span>
                <p className="text-sm font-mono text-[#032147] mt-0.5">{selectedTool.source_file}</p>
              </div>
            )}

            {/* Parameters */}
            <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
              <h3 className="text-sm font-semibold text-[#032147] uppercase tracking-wide mb-3">
                Parameters
              </h3>
              {selectedTool.tool_params.length === 0 ? (
                <p className="text-xs text-[#888888]">No parameters defined.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-[#888888]">
                      <th className="text-left py-1">Name</th>
                      <th className="text-left py-1">Required</th>
                      <th className="text-left py-1">Default</th>
                      <th className="text-left py-1">Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedTool.tool_params.map((p) => (
                      <tr key={p.name} className="border-t border-gray-50">
                        <td className="py-2 font-mono text-xs text-[#209dd7]">{p.name}</td>
                        <td className="py-2">
                          {p.required ? (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-medium">
                              required
                            </span>
                          ) : (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
                              optional
                            </span>
                          )}
                        </td>
                        <td className="py-2 font-mono text-xs text-[#888888]">{p.default ?? "—"}</td>
                        <td className="py-2 text-xs text-[#888888]">{p.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* Version History */}
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-[#032147] uppercase tracking-wide mb-3">
                Version History
              </h3>
              {histLoading ? (
                <p className="text-xs text-[#888888]">Loading history…</p>
              ) : history.length === 0 ? (
                <p className="text-xs text-[#888888]">No history available.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-[#888888]">
                      <th className="text-left py-1">Version</th>
                      <th className="text-left py-1">Change</th>
                      <th className="text-left py-1">By</th>
                      <th className="text-left py-1">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h, i) => (
                      <tr key={i} className="border-t border-gray-50">
                        <td className="py-2 font-mono text-xs">v{h.tool_version}</td>
                        <td className="py-2 text-xs text-[#888888]">{h.change_type}</td>
                        <td className="py-2 text-xs text-[#888888]">{h.changed_by}</td>
                        <td className="py-2 text-xs text-[#888888]">
                          {h.archived_at ? new Date(h.archived_at).toLocaleDateString() : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>

      {/* Source Code Modal */}
      {modal && (
        <SourceModal
          tool={modal.tool}
          version={modal.version}
          source={modal.source}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Main SopManagementPanel
// ──────────────────────────────────────────────────────────────
export default function SopManagementPanel() {
  const [subTab, setSubTab] = useState<"sop" | "tools">("sop");
  const [mappings, setMappings] = useState<SopMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [selectedSopId, setSelectedSopId] = useState<string | null>(null);
  const [addingNew, setAddingNew] = useState(false);
  const [wfPreload, setWfPreload] = useState<string | null>(null);

  function loadMappings(selectId?: string) {
    setLoading(true);
    fetchSopMappings()
      .then((data) => {
        setMappings(data);
        if (selectId) setSelectedSopId(selectId);
      })
      .catch(() => setMappings([]))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadMappings();
  }, []);

  const filtered = mappings.filter(
    (m) =>
      m.sop_id.toLowerCase().includes(filter.toLowerCase()) ||
      (m.name || "").toLowerCase().includes(filter.toLowerCase())
  );

  const selectedMapping = mappings.find((m) => m.sop_id === selectedSopId) ?? null;

  function handleClassifierSaved(updated: Partial<SopMapping>) {
    setMappings((prev) =>
      prev.map((m) => (m.sop_id === selectedSopId ? { ...m, ...updated } : m))
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]">
      {/* Sub-tab bar */}
      <div className="flex border-b border-gray-200 bg-white px-4 pt-3">
        {(["sop", "tools"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setSubTab(tab)}
            className={`px-5 py-2 text-sm font-medium border-b-2 transition-colors mr-1 ${
              subTab === tab
                ? "border-[#209dd7] text-[#209dd7]"
                : "border-transparent text-[#888888] hover:text-[#032147]"
            }`}
          >
            {tab === "sop" ? "SOP Registry" : "Tool Registry"}
          </button>
        ))}
      </div>

      {/* Tool Registry sub-tab */}
      {subTab === "tools" && <ToolRegistryPanel />}

      {/* SOP Registry sub-tab */}
      {subTab === "sop" && (
    <div className="flex flex-1 gap-0 overflow-hidden">
      {/* LEFT PANEL */}
      <div className="w-1/3 min-w-[280px] flex flex-col border-r border-gray-200 bg-white">
        <div className="p-4 border-b border-gray-200">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-bold text-[#032147]">SOP IDs</h2>
            <button
              onClick={() => { setAddingNew(true); setSelectedSopId(null); }}
              className="px-3 py-1 text-xs bg-[#209dd7] text-white rounded hover:bg-[#1a7fb0] transition-colors"
            >
              + Add New
            </button>
          </div>
          <input
            type="text"
            placeholder="Filter by SOP ID or name…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
          />
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <p className="text-[#888888] p-4 text-sm">Loading…</p>
          ) : filtered.length === 0 ? (
            <p className="text-[#888888] p-4 text-sm">No SOPs found.</p>
          ) : (
            <div className="divide-y divide-gray-100">
              {filtered.map((m) => (
                <button
                  key={m.sop_id}
                  onClick={() => { setSelectedSopId(m.sop_id); setAddingNew(false); }}
                  className={`w-full text-left px-4 py-3 hover:bg-blue-50 transition-colors ${
                    selectedSopId === m.sop_id && !addingNew
                      ? "bg-blue-50 border-l-4 border-[#209dd7]"
                      : ""
                  }`}
                >
                  <p className="font-mono text-sm font-semibold text-[#209dd7]">{m.sop_id}</p>
                  <p className="text-xs text-[#888888] truncate">{m.name}</p>
                  {m.seeded && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#ecad0a] text-[#032147] font-medium">
                      seeded
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* RIGHT PANEL */}
      <div className="w-2/3 overflow-y-auto bg-[#f8f9fb]">
        {addingNew ? (
          <AddSopPanel
            onCreated={(sopId) => {
              setAddingNew(false);
              loadMappings(sopId);
            }}
            onCancel={() => setAddingNew(false)}
          />
        ) : !selectedMapping ? (
          <div className="flex items-center justify-center h-full text-[#888888]">
            <p>Select a SOP ID from the list to view details</p>
          </div>
        ) : (
          <div className="p-6">
            <div className="mb-5">
              <h2 className="text-xl font-bold text-[#032147]">{selectedMapping.sop_id}</h2>
              <p className="text-sm text-[#888888]">{selectedMapping.name}</p>
            </div>

            <FileMappingSection
              mapping={selectedMapping}
              onWorkflowFileContent={(content) => setWfPreload(content)}
              onSaved={() => loadMappings(selectedSopId ?? undefined)}
            />

            <WorkflowEditorSection
              sopId={selectedMapping.sop_id}
              preloadContent={wfPreload}
              onClearPreload={() => setWfPreload(null)}
            />

            <ClassifierSection
              mapping={selectedMapping}
              onSaved={handleClassifierSaved}
            />
          </div>
        )}
      </div>
    </div>
      )}
    </div>
  );
}
