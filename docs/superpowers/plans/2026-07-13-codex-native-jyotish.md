# Codex-Native Jyotish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install a local stdio MCP server and global Codex skill that support ordinary Jyotish conversation, stateless quick questions, contextual follow-ups, and ResearchRun-backed deep research.

**Architecture:** Add a typed `JyotishMcpFacade` over the existing calculation, corpus, ResearchService, and SQLite layers, then expose that facade through the stable v1 official MCP Python SDK. Keep quick operations stateless; deep operations reuse the existing authoritative ledger. Install a source-controlled skill through a user-level symlink and register the stdio server in Codex global MCP config.

**Tech Stack:** Python 3.12, `mcp>=1.27,<2`, FastMCP stdio, Pydantic 2, SQLite/WAL, pytest, Codex MCP config, Agent Skills.

## Global Constraints

- No separately managed FastAPI or Pi process is required for Codex use.
- Quick calculations and source searches create no ResearchRun rows.
- Deep research creates one authoritative run and preserves AnswerContract 2.0 validation.
- The default profile is private, outside Git, with `0700` directories and `0600` file mode.
- MCP stdout contains protocol frames only; diagnostics never contain birth data, questions, excerpts, or claims.
- Ordinary answers hide claims, confidence, evidence IDs, checksums, fact paths, and state-machine details.
- Existing FastAPI, CLI, Pi, v1/v2 contracts, and completed runs remain compatible.

---

### Task 1: MCP dependency and typed facade boundary

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/jyotish_agent/mcp_models.py`
- Create: `src/jyotish_agent/mcp_facade.py`
- Create: `tests/test_mcp_facade.py`

**Interfaces:**
- Produces: `JyotishMcpFacade(data_root: Path, default_profile_path: Path | None, clock=...)`.
- Produces: `get_profile`, `calculate`, `search_sources`, `research`, `finalize_research`, and `inspect_research` methods returning Pydantic response models.
- Consumes: existing `ResearchBirthProfileRequest`, `CalculationConfigRequest`, `ResearchService`, `ResearchStore`, and `compute_chart`.

- [ ] **Step 1: Add failing profile and stateless-operation tests**

Create fixtures with a private profile JSON and temporary data root. Assert:

```python
facade = JyotishMcpFacade(tmp_path / "data", profile_path)
assert facade.get_profile().profile["name"] == "Vlad"
before = facade.store.count_runs()
quick = facade.calculate(CalculateInput(question="What is my D10 ascendant?", charts=["D1", "D10"]))
sources = facade.search_sources(SourceSearchInput(query="career", limit=5))
assert facade.store.count_runs() == before
assert quick.mode == "quick"
assert sources.mode == "quick"
```

Also test missing profile, inline-profile override, another-person input never falling back to default, file mode rejection, module caps, query caps, and absence of private values from exception strings.

- [ ] **Step 2: Run focused tests RED**

```bash
uv run pytest tests/test_mcp_facade.py -q
```

Expected: import failure because the MCP facade does not exist.

- [ ] **Step 3: Add the stable MCP dependency**

```bash
uv add 'mcp>=1.27,<2'
```

Add `jyotish-mcp = "jyotish_agent.mcp_server:main"` under `[project.scripts]` after Task 3 creates the entrypoint.

- [ ] **Step 4: Implement boundary models and profile loading**

Define strict Pydantic inputs with `extra="forbid"`, bounded strings/results, explicit charts/modules, `profile="default" | "inline"`, and inline `ResearchBirthProfileRequest`. Load the default JSON only when `profile="default"`; validate ancestors, reject symlinks, require a regular file with no group/other mode bits, and validate through `ResearchBirthProfileRequest`.

- [ ] **Step 5: Implement quick calculation and source search**

Adapt fixed-offset and IANA research profiles to the existing calculation boundary without persistence. Return normalized input, facts, warnings, provenance, and selected scope. Search only `ResearchService.search_corpus`; return approved fragment data as quoted data. Do not call `create_run` from either method.

- [ ] **Step 6: Run focused tests GREEN and commit**

```bash
uv run pytest tests/test_mcp_facade.py -q
git add pyproject.toml uv.lock src/jyotish_agent/mcp_models.py src/jyotish_agent/mcp_facade.py tests/test_mcp_facade.py
git commit -m "feat: add Codex Jyotish MCP facade"
```

### Task 2: One-call deep research and validated finalization

**Files:**
- Modify: `src/jyotish_agent/mcp_models.py`
- Modify: `src/jyotish_agent/mcp_facade.py`
- Modify: `src/jyotish_agent/research_store.py`
- Modify: `tests/test_mcp_facade.py`

**Interfaces:**
- Produces: `research(input: ResearchInput) -> ResearchBundle`.
- Produces: `finalize_research(input: FinalizeResearchInput) -> FinalizedResearch`.
- Produces: `inspect_research(input: InspectResearchInput) -> ResearchInspection`.

- [ ] **Step 1: Add failing deep-flow tests**

Use a fake calculator and approved test fragment. Assert one `research` call performs create → screen → plan → calculate → retrieve, creates exactly one run, and returns `run_id`, revision, plan, facts, source results, evidence summaries, and limitations. Test unsafe and unsupported terminal branches without calculation.

Add finalization tests where findings contain `text`, `materiality`, `confidence`, and `supports`. Assert the facade constructs computed/source claims plus synthesis claims, submits AnswerContract 2.0, returns human Markdown without `## Claims`, and rejects missing/foreign supports or stale revisions.

- [ ] **Step 2: Run deep-flow tests RED**

```bash
uv run pytest tests/test_mcp_facade.py -k 'research or finalize or inspect' -q
```

Expected: methods are missing.

- [ ] **Step 3: Add a public run-count helper for invariant tests**

Add `ResearchStore.count_runs() -> int` using `_ready_connection()` and `SELECT COUNT(*) FROM research_runs`. This avoids test/runtime code reaching through private connection helpers.

- [ ] **Step 4: Implement one-call orchestration**

Generate UUID4 operation IDs internally. Pin versions from package constants, deterministically classify the supported `career_factors_and_timing` family from the MCP input, and call the existing service methods in revision order. Retrieval is optional only when the approved corpus is empty; return an explicit limitation rather than fabricating sources.

- [ ] **Step 5: Implement finalization and inspection**

Resolve every support against the run evidence. Create one computed/source leaf claim per referenced evidence item, deduplicate leaves, then create ordered synthesis claims pointing to those leaf claims. Submit through `ResearchService.submit_answer`. Inspection returns concise mode by default and complete `inspect_run`/replay data only when `include_provenance=True`.

- [ ] **Step 6: Run deep-flow and existing v2 tests GREEN and commit**

```bash
uv run pytest tests/test_mcp_facade.py tests/test_answer_contract_v2.py tests/test_research_api.py -q
git add src/jyotish_agent/mcp_models.py src/jyotish_agent/mcp_facade.py src/jyotish_agent/research_store.py tests/test_mcp_facade.py
git commit -m "feat: orchestrate optional deep research over MCP"
```

### Task 3: FastMCP stdio server

**Files:**
- Create: `src/jyotish_agent/mcp_server.py`
- Create: `tests/test_mcp_server.py`
- Create: `tests/test_mcp_stdio.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

**Interfaces:**
- Produces console script: `jyotish-mcp`.
- Produces six MCP tools named `get_profile`, `calculate`, `search_sources`, `research`, `finalize_research`, and `inspect_research`.
- Consumes `JYOTISH_AGENT_DATA_ROOT` and `JYOTISH_DEFAULT_PROFILE_PATH`.

- [ ] **Step 1: Add failing server metadata tests**

Instantiate the server in-process with a temporary facade and use the MCP client/session test transport to assert initialization instructions, exact tool set, JSON schemas, structured output, and tool annotations. Assert the first 512 instruction characters state that normal conversation is default and ResearchRun is only for broad/explicit deep requests.

- [ ] **Step 2: Add failing stdio black-box test**

Start `uv run jyotish-mcp` through `mcp.client.stdio.stdio_client`, initialize a `ClientSession`, list tools, and call `get_profile` and `calculate`. Capture stderr separately and assert stdout protocol parsing succeeds with no contamination.

- [ ] **Step 3: Run server tests RED**

```bash
uv run pytest tests/test_mcp_server.py tests/test_mcp_stdio.py -q
```

Expected: MCP entrypoint is missing.

- [ ] **Step 4: Implement FastMCP registration**

Create `build_server(facade=None) -> FastMCP`, register the six typed functions, and set read-only/destructive/idempotent annotations accurately. Construct the facade lazily from environment paths. `main()` calls `mcp.run(transport="stdio")`; never print to stdout.

- [ ] **Step 5: Add script and operator documentation**

Add `jyotish-mcp` to project scripts. Document the one-time Codex setup, default profile path, explicit quick/deep phrases, `/mcp` verification, and the fact that FastAPI/Pi are compatibility paths rather than prerequisites.

- [ ] **Step 6: Run server tests and type checks GREEN, then commit**

```bash
uv run pytest tests/test_mcp_server.py tests/test_mcp_stdio.py -q
uv run python -m compileall -q src/jyotish_agent
git add pyproject.toml uv.lock README.md src/jyotish_agent/mcp_server.py tests/test_mcp_server.py tests/test_mcp_stdio.py
git commit -m "feat: expose Jyotish as a stdio MCP server"
```

### Task 4: Global Codex skill and private local setup

**Files:**
- Create: `.agents/skills/jyotish-consultant/SKILL.md`
- Create: `.agents/skills/jyotish-consultant/agents/openai.yaml`
- Create: `.agents/skills/jyotish-consultant/references/career.md`
- Create: `.agents/skills/jyotish-consultant/references/timing.md`
- Create: `.agents/skills/jyotish-consultant/references/evidence.md`
- Create: `.agents/skills/jyotish-consultant/references/safety.md`
- Create: `tests/test_codex_skill.py`
- Modify outside Git: `~/.local/share/jyotish-agent/profiles/vlad.json`
- Modify outside Git: `~/.agents/skills/jyotish-consultant` symlink
- Modify outside Git: `~/.codex/config.toml` through `codex mcp add`

**Interfaces:**
- Produces implicit Codex skill `jyotish-consultant` with MCP dependency `jyotish`.
- Produces global stdio MCP configuration named `jyotish`.

- [ ] **Step 1: Add failing deterministic skill checks**

Assert frontmatter/name/description, `agents/openai.yaml` dependency, one-level reference links, explicit quick/deep overrides, default-profile rule, follow-up no-run rule, no technical chat output, and no private birth values committed to the skill tree.

- [ ] **Step 2: Run skill checks RED**

```bash
uv run pytest tests/test_codex_skill.py -q
```

Expected: skill files do not exist.

- [ ] **Step 3: Initialize and author the skill**

Run the built-in `init_skill.py` for `jyotish-consultant` under `.agents/skills` with references and UI interface values. Replace generated placeholders with a concise router and the four one-level references. Run `quick_validate.py` and focused tests.

- [ ] **Step 4: Create the private default profile and governed corpus**

Read Влад's validated profile from the existing authoritative run, write it atomically to `~/.local/share/jyotish-agent/profiles/vlad.json`, set parent directories `0700` and file `0600`, and verify it with `ResearchBirthProfileRequest`. Explicitly seed the bundled governed corpus into the local SQLite store once and verify approved versions/fragments and locator resolution.

- [ ] **Step 5: Install global discovery and MCP configuration**

Create/update the user skill symlink at `~/.agents/skills/jyotish-consultant` pointing to the repository skill. Register:

```bash
codex mcp add jyotish \
  --env JYOTISH_AGENT_DATA_ROOT="$HOME/.local/share/jyotish-agent" \
  --env JYOTISH_DEFAULT_PROFILE_PATH="$HOME/.local/share/jyotish-agent/profiles/vlad.json" \
  -- uv --directory /Users/vlad/Desktop/Projects/jyotish-agent/.worktrees/research-agent-v2 run jyotish-mcp
```

Set the MCP server as enabled/required, allow-list the six tools, and use read/write-aware approvals.

- [ ] **Step 6: Validate installation and commit**

```bash
uv run pytest tests/test_codex_skill.py -q
python /Users/vlad/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/jyotish-consultant
codex mcp get jyotish
git add .agents/skills/jyotish-consultant tests/test_codex_skill.py
git commit -m "feat: add global Codex Jyotish consultant skill"
```

### Task 5: Black-box Codex and completion audit

**Files:**
- Modify only scoped defects or tests revealed by verification.

**Interfaces:**
- Consumes installed global skill and MCP configuration.
- Produces verified normal Codex conversation across conceptual, quick, follow-up, and deep modes.

- [ ] **Step 1: Run MCP client black-box scenarios**

From outside the repository, initialize the configured stdio command, list six tools, call quick calculation, search approved sources, create one deep run, finalize it, and inspect it. Confirm quick calls do not change run count and deep flow changes it by exactly one.

- [ ] **Step 2: Run real Codex non-interactive smoke scenarios**

Start fresh Codex processes with the installed MCP/skill and prompts for:

1. conceptual question — no Jyotish tool call;
2. quick personal question with `ответь кратко` — calculation allowed, no run;
3. follow-up to the quick answer — no new run unless a missing fact is required;
4. `сделай глубокий разбор карьеры` — exactly one run and readable prose.

Capture JSONL or session evidence and assert user-visible output omits technical contracts.

- [ ] **Step 3: Run full regression and privacy checks**

```bash
uv run pytest -q
bun test ts-tests/jyotish.test.ts
bun run typecheck
uv run ruff check src tests
git diff --check
```

Inspect logs, Git diff, MCP config, profile permissions, skill symlink, and SQLite counts. Confirm no birth data or credentials entered Git/logs.

- [ ] **Step 4: Audit every design requirement**

Create a checklist from `docs/superpowers/specs/2026-07-13-codex-native-jyotish-design.md` and attach one authoritative file/test/runtime command to each requirement. Treat missing or indirect evidence as incomplete and continue fixing until every item is proven.

- [ ] **Step 5: Commit fixes, push, and keep worktree for the existing PR**

```bash
git push origin codex/research-agent-v2
```
