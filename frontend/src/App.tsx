import { useEffect, useMemo, useState } from "react";
import { BrainCircuit, ShieldCheck } from "lucide-react";
import {
  createRun,
  getReport,
  getRun,
  getRunHistory,
  type AccountReport,
  type FreshnessWindow,
  type ResearchMode,
  type ResearchRun,
  type RunHistoryItem
} from "./lib/api";
import { ProgressPanel } from "./components/ProgressPanel";
import { ReportViewer } from "./components/ReportViewer";
import { RunHistory } from "./components/RunHistory";
import { RunForm } from "./components/RunForm";

export function App() {
  const [companyName, setCompanyName] = useState("Oracle Corporation");
  const [mode, setMode] = useState<ResearchMode>("deep");
  const [freshnessWindow, setFreshnessWindow] = useState<FreshnessWindow>("12m");
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [report, setReport] = useState<AccountReport | null>(null);
  const [history, setHistory] = useState<RunHistoryItem[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canPoll = useMemo(() => run && !["completed", "failed"].includes(run.status), [run]);

  useEffect(() => {
    void refreshHistory();
  }, []);

  useEffect(() => {
    if (!run || !canPoll) return;
    const interval = window.setInterval(async () => {
      const nextRun = await getRun(run.id);
      setRun(nextRun);
      if (nextRun.status === "completed") {
        const nextReport = await getReport(nextRun.id);
        setReport(nextReport);
        void refreshHistory();
      }
    }, 1200);
    return () => window.clearInterval(interval);
  }, [run, canPoll]);

  async function refreshHistory() {
    setIsHistoryLoading(true);
    try {
      const runs = await getRunHistory();
      setHistory(runs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load report history.");
    } finally {
      setIsHistoryLoading(false);
    }
  }

  async function openRun(runId: string) {
    setError(null);
    try {
      const selectedRun = await getRun(runId);
      setRun(selectedRun);
      if (selectedRun.status === "completed") {
        setReport(await getReport(selectedRun.id));
      } else {
        setReport(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to open saved run.");
    }
  }

  async function startRun() {
    setIsSubmitting(true);
    setError(null);
    setReport(null);
    try {
      const created = await createRun(companyName, mode, freshnessWindow);
      setRun(created);
      void refreshHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start research run.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-mark" aria-hidden="true">
          <BrainCircuit size={28} />
        </div>
        <div>
          <h1>HCLTech Market Research Portal</h1>
          <p>Source-grounded account intelligence, strategy, and export-ready reports.</p>
        </div>
        <div className="trust-chip">
          <ShieldCheck size={16} />
          Claim-level evidence
        </div>
      </header>

      <RunForm
        companyName={companyName}
        mode={mode}
        freshnessWindow={freshnessWindow}
        isSubmitting={isSubmitting}
        onCompanyNameChange={setCompanyName}
        onModeChange={setMode}
        onFreshnessWindowChange={setFreshnessWindow}
        onSubmit={startRun}
      />

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="workbench">
        <div className="left-rail">
          <ProgressPanel run={run} />
          <RunHistory
            activeRunId={run?.id}
            runs={history}
            isLoading={isHistoryLoading}
            onOpenRun={openRun}
            onRefresh={refreshHistory}
          />
        </div>
        <ReportViewer report={report} />
      </div>
    </div>
  );
}
