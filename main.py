import sys
import os
from config import load_config
from pipeline.resolver import MetadataResolver
from pipeline.filename_parser import parse_filename_identity
from pipeline.scoring import score_identity_candidate
from app import run_server

def run_dry_run(target_path: str):
    """
    Executes a dry-run evaluation on a file or folder directory,
    displaying resolved identity candidates and confidence scores without modifying files.
    """
    cfg = load_config()
    resolver = MetadataResolver(cfg)
    target = os.path.abspath(target_path)

    print("=" * 60)
    print(f" DRY-RUN MODE: Evaluating '{target}'")
    print("=" * 60)

    if os.path.isfile(target):
        files = [target]
    elif os.path.isdir(target):
        files = [os.path.join(target, f) for f in os.listdir(target) if f.lower().endswith(('.cbz', '.cbr'))]
    else:
        print(f"Error: Path '{target}' not found.")
        return

    for idx, fpath in enumerate(files, 1):
        parsed = parse_filename_identity(fpath)
        comic, provider = resolver.resolve_file_metadata(fpath)

        score, status, reasons = 0.0, "UNRESOLVED", []
        if comic:
            from models.identity import ComicIdentity
            cand = ComicIdentity(
                provider=provider,
                series_name=comic.series,
                publication_year=comic.year,
                publisher=comic.publisher,
                issue_number=comic.number
            )
            score, status, reasons = score_identity_candidate(cand, parsed)

        print(f"\n[{idx}/{len(files)}] File: {os.path.basename(fpath)}")
        print(f"  ├─ Parsed Series: '{parsed.series_name}', Issue #{parsed.issue_number}, Year: {parsed.year}")
        if comic:
            print(f"  ├─ Resolved Identity: '{comic.series} #{comic.number}' ({comic.publisher}, {comic.year}) via {provider}")
            print(f"  ├─ Confidence Score: {score:.1f}% [{status}]")
            print(f"  ├─ Action: {'UPDATE (Safe to embed)' if status == 'AUTO_ACCEPT' else 'MANUAL_REVIEW (Low confidence)'}")
            for r in reasons:
                print(f"  │   └─ {r}")
        else:
            print("  └─ Resolved Identity: UNRESOLVED")
            print("  └─ Action: SKIP (No metadata match found)")

    print("\n" + "=" * 60)
    print(" DRY-RUN COMPLETE: 0 files were modified.")
    print("=" * 60)


def main():
    if "--dry-run" in sys.argv:
        idx = sys.argv.index("--dry-run")
        target = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else os.getcwd()
        run_dry_run(target)
        return

    port = 5005
    for arg in sys.argv[1:]:
        if arg.isdigit():
            port = int(arg)
    run_server(port)

if __name__ == "__main__":
    main()
