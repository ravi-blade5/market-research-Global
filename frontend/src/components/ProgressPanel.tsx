import { ChevronDown, ChevronUp, CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import { useState } from "react";
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
  const [showRunNotes, setShowRunNotes] = useState(false);

  if (!run) {
    return (
      <section className="surface muted-state">
        <p>No active run.</p>
      </section>
    );
  }

  const runNotes = run.run_notes ?? [];
  const checkpointNotes = runNotes.filter((note) => note.includes("Cloud Tasks"));
  const primaryNotes = runNotes.filter((note) => !note.includes("Cloud Tasks")).slice(0, 2);
  const collapsedNotes = [
    ...primaryNotes,
    ...(checkpointNotes.length > 0 ? [`Cloud Tasks checkpoint activity: ${checkpointNotes.length} dispatch events recorded.`] : [])
  ];
  const visibleNotes = showRunNotes ? runNotes : collapsedNotes;
  const hasHiddenNotes = runNotes.length > collapsedNotes.length || checkpointNotes.length > 0;

  return (
    <section className="surface">
      <div className="surface-header">
        <div>
          <h2>Research Progress</h2>
          <p>{run.company_name}</p>
          {run.department ? <p className="workflow-note">Department Lens: {run.department}</p> : null}
          <p className="workflow-note">
            {run.workflow_profile === "deep_dive_live_single_worker"
              ? "Deep Dive live MVP: expanded research stages. Full one-hour Cloud Workflow is the next production step."
              : "Quick Scan workflow."}
          </p>
        </div>
        <span className={`status-pill ${run.status}`}>{run.status}</span>
      </div>

      {visibleNotes.length > 0 ? (
        <div className={`run-notes ${showRunNotes ? "expanded" : "collapsed"}`}>
          {visibleNotes.map((note, index) => (
            <p key={`${index}-${note}`}>{note}</p>
          ))}
          {hasHiddenNotes ? (
            <button className="run-notes-toggle" onClick={() => setShowRunNotes((current) => !current)} type="button">
              {showRunNotes ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              {showRunNotes ? "Hide activity details" : `Show activity details (${runNotes.length})`}
            </button>
          ) : null}
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
