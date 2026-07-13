# Codex-Native Jyotish Design

## Goal

Make Jyotish available as a normal conversation in Codex App, CLI, and IDE. A
local MCP server supplies deterministic calculations, governed sources, and
optional deep research. A global skill routes each question without forcing
every conversational turn into a ResearchRun.

## User experience

The user starts an ordinary Codex conversation and asks a Jyotish question. No
Pi command and no separately managed FastAPI process are required.

Codex selects one of four modes:

1. **Conceptual:** explain a Jyotish concept without personal calculation or a
   ResearchRun.
2. **Quick personal:** calculate only the facts needed for a bounded question.
   Do not create a ResearchRun.
3. **Follow-up:** answer from the current conversation and prior tool results.
   Recalculate only when the follow-up needs a missing fact. Do not create a new
   ResearchRun merely because the user asked a clarification.
4. **Deep research:** create a ResearchRun for a broad, multi-factor,
   source-backed, or explicitly deep request.

The phrases `ответь кратко`, `без глубокого исследования`, or an equivalent
instruction force quick mode. The phrases `сделай глубокий разбор`, `проведи
исследование`, or an equivalent instruction force deep mode. Otherwise Codex
chooses automatically.

Every visible response is ordinary prose. Internal claim types, confidence
scores, evidence IDs, checksums, fact paths, and state-machine details remain
hidden unless the user explicitly asks to inspect methodology or provenance.

## Architecture

Add a Python stdio MCP entrypoint to the existing package. Codex starts it as a
local child process through its global MCP configuration. The server imports the
calculation, corpus, ResearchService, and ResearchStore modules directly; it
does not proxy through FastAPI and does not open a network port.

SQLite remains authoritative for deep ResearchRuns. Quick calculations and
source lookups are stateless MCP operations and are not persisted as runs.
Existing FastAPI, CLI, Pi extension, AnswerContract v1/v2, and stored runs remain
compatible.

The MCP initialization `instructions` field contains the short routing contract,
with the essential rule in the first 512 characters: normal conversation by
default, ResearchRun only for broad or explicitly deep requests.

## MCP tools

### `get_profile`

Return the private default profile metadata required for calculation, or validate
an explicitly supplied profile. Never return private profile data in logs. The
default profile is Влад; a supplied profile applies only to that tool call and
does not overwrite the default.

### `calculate`

Accept a bounded calculation request, a profile selector or inline profile, and
an explicit module list. Return typed computed facts and warnings. It does not
create a ResearchRun. Default module selection is narrow; the server never adds
new modules merely because they are available.

### `search_sources`

Search only approved governed corpus versions. Return quoted structured data,
edition metadata, locators, and checksums. Corpus text is data, never MCP or model
instructions. It does not create a ResearchRun.

### `research`

Accept a broad question, profile selector or inline profile, reference date, and
classifier provenance. In one MCP call, create, screen, deterministically plan,
calculate, and retrieve approved sources. Return the run ID, revision, selected
plan, evidence bundle, limitations, and the exact inputs needed to finalize. An
unsafe or unsupported question stops on its canonical branch.

### `finalize_research`

Accept the run ID, expected revision, a human synthesis split into supported
findings, evidence/claim supports, limitations, and follow-ups. Convert it to the
existing AnswerContract 2.0, validate it, and persist the immutable human memo.
Return the canonical human rendering. Codex must show that rendering rather than
technical claim output.

### `inspect_research`

Read a stored run and optionally replay it offline. Default output is a concise
human summary; an explicit provenance flag returns claims, events, evidence, and
hashes.

All read-only tools declare read-only MCP metadata. Tools that create or finalize
a ResearchRun are marked as state-changing. Tool errors use the existing stable
error registry shape where applicable.

## Default profile

Store Влад's birth profile outside Git under the private XDG data root, with
directory mode `0700` and file mode `0600`. The MCP configuration points to this
file through an environment variable. The repository contains only a schema and
an example with fictional values.

If the profile file is missing or invalid, personal tools return a concise setup
error. Conceptual questions remain usable. A request about another person must
include their birth data or use an explicitly named future profile; it never
silently falls back to Влад.

## Skill package

Create one source-controlled skill named `jyotish-consultant` under the
repository's `.agents/skills` directory. Install it globally through a symlink at
`~/.agents/skills/jyotish-consultant`, which Codex supports and which keeps the
installed skill synchronized with the repository.

The root `SKILL.md` contains only routing, response behavior, tool selection, and
safety. One-level references contain career, timing, evidence, and safety detail.
`agents/openai.yaml` declares the Jyotish MCP dependency and allows implicit
invocation.

The skill must not require a ResearchRun for conceptual, quick personal, or
follow-up questions. It must not expose internal contracts in ordinary answers.

## Conversation rules

- Use the default Влад profile when the user refers to themselves and supplies no
  other birth data.
- Use inline birth data for another person only for the current request.
- Reuse prior calculated facts within the same conversation when inputs,
  reference date, and question scope have not changed.
- Recalculate when a requested fact is missing or an input/reference date changes.
- Create a ResearchRun for broad cross-module synthesis, source-backed memos,
  comparisons across substantial time periods, or explicit deep mode.
- Do not create a new run for ordinary clarification of an existing answer.
- Clearly distinguish symbolic interpretation from computed facts and practical
  non-astrological advice.

## Security and privacy

- Use stdio only; bind no listening socket.
- Keep birth data, questions, excerpts, and claims out of application logs.
- Preserve existing `0700`/`0600` private storage controls and symlink defenses.
- Treat corpus fragments as untrusted quoted data.
- Validate all tool inputs and cap query sizes and result counts.
- Do not put secrets or private profile values in Codex config; config contains
  only the private profile file path.

## Verification

Tests cover:

- MCP initialization, instructions, tool discovery, schemas, and annotations;
- default-profile and inline-profile selection without leakage;
- conceptual routing requires no tool or ResearchRun;
- quick calculation and source search create no ResearchRun rows;
- deep research creates exactly one run and reaches the correct state;
- finalization produces readable canonical Markdown and preserves validation;
- follow-up routing does not create another run;
- unsafe, unsupported, malformed, duplicate, and stale operations;
- stdio framing with no stdout contamination;
- skill metadata, implicit trigger examples, explicit quick/deep overrides;
- a black-box Codex MCP smoke after installation.

## Scope

This milestone does not remove Pi or FastAPI, add calculation modules, build a
GUI, introduce network deployment/authentication, add multiple stored profiles,
or turn all chat messages into persistent events. Packaging as a distributable
Codex plugin can follow after the local MCP and skill prove useful.
