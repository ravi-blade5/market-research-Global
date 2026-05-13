import { FileText, RefreshCw } from "lucide-react";
import type { RunHistoryItem } from "../lib/api";

interface RunHistoryProps {
  activeRunId?: string | null;
  runs: RunHistoryItem[];
  isLoading: boolean;
  onOpenRun: (runId: string) => void;
  onRefresh: () => void;
}

function formatDate(value?: string | null) {
  if (!value) return "Not completed";
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function RunHistory({ activeRunId, runs, isLoading, onOpenRun, onRefresh }: RunHistoryProps) {
  return (
    <section className="surface history-panel">
      <div className="surface-header">
        <div>
          <h2>Recent Reports</h2>
          <p>{runs.length} saved runs</p>
        </div>
        <button className="icon-action" onClick={onRefresh} title="Refresh history" type="button">
          <RefreshCw size={16} className={isLoading ? "spin" : ""} />
        </button>
      </div>

      {runs.length === 0 ? (
        <p className="workflow-note">No saved runs yet. Completed reports will appear here.</p>
      ) : (
        <div className="history-list">
          {runs.slice(0, 12).map((item) => (
            <button
              className={activeRunId === item.id ? "history-row active" : "history-row"}
              key={item.id}
              onClick={() => onOpenRun(item.id)}
              type="button"
            >
              <FileText size={16} />
              <span>
                <strong>{item.company_name}</strong>
                <small>
                  {item.mode} | {item.status} | {formatDate(item.completed_at ?? item.created_at)}
                </small>
                {item.has_report && (
                  <small>
                    {item.claim_count} claims | {item.source_count} sources | {item.table_row_count} rows
                  </small>
                )}
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
