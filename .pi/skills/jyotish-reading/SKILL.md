---
name: jyotish-reading
description: How to answer Jyotish questions from computed chart facts. Use whenever the user asks about a birth chart, planetary placements, dashas, or panchanga.
---

# Jyotish reading

Answer Jyotish questions only from facts returned by the calculation tools. The
product's whole value is the visible boundary between **computed facts** and
**interpretation**. Never blur them, and never cite a fact the tools didn't return.

## ResearchRun v2 workflow

When the `jyotish_*_research_run` tools are available, this workflow is mandatory:

1. Call `jyotish_create_research_run` with fresh `rr_` and `op_` UUID4 values,
   `expected_revision=0`, the question/profile/config, and explicit version labels.
2. Call `jyotish_screen_research_run` with the returned run and revision. Stop on
   the canonical unsafe refusal branch.
3. Call `jyotish_calculate_research_run` only after a safe screen. Treat its
   evidence IDs and structured facts as authoritative.
4. Build AnswerContract `2.0`: computed claims support `evi_` IDs and contain no
   prose; synthesis/source claims contain explicit text and valid supports.
5. Call `jyotish_submit_answer`. If rejected, use the single repair opportunity.
   Never write an independent final answer: the backend canonical Markdown returned
   through the message gate is the only permitted terminal response.

The legacy workflow below applies only when the v2 research tools are unavailable
and there is no active v2 ResearchRun.

## Legacy workflow

1. **Safety screen first.** Call `jyotish_screen_question` with the user's question.
   If it returns `safe=false`, refuse and use the returned redirect; do not compute a
   chart. The screen is a coarse keyword filter — also apply your own judgement (see
   Safety).
2. Gather birth data: date, exact time, and place as latitude/longitude/timezone
   (there is no place resolver; ask for explicit coordinates and UTC offset).
3. Call `jyotish_validate_birth_data` if the birth data may be incomplete or the
   time is imprecise. Surface any warnings it returns.
4. Call `jyotish_compute_chart` (pass a `reference_date` for dasha questions). Treat
   the returned JSON block as authoritative; the summary line is rounded. Keep the
   `facts_token` from the response — you need it for step 6.
5. Draft your answer in the answer contract shape below.
6. Call `jyotish_check_answer` with your `summary`, `facts_used`, and the
   `facts_token` from step 4. Do NOT pass the `facts` object — the server looks it up
   by token. If it returns violations, fix `facts_used` and the prose, then re-check.
   Do not give the user an answer that hasn't passed this check.

This check verifies that the facts you *chose to cite* are real and unmodified (the
`facts_token` binds them to the computed chart). It also scans your `summary` for
"<Planet> in <Sign>" claims and rejects any that contradict the computed charts — so
a wrong placement in prose is caught even if you forgot to cite it. It still cannot
verify every kind of prose claim (aspects, dashas, nuanced statements), so the rule
stands: back every factual claim in `summary` with an entry in `facts_used`.

## Answer contract

```json
{
  "summary": "Short, direct answer.",
  "facts_used": [
    { "path": "d1.Sun.sign", "value": "Sagittarius" },
    { "path": "vimshottari.mahadasha.lord", "value": "Saturn" }
  ],
  "uncertainty": ["Birth time confidence is 'approximate'."],
  "followups": ["Want the D9 (navamsa) reading for marriage signals?"]
}
```

`facts_used` paths are dotted references into the computed `facts`:

- `ascendant.sign`, `ascendant.degrees`
- `d<N>.<Planet>.sign`, `d<N>.<Planet>.degrees`, `d<N>.<Planet>.house` for each
  computed divisional chart (`d1`, `d9`, and any others requested via `config.charts`
  such as `d10` for career), where `<Planet>` is Sun, Moon, Mars, Mercury, Jupiter,
  Venus, Saturn, Rahu, Ketu. `house` is whole-sign, counted from that chart's own
  lagna. Request the charts you need (e.g. D10 for career, D7 for children) in
  `jyotish_compute_chart`'s `config.charts`.
- `houses.<N>.sign`, `houses.<N>.lord` for the D1 bhava table (N = 1..12), e.g.
  `houses.10.lord` is the 10th-house (career) lord.
- `aspects.<From>.<To>` (value `true`) for D1 graha drishti, e.g. `aspects.Saturn.Moon`
  means Saturn aspects the Moon. Every planet aspects the 7th; Mars also 4th/8th,
  Jupiter 5th/9th, Saturn 3rd/10th. Rahu/Ketu aspect the 7th only unless
  `config.node_aspects="jupiter_like"` (then 5th/7th/9th).
- `lagnas.<chart>.sign` for each computed chart's own lagna (e.g. `lagnas.d9.sign` is
  the navamsa lagna; chart keys are lowercase like `d1`/`d9`). `ascendant` is the d1
  alias.
- `bhava.<chart>.<N>.sign`, `bhava.<chart>.<N>.lord` for each chart's 12-house bhava
  table (N = 1..12), e.g. `bhava.d9.10.lord`. `houses.<N>` is the d1 alias.
- `shadbala.<Planet>.rupas`, `shadbala.<Planet>.strength_ratio`,
  `shadbala.<Planet>.components.<sthana|kaala|dig|cheshta|naisargika|drik>` — six-fold
  strength for the 7 classical grahas (no Rahu/Ketu). Request via
  `config.modules: ["shadbala"]` when the question concerns planetary strength.
  Numbers only: do NOT assert "strong/weak" thresholds as facts (cutoffs vary by
  school); a ratio > 1 means the planet exceeds its classical minimum, say it that way.
- `ashtakavarga.sav.<Sign>`, `ashtakavarga.bav.<Planet|Lagna>.<Sign>` — raw
  (pre-sodhana) Samudaya/Bhinna Ashtakavarga bindu counts. Request via
  `config.modules: ["ashtakavarga"]`. SAV points (per sign, out of a fixed 337
  total) measure how favorable a sign is for transits — higher is more
  supportive. Numbers only: do NOT assert good/bad cutoffs (e.g. "below 28 is
  weak") as facts; cite the points and phrase any threshold as interpretive
  convention, not computation.
- `transits.<Planet>.sign`, `transits.<Planet>.house_from_moon`,
  `transits.<Planet>.house_from_lagna`, and `transits.natal_moon_sign` — classical
  gochara: D1 positions at the reference moment (NOT birth). Request via
  `config.modules: ["transits"]` (pass `config.reference_date` for a specific day);
  add `"ashtakavarga"` too to also get `transits.<Planet>.sav_points`, the SAV
  bindus of the transited sign — the classical SAV-weighted transit strength.
  Houses are whole-sign counts from the NATAL Moon (`house_from_moon`, the classical
  gochara reference) and from the NATAL lagna (`house_from_lagna`) — always name
  which reference you are counting from. The transit anchor is local noon of
  `reference_date` (surfaced as `facts.transits.anchor`, context only — not
  citable); the Moon moves ~13°/day, so its transit sign is a noon snapshot — say
  so whenever the question hinges on the transit Moon.
- `yogas.<Name>.present` (`true`/`false`) for the supported geometric yogas
  (Gajakesari, Chandra-Mangala, Budha-Aditya). Each yoga in `facts.yogas` also carries
  the exact `definition` used and the `basis` geometry — cite the definition, and only
  claim a yoga when `present` is `true`. This is a deliberately NARROW geometric set
  (not full yoga coverage) with no strength/combustion/cancellation analysis; do not
  imply completeness or claim a yoga's effect as deterministic.
- `yogas_engine.<chart>.<key>.present` (always `true`) and `yogas_engine.status` —
  the PyJHora engine's own yoga scan (~284 checks) per computed chart (chart keys
  lowercase like `d1`/`d9`), requested via `config.modules: ["yogas_engine"]`. Keys
  are the engine's stable snake_case identifiers (e.g. `vesi_yoga`). MANDATORY
  hedge: these are UNVERIFIED engine verdicts — phrase every one as "the PyJHora
  engine detects X; this definition is not independently verified", never as bare
  fact. Detected-only: a yoga's ABSENCE is not a fact — phrase it as "not among the
  engine-detected yogas", never "the chart has no X". If `yogas_engine.status` is
  `"partial"`, some engine checks failed silently (the list may be incomplete — say
  so); if `"unavailable"`, the scan could not run at all. On any conflict with the
  verified geometric tier (`yogas.<Name>.present`), the verified tier WINS: surface
  any strings in `facts.yogas_engine.mismatches` under `uncertainty` and side with
  `facts.yogas`.
- `varshaphal.lagna.sign`, `varshaphal.lagna.degrees`, `varshaphal.<Planet>.sign`,
  `varshaphal.<Planet>.degrees`, `varshaphal.munthi.sign`,
  and `varshaphal.pravesh` — the Tajaka varshaphal, i.e. the Vedic ANNUAL
  (solar-return) chart active at the reference date. Year selection is anchored at
  LOCAL NOON of the reference date: on the pravesh day itself, a return later that
  day means the PREVIOUS year's chart is still reported — check
  `varshaphal.pravesh` for the exact moment when that matters. Request via
  `config.modules: ["varshaphal"]` (with `config.reference_date`) for "what does
  this year hold" questions. This is NOT Western progressions — call it the
  annual/varshaphal chart. The chart is valid pravesh-to-pravesh (from the solar
  return in `varshaphal.pravesh` until the next return, roughly one year later
  near the birthday) — when answering year questions, state those boundary dates,
  not calendar years. `varshaphal.age_year` is context (the year of life the
  chart covers), not citable. `munthi` is the classical progressed point (natal
  lagna + one sign per completed year). No year lord (varsheshvara) is emitted —
  its rule is school-dependent and unverified here; if asked, say it is not
  computed rather than deriving one.
- `panchanga.tithi`, `panchanga.nakshatra` (+ `panchanga.nakshatra.pada`),
  `panchanga.yoga`, `panchanga.karana`, `panchanga.weekday`
- `vimshottari.mahadasha.lord` / `.start` / `.end` (and `bhukti`, `antara`)

Copy `value` verbatim from the authoritative JSON.

Rules:

- Every claim in `summary` that rests on a placement, dasha, nakshatra, or panchanga
  value must appear in `facts_used`. If you need a fact the tools don't provide, say
  so in `uncertainty` — do not invent it.
- Keep interpretation in `summary`, clearly symbolic, never presented as
  deterministic fact.
- Put tool warnings (low birth-time confidence, Moshier-fallback precision) and the
  limits of the MVP fact set in `uncertainty`.

## Safety

Jyotish interpretation is reflective and symbolic. Do not give medical, legal,
financial, or emergency guidance, and do not make deterministic claims about death,
illness, or harm. For such questions, decline the specific request, say why, and
redirect to a qualified professional (or a crisis line for self-harm). You may still
describe relevant chart symbolism in general, reflective terms if appropriate.
