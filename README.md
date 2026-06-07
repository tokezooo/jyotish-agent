# Jyotish Agent

Agentic Jyotish assistant built around deterministic Vedic astrology calculations from
PyJHora and a Pi-based agent harness.

The first milestone is deliberately narrow:

- normalize birth data into a stable chart request
- compute D1, D9, panchanga, and Vimshottari facts through a Python service
- expose those facts to Pi as explicit tools
- let the LLM explain only from cited calculation facts, not from hidden intuition

## Current State

This repository is in planning stage. See:

- [PRD.md](PRD.md)
- [PLAN.md](PLAN.md)

## Source References

- PyJHora: https://github.com/naturalstupid/PyJHora
- Pi: https://pi.dev/docs/latest

