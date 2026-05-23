# Memory Provider + Policy Pipeline Design

## Goal

PAM-OS should evolve from a local demo with keyword-heavy rules into a local-first memory framework. The core runtime must keep working without network access or external services, while allowing LLM and embedding providers to improve memory decisions, extraction, retrieval, reranking, and consolidation.

The next implementation phase focuses on architecture migration, not on making external LLM calls by default.

## Current Problem

`orchestrator.py` currently decides whether to read or capture memory by matching fixed keyword lists. `consolidator.py` currently promotes memories into profile traits using domain-specific rules such as self-hosting, SQLite, Qdrant, and MVP language.

Those rules are useful as a deterministic MVP fallback, but they do not form a general memory framework. They are hard to extend, hard to evaluate across domains, and tied too closely to the initial PAM-OS project context.

## Design Principles

- Local-first by default: SQLite and deterministic rule providers remain enough to run the system.
- Provider-based intelligence: policy, extraction, retrieval, reranking, and consolidation are replaceable capabilities.
- Explicit fallback: LLM or embedding failures fall back to local rule behavior.
- Explainability: every read/capture/consolidation decision includes reason, confidence, and signals.
- Compatibility: existing CLI, MCP, REST, and tests continue to work through the same public runtime methods.
- Incremental migration: first introduce abstractions and move existing behavior behind them; later add real LLM and embedding providers.

## Pipeline

The target pipeline is:

```text
Task/Event
  -> MemoryPolicy
  -> MemoryExtractor
  -> MemoryStore
  -> MemoryRetriever
  -> MemoryReranker
  -> ContextAssembler
  -> MemoryConsolidator
```

Pre-answer flow:

```text
task + optional conversation summary
  -> policy.decide_read
  -> retriever.retrieve
  -> reranker.rerank
  -> context assembler
  -> stored context package
```

Post-answer or capture flow:

```text
content + metadata
  -> policy.decide_capture
  -> extractor.extract
  -> event and memories stored
```

Consolidation flow:

```text
recent memories + behavior events
  -> consolidator.generate_evidence
  -> trait/link/conflict merge
  -> profile traits updated
```

## Core Interfaces

Add a small provider interface layer under `src/pam_os/`:

```python
class MemoryPolicy(Protocol):
    def decide_read(self, task: str, conversation_summary: str | None = None) -> MemoryUseDecision:
        ...

    def decide_capture(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryUseDecision:
        ...


class MemoryExtractor(Protocol):
    def extract(self, event_id: str, content: str, metadata: dict[str, Any]) -> list[Memory]:
        ...


class MemoryRetriever(Protocol):
    def retrieve(self, query: str, *, limit: int, types: list[str] | None = None) -> list[SearchResult]:
        ...


class MemoryReranker(Protocol):
    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        ...


class ProfileConsolidator(Protocol):
    def consolidate(self, *, recent: int = 100) -> ConsolidationResult:
        ...
```

The existing `Extractor` protocol can either remain in `extractor.py` or move into the new interface module. The migration should avoid churn unless moving it improves clarity.

## Provider Types

### Rule Provider

The rule provider is the default and has no external dependencies. It wraps the current behavior:

- read/capture policy from `MemoryOrchestrator`
- extraction from `RuleBasedExtractor`
- lexical retrieval from `MemoryStore`
- deterministic reranking from current `_rerank`
- profile consolidation from current `MemoryConsolidator`

The fixed keyword lists should move out of the orchestration coordinator and into the rule policy implementation.

### LLM Provider

The LLM provider is optional and disabled by default in the first phase. The architecture should provide stable extension points for:

- read/capture decisions with JSON output
- memory extraction into typed memories
- profile evidence generation
- trait merge, contradiction, and supersession analysis
- reflection summaries from recent memories

LLM outputs must be schema-validated. Invalid output falls back to the rule provider and records a provider error when provider run logging exists.

### Embedding Provider

The embedding provider is optional and disabled by default in the first phase. The architecture should leave room for:

- memory embeddings
- semantic retrieval
- hybrid lexical plus semantic retrieval
- similarity links such as `similar_to`
- duplicate or near-duplicate detection

No embedding dependency is required for the first architecture migration.

## Orchestrator Changes

`MemoryOrchestrator` should become a coordinator rather than the owner of domain-specific decision rules.

Responsibilities it should keep:

- call the configured policy
- build the query
- request profile traits
- retrieve candidate memories
- rerank and budget candidates
- compile and save context packages
- call capture flow when requested

Responsibilities to move out:

- keyword signal maps
- generic question marker rules
- capture signal maps
- hard-coded policy scoring

The default behavior remains identical because the rule policy provider contains the old rules.

## Consolidator Changes

`MemoryConsolidator` should stop being the place where project-specific profile rules accumulate. It should become either:

- the rule provider's deterministic consolidator, or
- a coordinator that delegates candidate generation and trait merge to configured consolidator providers.

For the first implementation phase, prefer the lower-risk path:

```text
MemoryConsolidator interface
  -> RuleProfileConsolidator existing behavior
  -> future LlmProfileConsolidator
```

The existing rule logic can remain behavior-compatible but should be named and located as a rule implementation.

## Retrieval and Reranking

The first phase keeps SQLite FTS/LIKE retrieval. The retriever abstraction should wrap `MemoryStore.search_memories`.

The reranker should preserve current scoring:

```text
relevance * 0.45
+ importance * 0.25
+ confidence * 0.15
+ recency * 0.10
+ stability * 0.05
```

This becomes the default `RuleMemoryReranker`. Future rerankers can add embeddings, profile affinity, task intent, link graph signals, or LLM scoring.

## Storage

Do not require a schema migration in the first implementation phase.

Future-compatible storage additions should be designed but not mandatory:

- `provider_runs`: provider name, capability, input summary, output JSON, error, latency, created_at
- `memory_embeddings`: memory_id, provider, model, dimension, vector encoding, created_at
- `memories.metadata_json`: provider-specific extraction metadata

Existing `memory_links` should become the preferred place for relations such as:

- `supports`
- `contradicts`
- `supersedes`
- `similar_to`
- `derived_from`

## Configuration

Extend configuration without breaking existing config files. Defaults should map to rule-only behavior.

Suggested future shape:

```toml
[memory]
pipeline = "rule"

[providers.rule]
enabled = true

[providers.llm]
enabled = false
provider = ""
model = ""
base_url = ""
api_key_env = ""

[providers.embedding]
enabled = false
provider = ""
model = ""
dimension = 0

[policy]
read_provider = "rule"
capture_provider = "rule"

[extraction]
provider = "rule"

[retrieval]
mode = "lexical"

[consolidation]
provider = "rule"
```

The first phase may add only the fields needed for provider selection. Unused future fields can remain documented but unimplemented until the corresponding provider exists.

## Public API Compatibility

These methods should keep their current public signatures:

- `PersonalMemoryRuntime.remember`
- `PersonalMemoryRuntime.search_memory`
- `PersonalMemoryRuntime.compile_context`
- `PersonalMemoryRuntime.should_use_memory`
- `PersonalMemoryRuntime.prepare_context`
- `PersonalMemoryRuntime.should_capture_memory`
- `PersonalMemoryRuntime.capture_memory`
- `PersonalMemoryRuntime.record_behavior_choice`
- `PersonalMemoryRuntime.consolidate_memory`
- `PersonalMemoryRuntime.get_user_profile`

CLI, MCP, and REST should continue to call the runtime in the same way.

## Implementation Phases

### Phase 1: Architecture Migration

- Add provider/interface modules.
- Move keyword read/capture policy into a rule policy implementation.
- Move current reranking into a rule reranker implementation.
- Wrap current store search in a retriever implementation.
- Move or wrap current consolidation as a rule profile consolidator.
- Update runtime wiring to assemble the rule-only pipeline by default.
- Keep all existing behavior and tests passing.
- Add focused tests that prove custom fake providers can be injected.

### Phase 2: LLM Provider

- Add optional LLM provider abstractions without a default external dependency.
- Use strict JSON schemas for policy, extraction, and consolidation outputs.
- Add timeout, validation, and fallback behavior.
- Add fake LLM provider tests.
- Optionally add provider run logging.

### Phase 3: Embedding and Hybrid Retrieval

- Add optional embedding provider.
- Add embedding storage and migration.
- Add semantic and hybrid retrieval modes.
- Add similarity and dedupe links.
- Add retrieval quality diagnostics.

## Testing Strategy

Phase 1 tests should verify:

- existing runtime tests still pass
- generic questions are still gated by the rule policy
- stable preferences are still captured by the rule policy
- context preparation still includes memories and profile traits
- consolidation still produces the current profile trait behavior
- fake policy provider can force read/capture decisions
- fake retriever/reranker can be injected without changing runtime API

Future provider tests should use fake providers, not real network calls.

## Success Criteria

- PAM-OS still runs fully offline with SQLite and rule providers.
- Existing CLI, MCP, REST behavior remains compatible.
- `orchestrator.py` no longer owns keyword policy tables.
- `consolidator.py` no longer needs to be the long-term home for domain-specific profile intelligence.
- The codebase has clear extension points for LLM and embedding providers.
- The first migration does not require users to configure API keys or install new services.
