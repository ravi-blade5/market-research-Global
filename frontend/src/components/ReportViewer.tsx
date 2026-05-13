import { type FormEvent, useState } from "react";
import { ChevronDown, ChevronUp, Download, FileJson, FileText, MessageCircle, Presentation, Send } from "lucide-react";
import {
  askReport,
  artifactUrl,
  type AccountReport,
  type Claim,
  type EvidenceSignal,
  type EvidenceSource,
  type EvidenceTableRow,
  type ReportChatResponse,
  type ReportSection
} from "../lib/api";

interface ReportViewerProps {
  report: AccountReport | null;
}

const sourceIdPattern = /src_[0-9a-f]{8,16}/g;
const clientTextReplacements: Record<string, string> = {
  "Company identity, official-source discovery, and report metadata are configured.":
    "Company overview remains partial until official company, investor, or filing evidence is extracted into exact facts.",
  "Priority taxonomy is ready; live source extraction will populate priorities per business function.":
    "Account priorities are reported only when section-specific filings, earnings calls, press releases, or credible news support them.",
  "Technology stack schema implemented with confidence scoring and source trail requirements.":
    "Technology stack analysis is partial; no vendor, platform, or tool will be listed without public job, official, partner, or credible evidence.",
  "Apify/Firecrawl-backed job and location extraction hooks are ready.":
    "Hiring and footprint analysis is partial unless public job, career, or official location evidence provides exact role, skill, and location signals.",
  "Signal validation policy is configured.":
    "Key signals are reported only when supported by official announcements or reputable news within the selected freshness window.",
  "Buying-center map schema implemented.":
    "The buying-center map is partial until verified executive and functional-leader evidence is available for named stakeholders.",
  "AI maturity and opportunity framework is implemented.":
    "AI strategy assessment is pending verified evidence on AI investments, partnerships, offerings, adoption, and roadmap signals.",
  "Opportunity-led account penetration playbook scaffold.":
    "HCLTech account-penetration guidance is pending verified account priorities, technology, sourcing, executive, and AI-strategy evidence.",
  "Consensus engine ready; live runs will rank account moves by evidence strength and strategic confidence.":
    "Consensus recommendation is pending verified section-level evidence and should not overstate unsupported account moves.",
  "Source-grounded report scaffold with fail-closed unavailable fields.":
    "Source-grounded report with unsupported fields marked unavailable.",
  "unavailable until official filings or investor materials are extracted by a live provider":
    "exact value not found in the extracted official evidence for this run",
  "Pending extraction of an exact revenue value from annual, quarterly, investor, or filing evidence.":
    "Exact revenue value not found in the extracted official financial evidence for this run.",
  "Pending extraction of an exact R&D value from annual, quarterly, investor, or filing evidence.":
    "Exact R&D value not found in the extracted official financial evidence for this run."
};

function sourceNumberMap(sources: EvidenceSource[]) {
  const publicSources = sources.filter((source) => source.url.startsWith("http"));
  return new Map(publicSources.map((source, index) => [source.id, index + 1]));
}

function cleanText(text: string, sourceNumbers: Map<string, number>) {
  let cleaned = text
    .replace(/\[[^\]]*(src_[0-9a-f]{8,16})[^\]]*\]/g, (_match, sourceId: string) => {
      const number = sourceNumbers.get(sourceId);
      return number ? `S${number}` : "source";
    })
    .replace(sourceIdPattern, (sourceId) => {
      const number = sourceNumbers.get(sourceId);
      return number ? `S${number}` : "source";
    })
    .replace(/\[\s*[,;:\s]*\]/g, "")
    .replace(/\[\s*(?:cited source[\s,;]*)+\]/gi, "")
    .replace(/\s*cited source(?:\s*,\s*cited source)*/gi, "")
    .replace("R&D;", "R&D");
  Object.entries(clientTextReplacements).forEach(([oldText, newText]) => {
    cleaned = cleaned.replace(oldText, newText);
  });
  return cleaned;
}

function sourceLabel(source: EvidenceSource, sourceNumbers: Map<string, number>) {
  const number = sourceNumbers.get(source.id);
  return number ? `S${number}` : "Internal";
}

function readableLabel(value: string | null | undefined) {
  return (value ?? "unclassified").replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function claimsForSection(report: AccountReport, section: ReportSection) {
  const claimIds = new Set(section.claim_ids);
  return report.claims.filter((claim) => claimIds.has(claim.id));
}

function signalsForSection(report: AccountReport, section: ReportSection) {
  return (report.evidence_signals ?? []).filter((signal) => signal.section_id === section.id);
}

function signalMix(signals: EvidenceSignal[]) {
  const counts = new Map<string, number>();
  signals.forEach((signal) => counts.set(signal.signal_type, (counts.get(signal.signal_type) ?? 0) + 1));
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
}

function tableMix(rows: EvidenceTableRow[]) {
  const counts = new Map<string, number>();
  rows.forEach((row) => counts.set(row.table_name, (counts.get(row.table_name) ?? 0) + 1));
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
}

function sourceChips(claims: Claim[], sources: EvidenceSource[], sourceNumbers: Map<string, number>) {
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  const ids = Array.from(new Set(claims.flatMap((claim) => claim.evidence_source_ids))).slice(0, 6);
  return ids
    .map((sourceId) => sourceById.get(sourceId))
    .filter((source): source is EvidenceSource => Boolean(source))
    .filter((source) => source.url.startsWith("http"))
    .map((source) => (
      <a className="source-chip" href={source.url} key={source.id} rel="noreferrer" target="_blank" title={source.title}>
        {sourceLabel(source, sourceNumbers)}
      </a>
    ));
}

function sectionBullets(section: ReportSection, sourceNumbers: Map<string, number>) {
  const synthesis = section.content.synthesis as { bullets?: unknown } | undefined;
  if (!synthesis || !Array.isArray(synthesis.bullets)) {
    return [];
  }
  return synthesis.bullets
    .filter((bullet): bullet is string => typeof bullet === "string" && bullet.trim().length > 0)
    .map((bullet) => cleanText(bullet, sourceNumbers));
}

export function ReportViewer({ report }: ReportViewerProps) {
  const [chatQuestion, setChatQuestion] = useState("");
  const [chatResponse, setChatResponse] = useState<ReportChatResponse | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());

  if (!report) {
    return (
      <section className="surface muted-state report-empty">
        <p>Completed reports will appear here with sections, evidence, and exports.</p>
      </section>
    );
  }

  const activeReport = report;
  const sourceNumbers = sourceNumberMap(report.sources);
  const publicSources = report.sources.filter((source) => source.url.startsWith("http"));
  const evidenceSignals = report.evidence_signals ?? [];
  const evidenceTableRows = report.evidence_table_rows ?? [];
  const evidenceSignalMix = signalMix(evidenceSignals);
  const evidenceTableMix = tableMix(evidenceTableRows);
  const blockerChecks = report.quality_checks.filter((check) => check.severity === "blocker" && !check.passed);
  const warningChecks = report.quality_checks.filter((check) => check.severity === "warning" && !check.passed);

  async function handleChatSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = chatQuestion.trim();
    if (!question || chatLoading) {
      return;
    }
    setChatLoading(true);
    setChatError(null);
    try {
      setChatResponse(await askReport(activeReport.run_id, question));
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "Report chat failed");
    } finally {
      setChatLoading(false);
    }
  }

  function toggleSection(sectionId: string) {
    setExpandedSections((current) => {
      const next = new Set(current);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  }

  return (
    <section className="report-layout">
      <aside className="section-nav">
        <h2>Sections</h2>
        {report.sections.map((section) => (
          <a href={`#${section.id}`} key={section.id}>
            {section.title}
          </a>
        ))}
      </aside>

      <main className="report-main">
        <div className="report-toolbar">
          <div>
            <h2>{report.company_name}</h2>
            <p>
              {report.mode} | freshness {report.freshness_window} | {report.claims.length} claims | {report.sources.length} sources |{" "}
              {evidenceSignals.length} signals | {evidenceTableRows.length} table rows
            </p>
            {(blockerChecks.length > 0 || warningChecks.length > 0) && (
              <div className="quality-summary">
                {blockerChecks.length > 0 && <span className="section-status rejected">{blockerChecks.length} blockers</span>}
                {warningChecks.length > 0 && <span className="section-status partial">{warningChecks.length} warnings</span>}
              </div>
            )}
          </div>
          <div className="artifact-actions">
            <a href={artifactUrl(report.run_id, "pptx")}>
              <Presentation size={16} />
              PPTX
              <Download size={14} />
            </a>
            <a href={artifactUrl(report.run_id, "pdf")}>
              <FileText size={16} />
              PDF
              <Download size={14} />
            </a>
            <a href={artifactUrl(report.run_id, "evidence_json")}>
              <FileJson size={16} />
              Evidence
              <Download size={14} />
            </a>
          </div>
        </div>

        <section className="surface report-chat-panel">
          <div className="chat-heading">
            <div>
              <h3>
                <MessageCircle size={18} />
                Ask This Report
              </h3>
              <p>Answers use DuckDB SQL summaries, semantic retrieval, and cited report evidence.</p>
            </div>
            <span className="section-status complete">hybrid chat ready</span>
          </div>
          <form className="chat-form" onSubmit={handleChatSubmit}>
            <input
              aria-label="Ask a question about this report"
              onChange={(event) => setChatQuestion(event.target.value)}
              placeholder="Ask about AI moves, partnerships, investments, buying centers, risks..."
              value={chatQuestion}
            />
            <button className="primary-action" disabled={chatLoading || chatQuestion.trim().length < 3} type="submit">
              <Send size={16} />
              {chatLoading ? "Thinking" : "Ask"}
            </button>
          </form>
          {chatError && <p className="chat-error">{chatError}</p>}
          {chatResponse && (
            <div className="chat-answer">
              <div className="chat-answer-body">
                {chatResponse.answer.split("\n").map((line, index) => (
                  <p key={`${index}-${line}`}>{cleanText(line, sourceNumbers)}</p>
                ))}
              </div>
              {chatResponse.evidence_rows.length > 0 && (
                <div className="chat-evidence">
                  <strong>Retrieved evidence</strong>
                  {chatResponse.evidence_rows.slice(0, 6).map((row) => (
                    <div className="chat-evidence-row" key={row.row_id}>
                      <span>
                        {readableLabel(row.table_name)} | {Math.round(row.confidence_score * 100)}%
                      </span>
                      <p>{cleanText(row.title, sourceNumbers)}</p>
                      <small>
                        {row.source_labels.join(", ")}
                        {row.retrieval_scores?.semantic ? ` | semantic ${Math.round(row.retrieval_scores.semantic * 100)}%` : ""}
                      </small>
                    </div>
                  ))}
                </div>
              )}
              <small className="chat-provider">
                Retrieval: {chatResponse.retrieval_mode} | Provider: {chatResponse.provider}
                {chatResponse.model ? ` | Model: ${chatResponse.model}` : ""}
              </small>
            </div>
          )}
        </section>

        <div className="section-stack">
          {report.sections.map((section) => {
            const claims = claimsForSection(report, section);
            const signals = signalsForSection(report, section);
            const bullets = sectionBullets(section, sourceNumbers);
            const isExpanded = expandedSections.has(section.id);
            const summary = cleanText(section.summary, sourceNumbers);
            const visibleBullets = isExpanded ? bullets : bullets.slice(0, 2);
            const hiddenBulletCount = bullets.length - visibleBullets.length;
            const hasExpandableContent = summary.length > 280 || hiddenBulletCount > 0;
            const chips = sourceChips(claims, report.sources, sourceNumbers);
            return (
              <article className={`report-section${isExpanded ? " expanded" : ""}`} id={section.id} key={section.id}>
                <div className="section-heading">
                  <h3>{section.title}</h3>
                  <span className={`section-status ${section.status}`}>{section.status}</span>
                </div>
                <div className="section-metrics">
                  <span className="metric-chip">{claims.length} claims</span>
                  {signals.length > 0 && <span className="metric-chip">{signals.length} signals</span>}
                  <span className="metric-chip">{Math.round(section.confidence_score * 100)}% confidence</span>
                </div>
                <p className="section-summary">{summary}</p>
                {visibleBullets.length > 0 && (
                  <ul className="section-points">
                    {visibleBullets.map((bullet, index) => (
                      <li key={`${section.id}-${index}-${bullet}`}>{bullet}</li>
                    ))}
                  </ul>
                )}
                {hasExpandableContent && (
                  <button className="text-action" onClick={() => toggleSection(section.id)} type="button">
                    {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    {isExpanded ? "Show less" : hiddenBulletCount > 0 ? `Expand +${hiddenBulletCount}` : "Expand"}
                  </button>
                )}
                <div className="section-evidence">
                  {chips.length > 0 ? chips : <span className="muted-inline">No public citation attached</span>}
                </div>
              </article>
            );
          })}
        </div>

        {(blockerChecks.length > 0 || warningChecks.length > 0) && (
          <section className="surface quality-panel">
            <h3>Quality Gate</h3>
            {[...blockerChecks, ...warningChecks].slice(0, 10).map((check) => (
              <div className="quality-row" key={`${check.name}-${check.message}`}>
                <span className={`section-status ${check.severity === "blocker" ? "rejected" : "partial"}`}>{check.severity}</span>
                <div>
                  <strong>{check.name.replace(/_/g, " ")}</strong>
                  <p>{check.message}</p>
                </div>
              </div>
            ))}
          </section>
        )}

        {evidenceSignals.length > 0 && (
          <section className="surface evidence-graph-panel">
            <h3>Evidence Graph</h3>
            <div className="signal-mix">
              {evidenceSignalMix.slice(0, 8).map(([type, count]) => (
                <span className="signal-chip" key={type}>
                  {readableLabel(type)} <strong>{count}</strong>
                </span>
              ))}
            </div>
            <div className="evidence-list compact">
              {evidenceSignals
                .slice()
                .sort((a, b) => b.confidence_score - a.confidence_score)
                .slice(0, 12)
                .map((signal) => (
                  <div className="evidence-row" key={signal.id}>
                    <div>
                      <strong>
                        {readableLabel(signal.signal_type)} | {readableLabel(signal.signal_strength)}
                      </strong>
                      <p>{cleanText(signal.title, sourceNumbers)}</p>
                      <div className="evidence-sources">
                        {sourceChips(
                          [{ id: signal.id, text: signal.detail, section_id: signal.section_id, claim_type: "inference", evidence_source_ids: signal.source_ids, confidence_score: signal.confidence_score, verification_status: "verified" }],
                          report.sources,
                          sourceNumbers
                        )}
                      </div>
                    </div>
                    <span className="section-status complete">{Math.round(signal.confidence_score * 100)}%</span>
                  </div>
                ))}
            </div>
          </section>
        )}

        {evidenceTableRows.length > 0 && (
          <section className="surface evidence-graph-panel">
            <h3>Evidence Tables</h3>
            <div className="signal-mix">
              {evidenceTableMix.slice(0, 10).map(([table, count]) => (
                <span className="signal-chip" key={table}>
                  {readableLabel(table)} <strong>{count}</strong>
                </span>
              ))}
            </div>
            <div className="evidence-list compact">
              {evidenceTableRows
                .filter((row) => row.include_in_analysis)
                .slice(0, 12)
                .map((row) => (
                  <div className="evidence-row" key={row.id}>
                    <div>
                      <strong>
                        {readableLabel(row.table_name)} | {readableLabel(row.row_type)}
                      </strong>
                      <p>{cleanText(row.title, sourceNumbers)}</p>
                      <small>{cleanText(row.detail, sourceNumbers)}</small>
                      <div className="evidence-sources">
                        {sourceChips(
                          [{ id: row.id, text: row.detail, section_id: row.section_id ?? "evidence", claim_type: "inference", evidence_source_ids: row.source_ids, confidence_score: row.confidence_score, verification_status: "verified" }],
                          report.sources,
                          sourceNumbers
                        )}
                      </div>
                    </div>
                    <span className="section-status complete">{Math.round(row.confidence_score * 100)}%</span>
                  </div>
                ))}
            </div>
          </section>
        )}

        <section className="surface evidence-panel">
          <h3>Claim-Level Evidence</h3>
          <div className="evidence-list">
            {report.claims.map((claim) => (
              <div className="evidence-row" key={claim.id}>
                <div>
                  <strong>{claim.claim_type}</strong>
                  <p>{cleanText(claim.text, sourceNumbers)}</p>
                  <div className="evidence-sources">{sourceChips([claim], report.sources, sourceNumbers)}</div>
                </div>
                <span className={`section-status ${claim.verification_status}`}>{claim.verification_status}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="surface sources-panel">
          <h3>Sources</h3>
          <div className="sources-grid">
            {publicSources.slice(0, 18).map((source) => (
              <a href={source.url} key={source.id} rel="noreferrer" target="_blank">
                <span>{sourceLabel(source, sourceNumbers)}</span>
                <strong>{source.title}</strong>
                <small>
                  {source.publisher ?? source.credibility} | {readableLabel(source.source_tier)}
                </small>
              </a>
            ))}
          </div>
        </section>
      </main>
    </section>
  );
}
