export type ResearchMode = "quick" | "deep";
export type FreshnessWindow = "6m" | "12m";
export type RunStatus = "queued" | "planning" | "researching" | "verifying" | "exporting" | "completed" | "failed";

export interface AgentRun {
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  message?: string | null;
}

export interface ResearchRun {
  id: string;
  company_name: string;
  department?: string | null;
  mode: ResearchMode;
  freshness_window: FreshnessWindow;
  status: RunStatus;
  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;
  progress: number;
  expected_duration_seconds?: number | null;
  workflow_profile?: string;
  run_notes?: string[];
  agents: AgentRun[];
  error?: string | null;
}

export interface RunHistoryItem {
  id: string;
  company_name: string;
  department?: string | null;
  mode: ResearchMode;
  freshness_window: FreshnessWindow;
  status: RunStatus;
  progress: number;
  created_at: string;
  completed_at?: string | null;
  has_report: boolean;
  claim_count: number;
  source_count: number;
  signal_count: number;
  table_row_count: number;
}

export interface ReportSection {
  id: string;
  title: string;
  summary: string;
  content: Record<string, unknown>;
  claim_ids: string[];
  confidence_score: number;
  status: "complete" | "partial" | "unavailable";
}

export interface Claim {
  id: string;
  text: string;
  section_id: string;
  claim_type: "fact" | "inference" | "recommendation" | "unavailable";
  evidence_source_ids: string[];
  confidence_score: number;
  verification_status: "pending" | "verified" | "rejected" | "unavailable";
}

export interface EvidenceSource {
  id: string;
  url: string;
  title: string;
  publisher?: string | null;
  published_at?: string | null;
  credibility: string;
  credibility_score: number;
  source_tier?: string | null;
  allowed_uses?: string[];
}

export interface EvidenceSignal {
  id: string;
  section_id: string;
  signal_type: string;
  title: string;
  detail: string;
  signal_strength: "exact" | "directional" | "inferred" | "unsupported";
  source_ids: string[];
  claim_ids: string[];
  confidence_score: number;
}

export interface EvidenceTableRow {
  id: string;
  table_name: string;
  row_type: "source" | "snapshot" | "claim" | "signal" | "extracted_value" | "section_summary" | "quality_check";
  section_id?: string | null;
  title: string;
  detail: string;
  normalized_fields: Record<string, unknown>;
  source_ids: string[];
  snapshot_ids: string[];
  claim_ids: string[];
  signal_ids: string[];
  extracted_value_ids: string[];
  confidence_score: number;
  include_in_analysis: boolean;
}

export interface ReportChatEvidenceRow {
  row_id: string;
  table_name: string;
  row_type: string;
  section_id?: string | null;
  title: string;
  detail: string;
  source_labels: string[];
  source_ids: string[];
  confidence_score: number;
  retrieval_scores?: {
    hybrid?: number | null;
    semantic?: number | null;
    keyword?: number | null;
  };
  normalized_fields: Record<string, unknown>;
}

export interface ReportChatResponse {
  id: string;
  parent_run_id: string;
  question: string;
  answer: string;
  source_ids: string[];
  evidence_rows: ReportChatEvidenceRow[];
  analytics: Record<string, unknown>;
  retrieval_mode: string;
  model?: string | null;
  provider: string;
  created_at: string;
}

export interface QualityCheck {
  name: string;
  passed: boolean;
  message: string;
  severity: "info" | "warning" | "blocker";
}

export interface AccountReport {
  run_id: string;
  company_name: string;
  department?: string | null;
  mode: ResearchMode;
  freshness_window: FreshnessWindow;
  sections: ReportSection[];
  claims: Claim[];
  sources: EvidenceSource[];
  evidence_signals?: EvidenceSignal[];
  evidence_table_rows?: EvidenceTableRow[];
  quality_checks: QualityCheck[];
}

declare global {
  interface Window {
    __APP_CONFIG__?: {
      apiBase?: string;
    };
  }
}

const API_BASE = window.__APP_CONFIG__?.apiBase || import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export async function createRun(companyName: string, mode: ResearchMode, freshnessWindow: FreshnessWindow, department?: string) {
  const trimmedDepartment = department?.trim();
  return request<ResearchRun>("/api/runs", {
    method: "POST",
    body: JSON.stringify({
      company_name: companyName,
      mode,
      freshness_window: freshnessWindow,
      department: trimmedDepartment || null
    })
  });
}

export async function getRun(runId: string) {
  return request<ResearchRun>(`/api/runs/${runId}`);
}

export async function getRunHistory() {
  return request<RunHistoryItem[]>("/api/runs/history");
}

export async function deleteRun(runId: string) {
  return request<{ deleted: boolean; run_id: string; evidence_rows_deleted: number; artifacts_deleted: number }>(`/api/runs/${runId}`, {
    method: "DELETE"
  });
}

export async function getReport(runId: string) {
  return request<AccountReport>(`/api/reports/${runId}`);
}

export async function askReport(runId: string, question: string, maxEvidenceRows = 24) {
  return request<ReportChatResponse>(`/api/reports/${runId}/chat`, {
    method: "POST",
    body: JSON.stringify({ question, max_evidence_rows: maxEvidenceRows })
  });
}

export function artifactUrl(runId: string, kind: "pptx" | "pdf" | "evidence_json") {
  return `${API_BASE}/api/reports/${runId}/artifacts/${kind}`;
}
