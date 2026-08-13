import sys
import os
from config import load_config
from pipeline.resolver import MetadataResolver
from pipeline.filename_parser import parse_filename_identity
from app import run_server

def run_dry_run(target_path: str):
    """
    Phase 24: Executes a dry-run evaluation on a file or folder directory,
    displaying resolved identity, confidence, evidence list, action, and changes
    without modifying any archive files.
    """
    cfg = load_config()
    resolver = MetadataResolver(cfg)
    target = os.path.abspath(target_path)

    print("=" * 65)
    print(f" DRY-RUN MODE: Evaluating '{target}'")
    print(" NO ARCHIVE FILES WILL BE MODIFIED")
    print("=" * 65)

    if os.path.isfile(target):
        files = [target]
    elif os.path.isdir(target):
        files = [os.path.join(target, f) for f in sorted(os.listdir(target)) if f.lower().endswith(('.cbz', '.cbr'))]
    else:
        print(f"Error: Path '{target}' not found.")
        return

    for idx, fpath in enumerate(files, 1):
        filename = os.path.basename(fpath)
        parsed = parse_filename_identity(fpath)
        identity, decision = resolver.resolve_identity(fpath)
        comic = resolver.retrieve_metadata(identity) if (identity and decision.action != "SKIP") else None

        print(f"\n[{idx}/{len(files)}] Archive:")
        print(f"  {filename}")
        print("\nIdentity:")
        print(f"  Series: {parsed.series_name}")
        print(f"  Issue: #{parsed.issue_number}")
        print(f"  Year: {parsed.year or 'Unknown'}")

        if identity:
            print("\nCandidate:")
            print(f"  {identity.provider} #{identity.issue_id or identity.series_id or 'Resolved'}")
            print("\nConfidence:")
            print(f"  {decision.score:.1f}% ({decision.level})")

            print("\nEvidence:")
            for ev in decision.evidence:
                sign = "+" if ev.score > 0 else ""
                print(f"  {sign}{ev.score:.0f} {ev.explanation}")

            print("\nAction:")
            print(f"  {decision.action}")

            if comic:
                print("\nChanges:")
                fields = []
                if comic.title: fields.append("Title")
                if comic.series: fields.append("Series")
                if comic.number: fields.append("Number")
                if comic.publisher: fields.append("Publisher")
                if comic.year: fields.append("Year")
                if comic.writers: fields.append("Writer")
                if comic.pencillers: fields.append("Penciller")
                if comic.characters: fields.append("Characters")
                for fld in fields:
                    print(f"  - {fld}")
        else:
            print("\nCandidate:")
            print("  None")
            print("\nConfidence:")
            print(f"  {decision.score:.1f}% ({decision.level})")
            print("\nAction:")
            print(f"  {decision.action}")

    print("\n" + "=" * 65)
    print(" DRY-RUN COMPLETE: 0 files were modified.")
    print("=" * 65)


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
