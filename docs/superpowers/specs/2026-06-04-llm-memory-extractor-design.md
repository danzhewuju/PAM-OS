# LLM Memory Extractor Provider Design

## Goal

Add an optional LLM-backed memory extractor without changing the default local-first behavior. The LLM extractor is a provider for `raw text -> typed memories`; it does not decide whether memory should be read, whether content should be captured, or how profile traits are consolidated.

## Scope

- Keep `RuleBasedExtractor` as the default extractor.
- Add `LlmMemoryExtractor` behind the existing `MemoryExtractor` protocol.
- Let tests inject fake LLM clients; do not require network access or provider dependencies in the first implementation.
- Add config fields for future provider selection, but keep `[extraction] provider = "rule"` as the default.

## Data Flow

1. `capture_memory` uses policy to decide whether content should be captured.
2. If capture is allowed, runtime calls the configured extractor.
3. `LlmMemoryExtractor` asks its client for strict JSON memories.
4. The extractor validates shape, type, scores, tags, content, and evidence.
5. If the LLM path fails or produces no valid memories, it falls back to `RuleBasedExtractor`.

## Validation Rules

- `type` must be one of `semantic`, `episodic`, `identity`, `preference`, `goal`, `project`, or `style`; invalid values become `semantic`.
- `importance` and `confidence` are clamped to `0..1`.
- `content` must be non-empty.
- `tags` must be a list of non-empty strings.
- If `evidence` is present, it must appear in the source text; otherwise the candidate is skipped.
- If a `fact_key` is present, it is stored as a `fact:<key>` tag.

## Runtime Configuration

Configuration gains these optional sections:

```toml
[extraction]
provider = "rule"

[providers.llm]
enabled = false
model = ""
api_key_env = "OPENAI_API_KEY"
timeout_seconds = 8
```

Runtime only auto-constructs the rule extractor for now. A real LLM client can be added later without changing the extractor protocol or tests.

## Tests

- Default runtime still uses `RuleBasedExtractor`.
- Config parses extraction and LLM provider settings.
- Fake LLM JSON creates typed memories.
- Invalid JSON falls back to rule extraction.
- Client exceptions fall back to rule extraction.
- Evidence not present in source text is rejected and can fall back.
- Invalid score/type fields are normalized.
