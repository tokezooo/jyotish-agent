# Private source Git LFS handoff

## Non-negotiable storage and rights boundary

Copyrighted or locally licensed books may be stored only under
`private_sources/`, tracked through Git LFS, and only while this repository
remains private with access restricted to its owner (Vlad). This storage policy
does **not** clear copyright, license, redistribution, lending, excerpting, or
derivative-use rights.

Never make this repository public, create a public fork, mirror, archive,
release asset, or public LFS URL, or grant any other person access to these source
bytes. If repository privacy or owner-only access cannot be confirmed, stop
before staging or pushing. Raw books must still never be copied into `src/`,
`tests/`, `docs/`, fixtures, a Docker image, or a public MCP runtime.

Secrets, credentials, tokens, personal profiles, databases, logs, generated
responses, and temporary/output artifacts are never source material and remain
excluded by `.gitignore`.

## 1. Prepare the private layout

From the repository root:

```bash
install -d -m 700 \
  private_sources/jaimini \
  private_sources/prashna \
  private_sources/muhurta
```

Acquire each edition through a lawful purchase, library, author/publisher grant,
or a verified public-domain archive. Do not copy a book into `src/`, `tests/`,
`docs/`, or any Git fixture. Track a source binary only beneath
`private_sources/` after its extension is covered by `.gitattributes` with the
Git LFS filter. Use the exact relative filename declared by the applicable
tracked `local_file` entry in `jaimini-sources.json`,
`prashna-sources.json`, or `muhurta-sources.json`, then set file permissions:

```bash
find private_sources -type d -exec chmod 700 {} +
find private_sources -type f -exec chmod 600 {} +
```

## 2. Record exact bibliography and bytes

Copy `src/jyotish_agent/data/doctrine/example-sources.json` to
`private_sources/source-manifest.json`. Replace every example-only field with the
exact title page/copyright page metadata. The manifest may be committed with the
private source package only when it contains bibliography/provenance rather than
credentials, personal data, or private/authenticated access URLs. For each file, calculate the hash
from the repository root:

```bash
shasum -a 256 private_sources/<local_file-from-domain-manifest>
```

Put the 64-character lowercase digest in `sha256`. `local_file` is relative to
`private_sources/`, never absolute. `page_offset` is:

```text
printed page number = PDF page index + page_offset
```

Use `license_class=copyrighted_local` unless the edition's rights are affirmatively
verified as public domain or separately licensed. Set `ocr_required=true` only for
pages without a reliable embedded text layer.

## 3. Verify without disclosing local paths

```bash
uv run python - <<'PY'
from pathlib import Path
from jyotish_agent.doctrine.sources import load_source_manifest, SourceVerifier

root = Path("private_sources")
manifest = load_source_manifest(root / "source-manifest.json")
report = SourceVerifier.verify(manifest, root)
print(report.model_dump_json(indent=2))
raise SystemExit(0 if report.ok else 1)
PY
```

The report contains source IDs and typed findings but no local paths, filenames,
file bytes, or excerpts. Resolve every missing/hash/path finding before ingestion.

## 4. Stage only the private, LFS-covered source package

After verification, keep runtime-safe doctrine data limited to reviewed
bibliography, SHA-256, locators, license classification, and permitted short
fragments. Before any commit or push, confirm the repository remains private,
access remains owner-only, and every source binary is represented by a Git LFS
pointer:

```bash
gh repo view --json nameWithOwner,isPrivate,visibility,viewerPermission
gh api repos/<owner>/<repo>/collaborators --paginate --jq '.[].login'
git check-attr filter -- private_sources/<source-file>
git lfs status
git diff --cached --check
git diff --cached --name-only
```

Stage an exact reviewed whitelist; do not use a broad `git add -A`. Before every
push, check that no `.env`, credential/token, profile, database, log, `tmp/`,
`output/`, generated response, or system-metadata path is staged. Push only the
intended branch, never `--all` or `--mirror`.

If a source's rights or edition identity is unclear, leave it
missing/quarantined; calculation may remain available, but its doctrine rules
cannot be admitted.
