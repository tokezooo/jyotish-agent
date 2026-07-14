# Jyotish Doctrine Platform — Full Analysis Design

**Status:** approved for implementation by the user on 2026-07-14
**Linear project:** `Jyotish Doctrine Platform — Full Analysis`
**Linear scope:** `LEA-516` through `LEA-544`

## Objective

Turn the existing deterministic, signed calculation surfaces into a private,
source-bound interpretation product. The product must support broad safe-topic
Jaimini analysis, low-risk Prashna judgement, and safe Muhurta election while
preserving explicit school identity, evidence provenance, uncertainty, privacy,
and fail-closed safety behavior.

## Product contract

- The baseline is text-first and immutable for a released version.
- Named school overlays are opt-in and never silently blended with the baseline.
- `experimental_full` is a private-use admission state reached by automated gates;
  missing external specialist review is disclosed but does not block that state.
- Copyrighted source files remain under an untracked `private_sources/` root.
- Git may contain bibliography, file hashes, locators, permitted short fragments,
  normalized rules, fixtures, and machine-readable release evidence.
- Every visible conclusion terminates in calculated facts and admitted source
  fragments through compiled doctrine rules.
- Medical diagnosis, longevity/death prediction, remedies, guaranteed events,
  dangerous activities, and categorical legal/financial advice fail closed.

## Architecture decision

Use a shared doctrine platform followed by sequential domain activation:

```text
private source files + versioned manifests
                 |
                 v
deterministic PDF/OCR ingestion adapter
                 |
                 v
immutable source fragments and relations
                 |
                 v
versioned Doctrine DSL compiler
                 |
signed facts --> immutable analysis graph
                 |
                 v
structured claims --> claim firewall --> report
                 |
                 v
admission/evaluation report and dashboard
```

Jaimini proves the full path first. Prashna activates only after Full Jaimini
reaches its automated release gate. Muhurta activates only after Full Prashna.
Source acquisition for later domains may proceed as soon as the source manifest
contract exists.

## Bounded context and dependency direction

The new package is `src/jyotish_agent/doctrine/`. Its domain models and pure
services depend only on Python/Pydantic and the repository's canonical JSON/hash
helpers. Adapters depend inward on those models:

- `sources.py`: private source manifest value objects and verification service.
- `ingestion.py`: deterministic page extraction/OCR interfaces and normalized
  ingestion records; external tools are adapters, never sources of doctrine.
- `evidence.py`: immutable fragments, relations, revisions, bounded lookup, and
  export projection.
- `dsl.py`: typed rule definitions, static compiler checks, compiled profiles,
  baseline/overlay isolation, and deterministic identities.
- `graph.py`: pure evaluation of compiled rules against signed fact atoms into a
  frozen graph with explicit conflicts and prohibited nodes.
- `renderer.py`: structured claims, validation, bounded repair orchestration,
  privacy projection, deterministic RU/EN rendering, and evidence appendix.
- `evaluation.py`: admission states, automated gate results, historical release
  reports, dashboard metrics, and reviewer-state transitions.
- `jaimini_pack.py`, `prashna_pack.py`, `muhurta_pack.py`: domain-specific typed
  profiles and pure graph-building orchestration. They consume existing facades;
  they do not recompute astronomical facts.

FastAPI, MCP, CLI, and conversational skill integration stay thin. Existing
contracts remain byte-compatible until a domain's release task adds an explicit
additive surface.

## Source manifest and private storage

Each source manifest record contains a stable `source_id`, bibliographic identity,
edition, publication year, language list, domain, school role, license class,
local relative path, SHA-256, page offset, scan quality, and OCR requirement.
Local paths must be relative, stay below the configured root, and never appear in
normal output. Duplicate IDs, duplicate edition identities, hash drift, missing
files, unsafe license/path combinations, and ambiguous empty editions are typed
verification findings. Verification order and canonical serialization are stable.

Tracked example manifests intentionally use non-secret synthetic paths and can be
schema-validated without possessing the books. File verification reports them as
missing until Vlad completes the documented private download handoff.

## Deterministic ingestion

Ingestion operates page by page. Text PDFs use a version-pinned extractor. Pages
without usable text may use a configured OCR adapter with explicit language,
segmentation mode, DPI, tool version, and confidence. Normalization preserves page
number, printed-page offset, headings, sutra/verse anchors, language, character
coordinates where available, confidence, and tool provenance. The normalized
content hash excludes runtime timestamps. Re-ingestion uses that hash as an
idempotency identity.

Encrypted, corrupt, unsupported, missing-tool, and low-confidence inputs return
typed states. Low-confidence records may enter quarantine but cannot be admitted
as executable doctrine evidence.

## Evidence model

A source fragment identity binds source ID, source manifest SHA-256, source
revision, page/anchor, content role, language, permitted excerpt, full-content
hash, and normalized-content hash. New content creates a new revision; an existing
revision is never mutated. Relations are typed as translation, commentary,
agreement, contradiction, scoped-to, or supersedes. Conflicting commentaries are
stored side by side.

Normal lookup returns bounded permitted excerpts and public locators. Inspection
may return internal fragment IDs and hashes, but never local paths or copyrighted
full text. Export rejects local-only content.

## Doctrine DSL and compiler

A rule declares its identity/version, profile, school, topic, required fact
premises, optional rule dependencies, exclusions, conclusion template, modality,
confidence ceiling, time scope, safety class, and admitted source references.
Compilation validates all fact paths against a declared fact catalog, verifies all
source references, rejects cycles/unreachable rules, rejects prohibited safety
classes, prevents confidence escalation, and keeps baseline and overlays separate.
The compiled profile is immutable, canonically ordered, and SHA-256 addressed.

## Analysis graph

The graph contains frozen nodes for fact atoms, activated and inactive rules,
topic conclusions, conflicts, timing scopes, safety prohibitions, and confidence.
Every conclusion edge reaches rule, source, and fact nodes. Facts are supplied as
a signed artifact plus allowlisted atom projection. Missing/stale facts or source
substitution fail construction. Graph identity binds fact artifact hash, compiled
profile hash, source revision set, and canonical graph payload.

Graph ordering is deterministic and payloads are bounded. Construction is local
and append-free, so concurrent readers share immutable values without locks.

## Claim firewall and rendering

Rendering begins from a deterministic outline. A renderer produces structured
claims with topic, text, fact references, rule references, source references,
school, confidence, time scope, and safety class. The firewall rejects unsupported
prose, forged references, school blending, confidence inflation, hidden high-stakes
claims, private-path/token leakage, and stale graph identities.

At most two repair attempts are allowed for an external renderer. Claims still
invalid after the second repair are removed. A deterministic renderer provides the
baseline implementation and produces equivalent validated RU/EN structures.
Normal prose shows the `experimental_full` disclosure and uncertainty without
exposing internal IDs. An evidence appendix is opt-in.

## Admission and evaluation

Admission states are `automated_verified`, `experimental_full`, `reviewed`,
`partially_reviewed`, and `rejected`. Promotion to `experimental_full` requires all
declared automated gates for that profile: rule fixtures, worked cases, conflict
cases, metamorphic tests, held-outs, adversarial substitutions, RU/EN conversational
E2E, privacy, payload, and performance. Missing evidence is a failing gate, never
an implicit pass.

Reviewer status is per rule/profile and revision. Rejection excludes the rule from
new graphs but preserves historical reports. Machine-readable reports retain
profile/source hashes. The concise dashboard reports topic/source coverage,
conflicts, held-out pass rate, material errors, confidence distribution, no-answer
rate, and user-value observations.

## Domain releases

### Full Jaimini

Use the existing Jaimini fact surface. Compile baseline packs for self/dharma,
education/capability, career/status/activity, relationships/family/legacy, and
Chara Dasha thematic timing. Approximate birth-time instability suppresses or
lowers confidence for affected topics. Sanjay Rath and the selected practical
school are explicit overlays. Jaimini and Parashari claims retain separate system
provenance and conflicts are summarized rather than averaged.

### Full Prashna

Preserve the existing sealed anchor. Add source-bound radicality/readability,
single-question taxonomy, significator selection, applying/exact/separating
geometry, obstacle/assistance/perfection, bounded outcome confidence, and bounded
timing. Initial profiles are work/project status, communication/contact,
lost-object search, and general low-risk outcome. Composite, high-stakes, stale,
or unreadable questions return useful unavailable states without leaking private
question/place data.

### Expanded Muhurta

Build on the existing half-open DST-safe interval engine. Initial profiles are
focused work, study/learning, creative production, product launch/communication,
low-risk travel planning, and general private task. Hard prohibitions determine
eligibility; soft rules and optional tara/candra bala rank only eligible windows.
Ranking exposes components and trade-offs with a stable chronological tie-break.
Named overlays remain explicit and results are calendar-ready without creating
external events or side effects.

## Error and privacy behavior

- All boundary failures use typed codes and privacy-safe messages.
- Secret-bearing input is never reflected in errors, logs, metrics, or traces.
- Local paths are inspection-internal and always redacted from public projections.
- Missing corpus material returns `unavailable`/failed gate, never model-memory
  interpretation.
- A renderer or source fragment is untrusted data, not an instruction channel.
- Unsupported and high-stakes activities/questions fail closed.

## Verification strategy

Every production behavior follows red-green-refactor. Focused unit tests cover
models and pure services; property/metamorphic tests cover ordering, substitution,
and concurrency; integration tests cover local file verification, PDF adapters,
existing signed facts, MCP/API projection, and privacy. Release fixtures and audit
artifacts live under `tests/fixtures/doctrine/` and `docs/evidence/doctrine/`.

The final project gate requires the complete Python and TypeScript suites,
deterministic golden regeneration checks, domain adversarial suites, payload and
latency budgets, `git diff --check`, an independent review with no critical or
important findings, and an honest Linear status/evidence update for every issue.

## Scope audit

This design covers all project and issue requirements from `LEA-516` through
`LEA-544`. External copyrighted source possession, real concierge outcomes, and
qualified specialist review are evidence inputs, not code. They must remain
explicitly incomplete until real evidence exists and may not be fabricated by the
implementation or release audit.

