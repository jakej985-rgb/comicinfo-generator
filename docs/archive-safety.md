# Archive Safety — ComicInfo Generator

## Purpose

Describes every safety guarantee that `writers/archive.py` provides  
and the invariants that must be maintained for all archive operations.

---

## Responsibilities

`writers/archive.py → embed_comicinfo_in_cbz(archive_path, comic)`

1. Record original archive entry list (Phase 18)
2. Create a temporary `.cbz` in the **same directory** as the target
3. Write all original entries (except old `ComicInfo.xml`) into the temp file
4. Write the new `ComicInfo.xml`
5. Preserve file permissions, timestamps, and ownership (Phase 17)
6. Verify the temp file before replacement (Phase 18)
7. `fsync` the temp file to stable storage (Phase 16)
8. `os.replace()` — atomic swap (Phase 16)
9. Verify the final file after replacement (Phase 18)

---

## The Atomic Write Contract

```text
[original.cbz]  ──read──▶  [.tmp_XXXXXX.cbz]
                                    │
                            verify_cbz_archive()
                                    │
                               fsync()
                                    │
                           os.replace(tmp → original)
                                    │
                            verify_cbz_archive()
```

`os.replace()` is atomic on POSIX systems when source and destination are on the same filesystem.  
The temp file is **always created in the same directory** as the target to guarantee this.

---

## Verification (`verify_cbz_archive`)

Every archive is verified at two checkpoints:

| Step | What is verified |
|---|---|
| Pre-replace (temp file) | ZIP integrity, ComicInfo.xml present, XML parseable, images present, no entry deletions |
| Post-replace (final file) | Same checks again on the written file |

Verification failure raises `ArchiveValidationError` and aborts.

---

## CBR → CBZ Conversion Safety

Defined in `converters/cbr_to_cbz.py`:

> **The original `.cbr` must never be deleted until:**
> 1. The `.cbz` file has been fully written
> 2. The `.cbz` has been verified (`verify_cbz_archive`)
> 3. The `.cbz` has been embedded with `ComicInfo.xml`
> 4. Post-embed verification has passed

`delete_original=True` is only honoured after all four conditions are met.

---

## Exception Hierarchy

| Exception | When raised |
|---|---|
| `ArchiveReadError` | Archive does not exist, is not a ZIP, or cannot be opened |
| `ArchiveWriteError` | Temp file creation fails, disk full, `os.replace` fails, permission denied |
| `ArchiveValidationError` | Integrity check fails before or after replacement |

All three inherit from `ArchiveError`. Callers should catch `ArchiveError` to handle all archive failures.

---

## Temp File Cleanup

If any step between temp-file creation and `os.replace` fails:
- The temp file is **always deleted** in the `except` block
- The original archive is **never touched**

This is tested by Phase 38 failure-injection tests.

---

## Dry-Run Mode

When `--dry-run` is passed to `main.py`:
- `embed_comicinfo_in_cbz` is **never called**
- No archive, temp file, or file hash is modified
- Dry-run mode logs what would have happened without doing it

---

## Invariants

1. The original archive is never modified in-place — only replaced atomically.
2. Temp files are always created in the same directory as the target.
3. Verification runs before **and** after every replacement.
4. A failed verification leaves the original archive intact.
5. `.cbr` originals are never deleted until their `.cbz` replacement is fully verified.
6. `fsync` is called before `os.replace` to ensure the temp file is on stable storage.

---

## Failure Modes

| Failure | Result |
|---|---|
| Permission denied | `ArchiveWriteError` raised, temp deleted, original safe |
| Disk full (ENOSPC) | `ArchiveWriteError` raised, temp deleted, original size unchanged |
| `os.replace` failure | `ArchiveWriteError` raised, temp deleted, original safe |
| Invalid XML generated | `ArchiveValidationError` on pre-replace verify, temp deleted, original safe |
| Corrupt image entry in original | `ArchiveValidationError` on `testzip()`, aborts before replacement |

---

## Testing Requirements

- Every archive write path must have a corresponding failure-injection test (Phase 38).
- Tests must assert: original archive exists and has the same size after a failed embed.
- Temp file leak tests must confirm zero `.tmp_*` files remain after failure.

---

## Do-Not-Do Rules

- Do not write directly to the target archive — always use temp + `os.replace`.
- Do not skip `verify_cbz_archive` before or after replacement.
- Do not delete the original `.cbr` before the `.cbz` is fully verified.
- Do not use cross-filesystem temp directories (e.g. `/tmp`) — must be same directory.
- Do not catch `ArchiveError` silently — always log and record job failure.
