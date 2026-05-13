from __future__ import annotations

from app.config import Settings
from app.providers.extraction import ApifyExtractionProvider, FirecrawlExtractionProvider
from app.providers.openai_provider import (
    MockDeepResearchProvider,
    MockSearchProvider,
    MockSynthesisProvider,
    OpenAIDeepResearchProvider,
    OpenAISearchProvider,
    OpenAISynthesisProvider,
)


class ProviderRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings

    def search_provider(self):
        if self.settings.openai_api_key and self.settings.allow_live_providers:
            return OpenAISearchProvider(self.settings)
        return MockSearchProvider()

    def synthesis_provider(self):
        if self.settings.openai_api_key and self.settings.allow_live_providers:
            return OpenAISynthesisProvider(self.settings)
        return MockSynthesisProvider()

    def deep_research_provider(self):
        if self.settings.openai_api_key and self.settings.allow_live_providers:
            return OpenAIDeepResearchProvider(self.settings)
        return MockDeepResearchProvider()

    def extraction_providers(self):
        return [
            FirecrawlExtractionProvider(self.settings),
            ApifyExtractionProvider(self.settings),
        ]
