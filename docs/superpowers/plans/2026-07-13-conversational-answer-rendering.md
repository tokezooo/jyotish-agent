# Conversational Answer Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a natural, backend-validated answer in Pi while keeping claims, confidence, evidence IDs, and fact paths out of the chat UI.

**Architecture:** Keep AnswerContract 2.0 and the immutable evidence ledger unchanged. Replace the technical canonical Markdown renderer with a deterministic human renderer based on synthesis text, limitations, and follow-ups; then make the Pi final-message gate preserve byte-identical validated prose and replace all divergent prose. Reset terminal run state only when a fresh run is explicitly reserved so a validated conversation can continue safely.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, SQLite, TypeScript, Pi extensions, pytest, Bun.

## Global Constraints

- AnswerContract 2.0 and its persisted claims/evidence graph remain unchanged.
- The visible answer must be byte-identical to backend-validated Markdown.
- Computed/source claim details stay available through SQLite and `run inspect --json`.
- Unsafe, invalid, unresolved, and repair-exhausted flows remain fail-closed.
- Existing immutable answer rows and hashes are never rewritten.

---

### Task 1: Deterministic human answer renderer

**Files:**
- Modify: `src/jyotish_agent/answer_contract.py:170-203`
- Modify: `tests/test_answer_contract_v2.py:166-185`

**Interfaces:**
- Consumes: `AnswerContractV2`, including ordered `SynthesisClaim.text`, `limitations`, and `followups`.
- Produces: unchanged `render_answer_markdown(answer, evidence_items) -> RenderedAnswer` signature with human-facing Markdown and SHA-256.

- [ ] **Step 1: Write the failing renderer test**

Replace the technical-output assertions with assertions that the synthesis prose is present and internal details are absent:

```python
assert first.markdown.startswith("# Career research memo\n\n")
assert "The computed ascendant can frame" in first.markdown
assert "## Важно" in first.markdown
assert "## Что можно уточнить" in first.markdown
for internal in ("## Claims", "Computed", "confidence", "ascendant.sign", "evi_"):
    assert internal not in first.markdown
assert first.sha256 == hashlib.sha256(first.markdown.encode()).hexdigest()
```

Add a test with two synthesis claims proving contract-order paragraph rendering and a test proving a contract without synthesis is rejected by `validate_answer_contract`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/test_answer_contract_v2.py::test_renderer_uses_structured_computed_evidence_and_is_deterministic -q
```

Expected: FAIL because the current renderer emits `## Claims`, `Computed`, confidence, and fact paths.

- [ ] **Step 3: Implement the minimal human renderer and synthesis validation**

In `validate_answer_contract`, add a violation when no `SynthesisClaim` exists. In `render_answer_markdown`, select synthesis claims in contract order and render:

```python
lines = [f"# {answer.title}", ""]
for index, claim in enumerate(synthesis_claims):
    if index:
        lines.append("")
    lines.append(claim.text.strip())
if answer.limitations:
    lines.extend(["", "## Важно", ""])
    lines.extend(f"- {item}" for item in answer.limitations)
if answer.followups:
    lines.extend(["", "## Что можно уточнить", ""])
    lines.extend(f"- {item}" for item in answer.followups)
```

The evidence parameter remains part of the stable interface but is not rendered.

- [ ] **Step 4: Run focused and contract tests GREEN**

Run:

```bash
uv run pytest tests/test_answer_contract_v2.py tests/test_research_api.py -q
```

Expected: all tests PASS after updating assertions that intentionally described technical Markdown.

- [ ] **Step 5: Commit**

```bash
git add src/jyotish_agent/answer_contract.py tests/test_answer_contract_v2.py tests/test_research_api.py
git commit -m "feat: render validated answers as human prose"
```

### Task 2: Conversational Pi final-message gate

**Files:**
- Modify: `.pi/extensions/jyotish.ts:992-1014`
- Modify: `ts-tests/jyotish.test.ts:868-995`

**Interfaces:**
- Consumes: `ResearchRuntime.validatedMarkdown` captured only from a validated backend result.
- Produces: `gateFinalMessage(message)` returns `undefined` for byte-identical validated prose and a replacement message for divergent prose.

- [ ] **Step 1: Write failing Pi gate tests**

Add assertions for both branches:

```typescript
const canonical = { role: "assistant", content: [{ type: "text", text: "# Answer\n\nHuman prose.\n" }] };
runtime.settle("submit-call", false, validatedDetails, () => {});
expect(runtime.gateFinalMessage(canonical)).toBeUndefined();

const divergent = { role: "assistant", content: [{ type: "text", text: "Unsupported addition" }] };
expect(runtime.gateFinalMessage(divergent)?.content).toEqual(canonical.content);
```

Keep the existing pre-validation, reconciliation, refusal, and capability-failure assertions unchanged.

- [ ] **Step 2: Run the focused Bun test and verify RED**

Run:

```bash
bun test ts-tests/jyotish.test.ts -t "preserves byte-identical validated prose"
```

Expected: FAIL because the current gate always returns a replacement even when text is identical.

- [ ] **Step 3: Implement exact-match preservation**

Extract the concatenated text only when every visible content item is text. If the validated state is complete and concatenated text is byte-identical to `validatedMarkdown`, return `undefined`; otherwise retain the current canonical replacement behavior. Tool calls and non-terminal messages remain untouched.

- [ ] **Step 4: Run extension tests and typecheck GREEN**

Run:

```bash
bun test ts-tests/jyotish.test.ts
bun run typecheck
```

Expected: all Bun tests PASS and TypeScript reports no errors.

- [ ] **Step 5: Commit**

```bash
git add .pi/extensions/jyotish.ts ts-tests/jyotish.test.ts
git commit -m "feat: preserve validated conversational replies"
```

### Task 3: Start a fresh run after a terminal answer

**Files:**
- Modify: `.pi/extensions/jyotish.ts:650-705`
- Modify: `ts-tests/jyotish.test.ts:414-575`
- Modify: `.pi/skills/jyotish-reading/SKILL.md`

**Interfaces:**
- Consumes: a `jyotish_create_research_run` reservation with a new `run_id`, fresh `operation_id`, and `expected_revision=0`.
- Produces: a new active run only when the previous run is terminal (`validated` or `refused_unsafe`); unresolved and nonterminal runs remain blocked.

- [ ] **Step 1: Write the failing lifecycle tests**

Restore a validated mirror, begin a new assistant-message leaf, and assert that a fresh create reservation is allowed. Add table-driven assertions that `created`, `screened_safe`, `planned`, `calculated`, `answer_needs_repair`, and `unresolved` still block fresh create. Verify the new reservation clears old `validatedMarkdown` and refusal state so stale output cannot pass the next final gate.

- [ ] **Step 2: Run focused lifecycle tests and verify RED**

Run:

```bash
bun test ts-tests/jyotish.test.ts -t "starts a fresh run after a terminal answer"
```

Expected: FAIL with `This Pi branch already has an active or unresolved research run.`

- [ ] **Step 3: Implement terminal-to-new-run transition**

In the create reservation branch, permit replacement only when the active snapshot is complete and its status is `validated` or `refused_unsafe`. Before appending the new reservation, clear terminal presentation state and make the new unresolved reservation authoritative. Do not broaden any other transition.

Update the root skill workflow to state that every new Jyotish question starts a new v2 run even on an existing Pi conversation, while follow-up clarification that does not make a new reading may remain conversational.

- [ ] **Step 4: Run Pi tests and typecheck GREEN**

Run:

```bash
bun test ts-tests/jyotish.test.ts
bun run typecheck
```

Expected: all tests PASS; stale terminal renderings cannot leak into the next run.

- [ ] **Step 5: Commit**

```bash
git add .pi/extensions/jyotish.ts .pi/skills/jyotish-reading/SKILL.md ts-tests/jyotish.test.ts
git commit -m "feat: continue research across Pi turns"
```

### Task 4: Regression and real-flow verification

**Files:**
- Modify only if a regression test reveals a scoped defect.

**Interfaces:**
- Consumes: the human renderer and Pi lifecycle changes from Tasks 1-3.
- Produces: evidence that validation, hash gates, replay, v1 compatibility, and conversational Pi output remain correct.

- [ ] **Step 1: Run the complete automated suite**

```bash
uv run pytest -q
bun test ts-tests/jyotish.test.ts
bun run typecheck
uv run ruff check src tests
git diff --check
```

Expected: all project tests pass; only the existing Swiss Ephemeris availability skips are allowed.

- [ ] **Step 2: Run an isolated end-to-end smoke**

Use a temporary `JYOTISH_AGENT_DATA_ROOT`, the real loopback FastAPI service, and a scripted/fake Pi provider to submit a supported answer. Assert the terminal stdout contains synthesis prose and does not contain `## Claims`, `Computed`, `confidence`, or a fact path. Submit a second question on the same simulated branch and assert it receives a different `run_id`.

- [ ] **Step 3: Verify the existing run can be displayed readably without mutation**

Load `rr_7ec47a40-5ce0-4c07-8c00-fcce12135650` from SQLite, pass its stored contract through the new human renderer in a read-only command, and compare the database answer payload before and after. The stored payload and hash must remain unchanged.

- [ ] **Step 4: Commit any verification fixture changes**

```bash
git add tests ts-tests
git commit -m "test: cover conversational research flow"
```

- [ ] **Step 5: Push the completed branch**

```bash
git push origin codex/research-agent-v2
```
