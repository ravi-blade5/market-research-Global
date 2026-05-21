import { Search, TimerReset, UsersRound } from "lucide-react";
import type { FreshnessWindow, ResearchMode } from "../lib/api";

interface RunFormProps {
  companyName: string;
  department: string;
  mode: ResearchMode;
  freshnessWindow: FreshnessWindow;
  isSubmitting: boolean;
  onCompanyNameChange: (value: string) => void;
  onDepartmentChange: (value: string) => void;
  onModeChange: (value: ResearchMode) => void;
  onFreshnessWindowChange: (value: FreshnessWindow) => void;
  onSubmit: () => void;
}

export function RunForm({
  companyName,
  department,
  mode,
  freshnessWindow,
  isSubmitting,
  onCompanyNameChange,
  onDepartmentChange,
  onModeChange,
  onFreshnessWindowChange,
  onSubmit
}: RunFormProps) {
  return (
    <section className="command-panel" aria-label="Create research run">
      <div className="command-main">
        <label htmlFor="company-name">Company</label>
        <div className="company-input">
          <Search size={20} aria-hidden="true" />
          <input
            id="company-name"
            value={companyName}
            onChange={(event) => onCompanyNameChange(event.target.value)}
            placeholder="Enter company name"
            onKeyDown={(event) => {
              if (event.key === "Enter") onSubmit();
            }}
          />
        </div>
      </div>

      <div className="command-main department-control">
        <label htmlFor="department-name">Department <span>optional</span></label>
        <div className="company-input">
          <UsersRound size={20} aria-hidden="true" />
          <input
            id="department-name"
            value={department}
            onChange={(event) => onDepartmentChange(event.target.value)}
            placeholder="e.g., IT, Finance, Procurement"
            onKeyDown={(event) => {
              if (event.key === "Enter") onSubmit();
            }}
          />
        </div>
      </div>

      <div className="control-row" aria-label="Research mode">
        <button className={mode === "quick" ? "segmented active" : "segmented"} onClick={() => onModeChange("quick")} type="button">
          <TimerReset size={16} />
          Quick Scan
        </button>
        <button className={mode === "deep" ? "segmented active" : "segmented"} onClick={() => onModeChange("deep")} type="button">
          <Search size={16} />
          Deep Dive
        </button>
      </div>

      <div className="mode-note">
        {mode === "deep"
          ? "Deep Dive: expanded live research stages now; production target is a 45-60 min background workflow."
          : "Quick Scan: accelerated source-backed meeting prep."}
      </div>

      <div className="control-row" aria-label="Freshness window">
        <button
          className={freshnessWindow === "6m" ? "segmented active" : "segmented"}
          onClick={() => onFreshnessWindowChange("6m")}
          type="button"
        >
          6 months
        </button>
        <button
          className={freshnessWindow === "12m" ? "segmented active" : "segmented"}
          onClick={() => onFreshnessWindowChange("12m")}
          type="button"
        >
          12 months
        </button>
      </div>

      <button className="primary-action" onClick={onSubmit} disabled={isSubmitting || companyName.trim().length < 2} type="button">
        {isSubmitting ? "Starting..." : "Start Research"}
      </button>
    </section>
  );
}
