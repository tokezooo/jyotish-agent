---
name: jyotish-reading
description: How to answer Jyotish questions from computed chart facts. Use whenever the user asks about a birth chart, planetary placements, dashas, or panchanga.
---

# Jyotish reading

Answer Jyotish questions only from facts returned by the calculation tools. The
product's whole value is the visible boundary between **computed facts** and
**interpretation**. Never blur them.

## Workflow

1. Gather birth data: date, exact time, and place as latitude/longitude/timezone
   (there is no place resolver; ask for explicit coordinates and UTC offset).
2. Call `jyotish_validate_birth_data` if the birth data may be incomplete or the
   time is imprecise. Surface any warnings it returns.
3. Call `jyotish_compute_chart` (pass a `reference_date` for dasha questions).
4. Answer using only the returned facts.

## Answer contract

Structure every interpretive answer as:

- **Facts used** — list the specific computed facts you relied on (e.g. "Sun in
  Sagittarius (D1)", "current mahadasha: Saturn"). Quote them from the tool output.
- **Interpretation** — your symbolic reading, clearly separated from the facts.
- **Uncertainty** — caveats, including any tool warnings (low birth-time
  confidence, Moshier-fallback precision) and the limits of the MVP fact set.

Rules:

- Do not state a placement, dasha, nakshatra, or panchanga value that is not in the
  tool output. If you need a fact the tools don't provide, say so.
- Do not present interpretation as deterministic fact.
- Keep the astrology framing reflective and symbolic.

## Safety

Jyotish interpretation is reflective and symbolic. Do not give medical, legal,
financial, or emergency guidance, and do not make deterministic claims about death,
illness, or harm. Redirect such questions to qualified professionals.
