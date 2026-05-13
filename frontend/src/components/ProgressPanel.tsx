import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import type { ResearchRun } from "../lib/api";

interface ProgressPanelProps {
  run: ResearchRun | null;
}

function AgentIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 size={16} className="status-complete" />;
  if (status === "running") return <Loader2 size={16} className="status-running spin" />;
  if (status === "failed") return <XCircle size={16} className="status-failed" />;
  return <Circle size={16} className="status-pending" />;
}

export function ProgressPanel({ run }: ProgressPanelProps) {
  if (!run) {
    return (
      <section className="surface muted-state">
        <p>No active run.</p>
      </section>
    );
  }

  return (
    <section className="surface">
      <div className="surface-header">
        <div>
          <h2>Research Progress</h2>
          <p>{run.company_name}</p>
          <p className="workflow-note">
            {run.workflow_profile === "deep_dive_live_single_worker"
              ? "Deep Dive live MVP: expanded research stages. Full one-hour Cloud Workflow is the next production step."
              : "Quick Scan workflow."}
          </p>
        </div>
        <span className={`status-pill ${run.status}`}>{run.status}</span>
      </div>

      {run.run_notes && run.run_notes.length > 0 ? (
        <div className="run-notes">
          {run.run_notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      ) : null}

      <div className="progress-track" aria-label={`Progress ${run.progress}%`}>
        <div style={{ width: `${run.progress}%` }} />
      </div>

      <div className="agent-grid">
        {run.agents.map((agent) => (
          <div className="agent-row" key={agent.name}>
            <AgentIcon status={agent.status} />
            <span>{agent.name}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
