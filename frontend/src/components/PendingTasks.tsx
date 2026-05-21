import { CheckCircle2, Clock3, ExternalLink, Loader2, RefreshCw, Trash2, XCircle } from "lucide-react";
import type { ResearchRun } from "../lib/api";

interface PendingTasksProps {
  activeRunId?: string | null;
  tasks: ResearchRun[];
  isRefreshing: boolean;
  refreshError?: string | null;
  onOpenRun: (runId: string) => void;
  onRefresh: () => void;
  onClearCompleted: () => void;
  onForgetRun: (runId: string) => void;
}

const terminalStatuses = new Set(["completed", "failed"]);

function formatDate(value?: string | null) {
  if (!value) return "Started in this browser";
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function TaskIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 size={15} className="status-complete" />;
  if (status === "failed") return <XCircle size={15} className="status-failed" />;
  if (status === "queued") return <Clock3 size={15} className="status-pending" />;
  return <Loader2 size={15} className="status-running spin" />;
}

export function PendingTasks({
  activeRunId,
  tasks,
  isRefreshing,
  refreshError,
  onOpenRun,
  onRefresh,
  onClearCompleted,
  onForgetRun
}: PendingTasksProps) {
  const activeCount = tasks.filter((task) => !terminalStatuses.has(task.status)).length;

  return (
    <section className="surface pending-tasks-panel">
      <div className="surface-header">
        <div>
          <h2>Pending Tasks</h2>
          <p>
            {activeCount} active | {tasks.length} saved in this browser
          </p>
        </div>
        <div className="panel-actions">
          <button className="icon-action" onClick={onRefresh} title="Refresh tasks" type="button">
            <RefreshCw size={16} className={isRefreshing ? "spin" : ""} />
          </button>
          <button className="icon-action" onClick={onClearCompleted} title="Clear completed tasks" type="button">
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      {refreshError ? <p className="workflow-note warning-note">{refreshError}</p> : null}

      {tasks.length === 0 ? (
        <p className="workflow-note">Runs started from this browser will stay visible after refresh or window close.</p>
      ) : (
        <div className="pending-task-list">
          {tasks.map((task) => (
            <div className={activeRunId === task.id ? "pending-task active" : "pending-task"} key={task.id}>
              <button className="pending-task-main" onClick={() => onOpenRun(task.id)} type="button">
                <TaskIcon status={task.status} />
                <span>
                  <strong>{task.company_name}</strong>
                  <small>
                    {task.mode} | {task.status} | {formatDate(task.completed_at ?? task.updated_at ?? task.created_at)}
                  </small>
                  {task.department && <small>Department Lens: {task.department}</small>}
                </span>
              </button>
              <div className="pending-task-progress" aria-label={`Task progress ${task.progress}%`}>
                <div style={{ width: `${task.progress}%` }} />
              </div>
              <div className="pending-task-actions">
                <button onClick={() => onOpenRun(task.id)} title="Open task" type="button">
                  <ExternalLink size={14} />
                  Open
                </button>
                <button onClick={() => onForgetRun(task.id)} title="Remove from this browser" type="button">
                  <Trash2 size={14} />
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
