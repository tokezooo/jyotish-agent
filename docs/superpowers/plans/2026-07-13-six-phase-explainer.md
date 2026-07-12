# Six-Phase Research Agent Explainer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained interactive HTML page that explains the six development phases as one understandable journey from question to replayable research memo.

**Architecture:** One file contains semantic HTML, responsive CSS, the six authored phase records, and a small state-driven JavaScript renderer. The UI never connects to production data; it visualizes the real workflow with safe illustrative content and exposes both guided autoplay and direct navigation.

**Tech Stack:** HTML5, inline CSS, vanilla JavaScript, browser Clipboard API with a fallback, no external dependencies.

## Global Constraints

- Create exactly one runtime artifact: `docs/jyotish-research-agent-explainer.html`.
- Do not load fonts, scripts, styles, images, analytics, APIs, or user data from the network.
- Explain concepts in Russian without deep API, database, or schema details.
- Preserve the distinction between automated guarantees and pending human/external validation.
- Support keyboard focus, mobile widths, and `prefers-reduced-motion`.
- Do not claim scientific predictive validity for Jyotish.

---

### Task 1: Build the guided six-phase journey

**Files:**
- Create: `docs/jyotish-research-agent-explainer.html`

**Interfaces:**
- Consumes: the six approved phase descriptions from `docs/superpowers/specs/2026-07-13-six-phase-explainer-design.md`.
- Produces: a standalone page with `state.activePhase`, `state.mode`, `state.autoplay`, `render()`, `setPhase(index)`, and `toggleAutoplay()`.

- [ ] **Step 1: Create the semantic content model**

Define a JavaScript `phases` array with six objects. Each object contains `number`, `title`, `short`, `what`, `why`, `value`, `checks`, `artifactLabel`, `artifactTitle`, and `artifactRows`. Use the exact narrative sequence: protected run, enforced workflow, validated answer, deterministic plan and governed library, visible uncertainty and replay, hardening and honest limits.

- [ ] **Step 2: Build the page structure**

Create a hero with the before/after statement and “Запустить путешествие” button; an accessible six-step orbit navigation; a phase explanation panel; a live research-card panel; simple/deeper explanation tabs; previous/next and pause controls; final disclosure panels; and a copyable CLI command.

- [ ] **Step 3: Implement the visual system**

Use inline CSS variables for the night-laboratory palette:

```css
:root {
  --night: #07111f;
  --panel: #0d1b2e;
  --indigo: #7187ff;
  --moon: #edf3ff;
  --gold: #e9bf67;
  --verified: #55d6be;
}
```

Use a restrained serif display stack for headings, a system sans stack for body text, and a monospace stack only for run IDs/statuses. The memorable element is a responsive orbital route whose active light moves between the six real sequential phases.

- [ ] **Step 4: Implement state-driven interactions**

All controls call one `render()` function. Autoplay advances once every 5.5 seconds and stops at phase six. Direct selection, previous/next navigation, simple/deeper mode, Escape-to-pause, and copy feedback update the same state object. Page visibility changes pause autoplay.

- [ ] **Step 5: Verify the standalone file manually**

Run:

```bash
open docs/jyotish-research-agent-explainer.html
```

Expected: the file opens without a local server or console/network dependency; every phase changes both the explanation and the live research card.

- [ ] **Step 6: Commit the page**

```bash
git add docs/jyotish-research-agent-explainer.html
git commit -m "docs: add interactive six-phase explainer"
```

### Task 2: Validate content, accessibility, and responsive behavior

**Files:**
- Modify: `docs/jyotish-research-agent-explainer.html`
- Modify: `README.md`

**Interfaces:**
- Consumes: the completed standalone page from Task 1.
- Produces: a discoverable, keyboard-usable explainer with no external requests and no misleading claims.

- [ ] **Step 1: Add deterministic static checks**

Use a Python standard-library parser to confirm the HTML has one `main`, six phase buttons, one live `aria-live` region, no external `src` or stylesheet links, and the phrases “Что система не обещает” and “manual”. Fail if any requirement is missing.

- [ ] **Step 2: Inspect desktop and mobile renderings**

Open the page in a browser, verify the two-column desktop composition and the single-column mobile composition, and confirm no horizontal overflow around 390px. Exercise keyboard tab order, phase selection, autoplay pause, disclosure panels, and copy feedback.

- [ ] **Step 3: Add README discovery link**

Add one operator-facing bullet under the ResearchRun references:

```markdown
- [interactive six-phase explainer](docs/jyotish-research-agent-explainer.html)
```

- [ ] **Step 4: Run repository-safe verification**

Run:

```bash
uv run ruff check src tests
git diff --check
```

Expected: both commands exit successfully; no production Python/TypeScript behavior changes.

- [ ] **Step 5: Commit documentation discovery and QA fixes**

```bash
git add README.md docs/jyotish-research-agent-explainer.html
git commit -m "docs: verify interactive explainer"
```
