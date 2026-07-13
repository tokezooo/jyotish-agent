# Conversational Answer Rendering

## Goal

Make interactive Pi sessions feel like a normal conversation while preserving the
backend as the trust boundary. The user sees a clear Jyotish answer, not the
internal claim ledger. Technical evidence remains available through run inspection.

## User-visible behavior

For a validated safe run, the final Pi message contains:

1. the answer title;
2. the validated synthesis as ordinary prose;
3. an optional short `Важно` section for material limitations;
4. an optional natural follow-up prompt.

The chat output must not expose claim-type labels, materiality, confidence scores,
evidence identifiers, source checksums, or computed fact paths. These remain stored
in the immutable AnswerContract, claims, supports, evidence, and event ledger.

Unsafe, invalid, unresolved, or unvalidated runs retain the existing fail-closed
refusal or blocker behavior.

## Design

The backend continues to accept AnswerContract 2.0. No schema migration is required.
The synthesis claim text is the authoritative human answer. A new deterministic
human renderer selects synthesis claims in contract order and renders only their
text, caveats that are suitable for the user, top-level limitations, and follow-ups.

Computed and source claims remain validation dependencies but are omitted from the
display rendering. The complete structured contract remains queryable through
`run inspect --json` and stored in SQLite.

`jyotish_submit_answer` returns the human rendering and its SHA-256. Pi records that
validated rendering. At `message_end`, Pi may leave the model's prose unchanged only
when it is byte-identical to the validated human rendering. Otherwise it replaces
the prose with that rendering. This preserves the existing guarantee that the final
visible answer is exactly the backend-approved artifact while allowing the common
path to look like uninterrupted conversation.

Canonical rendering remains deterministic. Existing immutable answers and hashes
are not rewritten. The new presentation applies to newly submitted answers. A
read-only display renderer may be used to show an old contract conversationally,
but it must not mutate the old canonical artifact or ledger.

## Conversation lifecycle

Each new research question creates a new run. A previously validated run does not
prevent the next user message from starting another run on the same Pi branch. Pi
may retain the prior conversation as context, but only the active run's validated
rendering can pass the final-message gate.

Non-research conversational turns that do not make Jyotish claims may remain normal
Pi conversation only when no v2 research operation is active or unresolved. A turn
that answers a Jyotish question must go through the complete research workflow.

## Error handling

- Missing synthesis: reject the AnswerContract; do not emit an empty answer.
- Multiple synthesis claims: render them in contract order as separate paragraphs.
- Invalid or exhausted repair: retain the current fail-closed blocker.
- Free prose differs from the validated rendering: replace it silently with the
  validated rendering.
- Technical evidence remains accessible even though it is hidden from chat.

## Verification

Tests must prove that:

- a validated answer renders as readable prose;
- technical claim labels, confidence, IDs, and fact paths are absent;
- limitations and follow-ups remain visible in human language;
- rendering is byte-deterministic and hash-stable;
- identical model prose is preserved;
- divergent or unsupported prose is replaced;
- unsafe and invalid runs remain fail-closed;
- the full claims and evidence graph remains persisted and inspectable;
- a new question can start after a validated run on the same branch.

## Scope

This change affects presentation and Pi conversation lifecycle only. It does not add
new Jyotish calculation modules, relax validation, change corpus governance, migrate
AnswerContract 2.0, or modify historical answer artifacts.
