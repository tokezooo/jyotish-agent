<!-- /autoplan restore point: /Users/vlad/.gstack/projects/tokezooo-jyotish-agent/HEAD-autoplan-restore-20260713-230208.md -->

# Plan: Praśna, Muhūrta, and Jaimini Analysis

**Status:** reviewed implementation plan; Alternative B approved  
**Repository baseline:** `origin/main` at `916185a`  
**Product posture:** local-only, deterministic calculation first, governed interpretation second

## Outcome

Make the agent able to:

1. answer a praśna from a sealed operational question moment and place;
2. search, rank, and explain muhūrta windows for a named activity and location;
3. produce a bounded, school-labelled Jaimini Core v1 analysis from natal data, including timing;
4. keep every visible technical claim inside the existing signed fact and governed-source contracts.

The user should ask naturally in Russian or English. Internal tools, fact paths, rule IDs,
scores, evidence IDs, and engine payloads remain hidden unless the user asks to inspect them.

## Confirmed premises

1. **Deterministic facts before interpretation.** No praśna judgement, muhūrta ranking, or
   Jaimini conclusion may be generated from model memory when a calculable fact or rule trace
   can be produced by code.
2. **Three distinct anchors.** Praśna uses a timezone-aware question moment and place;
   muhūrta searches a future interval at an event place; Jaimini uses a natal profile plus a
   reference date for daśā timing. Birth time must never silently substitute for the first two.
3. **School differences are data.** Jaimini and muhūrta rules vary by lineage. Every result
   carries a versioned `rule_profile`; disputed rules are configurable or labelled, never blended.
4. **A practical complete v1 is bounded.** “Jaimini Core v1” means the complete analysis graph in
   the scope below, not every published Jaimini-derived technique. “Muhūrta” means a general
   search engine plus reviewed activity packs, not an unbounded encyclopedia of ceremonies.
5. **Existing trust boundary stays mandatory.** New calculations flow through signed facts,
   citable atoms, source governance, validation, and exact canonical Markdown for deep work.
6. **PyJHora is a primitive provider, not an authority.** Reuse verified astronomical and
   geometric functions, but wrap them with stable schemas and independent fixtures. Do not expose
   raw PyJHora structures or unaudited prediction prose.

## Scope

### Praśna v1

- Strict `PrashnaRequest`: question text, aware `asked_at`, event place/coordinates/timezone,
  time confidence, and rule profile. The operational moment is the receipt of the first complete
  question or an explicit user-supplied time. If the user says “сейчас”, capture once, return the
  normalized timestamp for confirmation, then calculate without recapturing the clock.
- Rāśi chart at the question moment: lagna, planets, bhāva, graha dṛṣṭi, rāśi dṛṣṭi,
  panchāṅga, Moon condition, lagna lord, relevant house/lord, applying/separating geometry where
  supported, and configurable praśna-lagna variants (time-chart default; KP-249/108/nāḍi only
  when explicitly requested).
- Typed topic router maps the question to one primary house and optional secondary houses.
  Unsupported/composite topics request clarification rather than inventing a judgement.
- Radicality/readability checks are emitted as rule results with `pass|warn|fail|not_applicable`,
  never as a silent refusal.
- Output separates chart facts, rule evaluations, interpretive synthesis, uncertainty, and
  follow-up conditions. No deterministic yes/no promise about death, health, litigation,
  pregnancy, investments, or harm.
- The first result returns a signed opaque `anchor_token`, privacy-safe `anchor_summary`, and
  `question_fingerprint`. A follow-up supplies either that token or a new anchor, never both.
  Backend policy verifies reuse for clarification of the same question; a materially new question
  returns `ANCHOR_MISMATCH` with `next_action=create_new_anchor`. The token exposes no raw question,
  coordinates, or birth data.

### Muhūrta v1

- Strict `MuhurtaSearchRequest`: activity type, place, aware date-time range, duration,
  hard constraints, preferences, optional natal profile, rule profile, result limit.
- Search by astronomical boundary events rather than minute-by-minute brute force. Build atomic
  intervals from sunrise/sunset, tithi/nakṣatra/yoga/karaṇa transitions, lagna transitions,
  rāhu-kāla/yamaganda/gulika, durmuhūrta, abhijit, varjyam/amṛta, and requested planetary changes.
- Two-stage evaluator:
  1. hard exclusions remove invalid windows and record exact rule traces;
  2. soft rules rank remaining windows with versioned weights and explain contributions.
- Start with `general` plus one separately reviewed low-risk activity pack selected at the Muhūrta
  gate. Marriage, elective medical, and contract recommendations are deferred from v1; a caveat
  alone is not sufficient risk control.
- Optional natal personalization uses tāra-bala, candra-bala, Janma nakṣatra and relevant natal
  sensitivities only when a natal profile is supplied; generic search must work without it.
- Results return top windows, rejected near-misses, timezone-aware boundaries, eligibility tier and
  explicit trade-offs,
  rule profile/version, calculation provenance, and a reason no window was found.
- Search limits: bounded range and candidates, deterministic tie-breaking, cancellation support,
  payload/latency budgets, and no hidden fallback to another place or timezone.

### Jaimini Core v1

- Versioned `JaiminiRuleProfile` freezes the included planets for the 7/8 chara-kāraka scheme,
  Rahu reversal, degree precision, exact/near-tie handling, arūḍha exception variant,
  Scorpio/Aquarius co-lord resolution, Chara Daśā progression/duration and antardaśā variants,
  required gender semantics, year-length convention, rounding, and `[start,end)` boundary rules.
  The default is named, documented, source-linked, and frozen by adjudicated fixtures.
- Chara-kārakas with exact ranking basis and tie handling: AK, AmK, BK, MK, PK, GK, DK;
  optional PiK for the 8-kāraka profile.
- Rāśi dṛṣṭi as sign-to-sign, sign-to-planet, and planet-to-sign facts.
- Arūḍha padas A1–A12, with AL and UL aliases, lord path, distance, exception applied, and
  independent geometry checks.
- Argalā/virodhārgalā for signs and relevant padas, with obstructed/unobstructed results and
  contributing planets.
- Svāṁśa and Kārakāṁśa from the AK in D9; relationships among AK, AmK, DK, AL, UL, D1 and D9.
- Special lagnas needed by the selected profile, emitted separately and never mixed with the
  ordinary ascendant.
- Jaimini timing: one canonical Chara Daśā implementation with mahādaśā/antardaśā boundaries,
  direction, duration basis, and active periods. Other rāśi-daśās remain named extensions until
  independently verified.
- Analysis graph covers self/dharma, vocation, relationships, public image/resources, key
  strengths/tensions, and current timing. Every conclusion points to computed facts and,
  where it states doctrine, an approved source fragment.
- Use independent implementations plus adjudicated fixtures as the authority for kāraka ranking,
  rāśi dṛṣṭi, arūḍha, argalā, and daśā. PyJHora comparisons are diagnostic/test-only and only for
  matching profiles; a different PyJHora lineage/default must not invalidate a correct result.
  PyJHora prediction strings are excluded.
- Reject `birth_time_confidence=unknown`. `approximate` requires a bounded earliest/latest range
  in the additive Jaimini input and runs a five-minute sensitivity sweep, maximum 120 minutes and
  25 samples, covering AK/D9, arūḍhas, special lagnas, and daśā boundaries. Mark each material fact
  stable/unstable and prohibit major synthesis from unstable facts; never analyze only the midpoint.

## Shared architecture

```text
Natural-language question
        |
        v
Conversation router + strict input collection
        |
        +----------------+------------------+
        |                |                  |
        v                v                  v
  PrashnaRequest   MuhurtaSearchRequest  Natal/JaiminiRequest
        |                |                  |
        +----------------+------------------+
                         |
                         v
             Time/place/chart kernel
             (ENGINE_LOCK + explicit config)
                         |
        +----------------+------------------+
        |                |                  |
        v                v                  v
   prashna rules    muhurta interval    jaimini geometry
                    + scoring engine     + rasi dasha
        |                |                  |
        +----------------+------------------+
                         |
                         v
       typed facts + rule traces + warnings + provenance
                         |
                         v
              signing / evidence projection
                         |
                         v
          quick validation or ResearchRun v2
                         |
                         v
             canonical conversational answer
```

### Core types and modules

- Add `event_models.py` for aware event anchors and place validation. Do not overload
  `BirthProfile` with question/event semantics.
- Extract one private locked engine session/callback from `pyjhora_facade.compute_chart()` that
  applies config and calculates all requested primitives inside a single `ENGINE_LOCK`. Both natal
  and new domain facades use it. Never call `compute_chart()` and then recompute Jaimini under a
  second lock, and never return mutable PyJHora structures. Preserve existing natal output
  byte-for-byte.
- Add `prashna.py`, `muhurta.py`, `jaimini.py`, and `rule_profiles.py`. Pure rule evaluation is
  isolated from PyJHora calls so it can be fixture-tested without global engine state.
- Add `intervals.py` for half-open timezone-aware intervals and boundary normalization.
- New public facades return Pydantic models; internal rule results use stable IDs, version,
  severity, status, inputs, outputs, and source references.
- Define `JaiminiInput`, `JaiminiBirthInput`, `JaiminiResult`, closed
  `JaiminiRuleProfileId`, and `AnalysisScope` before geometry code. Public fields use
  `extra="forbid"`, descriptions, units, examples, bounds, and cross-field validators. Results are
  a discriminated union: `completed | needs_input | unavailable | incomplete`, never an opaque
  success/error dictionary. The v1 rule profile is one documented Literal; add a read-only
  capability catalog only when a second profile exists.
- First wedge exposes one additive `jaimini` MCP tool over a pure Python domain facade. Do not add
  Jaimini to `CalculationConfig.modules`; existing `calculate` and `/charts/compute` remain
  byte/schema compatible. REST, Pi, and ResearchRun integration are later value-gated surfaces.
- When later modes pass their gates, add explicit `prashna` and `muhurta` MCP tools rather than a
  profile-centric union inside `calculate`. Keep descriptions short and route naturally in the
  consultant skill.
- Extend Pi only after the Python/MCP contracts stabilize; mirror schemas and add drift guards.

First-wedge request shape (illustrative; Phase 0 freezes the actual profile ID):

```json
{
  "profile": "default",
  "birth": {"confidence": "exact"},
  "rule_profile": "jaimini_core_v1",
  "analysis_scope": "core_with_chara_dasha",
  "reference_date": "2026-07-13",
  "include_trace": false
}
```

The normal result contains `status`, `request_id`, `mode`, `profile_name`, `rule_profile`, a
privacy-safe `anchor_summary`, bounded deterministic `sections`, `warnings`, `limitations`,
`interpretation_status`, provenance hashes, and artifact ID/hash. Full rule traces and internal
IDs require `include_trace=true` or an explicit inspection path.

## Fact and evidence contracts

- Add citable namespaces: `prashna.*`, `muhurta.windows.<id>.*`, `jaimini.*`.
- Rule traces are facts only when they contain deterministic inputs and outcomes. Interpretive
  labels such as “excellent” are synthesis unless a rule profile defines them exactly.
- Define one signed domain artifact that binds mode, normalized-anchor hash, rule-profile hash,
  source-pack hash, facts, provenance, and (for Muhūrta) search range/window IDs. Add a matching
  domain answer-check/finalization path before claiming that visible quick readings are enforced.
  Until then, describe quick MCP output honestly as computed facts, not backend-validated prose.
- Extend `iter_fact_atoms()` through per-domain atomizers to avoid one monolithic function.
- Extend ResearchRun only after a wedge passes its value gate. Each admitted family gets its own
  allowlisted fact projection; do not pre-create all three families.
- Deep finalization must reject missing rule/source support, mixed anchors, stale window IDs,
  unapproved source fragments, and source/geometry contradictions.
- Output ceilings: 512 KiB serialized per normal MCP result; Jaimini returns at most 12 top-level
  periods and 144 nested periods, Praśna at most 100 compact rule results, and Muhūrta defaults to
  7 days/5 windows/5 near-misses with maxima of 31 days/20 windows/20 near-misses and 5,000
  candidate intervals. Overflow returns deterministic ordering plus `truncated`, `total_count`,
  and `returned_count`; it never silently drops facts used by visible synthesis.

## Rule and source governance

- Store rule profiles as reviewed versioned data with JSON Schema/Pydantic validation, not prompt
  prose. Each rule records school, approved `fragment_id` plus checksum, calculation semantics,
  applicability, hard/soft class, and weight where relevant.
- Add a source-admission milestone before interpretive launch: public-domain root text or
  licensed/reviewed translations for Jaimini doctrine, praśna rules, and muhūrta rules. Quarantine
  sources with unclear editions/rights exactly as the current BPHS entry is quarantined.
- Keep astronomical calculations usable before the interpretation corpus is approved, but return
  `interpretation_unavailable` instead of generating doctrine from model memory.
- Golden rule packs are immutable by version. Changes create a new version and migration note.

## Delivery phases

### Phase 0: executable Jaimini feasibility gate — no production code

- Name the canonical Jaimini rule profile and qualified reviewer; record reviewer identity/role,
  approval criteria, and adjudication procedure.
- Admit usable/licensed Jaimini source fragments. Every proposed v1 rule must resolve to an
  approved `fragment_id` and checksum.
- Produce five reviewed end-to-end examples covering the chosen profile, including at least one
  kāraka tie, arūḍha exception, co-lord case, and exact daśā boundary. Resolve disagreements before
  schema work.
- Exit only when rule choices, source rights, expected facts, and reviewer sign-off are concrete.
  Otherwise stop the Jaimini bet without building shared abstractions for hypothetical later modes.

### Phase 1: locked calculation kernel, with zero natal drift

- Extract the single-session engine callback while retaining natal byte compatibility and current
  ayanāṁśa/node semantics.
- Prove existing Moshier/Swiss goldens, configuration isolation, concurrency, privacy, and all
  current MCP/API snapshots before adding any Jaimini output.
- Preserve resolved UTC instant, timezone/tzdb fingerprint, ephemeris mode, engine/implementation
  versions, and rule/source hashes in new-domain provenance.

### Phase 2: Jaimini Core geometry and one MCP vertical

- Implement and cross-check kārakas, rāśi dṛṣṭi, A1–A12/AL/UL, argalā, svāṁśa,
  kārakāṁśa, special lagnas, and configured exceptions.
- Add typed facts, signed artifact, a pure Python `JaiminiFacade`, one additive MCP tool,
  quick-answer checker, routing, docs, and fixtures. Do not add REST/Pi/ResearchRun yet.
- Do not ship interpretation until source admission and contradiction tests pass.

### Phase 3: Jaimini timing, governed analysis, and value gate

- Implement canonical Chara Daśā with exact boundaries and active periods.
- Add the analysis graph and source support through the minimal domain finalizer. Add ResearchRun
  support only if real sessions require stored deep memos rather than stateless conversation.
- Add held-out evals for computed accuracy, school labelling, unsupported-claim rejection, and
  conversational rendering.
- Run 10–20 real/concierge sessions and record actionable usefulness, return/follow-up behavior,
  reviewer material-error rate, latency versus manual reading, and preference versus the current
  alternative. Praśna work requires this gate to pass explicitly.

### Phase 4: Praśna feasibility gate and vertical

- Repeat Phase 0 for one named Praśna profile: sources, reviewer, five adjudicated cases, and one
  bounded question family before production code.
- Implement question-anchor lifecycle, topic-to-house router, time chart, optional numbered
  praśna-lagna methods, readability checks, and rule trace.
- Add pure Python facade, MCP tool, skill routing, follow-up anchor policy, source pack, and evals;
  defer REST/Pi unless demanded by the validated workflow.
- Test clock capture, duplicate/rephrased questions, missing place/timezone, DST, unsafe topics,
  and anchor mixing.

### Phase 5: Muhūrta feasibility gate and one-day benchmark

- Select one low-risk activity, source pack, reviewer, and five adjudicated searches. Prototype
  usable calendar output/conflict input and benchmark a one-day search before fixing architecture
  or a 31-day SLO.
- Implement boundary collection, half-open interval algebra, hard exclusions, deterministic
  eligibility tiers, explicit trade-offs, rejected-near-miss explanations, and range/resource
  limits. Avoid a single precision-looking score unless the reviewed profile truly defines one.
- Add generic rule pack and pure Python/MCP vertical; prove results against fixed calendar fixtures.
- Add cancellation, progress metadata, and latency/payload budgets.

### Phase 6: Muhūrta expansion after value gate

- Add activity packs one at a time after separate source/reviewer adjudication; high-stakes packs
  remain out of v1.
- Add optional tāra-bala/candra-bala and natal checks without making a natal profile mandatory.
- Extend MCP/skill/ResearchRun, source support, held-out evals, docs, and operator diagnostics.

### Phase 7: optional surface expansion and release gate

- If a validated workflow requires Pi or REST, mirror only the admitted stable schemas and add
  drift tests; otherwise keep those surfaces unchanged.
- Run the admitted vertical's Python, MCP stdio, golden, privacy, concurrency, latency, and held-out
  eval gates. Run Pi/Bun/API gates only for surfaces actually added. Default natal chart output
  must remain byte-identical.
- Perform real Codex conversational smokes for one quick and one deep case per domain, including
  Russian input and technical-inspection opt-in.
- Update README, skill references, error-code guide, migration/backup docs, and TODOS.

## Error and rescue behavior

| Condition | Error/result | User rescue |
|---|---|---|
| Missing or naive question/event time | `EVENT_TIME_REQUIRED` | `next_action=confirm_anchor` or provide explicit time/timezone |
| Ambiguous/nonexistent DST time | existing stable DST code | offer exact valid instants with offsets/fold |
| Missing event place | `EVENT_PLACE_REQUIRED` | `next_action=provide_event_place` |
| Unsupported/composite praśna topic | typed `needs_input` result | `next_action=provide_primary_question` |
| Incompatible Praśna follow-up | `ANCHOR_MISMATCH` | `next_action=create_new_anchor` |
| Muhūrta range too large | `SEARCH_RANGE_TOO_LARGE` | `next_action=narrow_search_range`, include supported maximum |
| No valid muhūrta window | successful empty result | explain decisive exclusions and nearest candidates |
| Unapproved rule/source pack | typed `unavailable` result | return calculations only and `next_action=inspect_source_status` |
| School profile mismatch | `RULE_PROFILE_UNSUPPORTED` | return supported values, never silently switch |
| Internal invariant/cross-check failure | `ENGINE_CROSSCHECK_FAILED` | block only affected facts and retain diagnostic privately |
| Search deadline/cancellation | typed `incomplete` result | return no ranking and `next_action=narrow_search_range` |
| Approximate range absent/too broad | `BIRTH_TIME_RANGE_REQUIRED` | `next_action=provide_birth_range`, include 120-minute maximum |

All domain errors use the existing uppercase registry and a privacy-safe envelope with
`error_code`, `request_id`, optional `run_id`, `mode`, `stage`, `retryable`, `problem`, `cause`,
`fix`, `invalid_fields`, `supported_values`, and machine-readable `next_action`. MCP adapters never
return raw exception text. `needs_input`, `unavailable`, successful empty search, and cooperative
`incomplete` are typed domain results, not transport exceptions.

## Test strategy

- **Pure unit tests:** interval algebra, rule evaluation, scoring, tie-breaking, kāraka ties,
  rāśi dṛṣṭi, arūḍha exceptions, argalā obstruction, daśā direction/duration.
- **Independent fixtures:** values reviewed outside the implementation path; never regenerate
  expected outputs from the same functions under test.
- **Property tests:** interval partitions have no gaps/overlap, rankings are stable, adding a hard
  exclusion cannot improve a candidate, all daśā periods are contiguous and bounded.
- **Contract tests:** Pydantic/MCP parity for every admitted vertical; OpenAPI/TypeBox parity only
  when those optional surfaces are added; strict extra-field rejection, stable errors,
  signed-anchor integrity, atom coverage.
- **Integration tests:** MCP stdio per admitted mode. Add API, ResearchRun, canonical Markdown,
  replay, backup/restore, and retention tests only when that vertical adopts those surfaces.
- **Safety/privacy:** no question text, birth data, event location, or rejected rule details in
  logs/errors; prompt/source injection cannot alter rule execution.
- **Performance:** record benchmarked warm p50/p95 for each admitted vertical; one-day Muhūrta
  benchmark precedes range/SLO selection. Enforce explicit deadlines, payload and candidate ceilings.
- **Regression:** existing default and all-module natal goldens unchanged; the complete current
  test suite passes.

## Release criteria

- For an admitted vertical, visible interpretive reading cannot bypass its calculation, signing,
  source support, and answer checker. Until that checker exists, the MCP exposes computed facts only.
- Every supported rule has a version, school, source locator, and executable test.
- The currently admitted mode has independent golden and held-out adversarial eval sets; later
  modes must meet the same gate before implementation/release.
- No high-severity disagreement remains between engine output and independent fixtures.
- Real Codex smokes produce natural answers without exposing internal ledgers.
- Documentation clearly states what Jaimini Core v1 and each admitted Muhūrta activity pack include
  and omit.

## NOT in scope

- Public SaaS deployment or multi-user accounts.
- GUI/calendar rendering and push notifications.
- Automatic booking, contract signing, medical scheduling, or other external side effects.
- Electional guarantees or deterministic future claims.
- Every regional muhūrta custom, every praśna lineage, KP horary judgement, Nāḍi prediction, or
  every Jaimini rāśi-daśā in the first release.
- Importing copyrighted modern translations without explicit rights review.

## CEO Review — premise challenge (checkpoint)

### 0A. The premise that must be chosen

The technical premise is sound: the three modes can share astronomical primitives, rule traces,
signed facts, governed sources, and conversational routing. The product premise is not yet proven:
Praśna, Muhūrta, and Jaimini solve three different jobs with different anchors, risk, frequency,
workflow, and alternatives. A common kernel does not make them one user bet.

Both independent CEO reviews therefore reject an unconditional three-track build. They recommend
preserving the requested destination while making each mode earn the next expansion checkpoint.
The least-expensive first wedge is **Jaimini Core v1**, because it extends the repository's existing
natal profile, chart calculation, source-backed ResearchRun, and answer-validation path. Praśna
introduces a new conversational anchor lifecycle; Muhūrta introduces a search/ranking product and
an incomplete calendar workflow.

### 0B. Existing-code leverage

| Capability | Reuse | Gap before user value |
|---|---|---|
| Natal profile, D1/D9, panchāṅga, signed facts | High for Jaimini | Jaimini geometry, rule profile, approved doctrine, analysis graph |
| Stateless Codex MCP calculation | High for all three | mode-specific requests/results and routing |
| ResearchRun v2 and canonical finalizer | High for deep Jaimini | new plan family, fact projection, source support |
| PyJHora facade and global-state lock | Medium | stable wrappers, independent fixtures, batch/search strategy |
| Current approved corpus | Low | no approved Praśna, Muhūrta, or Jaimini source pack yet |
| FastAPI/Pi compatibility paths | Optional | no evidence that new REST/Pi contracts are needed for the first wedge |

### 0C. Product sequence alternatives

| Alternative | What ships first | Advantage | Main risk | CEO verdict |
|---|---|---|---|---|
| A — one program | Shared kernel, then all three modes | Architectural coherence | Months of scope before learning; source/reviewer bottleneck multiplies | Reject |
| B — staged bets | Jaimini Core v1 → explicit value/source gate → Praśna → gate → Muhūrta | Fastest reuse and earliest adjudicated feedback while preserving all three | Later modes are not calendar commitments | Recommend |
| C — action wedge | One business-launch Muhūrta workflow first | Most directly actionable result | Needs calendar availability/last-mile UX and normative scoring | Consider only if actionability is the primary goal |

### 0D. Required zero-code feasibility gate

Before implementing a vertical mode, secure one named rule profile, a usable/licensed source pack,
a qualified reviewer, and five adjudicated end-to-end examples for that mode. Failure stops that bet
before expanding schemas and interfaces. `Deterministic` means reproducible calculation; it must not
be used as a synonym for doctrinal correctness or user value.

For the first vertical, run 10–20 real or concierge sessions and record: whether the answer changes
or clarifies a decision, whether the user follows up/returns, reviewer material-error rate, answer
latency versus a manual reading, and preference versus the user's current alternative. These are
expansion gates, not claims that Jyotish predictions are empirically validated.

### 0E. Scope corrections recommended regardless of sequence

- Call the bounded first release **Jaimini Core v1**, not “full Jaimini”.
- Define Praśna time operationally as the received timestamp of the first complete question, or an
  explicit user-supplied moment; do not claim the system can measure sincerity or inner clarity.
- Start Muhūrta with `general` plus one low-risk activity pack. Defer marriage, elective medical,
  and contract recommendations until separately reviewed. Prefer eligibility tiers and explicit
  trade-offs over one authoritative-looking scalar score.
- Ship the first wedge through the existing Codex MCP and pure Python domain API. Add REST, Pi,
  ResearchRun, or further tool surfaces only when the selected user flow needs them.
- Benchmark a one-day Muhūrta search before promising a 31-day latency target; PyJHora calls are
  serialized under the current engine lock, so batching and cached boundary tables may be required.
- Treat public distribution/licensing as a separate decision: the current PyJHora-based posture is
  local-only and cannot silently become a hosted product roadmap.

### 0F. Temporal check

- **Now:** validate source/reviewer feasibility and one complete Jaimini decision loop.
- **After the first value gate:** harden Jaimini Core, then run a separate Praśna feasibility/value
  gate rather than assuming it inherits Jaimini demand.
- **After the Praśna gate:** prototype one Muhūrta activity end to end, including usable calendar
  output or conflict input, before generalizing rule packs.
- **Six-month failure mode to avoid:** three half-integrated modes, seven shallow activity packs,
  duplicated MCP/REST/Pi schemas, and technically auditable outputs with no demonstrated repeated use.

### CEO consensus

| Issue | CEO voice 1 | CEO voice 2 | Consensus |
|---|---|---|---|
| Three modes as one roadmap | Three hidden products | Common kernel mistaken for one product | Challenge |
| First wedge | Jaimini adjacency is cheapest | Jaimini slice over existing natal pipeline | Agree: Jaimini Core v1 |
| Sources/reviewer | Pre-code kill gate | Critical external blocker | Agree: gate before implementation |
| Interfaces | MCP + pure Python first | REST/Pi contracts premature | Agree: defer unused surfaces |
| Muhūrta breadth | Remove high-stakes packs; tiers/Pareto | Seven packs create shallow authority | Agree: one low-risk pack first |
| Trust claim | Quick path is not fully backend-enforced | Determinism does not prove validity/value | Agree: narrow claims and test both |

**Explicit premise checkpoint — resolved 2026-07-13:** Alternative B selected. The rest of this
plan is reviewed as staged independent bets: Jaimini Core v1 first, then a source/reviewer/value
gate; Praśna second behind its own gate; Muhūrta third behind its own gate. All three remain in the
target architecture, but passing one mode does not automatically authorize implementation of the
next.

## Engineering Review

### Blocking invariants

1. No production Jaimini code starts until the named profile, reviewer, approved source/checksum
   mapping, and five adjudicated examples make the feasibility gate executable.
2. The locked PyJHora session is the only owner of process-global engine configuration. A request
   cannot calculate natal positions under one lock and Jaimini primitives under another.
3. Existing natal `compute_chart()`, `calculate`, `/charts/compute`, and their schemas/goldens stay
   unchanged. Jaimini is a separate domain facade and additive MCP tool.
4. Rule-profile choices and time conventions are explicit data. Library defaults, Python sort
   order, float rounding, or ambiguous interval endpoints cannot decide doctrine silently.
5. PyJHora is neither runtime doctrinal authority nor an independent oracle. Runtime failures are
   driven by violated invariants; profile-matched differential checks remain diagnostics/tests.
6. Release language distinguishes computed quick facts from backend-validated prose until a
   domain signed artifact and answer checker close that boundary.

### Required implementation map

| Area | Primary files | Required change |
|---|---|---|
| Locked kernel | `src/jyotish_agent/pyjhora_facade.py`, `config.py` | one config+compute session; immutable normalized outputs; natal byte parity |
| Jaimini domain | new `jaimini.py`, `jaimini_models.py`, versioned rule-profile data | pure geometry/timing, complete profile choices, stable error/result models |
| Trust boundary | `interpretations.py`, domain signer/checker, later `answer_contract.py` | domain atomizer; hashes bind anchor/rules/sources/provenance; no unsupported prose |
| MCP vertical | `mcp_models.py`, `mcp_facade.py`, `mcp_server.py` | one additive `jaimini` tool; existing `calculate` unchanged |
| Sources | governed corpus manifests/fragments and review metadata | approved fragments/checksums per rule; quarantine uncertain rights |
| Conversation | consultant routing/reference files | exact/approximate birth-time behavior; RU/EN natural rendering; internals hidden |
| Tests | focused new Jaimini tests plus existing golden/concurrency/MCP suites | ties, co-lords, variants, boundaries, provenance, schema snapshots, Russian smoke |

### Correctness and test matrix

- Property tests: rāśi-dṛṣṭi symmetry/allowed sign classes, arūḍha distance and exceptions,
  argalā obstruction invariants, unique kāraka assignment, and deterministic serialization.
- Table tests: seven/eight kārakas, Rahu reversal, exact and near ties, both co-lord signs,
  arūḍha variants, year-length/rounding choices, and every supported Chara Daśā branch.
- Timeline tests: nested periods are contiguous, non-overlapping, cover the parent, use half-open
  bounds, and select the correct period exactly at start/end instants.
- Anchor tests: timezone-equivalent inputs resolve identically; DST fold/nonexistence is explicit;
  tzdb/UTC/ephemeris/profile/source hashes survive signing and replay.
- Uncertainty tests: `unknown` is rejected; `approximate` cannot produce a major claim from an
  unstable AK/D9/arūḍha/special-lagna/daśā fact without the declared sensitivity policy.
- Compatibility tests: existing Moshier/Swiss golden bytes, cross-config concurrency, API/MCP
  snapshots, installed package data, and current ResearchRun behavior remain unchanged.
- Conversation tests: Russian and English quick/deep prompts, hidden internal ledgers, unsupported
  doctrine rejection, and exact canonical rendering where validation is claimed.

### Performance policy

Replace the unmeasured `<1 s` Jaimini requirement with a benchmarked warm p95 after Phase 2. Record
kernel-only, geometry, signing, and rendering separately. For Muhūrta, benchmark one day first;
then choose batching/cached boundary tables and a justified maximum range before publishing a
31-day SLO. Cancellation is cooperative between locked engine batches, not assumed inside an
uninterruptible PyJHora call.

### Dual-voice engineering consensus

| Finding | Independent reviewer | Codex repository pass | Resolution |
|---|---|---|---|
| Source/reviewer gate was aspirational | Blocker | Confirmed current corpus has no admitted mode pack | Make Phase 0 executable and no-code |
| Jaimini as ordinary module is wrong boundary | Must fix | Existing `calculate` is narrow/profile-centric | Separate facade + additive MCP tool |
| Global PyJHora state can split a result | Must fix | `ENGINE_LOCK` owns config+compute today | One locked session/callback |
| Rule profile is under-specified | Must fix | Library embeds multiple method defaults | Freeze every doctrinal/time choice |
| Quick trust claim is too broad | Must fix | Deep ResearchRun is enforceable; quick prose is not | Signed domain artifact/checker or narrow claim |
| Birth-time uncertainty omitted | Must fix | Existing ResearchRun already has sensitivity concepts | Reject unknown; explicit approximate policy |
| Performance targets unmeasured | Must fix | Serial engine work dominates | Benchmark p95 and one-day Muhūrta first |

The Codex CLI pass was stopped after repository evidence converged with the independent reviewer;
its exhaustive final prose was not required to accept the shared findings above.

## Developer Experience Review

### Agent happy paths

```text
Jaimini
  natural question
    -> choose default or explicit inline person
    -> exact birth time: calculate
       approximate: request bounded range -> sensitivity sweep
       unknown: stable needs_input/unavailable response
    -> bounded facts + interpretation status
    -> checked conversational answer

Praśna
  one concrete question + place
    -> explicit time OR capture first complete-message receipt once
    -> if captured "now": return confirmable anchor
    -> calculate -> opaque anchor_token
    -> follow-up: reuse token OR create new anchor

Muhūrta
  activity + place + [start,end) + duration
    -> validate range/limits/timezone
    -> search -> ranked eligible windows OR successful empty result
    -> calendar-ready timezone-aware output + explicit trade-offs
```

The agent never asks a user to know `rule_profile`, tzdb hashes, fold semantics, source IDs, or
internal mode names unless ambiguity cannot be resolved safely. Schema descriptions and typed
`next_action` values drive recovery; prose is presentation, not a parser contract.

### Time and timezone contract

- Event inputs use RFC 3339 timestamps with offset plus an IANA `zone_id`; validate the supplied
  offset against the pinned tzdb result and require explicit `fold` only for ambiguous local time.
- Return normalized UTC instant, resolved offset, fold, zone ID, and tzdb fingerprint in
  provenance. A conflicting offset/zone is a correctable input result, never silently normalized.
- Muhūrta start/end share one event timezone and use `[start,end)` consistently.
- Praśna capture/confirmation is idempotent: retries reuse the sealed instant and token rather than
  sampling a later clock.

### Observability and privacy

Every domain operation returns a privacy-safe `request_id` and records domain/stage, rule/source/
profile hashes, engine-lock wait, duration, result bytes, completion state, and cache state. Muhūrta
also records boundary/candidate/excluded/processed counts and cancellation reason. Never log raw
questions, birth data, coordinates, windows, rule inputs derived from them, tokens, or rendered
answers. MCP stdout remains JSON-RPC only; diagnostics go to stderr or privacy-safe local records.

### Vertical documentation contract

Documentation ships with each vertical, not Phase 7: one minimal RU and EN happy path, inline
profile example, exact/approximate/unknown matrix, included/excluded techniques, profile/source
status, limits, error/rescue examples, inspection opt-in, and compatibility statement that existing
`calculate` is unchanged. MCP tools remain read-only/idempotent until a later persisted ResearchRun
flow is explicitly added.

### Reproducible development gates

For Jaimini create `test_jaimini_models.py`, `test_jaimini_geometry.py`,
`test_jaimini_timing.py`, `test_jaimini_facade.py`, MCP server/stdio tests, and JSON Schema/tool-list
snapshots. Add drift tests between Pydantic JSON Schema, FastMCP discovery, and documented examples.
Each vertical gate must prove:

1. model/schema snapshot and invalid cross-field cases;
2. stdio happy path and every typed rescue path;
3. output ceiling/truncation and deterministic ordering;
4. privacy/log/stdout assertions;
5. deadline/cancellation behavior where applicable;
6. all existing natal goldens and concurrency/config-isolation tests;
7. a saved benchmark report and one documented local command bundle (`uv run pytest -q` plus only
   explicitly pinned format/lint tools).

Do not declare `ruff` or another formatter a required gate unless it is added and pinned in the dev
dependencies.

### Dual-voice DX consensus

| Finding | Independent reviewer | Codex DX pass | Resolution |
|---|---|---|---|
| Opaque MCP dictionaries are not discoverable | Must fix | Confirmed current broad `dict` shapes | Typed per-domain models and result union |
| Praśna follow-up lacks state protocol | Must fix | Semantic model inference is unsafe | Signed opaque continuation token |
| Approximate birth input conflicts with current model | Must fix | One v1 policy required | Additive range input + bounded sweep |
| Lowercase errors drift from registry | Must fix | Registry is uppercase/research-oriented | Shared domain envelope + `next_action` |
| Output/trace limits lack numbers | Must fix | Agent context can be flooded | Numeric ceilings and truncation metadata |
| Docs/tests are postponed too late | Must fix | Staged bets need staged gates | Ship examples, stdio smoke, and rescue tests per vertical |

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| 1 | Preamble | Keep artifact sync off | Mechanical | Privacy-preserving default | Repository artifacts were not previously configured for sync | Enabling sync without consent |
| 2 | Review routing | Skip design review | Mechanical | Review only material surfaces | The plan adds no GUI or visual interaction | Running a UI critique on API/domain work |
| 3 | CEO | Preserve all three requested capabilities but challenge unconditional sequencing | User challenge | Shared architecture does not prove shared demand | Both CEO voices independently identified three distinct product bets | Silently deleting requested modes; silently accepting one large program |
| 4 | CEO checkpoint | Select staged independent bets, Jaimini Core first | User choice | Learn before multiplying scope | User selected Alternative B at the mandatory premise gate | One committed three-mode program; Muhūrta-first wedge |
| 5 | Engineering | Keep Jaimini outside `CalculationConfig.modules` | Reversible architecture | Preserve stable semantics | Existing calculate contract represents optional chart modules, not a separate doctrinal mode | Expanding the union and coupling every client |
| 6 | Engineering | Defer REST, Pi, and ResearchRun for the first wedge | Reversible scope | Add surfaces only for proven flows | Codex MCP is the current primary UX and the value gate may invalidate the wedge | Building schema parity before usage evidence |
| 7 | Engineering | Reject unknown birth time; gate approximate interpretation | Safety/correctness | Do not present unstable geometry as authoritative | Jaimini Core depends materially on D9, AK, arūḍhas, and exact period boundaries | Silent midpoint analysis |
| 8 | DX | Use an additive Jaimini birth input with bounded range | Reversible compatibility | Do not break existing profile validation | Current shared model cannot express the required approximate sweep safely | Mutating the existing Research birth contract |
| 9 | DX | Seal Praśna continuity in an opaque signed token | Safety/correctness | Stateful meaning needs backend enforcement | Stateless MCP conversation cannot reliably remember or validate the anchor | Asking the model to infer reuse from prose |
| 10 | DX | Use typed domain results and `next_action` | Reversible contract | Agents should recover without parsing English | Existing registry and new staged workflows need a shared actionable boundary | Raw exceptions; unstructured error prose |
