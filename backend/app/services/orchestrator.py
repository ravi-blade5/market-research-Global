from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import Agent, AgentContext
from app.agents.pipeline import get_agent_sequence, new_report_for_run, refresh_evidence_tables
from app.config import Settings
from app.models import AgentRun, AgentStatus, ResearchRun, ResearchRunCreate, RunStatus, utc_now
from app.providers.registry import ProviderRegistry
from app.services.exporter import ReportExporter
from app.storage.gcs_artifacts import GCSArtifactStore


class ResearchOrchestrator:
    def __init__(self, settings: Settings, store: Any):
        self.settings = settings
        self.store = store
        self.providers = ProviderRegistry(settings)
        self.exporter = ReportExporter()
        self.artifact_store = (
            GCSArtifactStore(settings.gcs_artifact_bucket)
            if settings.artifact_backend.lower() == "gcs" and settings.gcs_artifact_bucket
            else None
        )

    def create_run(self, request: ResearchRunCreate) -> ResearchRun:
        agent_sequence = get_agent_sequence(request.mode)
        run = ResearchRun(
            company_name=request.company_name.strip(),
            mode=request.mode,
            freshness_window=request.freshness_window,
            workflow_profile="deep_dive_live_single_worker" if request.mode.value == "deep" else "quick_scan_quality_first",
            expected_duration_seconds=3600 if request.mode.value == "deep" else 900,
            run_notes=(
                [
                    "Deep Dive now waits on OpenAI Deep Research background polling, Firecrawl extraction jobs, and Apify actor extraction when providers are configured.",
                    "Quality-first mode is active: OpenAI search, synthesis, and strategy agents use high/xhigh reasoning with broader evidence payloads before optimization.",
                    "Local execution persists agent checkpoints after each orchestration wave and can resume from the last completed agent if re-executed.",
                    "Production deployment should dispatch Deep Dive through Cloud Tasks/Workflows instead of FastAPI BackgroundTasks.",
                ]
                if request.mode.value == "deep"
                else [
                    "Quality-first Quick Scan uses expanded OpenAI source discovery across filings, press releases, partnerships, AI, hiring, and vendor signals.",
                    "Quick Scan skips one-hour Deep Research/background crawling, but still runs high-reasoning section synthesis and may take 5-15 minutes depending on provider latency.",
                ]
            ),
            agents=[
                AgentRun(
                    name=agent.name,
                    model=agent.model,
                    reasoning_effort=agent.reasoning_effort,
                    tools=agent.tools,
                )
                for agent in agent_sequence
            ],
        )
        return self.store.save(run)

    async def execute_run(self, run_id: str) -> ResearchRun:
        run = self.store.get(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        if run.status == RunStatus.completed and run.report:
            return run

        run.status = RunStatus.planning
        run.updated_at = utc_now()
        if run.report is None:
            run.report = new_report_for_run(run)
        elif "Resuming from last saved agent checkpoint." not in run.run_notes:
            run.run_notes.append("Resuming from last saved agent checkpoint.")
        self.store.save(run)

        context = AgentContext(run=run, report=run.report, providers=self.providers)
        agent_sequence = get_agent_sequence(run.mode)
        total = len(agent_sequence)
        completed_agent_names = {agent.name for agent in run.agents if agent.status == AgentStatus.completed}
        completed_agents = min(len(completed_agent_names), total)

        for agent_group in self._agent_groups(agent_sequence):
            pending_group = [agent for agent in agent_group if agent.name not in completed_agent_names]
            if not pending_group:
                continue
            run.status = self._status_for_agent_group(agent_group)
            for agent in pending_group:
                self._set_agent_status(run, agent.name, AgentStatus.running)
            run.progress = min(95, int(completed_agents / total * 100))
            run.updated_at = utc_now()
            self.store.save(run)

            results = await self._run_agent_group(pending_group, context)
            failures = [(agent, exc) for agent, exc in results if exc is not None]
            if failures:
                for agent, exc in failures:
                    self._set_agent_status(run, agent.name, AgentStatus.failed, str(exc))
                run.status = RunStatus.failed
                run.error = "; ".join(f"{agent.name}: {exc}" for agent, exc in failures)
                self.store.save(run)
                raise RuntimeError(run.error)

            for agent, _ in results:
                self._set_agent_status(run, agent.name, AgentStatus.completed)
                completed_agent_names.add(agent.name)
            completed_agents += len(pending_group)
            refresh_evidence_tables(context)
            run.report = context.report
            run.updated_at = utc_now()
            self.store.save(run)

        if run.report:
            pptx_path = self.store.artifact_path(run.id, "pptx")
            pdf_path = self.store.artifact_path(run.id, "pdf")
            evidence_path = self.store.artifact_path(run.id, "evidence.json")
            artifacts = self.exporter.export_all(run.report, pptx_path, pdf_path, evidence_path)
            if self.artifact_store:
                artifacts = self.artifact_store.upload_artifacts(run.id, artifacts)
            run.report.artifacts = artifacts

        run.status = RunStatus.completed
        run.progress = 100
        run.completed_at = utc_now()
        run.updated_at = utc_now()
        return self.store.save(run)

    async def _run_agent(self, agent: Agent, context: AgentContext) -> tuple[Agent, Exception | None]:
        try:
            await agent.run(context)
            return agent, None
        except Exception as exc:  # pragma: no cover - defensive status path
            return agent, exc

    async def _run_agent_group(self, agent_group: list[Agent], context: AgentContext) -> list[tuple[Agent, Exception | None]]:
        parallelism = max(1, self.settings.agent_parallelism)
        semaphore = asyncio.Semaphore(parallelism)

        async def run_limited(agent: Agent) -> tuple[Agent, Exception | None]:
            async with semaphore:
                return await self._run_agent(agent, context)

        return await asyncio.gather(*[run_limited(agent) for agent in agent_group], return_exceptions=False)

    def _agent_groups(self, agent_sequence: list[Agent]) -> list[list[Agent]]:
        core_research = {
            "Company Overview Agent",
            "Financial Agent",
            "Recent Investments Agent",
            "Partnerships/Deals Agent",
            "Account Priorities Agent",
            "Tech Stack Agent",
            "Hiring/Footprint Agent",
            "News/Signals Agent",
            "Executive Agent",
        }
        post_research = {
            "IT Spend Signals Agent",
            "Outsourcing/Vendor Agent",
            "AI Strategy Agent",
        }
        pre: list[list[Agent]] = []
        core: list[Agent] = []
        post: list[Agent] = []
        tail: list[list[Agent]] = []
        seen_research = False
        for agent in agent_sequence:
            if agent.name in core_research:
                core.append(agent)
                seen_research = True
                continue
            if agent.name in post_research:
                post.append(agent)
                seen_research = True
                continue
            if seen_research:
                tail.append([agent])
            else:
                pre.append([agent])
        groups = [*pre]
        if core:
            groups.append(core)
        if post:
            groups.append(post)
        groups.extend(tail)
        return groups

    def _status_for_agent_group(self, agent_group: list[Agent]) -> RunStatus:
        names = {agent.name for agent in agent_group}
        if "Verification Agent" in names:
            return RunStatus.verifying
        if names & {"Report Generator Agent", "Export QA Agent"}:
            return RunStatus.exporting
        return RunStatus.researching

    def _set_agent_status(self, run: ResearchRun, name: str, status: AgentStatus, message: str | None = None) -> None:
        now = utc_now()
        for agent in run.agents:
            if agent.name == name:
                agent.status = status
                agent.message = message
                if status == AgentStatus.running:
                    agent.started_at = now
                if status in {AgentStatus.completed, AgentStatus.failed}:
                    agent.completed_at = now
                return
