# People Understanding / Profile Memory Design

## Goal

The memory runtime should not only remember facts. It should gradually understand the user as a person by tracking explicit statements, behavior choices, corrections, and repeated patterns.

The result is a stable, explainable profile layer that can be injected before ordinary project memories.

## Memory Layers

```text
Raw Events
  -> Extracted Memories
  -> Profile Evidence
  -> Profile Traits
  -> Prepared Context
```

Raw events are immutable evidence. Extracted memories are searchable long-term facts. Profile evidence records why the system believes something about the user. Profile traits are ultra-long-term user attributes such as preferences, values, decision style, workflow, interests, constraints, and communication style.

## Evidence Types

- `explicit_statement`: the user directly states a preference, goal, style, value, or constraint.
- `behavior_choice`: the user chooses, rejects, or defers options during interaction.
- `correction`: the user corrects the model's understanding.
- `repeated_pattern`: the consolidator detects a stable repeated pattern.

One event should not directly become an ultra-long-term trait. It should first become evidence. Repeated or high-quality evidence raises trait confidence and stability.

## Behavior Choices

Behavior choices are first-class because users reveal themselves through decisions.

Example:

```json
{
  "context": "PAM-OS 技术路线",
  "chosen": ["SQLite FTS5"],
  "rejected": ["Qdrant", "Neo4j"],
  "reason": "MVP 阶段先保持本地、轻量、可控"
}
```

This becomes evidence for a trait such as:

```text
用户做技术选型时倾向先选择轻量、本地、可控、可运行的方案验证闭环。
```

## Profile Trait Shape

```text
trait_key: stable normalized key, for example technical.decision_style
trait_type: preference / value / style / interest / capability / constraint / identity / workflow / decision_style
statement: natural language statement for prompt injection
scope: technical / communication / work / personal / general
confidence: how certain the system is
stability: how durable this trait appears
evidence_count: supporting evidence count
status: active / weak / contradicted / archived
```

## Consolidation

The consolidator scans recent memories and behavior events, creates profile evidence, and upserts profile traits.

Promotion is based on simple v0.3 rules:

```text
explicit preference/style/goal/project memory -> profile evidence candidate
behavior choice with chosen/rejected/deferred options -> decision_style evidence
repeated evidence with same trait_key -> higher confidence and stability
```

The MVP keeps this rule-based and deterministic, while leaving room for an LLM consolidator later.

## Context Use

`prepare_context` should prefer profile traits before ordinary memories:

```text
# User Profile
- 用户偏好 self-host、开源、可控系统。
- 用户做技术决策时倾向先用轻量方案验证闭环。

# User Memory Context
...
```

Profile traits are ultra-long-term context. They should be concise, explainable, and backed by evidence.

## Interfaces

REST:

```text
POST /v1/behavior/choice
POST /v1/memory/consolidate
GET /v1/profile
```
