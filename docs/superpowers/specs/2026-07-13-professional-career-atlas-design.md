# Professional Career Atlas — Design Specification

## Purpose

Create a private, self-contained interactive HTML page that helps Vlad compare concrete career models against both:

- the already validated Jyotish professional-realization research;
- practical constraints such as autonomy, capital dependence, marketing burden, income speed, asset accumulation, and burnout risk.

The page is a personal decision instrument, not investor collateral. It must make a long interpretive memo easier to understand without presenting astrology as a probability model.

## Deliverable

- One autonomous HTML file with inline CSS and JavaScript.
- No external dependencies, backend, analytics, or network requests.
- Readable static content when JavaScript is unavailable.
- Responsive behavior for desktop and mobile.
- Preferences saved only in browser `localStorage`.

## Career Models

The explorer compares six models:

1. Independent product founder with one flagship product.
2. Capital-backed venture-studio founder with a portfolio.
3. Technical cofounder or venture partner paired with external capital and distribution.
4. Fractional CTO / product architect as a financial bridge.
5. Productized AI/technology consultancy that accumulates reusable IP.
6. Salaried CTO / Principal Engineer as a lower-emphasis fallback.

Each model includes:

- Jyotish alignment;
- practical advantages;
- key contradictions;
- suitable horizon;
- entry condition;
- exit condition;
- scores for the decision criteria.

## Decision Criteria

The adjustable criteria are:

- autonomy;
- accumulation of an owned asset;
- speed to income;
- capital accessibility / tolerance for external funding dependence;
- manageable marketing burden;
- protection from fragmentation and burnout.

The numeric compatibility score is explicitly labeled as a transparent decision aid, not an astrological probability or prediction.

## Interaction Model

### Presets

The compact priority compass provides three presets:

- **Build an owned asset** — default.
- **Protect the runway**.
- **Maximize scale**.

Users may also change individual criterion weights. Every change updates the highlighted route and model ranking immediately.

### Model exploration

- Career models appear as stops on a vertical route.
- Clicking a model expands its full reasoning.
- Up to three models can be added to a compact comparison view.
- The current top route is visually highlighted without hiding alternatives.

### Personal route output

The final section generates a natural-language summary containing:

- the primary career path;
- a financial bridge;
- a scenario to avoid;
- the active priority assumptions.

The summary updates live and has a copy button with brief feedback. A reset control restores the default preset and clears saved state.

## Content Architecture

1. **Hero / thesis:** “Строить то, чего ещё нет.”
2. **Professional center:** concise synthesis of the validated D1/D9/D10 findings.
3. **Priority compass:** presets and adjustable weights.
4. **Route map:** six expandable career models.
5. **Comparison drawer:** two or three selected models.
6. **2026–2029 pass:** the current transition from repeated experiments toward an owned, compounding asset.
7. **Personal route:** generated decision summary and copy action.
8. **Epistemic note:** Jyotish is symbolic; market and financial decisions require real-world validation.

## Visual Direction

### Concept

“Living Atlas”: a calm personal map rather than a dashboard or investor deck.

### Palette

- `Atlas Snow` — `#EDF3F7`
- `Deep Ink` — `#172B42`
- `Contour Blue` — `#6F8BA7`
- `Route Amber` — `#D28746`
- `Pine` — `#315E5B`
- `Mist` — `#C9D8E2`

The page may use a dark ink utility rail while keeping the main atlas light. This preserves the selected light direction and gives controls sufficient contrast.

### Typography

- Display: a restrained Georgia-style serif stack for the reflective thesis.
- Body: a humanist system sans-serif stack for sustained Russian reading.
- Utility/data: system monospace for coordinates, scores, and map labels.

No remote font files are used.

### Layout

Desktop:

```text
┌──────────────┬──────────────────────────────────────────┐
│ priority     │ hero / professional center               │
│ compass      ├──────────────────────────────────────────┤
│ presets      │ vertical route with six model stops      │
│ weights      │ expandable model detail                  │
│              ├──────────────────────────────────────────┤
│ sticky       │ comparison → transition → personal route │
└──────────────┴──────────────────────────────────────────┘
```

Mobile:

```text
hero → compact priority controls → vertical route → comparison → personal route
```

### Signature element

One animated amber route travels through subtle topographic contour lines and reconnects to the currently preferred model. This is the only expressive visual flourish; all other decoration remains restrained.

## Accessibility and Resilience

- Semantic headings, buttons, fieldsets, and labels.
- Visible keyboard focus.
- Sufficient text and control contrast.
- `prefers-reduced-motion` disables route drawing and reveal animation.
- All model details remain present in the document for static reading.
- Invalid or missing saved state falls back to defaults.
- Clipboard failure leaves the generated summary selectable and displays a concise instruction.

## Verification

- Validate HTML structure and JavaScript syntax.
- Exercise all presets and sliders.
- Verify ranking changes and tie handling.
- Verify maximum three-model comparison selection.
- Verify copy and reset behavior.
- Check persistence and invalid-state fallback.
- Inspect desktop and mobile layouts in a browser.
- Test keyboard navigation and reduced-motion behavior.
- Confirm the page makes no network requests.

## Scope Boundaries

- No modification of the Jyotish calculation API.
- No fresh astrological claims beyond the validated research memo.
- No investor-facing deck or fundraising copy.
- No backend persistence, authentication, user accounts, or tracking.
- No recommendation that a chart should override product, market, or financial evidence.
