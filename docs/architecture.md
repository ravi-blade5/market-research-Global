# Architecture Notes

## ADK-inspired patterns adopted

- Two-phase workflow: plan and lock outline, then autonomous research.
- Iterative research loop: search, extract, critique, refine, synthesize.
- Research anchor: preserves sources, raw URLs, extracted values, claim IDs, and section lineage across later report generation.
- DeckSpec: verified report JSON is converted into a presentation-neutral structure before rendering.
- Export QA: PPTX/PDF artifacts are checked before publication.

## Provider adapter boundary

The backend owns orchestration, retries, state, and storage. Providers only supply search, deep research, extraction, presentation rendering, or citation normalization capabilities.

Initial adapters:

- `OpenAISearchProvider`
- `OpenAIDeepResearchProvider`
- `FirecrawlExtractionProvider`
- `ApifyExtractionProvider`
- `LocalPresentationProvider`

Future adapters can slot in without changing the agent contracts:

- Perplexity/Sonar search or deep research
- Gemini deep research
- Licensed data providers
- Internal HCLTech RAG

## Grounding stance

The app fails closed. Missing evidence produces unavailable fields, not invented values. Strategic recommendations can be generated, but their premises must be tied to claims and evidence.

## Evidence mart and report chat

Completed reports are also projected into a local DuckDB evidence mart. The canonical JSON report remains the source of truth for the MVP, while DuckDB provides fast table counts, table-specific browsing, SQL-style analytical summaries, keyword retrieval, semantic retrieval, and report-chat context.

The report chat endpoint retrieves relevant DuckDB rows first. When live providers are enabled, it embeds report rows and the question with the configured OpenAI embedding model, blends semantic similarity with keyword ranking and confidence, and passes only retrieved rows plus safe DuckDB summary aggregates to `gpt-5.4-mini`. When live providers are disabled, or if embeddings fail, the endpoint returns/falls back to SQL-plus-keyword retrieval so the portal remains safe in mock/local mode.
