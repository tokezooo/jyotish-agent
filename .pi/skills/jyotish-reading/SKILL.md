---
name: jyotish-reading
description: How to answer Jyotish questions from computed chart facts. Use whenever the user asks about a birth chart, planetary placements, dashas, or panchanga.
---

# Jyotish reading

Answer Jyotish questions only from facts returned by the calculation tools. The
product's whole value is the visible boundary between **computed facts** and
**interpretation**. Never blur them, and never cite a fact the tools didn't return.

## Workflow

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
   `facts` block and `facts_token` from the response — you need both for step 6.
5. Draft your answer in the answer contract shape below.
6. Call `jyotish_check_answer` with your `facts_used` and the `facts` + `facts_token`
   from step 4. If it returns violations, fix `facts_used` and the prose, then
   re-check. Do not give the user an answer that hasn't passed this check.

This check verifies that the facts you *chose to cite* are real and unmodified (the
`facts_token` binds them to the computed chart). It cannot read your prose, so it is
on you to ensure every factual claim in `summary` is backed by an entry in
`facts_used` — that is the rule, and the check only enforces the part it can see.

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
