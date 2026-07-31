# LEA-530 — Independent Jaimini Geometry Held-out Gate

**Goal:** Close the automated `held_out_cases` gap for Full Jaimini with a physically separate, checksum-bound corpus of hand-authored expected geometry and explicit school identity, without claiming source admission, specialist review, or doctrinal outcome validation.

## Global Constraints

- Expected values are authored directly from sign-counting and fixed timeline arithmetic; no production function or generated production output may create or refresh them.
- The held-out corpus is never used for tuning or implementation decisions and execution requires an explicit final-review opt-in.
- Every case is labeled `project-canonical-jaimini-v1`, bound to `jaimini_core_v1` and its current SHA-256, and names the exact frozen rule family it exercises.
- A missing, unknown, disguised, or mismatched school/profile/hash fails closed before any case executes.
- Keep the existing `adjudication_fixtures_v1.json` review state pending: automated geometry evidence is not human doctrinal adjudication.
- No private source path, copyrighted text, birth profile, interpretation, or astrology outcome enters the corpus.
- Passing this task changes only the automated `held_out_cases` release gate. `hand_worked_cases`, `deep_conversational_e2e`, source admission, Subodhini acquisition, and specialist review remain honest blockers.
- Existing Python, REST, MCP, and TypeScript contracts remain backward compatible.

### Task 1: Independent geometry corpus, evaluator, and release evidence

**Files:** `eval/jaimini/geometry-held-out-v1.json`, `eval/jaimini/geometry-held-out-v1-checksums.json`, `src/jyotish_agent/jaimini_evaluation.py`, `tests/test_jaimini_geometry_heldout.py`, `src/jyotish_agent/data/doctrine/jaimini-release.json`, `docs/evidence/doctrine/jaimini-release.json`, `docs/evidence/doctrine/project-release.json`, `TODOS.md`.

- [ ] Add a strict versioned corpus and SHA-256 manifest. It must declare `authorship=hand_authored_not_generated`, `used_for_tuning=false`, `public_safe=true`, and contain only synthetic scalar/sign inputs.
- [ ] Cover these independent oracle families through production boundaries: 7- and 8-karaka ranking plus exact-tie error; all 12 modal rasi-drishti rows; ordinary and same/seventh Arudha cases; all three co-lord comparators; all four Argala statuses; BL/HL/GL wrap; Chara Dasha direction/duration plus a half-open boundary.
- [ ] Use these hand-authored oracle values: 7-karaka input `Sun=12, Moon=4, Mars=27, Mercury=16, Jupiter=8, Venus=22, Saturn=1` ranks `AK=Mars, AmK=Venus, BK=Mercury, MK=Sun, PK=Jupiter, GK=Moon, DK=Saturn`; adding `Rahu=28` ranks `AK=Mars, AmK=Venus, BK=Mercury, MK=Sun, PiK=Jupiter, PK=Moon, GK=Rahu, DK=Saturn`; equal `Sun=18, Moon=18` is `EXACT_KARAKA_TIE`.
- [ ] Use the full rasi-drishti matrix `0:[4,7,10], 1:[3,6,9], 2:[5,8,11], 3:[1,7,10], 4:[0,6,9], 5:[2,8,11], 6:[1,4,10], 7:[0,3,9], 8:[2,5,11], 9:[1,4,7], 10:[0,3,6], 11:[2,5,8]`.
- [ ] Use Arudha cases `(house,lord)->pada`: `(0,0)->9`, `(0,6)->9`, `(0,2)->4`, `(5,8)->2`; the last case first projects to the seventh sign (11) and therefore applies the frozen same/seventh exception to the tenth sign (2). Use co-lord outcomes `duration 4/7 degree 29/1 -> Ketu`, `7/7 degree 2/3 -> Ketu`, `7/7 degree 3/3 -> Mars`, and Aquarius exact comparator tie -> `Saturn`.
- [ ] Use the Argala oracle from source sign 0 with occupants `1:[Moon,Mars], 11:[Saturn], 10:[Jupiter], 4:[Venus], 8:[Rahu,Ketu]`, producing houses `2/4/11/5` with statuses `partial/absent/unobstructed/obstructed`; use special-lagna input Sun 350 degrees and 120 elapsed minutes to produce BL 20, HL 50, GL 140 degrees.
- [ ] Use Chara Dasha input lagna 2, lords `[4,5,6,7,8,9,10,11,0,1,2,3]`, male, UTC start `2000-01-01T00:00:00Z`; expected sign order is `[2,3,4,5,6,7,8,9,10,11,0,1]`, years `[4,8,4,8,4,8,4,8,4,8,4,8]`, first end `2003-12-31T23:16:48Z`, and that instant belongs to the second period, not the first.
- [ ] Implement one case-ID-independent evaluator that dispatches by declared rule family, compares exact canonical observed/expected values, reports counts and failures, and refuses held-out execution unless `allow_held_out=True`.
- [ ] Test RED first, then GREEN. Mutation tests must independently prove checksum drift, expected-value drift, missing/wrong school identity, profile/hash mismatch, duplicate IDs, tuning misuse, and non-synthetic/private payload rejection.
- [ ] Mark only `held_out_cases` passed in both Jaimini release artifacts, cite the executable corpus/evaluator evidence, remove only the obsolete held-out blocker, regenerate the project audit, and check that every remaining blocker is preserved.
- [ ] Run focused tests, affected doctrine tests, full Python and TypeScript suites, `git diff --check`, and a tracked-private-source scan. Commit with `LEA-530` in the message.
