import { FileText, RefreshCw, Search, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { RunHistoryItem } from "../lib/api";

interface RunHistoryProps {
  activeRunId?: string | null;
  runs: RunHistoryItem[];
  isLoading: boolean;
  onOpenRun: (runId: string) => void;
  onRefresh: () => void;
  onDeleteRun: (runId: string) => void;
}

function formatDate(value?: string | null) {
  if (!value) return "Not completed";
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function RunHistory({ activeRunId, runs, isLoading, onOpenRun, onRefresh, onDeleteRun }: RunHistoryProps) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const filteredRuns = useMemo(() => {
    if (!normalizedQuery) {
      return runs;
    }
    return runs.filter((item) =>
      [
        item.id,
        item.company_name,
        item.mode,
        item.status,
        item.freshness_window,
        formatDate(item.completed_at ?? item.created_at)
      ]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery)
    );
  }, [normalizedQuery, runs]);

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

      <div className="history-search">
        <Search size={15} />
        <input
          aria-label="Search recent reports"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search company, mode, status..."
          type="search"
          value={query}
        />
        {query && (
          <button aria-label="Clear recent report search" onClick={() => setQuery("")} type="button">
            <X size={14} />
          </button>
        )}
      </div>

      {runs.length === 0 ? (
        <p className="workflow-note">No saved runs yet. Completed reports will appear here.</p>
      ) : filteredRuns.length === 0 ? (
        <p className="workflow-note">No reports match this search.</p>
      ) : (
        <div className="history-list">
          {filteredRuns.slice(0, 12).map((item) => (
            <div
              className={activeRunId === item.id ? "history-row active" : "history-row"}
              key={item.id}
            >
              <button className="history-row-main" onClick={() => onOpenRun(item.id)} type="button">
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
              <button
                aria-label={`Delete ${item.company_name} report`}
                className="history-delete-button"
                onClick={() => onDeleteRun(item.id)}
                title="Delete run and artifacts"
                type="button"
              >
                <Trash2 size={14} />
                <small>Delete</small>
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
