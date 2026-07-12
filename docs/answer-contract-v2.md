# AnswerContract v2

`schema_version` is `2.0`. An answer has a run status, title, one or more typed
claims, optional limitations, and optional follow-ups. Claims are `computed`,
`source`, or `synthesis`; each has a stable claim ID, materiality, confidence, and
non-empty supports.

Computed claims copy calculated evidence exactly. Source claims quote only approved
fragments and preserve source version, class, locator, checksum, rights note, and
provenance. Synthesis claims identify their contributing evidence/claims and surface
conflicts and caveats. The validator checks type compatibility, support closure,
cycles, quote/value equality, pinned planning, projection hashes, unsupported
claims, and the one-repair-attempt rule.

Only backend canonical Markdown from a validated submission is user-visible. Its
SHA-256 is checked at the CLI boundary and again during replay. A render mismatch,
missing evidence, changed source quote, or unsupported material claim blocks the
answer; never repair it in free-form prose outside the contract.
