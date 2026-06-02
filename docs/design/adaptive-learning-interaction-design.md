# Adaptive Learning Interaction Design

## Goal

PAM-OS should be able to adapt while the user talks normally with a model. The user should not need to call `learn_policy_signal` or think in terms of tables, thresholds, or policy actions.

Internally, the system still needs explicit, auditable operations. "No explicit call" means no explicit call from the user, not no write path inside PAM-OS.

The interaction design should make the assistant feel attentive without becoming spooky, noisy, or hard to correct.

## Design Principles

- Invisible by default, inspectable on demand.
- Evidence before belief: one turn creates a candidate, not a stable rule.
- Local admission decides what enters storage; LLM output can propose, but cannot directly persist trusted policy.
- Confirmation is reserved for ambiguous, high-impact, or personal identity changes.
- Corrections should be first-class feedback, not just new memories.
- Every automatic learning decision must be explainable from local signals, thresholds, and trace records.

## User-Facing Modes

### Quiet Auto

Default mode for normal conversation.

The assistant silently observes turns, captures low-risk stable facts, and creates weak policy candidates when confidence is moderate. It should not interrupt the conversation with "I learned this" messages.

Examples:

- User says: "以后遇到这种情况，默认先给我两个方案再推荐一个。"
- PAM-OS captures a style/workflow memory.
- PAM-OS may create an active capture policy signal for `feature:future_instruction`.

### Confirm Important

Used when the candidate affects identity, privacy, broad behavior, or long-lived automation.

Examples that should ask or stage instead of immediately stabilizing:

- "I am a doctor" / "用户是医生"
- "Always remember anything I say"
- "Use memory for every question"
- "Never ask me before saving"

The confirmation should be short:

```text
我可以把“以后默认先给两个方案再推荐一个”作为长期交互偏好记住。
```

The product UI can expose accept / edit / dismiss. A plain chat-only surface can defer confirmation until the next summary or memory review.

### Review Digest

Periodic review mode, not every turn.

The system summarizes recent candidates:

```text
本轮我观察到 3 个可能值得长期保留的点：
- 你偏好先看两个方案再给推荐。
- 你在 PAM-OS 中倾向本地、可审计的自动学习。
- “沿着那条线”常表示继续之前的项目上下文。
```

The user can approve, edit, reject, or ignore. Ignored candidates remain weak and expire or archive.

### Explain / Undo

The user can ask:

```text
你为什么刚才读了记忆？
你刚才学到了什么？
撤销刚才学到的东西。
不要再因为“那条线”读记忆。
```

These interactions should map to quality traces, policy signal reinforcement, and archival.

## Internal Turn Loop

```text
User message
  -> before_turn
      -> prepare_context
      -> record policy decision trace
  -> model response
  -> after_turn observer
      -> extract memory candidates
      -> extract policy candidates
      -> admission gate
      -> store candidate / active signal
      -> record admission trace
  -> later feedback
      -> reinforce or reject matching signals
      -> promote / archive via status machine
```

The user experiences this as normal conversation. PAM-OS experiences it as explicit runtime calls.

## Candidate Types

### Memory Candidate

Long-term user or project content:

- identity: name, role, location, timezone, language
- preference: tools, style, interests, constraints
- goal: durable objective or plan
- project: technical decision or active context
- style: response and collaboration guidance

These flow through `capture_memory`.

### Policy Signal Candidate

A rule about when PAM-OS should use memory:

- read: "continue that thread" means use memory
- capture: "next time default to X" means capture a durable instruction
- suppress: "don't remember this kind of thing" means avoid capture
- consolidate: repeated behavior choices should be promoted

These flow through a new admission controller before `learn_policy_signal`.

### Behavior Feedback Candidate

Evidence from choices and corrections:

- user chooses one proposed option
- user rejects retrieved context
- user says the assistant forgot something
- user says a memory was wrong

These flow through `record_behavior_choice` and policy reinforcement.

## Policy Signal Admission

Automatic policy learning should not call `learn_policy_signal` directly. It should pass through a local gate:

```python
class PolicySignalAdmissionController:
    def evaluate(self, candidate: PolicySignalCandidate) -> AdmissionDecision:
        ...
```

The decision has:

```text
allow: bool
status: skipped / candidate / active / stable
confidence: float
reason: str
signals: list[str]
risk: low / medium / high
```

### Admission Rules

Low-risk candidates may become `active` automatically:

- explicit future instruction: "以后/下次/默认/from now on"
- repeated short follow-up phrase with clear context
- correction that narrowly changes a read/capture behavior

Medium-risk candidates become `candidate` and wait for repetition or review:

- broad workflow preference
- ambiguous project shorthand
- model-inferred pattern with no explicit user phrasing

High-risk candidates are skipped or require confirmation:

- secrets, credentials, private identifiers
- medical/legal/financial-sensitive personal attributes
- "remember everything" / "always use memory"
- broad suppressions that could disable memory globally

### Example Scoring

```text
base explicit future instruction      +0.35
first-person statement                +0.10
contains "以后/下次/默认"              +0.25
same pattern seen before              +0.10
model-only inference                  -0.20
too broad pattern                     -0.30
sensitive/private content             reject
```

Suggested thresholds:

```text
score >= 0.85 and support_count >= 3 -> stable
score >= 0.62                       -> active
score >= 0.40                       -> candidate
otherwise                           -> skip
```

This matches the existing `policy_signals` status machine while adding a pre-write gate.

## Feedback and Reinforcement

Positive reinforcement:

- user says "对，就是这个"
- retrieved memory directly helps answer
- user continues smoothly after a memory-based answer
- user repeats the same shorthand in a similar context

Negative reinforcement:

- user says "不是这个"
- user corrects identity or preference
- retrieved context is ignored or contradicted
- user asks why memory was used and rejects the reason

Negative feedback should call `reinforce_policy_signal(..., supported=False)` or archive a candidate.

## Audit Trail

Automatic learning needs quality traces, just like `prepare_context` and `capture_memory`.

Recommended trace shape:

```text
operation = learn_policy_signal
stage = admission
provider = PolicySignalAdmissionController
decision = skip / candidate / active / stable / rejected
signals = [...]
related_ids = [policy_signal_id]
metrics = {
  confidence,
  risk,
  pattern,
  normalized_intent,
  source_turn_id
}
```

This lets a user or developer answer:

- Why did PAM-OS learn this?
- Which turn caused it?
- Was it an LLM suggestion or local rule?
- How confident was the admission gate?
- How do I undo it?

## Interaction Commands

The chat layer should support natural-language control phrases:

```text
你刚才学到了什么？
解释为什么这次读记忆。
撤销刚才学到的。
不要因为“那条线”自动读记忆。
以后这种都不用问我。
这条可以记住。
这条不要记。
```

These map to inspect, reinforce, archive, capture, or review operations.

## Implementation Phases

### Phase 1: Observe and Trace

- Add `AdaptiveLearningLoop.observe_turn`.
- Generate memory and policy candidates.
- Record traces for candidates.
- Do not write policy signals automatically except very explicit low-risk cases.

### Phase 2: Candidate Store

- Add candidate/staging status for automatic policy candidates.
- Review digest can list candidates.
- Repetition reinforces candidates.

### Phase 3: Automatic Active Signals

- Allow low-risk candidates to become active automatically.
- Require confirmation for high-impact candidates.
- Add undo and suppression interactions.

### Phase 4: Rich Feedback

- Use answer outcomes and user corrections to reinforce or archive signals.
- Link policy signals to quality traces and source turns.
- Add user-facing review and edit flows.

## Non-Goals

- Do not make the LLM the authority for persistent learning.
- Do not learn from every message.
- Do not turn every memory into a policy signal.
- Do not silently stabilize sensitive identity, privacy, or global automation rules.
- Do not make policy decisions impossible to inspect or undo.

## Recommended Default

Start conservative:

```text
quiet auto capture for low-risk memories
candidate-only policy learning for inferred patterns
active policy learning for explicit durable instructions
review digest for medium-risk patterns
confirmation for high-risk patterns
full quality trace for every admission decision
```

This gives the user the feeling that PAM-OS adapts during normal conversation while keeping the system local, explainable, and reversible.
