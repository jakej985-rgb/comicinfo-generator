# Archive Safety — ComicInfo Generator

## Purpose

Describes every safety guarantee that `writers/archive.py` provides  
and the invariants that must be maintained for all archive operations.

---

## Responsibilities

`writers/archive.py → embed_comicinfo_in_cbz(archive_path, comic)`

1. Record original archive entry manifest with entry-by-entry CRC32 and uncompressed sizes
2. Create a temporary `.cbz` in the **same directory** as the target (same filesystem)
3. Stream-copy original image and asset entries without re-compressing uncompressed data
4. Write the new `ComicInfo.xml` (preserving unrecognised XML fields)
5. Preserve file permissions, timestamps, and ownership
6. Verify the temporary archive with entry-by-entry CRC and size matching before replacement
7. `fsync` the temp file file descriptor to flush data blocks to stable storage
8. `fsync_directory` to ensure directory metadata changes are durable on disk
9. `os.replace()` — atomic swap on POSIX filesystem
10. Verify the final archive with post-replacement CRC verification

---

## The 9-Step Atomic Write Contract

```text
[original.cbz]  ──read manifest (CRC32, size)──▶  [.tmp_XXXXXX.cbz]
                                                          │
                                         verify_cbz_archive(temp, original_manifest)
                                                          │
                                                     fsync(temp_fd)
                                                          │
                                                    fsync_directory(dir)
                                                          │
                                              os.replace(tmp → original)
                                                          │
                                                    fsync_directory(dir)
                                                          │
                                         verify_cbz_archive(final, original_manifest)
```

`os.replace()` is guaranteed atomic on POSIX systems when source and destination are on the same filesystem.  
The temp file is **always created in the same directory** as the target to guarantee this.

---

## Verification (`verify_cbz_archive`)

Every archive is verified at two checkpoints (pre-replace on temp file, and post-replace on target file):

| Check | What is verified |
|---|---|
| ZIP Structure | Integrity verified via `ZipFile.testzip() == None` |
| ComicInfo.xml | File present, parseable XML, valid schema fields |
| Image Preserved | At least one image exists, entry count matches original |
| Entry CRC32 | Every image entry CRC32 exactly matches the pre-write manifest |
| Entry File Size | Every image entry uncompressed size exactly matches original |

Verification failure raises `ArchiveValidationError` and aborts immediately.

---

## CBR → CBZ Conversion Safety

Defined in `converters/cbr_to_cbz.py`:

> **The original `.cbr` must never be deleted until:**
> 1. The `.cbz` file has been fully written
> 2. The `.cbz` has passed pre-embed verification (`verify_cbz_archive`)
> 3. The `.cbz` has been embedded with `ComicInfo.xml`
> 4. Post-embed verification has passed

`delete_original=True` is only honoured after all four conditions are met.

---

## Exception Hierarchy

| Exception | When raised |
|---|---|
| `ArchiveReadError` | Archive does not exist, is not a ZIP, or cannot be opened |
| `ArchiveWriteError` | Temp file creation fails, disk full, `os.replace` fails, permission denied |
| `ArchiveValidationError` | Integrity or CRC check fails before or after replacement |

All three inherit from `ArchiveError`.

---

## Temp File Cleanup

If any step between temp-file creation and `os.replace` fails:
- The temp file is **always deleted** in the `except` block
- The directory inode is cleaned up
- The original archive is **never touched or truncated**

---

## Dry-Run Isolation

When `--dry-run` is active:
- `embed_comicinfo_in_cbz` execution is intercepted by `DryRunContext`
- No physical files or temp files are created
- Physical files retain their original mtime, SHA256 hash, and byte content

---

## Summary of Invariants

1. The original archive is never modified in-place — only replaced atomically via same-directory temp file.
2. Verification with entry-level CRC matching runs before **and** after every replacement.
3. A failed verification leaves the original archive intact.
4. `.cbr` originals are never deleted until their `.cbz` replacement is fully verified.
5. `fsync` on both file descriptor and directory inode is executed to guarantee on-disk durability.
