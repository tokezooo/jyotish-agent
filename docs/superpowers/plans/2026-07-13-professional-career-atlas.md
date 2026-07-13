# Professional Career Atlas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one self-contained interactive HTML atlas that compares six career models against Vlad's validated Jyotish professional contour and practical decision criteria.

**Architecture:** A single semantic HTML document contains the complete readable content, inline design tokens, and one inline JavaScript state machine. Static text is present before JavaScript runs; JavaScript progressively adds presets, normalized weighted scoring, route highlighting, comparison selection, persistence, and the generated personal-route summary.

**Tech Stack:** HTML5, CSS custom properties, vanilla JavaScript, `localStorage`, Clipboard API, `/usr/bin/tidy`, Node syntax validation.

## Global Constraints

- Deliverable is exactly one autonomous HTML file with no external dependencies or network requests.
- Do not modify the Jyotish calculation API or add fresh astrological claims.
- Use the validated professional-research synthesis as the content boundary.
- Default visual direction is the light “Living Atlas” with a dark utility rail and one animated amber route.
- Keep the salaried CTO / Principal Engineer model visible but visually secondary.
- Numeric scores are a transparent decision aid, never an astrological probability.
- Preserve keyboard accessibility, responsive layout, reduced-motion behavior, and readable no-JavaScript content.

---

### Task 1: Build the self-contained career atlas

**Files:**
- Create: `professional-career-atlas.html`

**Interfaces:**
- Consumes: the approved content and interaction design in `docs/superpowers/specs/2026-07-13-professional-career-atlas-design.md`.
- Produces: `window.CareerAtlas` with pure helpers `calculateScores(state)`, `rankModels(state)`, and `buildSummary(state)` plus UI methods `render()`, `applyPreset(name)`, `toggleCompare(id)`, and `reset()`.

- [ ] **Step 1: Create semantic static content and model data**

Use a `<main>` with hero, professional-center, route, transition, comparison, and personal-route sections. Define these model identifiers in inline JavaScript:

```js
const MODEL_DATA = {
  independentFounder: {
    title: 'Независимый product founder',
    scores: { alignment: 5, autonomy: 5, asset: 5, income: 1.5, capital: 2, marketing: 2, focus: 4 }
  },
  ventureStudio: {
    title: 'Основатель венчурной мини-студии',
    scores: { alignment: 4, autonomy: 4, asset: 4, income: 1, capital: 1, marketing: 1, focus: 1 }
  },
  venturePartner: {
    title: 'Технический сооснователь / venture partner',
    scores: { alignment: 4, autonomy: 3.5, asset: 3.5, income: 2.5, capital: 4, marketing: 4, focus: 3 }
  },
  fractionalCto: {
    title: 'Fractional CTO / product architect',
    scores: { alignment: 3.5, autonomy: 3.5, asset: 1, income: 5, capital: 5, marketing: 4, focus: 3 }
  },
  productizedConsulting: {
    title: 'Продуктизированная AI/tech-консультация',
    scores: { alignment: 3.5, autonomy: 4, asset: 2.5, income: 4, capital: 5, marketing: 3, focus: 2.5 }
  },
  salariedLeader: {
    title: 'Наёмный CTO / Principal Engineer',
    scores: { alignment: 2.5, autonomy: 1.5, asset: 0.5, income: 5, capital: 5, marketing: 5, focus: 4 }
  }
};
```

Each model's static article must include its Jyotish fit, practical benefits, contradiction, horizon, entry condition, and exit condition.

- [ ] **Step 2: Implement weighted scoring and presets**

Use normalized weights so sliders do not need to sum to 100:

```js
const PRESETS = {
  asset: { alignment: 28, autonomy: 18, asset: 24, income: 8, capital: 8, marketing: 8, focus: 6 },
  runway: { alignment: 15, autonomy: 8, asset: 8, income: 25, capital: 20, marketing: 14, focus: 10 },
  scale: { alignment: 18, autonomy: 12, asset: 20, income: 5, capital: 15, marketing: 20, focus: 10 }
};

function calculateScores(state) {
  const weightTotal = Object.values(state.weights).reduce((sum, value) => sum + value, 0) || 1;
  return Object.fromEntries(Object.entries(MODEL_DATA).map(([id, model]) => {
    const weighted = Object.entries(state.weights).reduce(
      (sum, [criterion, weight]) => sum + model.scores[criterion] * weight,
      0
    );
    return [id, Math.round((weighted / weightTotal / 5) * 100)];
  }));
}
```

Every preset and range input calls `render()` immediately. The UI must say “индекс соответствия”, not “вероятность успеха”.

- [ ] **Step 3: Implement comparison, persistence, summary, and resilience**

Comparison is capped at three selected model IDs. Invalid saved JSON is ignored. The personal route uses the top-ranked model, the highest-ranked bridge from `fractionalCto`, `productizedConsulting`, and `salariedLeader`, and the lowest-ranked overall model as the caution scenario.

```js
function toggleCompare(id) {
  const selected = new Set(state.compare);
  if (selected.has(id)) selected.delete(id);
  else if (selected.size < 3) selected.add(id);
  else return showNotice('Можно сравнить не больше трёх моделей.');
  state.compare = [...selected];
  persist();
  render();
}

function rankModels(currentState = state) {
  const scores = calculateScores(currentState);
  return Object.keys(MODEL_DATA).sort(
    (left, right) => scores[right] - scores[left] || MODEL_DATA[left].order - MODEL_DATA[right].order
  );
}

function buildSummary(currentState = state) {
  const ranking = rankModels(currentState);
  const bridgeIds = ['fractionalCto', 'productizedConsulting', 'salariedLeader'];
  const bridge = ranking.find(id => bridgeIds.includes(id));
  const caution = ranking.at(-1);
  return `Основной путь: ${MODEL_DATA[ranking[0]].title}. ` +
    `Финансовый мост: ${MODEL_DATA[bridge].title}. ` +
    `Сценарий с наибольшим противоречием текущим приоритетам: ${MODEL_DATA[caution].title}.`;
}

function applyPreset(name) {
  if (!PRESETS[name]) return;
  state.preset = name;
  state.weights = { ...PRESETS[name] };
  persist();
  render();
}

function reset() {
  state = structuredClone(DEFAULT_STATE);
  localStorage.removeItem(STORAGE_KEY);
  render();
}

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved && saved.weights && Array.isArray(saved.compare)) return sanitizeState(saved);
  } catch (_) {}
  return structuredClone(DEFAULT_STATE);
}
```

Copy uses `navigator.clipboard.writeText()` and falls back to selecting the generated summary with an instruction when clipboard access fails.

- [ ] **Step 4: Implement the approved Living Atlas visual system**

Define the approved tokens exactly:

```css
:root {
  --atlas-snow: #edf3f7;
  --deep-ink: #172b42;
  --contour-blue: #6f8ba7;
  --route-amber: #d28746;
  --pine: #315e5b;
  --mist: #c9d8e2;
}
```

Use a sticky dark utility rail, light atlas canvas, topographic SVG background, vertical route with model stops, expanded card states, and a single amber route animation. At `max-width: 820px`, collapse to one column and move controls above the route. Under `prefers-reduced-motion: reduce`, remove animation and smooth scrolling.

- [ ] **Step 5: Run static verification**

Run:

```bash
tidy -errors -quiet professional-career-atlas.html
```

Expected: no structural HTML errors. Warnings about HTML5 custom data attributes are acceptable only if no error lines are emitted.

Run:

```bash
node -e "const fs=require('fs');const h=fs.readFileSync('professional-career-atlas.html','utf8');const s=h.match(/<script>([\\s\\S]*?)<\\/script>/);if(!s)throw Error('inline script missing');new Function(s[1]);console.log('javascript syntax ok')"
```

Expected: `javascript syntax ok`.

Run:

```bash
rg -n "https?://|src=|href=" professional-career-atlas.html
```

Expected: no external `http` resources; local anchors are allowed.

- [ ] **Step 6: Commit the working artifact**

```bash
git add professional-career-atlas.html
git commit -m "feat: add interactive professional career atlas"
```

### Task 2: Browser QA and final polish

**Files:**
- Modify: `professional-career-atlas.html`

**Interfaces:**
- Consumes: the complete single-file atlas from Task 1.
- Produces: verified desktop/mobile behavior and accessible interaction states.

- [ ] **Step 1: Open the page in a real browser**

Run:

```bash
open professional-career-atlas.html
```

Expected: the page opens locally without a server and displays the “Строить то, чего ещё нет” hero.

- [ ] **Step 2: Exercise the state transitions**

Verify manually:

1. Each preset changes the top route and scores immediately.
2. Each slider updates its displayed value and score ordering.
3. Model details expand with mouse and keyboard.
4. Selecting a fourth comparison model displays the three-model limit notice.
5. Copy shows success feedback; reset restores the asset preset.
6. Reload preserves valid choices.
7. Corrupting the storage value does not break page initialization.

- [ ] **Step 3: Inspect responsive and motion behavior**

At desktop width, the compass remains sticky beside the atlas. At widths below 820px, controls move above the route, comparison cards stack, no horizontal scrolling appears, and all buttons remain at least 44px tall. Emulate reduced motion and confirm the amber path is static.

- [ ] **Step 4: Re-run validation after polish**

Run the three Task 1 verification commands again plus:

```bash
git diff --check
```

Expected: all checks pass and no whitespace errors are reported.

- [ ] **Step 5: Commit QA polish if the browser review changed the artifact**

```bash
git add professional-career-atlas.html
git commit -m "fix: polish career atlas interactions and responsive layout"
```
