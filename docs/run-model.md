# ResearchRun v2 state and run model

SQLite is authoritative. Pi transcripts, terminal output, and exported Markdown are
mirrors and may be stale. A run pins its engine, planner, corpus, contract, timezone
resolution, request hash, and reference date. Every mutation uses a unique `op_`
UUID and expected revision; exact retries are idempotent, while changed input or a
stale revision conflicts.
Create-operation identity is computed from the original normalized client payload,
before the server resolves an omitted `reference_date`. The first resolution is
pinned in the result, so an identical retry after midnight replays it; adding or
changing an explicit date conflicts. The server owns the only supported answer
contract pin (`2.0`); clients may omit it, but cannot create a run pinned to another
contract.

The normal state sequence is create → screen → classify/plan → calculate → retrieve
→ submit → validated. Unsafe, unknown, composite, and unsupported branches stop or
clarify without speculative calculation. Events are append-only, contiguous, and
hash-linked. Claims and evidence are immutable. Offline replay rebuilds projections,
claim closure, and canonical memo from the ledger and fails closed on missing pinned
versions, corrupt payloads, broken links, or render hashes.

Crash rule: retry with the same operation ID and identical request after an unknown
commit outcome. Never issue a changed request under that ID. SQLite uses WAL and a
bounded busy timeout; a persistent lock is an operator error, not permission to
bypass the ledger.

The Pi extension fails closed unless the host completes an explicit behavioral
handshake proving tool-call blocking, tool-result modification, and final-message
replacement. Merely exposing hook names is insufficient.
