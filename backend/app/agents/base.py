from __future__ import annotations

from dataclasses import dataclass

from app.models import AccountReport, ResearchRun
from app.providers.registry import ProviderRegistry


@dataclass
class AgentContext:
    run: ResearchRun
    report: AccountReport
    providers: ProviderRegistry


class Agent:
    name = "agent"
    model = "gpt-5.5"
    reasoning_effort = "medium"
    tools: list[str] = []

    async def run(self, context: AgentContext) -> AgentContext:
        return context
