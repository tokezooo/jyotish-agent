<!-- /autoplan restore point: /Users/vlad/.gstack/projects/jyotish-agent/main-autoplan-restore-20260607-135529.md -->
# Plan: Jyotish Agent On PyJHora + Pi

## Current Context

Repository started empty on 2026-06-07.

External inputs checked:

- PyJHora `4.8.6`, GitHub HEAD `d8bfa36f9e2206ca0894a833d8dc7106bc955419`.
- Pi coding agent package `@earendil-works/pi-coding-agent` version `0.78.1`.
- PyJHora README says package wheels no longer include ephemeris files from
  version `3.6.6`; they must be copied into `jhora/data/ephe`.
- PyJHora repository `LICENSE` is AGPL-3.0. Packaging metadata inspected in
  `pyproject.toml` also showed MIT, but the repository license file and source
  headers should be treated as controlling for planning. MVP should remain local
  until distribution obligations are deliberately handled.

## Working Thesis

Do not put Jyotish logic inside prompts. Put calculations behind typed tools.

Pi should orchestrate:

- user conversation
- tool selection
- interpretation prompts
- answer formatting

Python should own:

- input validation
- timezone/place normalization
- PyJHora calls
- calculation config
- raw fact serialization
- deterministic tests

## Architecture

```text
User
  |
  v
Pi session
  |
  | calls tools
  v
.pi/extensions/jyotish.ts
  |
  | HTTP or subprocess JSON
  v
Python FastAPI service / CLI adapter
  |
  v
PyJHora facade
  |
  v
PyJHora + ephemeris + place data
```

## Components

### Python Package

Target layout:

```text
jyotish_agent/
  __init__.py
  config.py
  models.py
  validation.py
  pyjhora_facade.py
  interpretations.py
  api.py
  cli.py
tests/
  test_birth_profile_validation.py
  test_pyjhora_facade_golden.py
  test_answer_fact_contract.py
```

Responsibilities:

- define typed request/response models
- isolate all direct PyJHora imports in `pyjhora_facade.py`
- expose deterministic JSON for Pi
- keep LLM interpretation outside calculation code

### Pi Extension

Target layout:

```text
.pi/
  extensions/
    jyotish.ts
  skills/
    jyotish-reading/
      SKILL.md
```

Tools to register:

- `jyotish_validate_birth_data`
- `jyotish_compute_chart`
- `jyotish_answer_question`

The first two tools must be deterministic. `jyotish_answer_question` may call
the calculation service and then force the model to cite only returned facts.

### API Shape

`POST /birth-profiles/validate`

```json
{
  "name": "Example",
  "date": "1990-01-01",
  "time": "12:30:00",
  "place": {
    "name": "Chennai, IN",
    "latitude": 13.0827,
    "longitude": 80.2707,
    "timezone": 5.5
  },
  "birth_time_confidence": "exact"
}
```

`POST /charts/compute`

```json
{
  "birth_profile": {},
  "config": {
    "ayanamsa": "LAHIRI",
    "rahu_ketu": "true_nodes",
    "charts": ["D1", "D9"],
    "reference_date": "2026-06-07"
  }
}
```

Response contract:

```json
{
  "normalized_input": {},
  "calculation_config": {},
  "facts": {
    "ascendant": {},
    "d1": [],
    "d9": [],
    "panchanga": {},
    "vimshottari": {}
  },
  "warnings": [],
  "provenance": {
    "engine": "PyJHora",
    "engine_version": "4.8.6"
  }
}
```

## Implementation Phases

### Phase 1: Repo Baseline

- Add Python project config with Python 3.12.
- Add FastAPI, Pydantic, pytest, httpx, PyJHora dependencies.
- Add README setup instructions.
- Add a license-risk note before distribution.

Exit criteria:

- `pytest` runs.
- Service imports without loading PyQt UI modules.

### Phase 2: PyJHora Facade Spike

- Install PyJHora and verify headless imports.
- Verify ephemeris data availability.
- Implement one known birth-data golden fixture.
- Compute D1, D9, panchanga basics, Vimshottari.
- Serialize all outputs to stable JSON.

Exit criteria:

- One golden fixture passes.
- Repeated runs return byte-stable normalized JSON except timestamps.

### Phase 3: Local API

- Add FastAPI endpoints for validation and chart computation.
- Add structured errors with problem/cause/fix.
- Add request logging without birth data leakage.
- Add test coverage for invalid dates, missing timezone, low precision time.

Exit criteria:

- Local `uvicorn` service answers chart requests.
- Invalid input produces actionable error messages.

### Phase 4: Pi Tooling

- Add `.pi/extensions/jyotish.ts`.
- Register deterministic validation and chart tools.
- Call Python service through HTTP first; subprocess fallback can come later.
- Add a Pi skill that tells the agent how to answer Jyotish questions from facts.

Exit criteria:

- In a Pi session, the agent can call `jyotish_compute_chart`.
- The tool result is visible and structured.

### Phase 5: Interpretation Contract

- Add prompt/skill rules for fact-cited answers.
- Add answer schema with `summary`, `facts_used`, `uncertainty`, `followups`.
- Add tests that fail when an answer references absent facts.

Exit criteria:

- Agent answers cite only facts returned by the tool.
- Safety redirects work for medical/financial/deterministic claims.

## Review Targets For `/autoplan`

UI scope: no.

DX scope: yes. This is a developer-facing agent backend and Pi extension.

Plan review should focus on:

- PyJHora license and distribution implications.
- Ephemeris/place-data install flow.
- Stability of PyJHora APIs used directly.
- Whether FastAPI is necessary for MVP or a subprocess JSON bridge is cleaner.
- Pi extension/tool contract and developer setup time.
- Golden fixture strategy and fact-citation enforcement.

## NOT In Scope

- Full SaaS deployment.
- User accounts.
- Payments.
- Web UI.
- Chart image rendering.
- Marriage matching.
- Remedial prescriptions.
- Full JHora parity.

## What Already Exists

- PyJHora has D1/D9 chart functions via `jhora.horoscope.chart.charts`.
- PyJHora has panchanga resources via `jhora.panchanga.info`.
- PyJHora has Vimshottari via `jhora.horoscope.dhasa.graha.vimsottari`.
- Pi supports project extensions under `.pi/extensions/`.
- Pi supports project skills under `.pi/skills/` and `.agents/skills/`.
- Pi SDK can create sessions and register tools through extensions.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| PyJHora AGPL license | Distribution may force AGPL obligations | Keep MVP local; consult license before SaaS/public package |
| Missing ephemeris files | Calculations fail or drift | Add startup check and setup script |
| PyQt dependency | Headless server install may become noisy | Avoid UI imports; test clean service startup |
| Place/timezone ambiguity | Wrong chart | Require explicit lat/lon/timezone after MVP |
| LLM hallucinated facts | User loses trust | Enforce `facts_used` and answer tests |
| PyJHora global config mutation | Cross-request contamination | Single-process lock or worker isolation if needed |

## Initial Test Plan

- Unit: validate birth profile schema.
- Unit: reject missing timezone unless lat/lon resolver is implemented.
- Unit: facade returns D1/D9 structures for golden fixture.
- Unit: facade includes calculation config in every response.
- Integration: FastAPI `POST /charts/compute`.
- Integration: Pi tool returns the same JSON as API.
- Contract: interpretation cannot reference facts absent from tool output.

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|---|---|---|---|---|---|
| 1 | Intake | Start with local deterministic Python calculation service plus Pi tools | Mechanical | Explicit over clever | Keeps PyJHora state, data, and validation away from prompts | Prompt-only Jyotish agent |
| 2 | Intake | MVP includes D1, D9, panchanga basics, Vimshottari only | Mechanical | Choose completeness | This is enough for useful readings without taking on full JHora parity | All PyJHora features in MVP |
| 3 | Intake | Treat PyJHora as AGPL-governed for planning | Mechanical | Pragmatic | The repository LICENSE is AGPL-3.0 despite conflicting package metadata | Assuming MIT from pyproject only |
| 4 | Intake | Force fact-cited answer contract from day one | Mechanical | Boil lakes | Trust boundary is core product behavior, not polish | Free-form LLM reading |

## Autoplan Review Report

STATUS: DONE_WITH_CONCERNS

This is a first-pass `/autoplan` report adapted to the current Codex environment.
The canonical gstack flow requires native AskUserQuestion gates and Claude subagent
execution; those were not available here. I still ran the useful review path:
external source check, repo/context inspection, CEO review, engineering review,
and DX review.

UI scope: no.

DX scope: yes. This is a developer-facing backend plus Pi extension.

### Phase 1: CEO Review

Premise challenge:

| Premise | Verdict | Reason |
|---|---|---|
| PyJHora should be the calculation base | Accepted with guardrail | It covers the needed Jyotish primitives, but must be wrapped behind a stable facade |
| Pi should be the harness/backend | Refined | Pi should be the harness and tool surface; Python should remain the calculation backend |
| The product can start as an agent, not a web app | Accepted | Local Pi gives faster iteration and avoids premature SaaS scope |
| Interpretations can be useful if calculation facts are reliable | Accepted with caveat | The product must visibly separate computed facts from symbolic interpretation |

Implementation alternatives:

| Option | Effort | Pros | Cons | Decision |
|---|---:|---|---|---|
| Prompt-only Pi skill | Low | Fastest demo | Hallucinates chart facts, weak trust | Rejected |
| Pi extension calling Python subprocess | Medium | Simple local install, no server lifecycle | Harder streaming/debugging for multi-call flows | Deferred |
| Pi extension calling FastAPI service | Medium | Clear boundary, testable API, easy future UI | One more process for MVP | Selected |
| Full SaaS from day one | High | Future distribution path | Distracts from calculation/tool contract | Rejected |

Dream state delta:

```text
CURRENT
  empty repo, researched PyJHora/Pi
THIS PLAN
  local deterministic calculator + Pi tools + fact-cited readings
12-MONTH IDEAL
  trusted Jyotish agent with profile memory, configurable traditions, evals,
  and optional product surfaces beyond Pi
```

CEO findings:

| Finding | Severity | Decision |
|---|---|---|
| AGPL licensing is the main strategic risk | High | Keep MVP local until distribution model is decided |
| Scope can explode into full JHora parity | High | Keep MVP to D1/D9/panchanga/Vimshottari |
| Trust boundary is the product | High | Fact-cited answer contract is mandatory |
| Distribution should wait | Medium | Local-first until license/data story is clean |

NOT in scope:

- SaaS deployment.
- Public distribution package.
- Marriage matching.
- Chart rendering.
- Remedies and deterministic predictions.

What already exists:

- PyJHora calculation modules for charts, panchanga, dashas, yogas, and doshas.
- Pi project extensions and skills discovery.
- Pi SDK/tool registration mechanism.

### Phase 2: Design Review

Skipped. No UI scope detected. The only user-facing surface in MVP is terminal/agent
conversation, covered under DX and answer-contract requirements.

### Phase 3: Engineering Review

Architecture diagram:

```text
.pi/extensions/jyotish.ts
  -> HTTP client
    -> FastAPI api.py
      -> Pydantic models.py
      -> validation.py
      -> pyjhora_facade.py
        -> jhora.horoscope.chart.charts
        -> jhora.panchanga.info / drik
        -> jhora.horoscope.dhasa.graha.vimsottari
```

Architecture findings:

| Finding | Severity | Fix |
|---|---|---|
| PyJHora may mutate global config | High | Keep all config explicit, serialize calls if needed, test cross-request isolation |
| Ephemeris files may be absent from wheel installs | High | Add startup check with exact remediation |
| PyQt dependency can leak into headless server | Medium | Never import `jhora.ui.*`; add import smoke test |
| Timezone/place resolution can silently corrupt output | High | Require explicit timezone in MVP |

Test diagram:

| Path | Test Type | Required Coverage |
|---|---|---|
| Birth profile validation | Unit | date/time format, timezone required, lat/lon ranges |
| PyJHora facade import | Unit | service imports without PyQt UI |
| D1/D9 calculation | Golden unit | one known fixture returns stable JSON |
| Panchanga basics | Golden unit | stable keys and config metadata |
| Vimshottari period | Golden unit | stable period structure for reference date |
| API chart endpoint | Integration | valid request and validation errors |
| Pi tool call | Integration/manual | Pi tool output matches API JSON |
| Answer facts contract | Contract | cited facts must exist in tool output |

Failure modes:

| Failure | User Impact | Mitigation |
|---|---|---|
| Missing ephemeris | chart request fails | startup check and setup script |
| Wrong timezone | wrong chart | require explicit timezone before resolver exists |
| Hallucinated interpretation | trust loss | schema + tests for `facts_used` |
| License mistake | distribution risk | local-only until AGPL obligations are addressed |

### Phase 3.5: DX Review

Developer persona:

Backend/product engineer building a local agent tool, comfortable with Python and
TypeScript, but expecting setup to work in under five minutes.

Developer journey map:

| Stage | Target Experience | Current Gap |
|---|---|---|
| Clone repo | obvious README | README exists but setup commands not implemented |
| Install Python deps | one command | no project config yet |
| Install Pi deps | one command | no `.pi` extension yet |
| Start service | one command | API not implemented yet |
| Validate birth data | one HTTP/tool call | models not implemented yet |
| Compute chart | one HTTP/tool call | facade not implemented yet |
| Ask question in Pi | direct agent flow | skill not implemented yet |
| Debug error | problem/cause/fix | error schema planned only |
| Extend tool | documented file boundaries | architecture planned only |

TTHW assessment:

- Current: not runnable yet.
- Target after Phase 4: under 5 minutes from clone to first computed chart.
- Blocking DX issue: no setup script or golden fixture yet.

DX scorecard:

| Dimension | Current | Target | Notes |
|---|---:|---:|---|
| Getting started | 2/10 | 8/10 | Needs pyproject, scripts, `.pi` files |
| API/tool naming | 7/10 | 8/10 | Proposed names are explicit |
| Error messages | 4/10 | 8/10 | Planned but not implemented |
| Docs | 5/10 | 8/10 | PRD/PLAN exist; README setup absent |
| Testability | 6/10 | 9/10 | Good test strategy, no code yet |
| Upgrade path | 3/10 | 6/10 | Pin versions and document data updates |

DX implementation checklist:

- [ ] Add `pyproject.toml` with pinned runtime dependencies.
- [ ] Add `scripts/check_pyjhora_data.py`.
- [ ] Add `make dev` or equivalent one-command local service start.
- [ ] Add `.pi/extensions/jyotish.ts`.
- [ ] Add `.pi/skills/jyotish-reading/SKILL.md`.
- [ ] Add copy-paste README quickstart.
- [ ] Add golden fixture and expected JSON.

### Cross-Phase Themes

Theme: trust boundary. Flagged by CEO, Eng, and DX. The project wins only if
calculation facts are deterministic and interpretations cite those facts.

Theme: local-first scope. Flagged by CEO and DX. It keeps licensing, install, and
product iteration manageable.

Theme: PyJHora packaging risk. Flagged by CEO and Eng. Ephemeris data and AGPL
obligations must be solved before distribution.

### Implementation Tasks

- [ ] P1 — Decide AGPL-safe PyJHora usage model: local-only, open-source release, or alternate engine.
- [ ] P1 — Add Python project baseline with tests.
- [ ] P1 — Implement `pyjhora_facade.py` with D1, D9, panchanga, Vimshottari.
- [ ] P1 — Add ephemeris/data startup check.
- [ ] P1 — Add golden fixture for one birth profile.
- [ ] P2 — Add FastAPI endpoints and structured error responses.
- [ ] P2 — Add Pi extension tools for validate and compute.
- [ ] P2 — Add Jyotish reading skill for fact-cited answers.
- [ ] P2 — Add answer contract tests.

### Review Scores

- CEO: pass with high concern on AGPL/scope.
- Design: skipped, no UI scope.
- Eng: pass with required guardrails before implementation.
- DX: 4/10 now, target 8/10 after setup and Pi extension.

### Unresolved Decisions

1. FastAPI vs subprocess bridge for the first Pi tool.
   Recommendation: FastAPI first because the boundary is cleaner and future UI/API
   reuse is likely.

2. Ayanamsa default.
   Recommendation: Lahiri for golden-test stability first; expose config explicitly.

3. Birth-place resolver.
   Recommendation: require explicit lat/lon/timezone in MVP, add resolver later.

4. Distribution posture.
   Recommendation: local-only until AGPL obligations are addressed.

## GSTACK REVIEW REPORT

| Review | Status | Findings |
|---|---|---|
| CEO Review | concerns_open | AGPL distribution risk, scope explosion risk, trust boundary mandatory |
| Design Review | skipped | no UI scope |
| Eng Review | concerns_open | global config, ephemeris data, timezone validation, PyQt import risk |
| DX Review | concerns_open | no runnable quickstart yet, TTHW target not met |
