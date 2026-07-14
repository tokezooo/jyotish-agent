# Private source download handoff

This repository never stores copyrighted or locally licensed books. The tracked
manifest is a hash commitment and bibliography; source bytes live only under the
gitignored `private_sources/` directory on Vlad's machine.

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
`docs/`, or any Git fixture. Use the exact relative filename declared by the
applicable tracked `local_file` entry in `jaimini-sources.json`,
`prashna-sources.json`, or `muhurta-sources.json`, then set file permissions:

```bash
find private_sources -type d -exec chmod 700 {} +
find private_sources -type f -exec chmod 600 {} +
```

## 2. Record exact bibliography and bytes

Copy `src/jyotish_agent/data/doctrine/example-sources.json` to an untracked working
manifest inside `private_sources/source-manifest.json`. Replace every example-only
field with the exact title page/copyright page metadata. For each file, calculate
the hash from the repository root:

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

## 4. Commit only the safe projection

After verification, copy only the reviewed bibliography, SHA-256, locators,
license classification, and permitted short fragments into tracked doctrine data.
Before any commit, confirm no private source is staged:

```bash
git status --short
git diff --cached --name-only | rg '\.(pdf|epub|djvu|tiff?|png|jpe?g)$' && exit 1 || true
git check-ignore -v private_sources/source-manifest.json
```

Never use `git add -f private_sources`. If a source's rights or edition identity is
unclear, leave it missing/quarantined; calculation may remain available, but its
doctrine rules cannot be admitted.
