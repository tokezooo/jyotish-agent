# PRD: Jyotish Agent

## Product Intent

Build a Jyotish assistant that can answer chart questions using deterministic
calculations from PyJHora and an agent harness based on Pi.

The user should be able to provide birth data, ask a natural-language Jyotish
question, and receive an answer that separates:

1. Computed chart facts.
2. Interpretive reasoning.
3. Uncertainty and caveats.

This distinction is the product. The agent must not pretend that an LLM generated
the chart or that an interpretation is a deterministic fact.

## Target User

Primary user for MVP: a Jyotish-interested human who wants a fast chart reading
assistant and can tolerate technical caveats if the answer is grounded.

Secondary user: Vlad as builder, using Pi locally to iterate on agent behavior,
tool boundaries, and prompt discipline.

## Problem

Most astrology agents blur computation and interpretation. They answer confidently
without showing which chart facts they used. For Jyotish this is especially bad
because small changes in birth time, place, ayanamsa, node mode, or dasha method
can materially change the answer.

## MVP Outcome

A local agent session can answer:

> Given this birth data, what are the strongest career-related signals in the
> chart?

with:

- normalized birth data
- D1 and D9 placements
- current Vimshottari period for a requested date
- panchanga basics
- a concise interpretation that cites the computed facts used
- a warning when the birth data is incomplete or low precision

## Non-Goals For MVP

- No medical, legal, or financial advice.
- No compatibility/matching workflow.
- No GUI chart renderer.
- No full JHora feature parity.
- No paid SaaS infrastructure.
- No automatic claims about remedies, gemstones, or deterministic future events.

## Key Product Decisions

### PyJHora Is A Calculation Engine, Not The Product Surface

PyJHora is broad and mutable. The MVP must wrap a small stable subset:

- chart normalization
- D1 Rasi chart
- D9 Navamsa chart
- panchanga basics
- Vimshottari dasha/bhukthi
- selected yogas/doshas only after the base flow is stable

### Agent Answers Must Be Fact-Cited

Every interpretive answer must include a machine-readable `facts_used` section.
The LLM may explain, synthesize, and prioritize, but must not invent placements,
dashas, strengths, or panchanga values.

### Ayanamsa And Node Mode Are First-Class

Default config should be explicit:

- ayanamsa: Lahiri for initial test parity unless changed deliberately
- Rahu/Ketu: true nodes vs mean nodes must be captured in the request and output
- timezone and daylight-saving behavior must be visible in the normalized input

## User Flows

### Flow 1: Create Birth Profile

Input:

- name or label
- date of birth
- exact time of birth
- place name or latitude/longitude/timezone
- optional confidence level for birth time

Output:

- normalized profile
- resolved coordinates/timezone
- validation warnings

### Flow 2: Compute Chart Facts

Input:

- birth profile
- calculation config

Output:

- D1 placements
- D9 placements
- ascendant
- panchanga basics
- current Vimshottari period for a reference date
- raw calculation metadata

### Flow 3: Ask Interpretive Question

Input:

- birth profile ID or inline birth data
- question
- reference date

Output:

- short answer
- supporting facts
- uncertainty notes
- suggested follow-up questions

## Trust And Safety

The agent must include an astrology disclaimer in system behavior, but not as noisy
marketing copy. Recommended phrasing:

> Jyotish interpretation is reflective and symbolic. Do not use this as medical,
> legal, financial, or emergency guidance.

Refuse or redirect:

- medical diagnosis
- financial certainty
- self-harm or crisis claims
- deterministic claims about death, illness, or harm

## Success Criteria

- A known birth profile produces repeatable chart facts across test runs.
- The same facts are returned through the Python API and Pi tool.
- The answer includes `facts_used` and does not cite facts absent from tool output.
- Invalid or ambiguous birth data produces actionable validation errors.
- The first local Pi session can complete the create-profile -> compute-chart ->
  answer-question loop in under five minutes.

