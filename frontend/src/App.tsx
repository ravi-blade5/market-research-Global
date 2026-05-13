import { useCallback, useEffect, useMemo, useState } from "react";
import { BrainCircuit, ShieldCheck } from "lucide-react";
import {
  createRun,
  deleteRun,
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
import { PendingTasks } from "./components/PendingTasks";

const PENDING_TASKS_STORAGE_KEY = "hcltech.marketResearch.pendingTasks.v1";
const TERMINAL_RUN_STATUSES = new Set(["completed", "failed"]);
const MAX_BROWSER_TASKS = 30;

function readBrowserTasks(): ResearchRun[] {
  try {
    const raw = window.localStorage.getItem(PENDING_TASKS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is ResearchRun => Boolean(item?.id && item?.company_name && item?.status))
      .slice(0, MAX_BROWSER_TASKS);
  } catch {
    return [];
  }
}

function sortBrowserTasks(tasks: ResearchRun[]) {
  return [...tasks].sort((a, b) => {
    const aTime = new Date(a.updated_at ?? a.completed_at ?? a.created_at ?? 0).getTime();
    const bTime = new Date(b.updated_at ?? b.completed_at ?? b.created_at ?? 0).getTime();
    return bTime - aTime;
  });
}

function upsertBrowserTask(tasks: ResearchRun[], nextRun: ResearchRun) {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  byId.set(nextRun.id, nextRun);
  return sortBrowserTasks(Array.from(byId.values())).slice(0, MAX_BROWSER_TASKS);
}

export function App() {
  const [companyName, setCompanyName] = useState("Oracle Corporation");
  const [mode, setMode] = useState<ResearchMode>("deep");
  const [freshnessWindow, setFreshnessWindow] = useState<FreshnessWindow>("12m");
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [report, setReport] = useState<AccountReport | null>(null);
  const [history, setHistory] = useState<RunHistoryItem[]>([]);
  const [browserTasks, setBrowserTasks] = useState<ResearchRun[]>(() => readBrowserTasks());
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isBrowserTasksRefreshing, setIsBrowserTasksRefreshing] = useState(false);
  const [browserTasksError, setBrowserTasksError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canPoll = useMemo(() => run && !["completed", "failed"].includes(run.status), [run]);
  const activeBrowserTaskIds = useMemo(
    () => browserTasks.filter((task) => !TERMINAL_RUN_STATUSES.has(task.status)).map((task) => task.id),
    [browserTasks]
  );
  const activeBrowserTaskKey = activeBrowserTaskIds.join("|");

  useEffect(() => {
    void refreshHistory();
  }, []);

  useEffect(() => {
    window.localStorage.setItem(PENDING_TASKS_STORAGE_KEY, JSON.stringify(browserTasks));
  }, [browserTasks]);

  useEffect(() => {
    if (!run || !canPoll) return;
    const interval = window.setInterval(async () => {
      try {
        const nextRun = await getRun(run.id);
        setRun(nextRun);
        setBrowserTasks((current) => upsertBrowserTask(current, nextRun));
        setBrowserTasksError(null);
        if (nextRun.status === "completed") {
          const nextReport = await getReport(nextRun.id);
          setReport(nextReport);
          void refreshHistory();
        }
      } catch {
        setBrowserTasksError("Active run could not refresh. Showing last known status until the API is reachable.");
      }
    }, 1200);
    return () => window.clearInterval(interval);
  }, [run, canPoll]);

  const refreshBrowserTasks = useCallback(
    async (targetIds: string[], options: { silent?: boolean } = {}) => {
      if (targetIds.length === 0) return;
      if (!options.silent) {
        setIsBrowserTasksRefreshing(true);
      }
      try {
        const settled = await Promise.allSettled(targetIds.map((runId) => getRun(runId)));
        const refreshedRuns = settled
          .filter((result): result is PromiseFulfilledResult<ResearchRun> => result.status === "fulfilled")
          .map((result) => result.value);
        const failedCount = settled.length - refreshedRuns.length;
        if (refreshedRuns.length > 0) {
          setBrowserTasks((current) => refreshedRuns.reduce((tasks, nextRun) => upsertBrowserTask(tasks, nextRun), current));
          const activeRun = refreshedRuns.find((item) => item.id === run?.id);
          if (activeRun) {
            setRun(activeRun);
            if (activeRun.status === "completed") {
              setReport(await getReport(activeRun.id));
              void refreshHistory();
            }
          }
        }
        setBrowserTasksError(
          failedCount > 0 ? "Some tasks could not refresh. Showing last known status until the API is reachable." : null
        );
      } catch {
        setBrowserTasksError("Tasks could not refresh. Showing last known browser state until the API is reachable.");
      } finally {
        if (!options.silent) {
          setIsBrowserTasksRefreshing(false);
        }
      }
    },
    [run?.id]
  );

  useEffect(() => {
    if (!activeBrowserTaskKey) return;
    void refreshBrowserTasks(activeBrowserTaskIds, { silent: true });
    const interval = window.setInterval(() => {
      void refreshBrowserTasks(activeBrowserTaskIds, { silent: true });
    }, 3000);
    return () => window.clearInterval(interval);
  }, [activeBrowserTaskKey, refreshBrowserTasks]);

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
      setBrowserTasks((current) => upsertBrowserTask(current, selectedRun));
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
      setBrowserTasks((current) => upsertBrowserTask(current, created));
      void refreshHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start research run.");
    } finally {
      setIsSubmitting(false);
    }
  }

  function clearCompletedBrowserTasks() {
    setBrowserTasks((current) => current.filter((task) => !TERMINAL_RUN_STATUSES.has(task.status)));
  }

  function forgetBrowserTask(runId: string) {
    setBrowserTasks((current) => current.filter((task) => task.id !== runId));
  }

  async function deleteSavedRun(runId: string) {
    const target = history.find((item) => item.id === runId);
    const label = target ? `${target.company_name} (${target.mode})` : runId;
    const confirmed = window.confirm(`Delete ${label}? This removes the run history, evidence rows, and generated artifacts.`);
    if (!confirmed) return;
    setError(null);
    try {
      await deleteRun(runId);
      setHistory((current) => current.filter((item) => item.id !== runId));
      setBrowserTasks((current) => current.filter((task) => task.id !== runId));
      if (run?.id === runId) {
        setRun(null);
        setReport(null);
      }
      void refreshHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete saved run.");
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
          <PendingTasks
            activeRunId={run?.id}
            tasks={browserTasks}
            isRefreshing={isBrowserTasksRefreshing}
            refreshError={browserTasksError}
            onOpenRun={openRun}
            onRefresh={() => void refreshBrowserTasks(browserTasks.map((task) => task.id))}
            onClearCompleted={clearCompletedBrowserTasks}
            onForgetRun={forgetBrowserTask}
          />
          <RunHistory
            activeRunId={run?.id}
            runs={history}
            isLoading={isHistoryLoading}
            onOpenRun={openRun}
            onRefresh={refreshHistory}
            onDeleteRun={deleteSavedRun}
          />
        </div>
        <ReportViewer report={report} />
      </div>
    </div>
  );
}
