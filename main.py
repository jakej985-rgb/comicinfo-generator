import sys
import os
from config import load_config
from pipeline.dry_run import DryRunContext
from app import run_server

def run_dry_run(target_path: str):
    """
    Phase 24 & 50: Executes a true side-effect-free dry-run evaluation on a file or folder directory,
    displaying resolved identity, confidence, evidence list, action, and changes
    without modifying any archive files or persistent database state.
    """
    cfg = load_config()
    target = os.path.abspath(target_path)

    print("=" * 65)
    print(f" DRY-RUN MODE: Evaluating '{target}'")
    print(" NO ARCHIVE FILES OR PERSISTENT DATABASES WILL BE MODIFIED")
    print("=" * 65)

    with DryRunContext(config=cfg) as ctx:
        results = ctx.evaluate_target(target)
        if not results:
            print(f"Error: Path '{target}' not found or contains no eligible comic archives.")
            return

        for idx, res in enumerate(results, 1):
            print(f"\n[{idx}/{len(results)}] Archive:")
            print(f"  {res.filename}")
            print("\nIdentity:")
            print(f"  Series: {res.parsed_series}")
            print(f"  Issue: #{res.parsed_issue}")
            print(f"  Year: {res.parsed_year or 'Unknown'}")

            if res.candidate:
                print("\nCandidate:")
                print(f"  {res.candidate.provider} #{res.candidate.issue_id or res.candidate.series_id or 'Resolved'}")
                print("\nConfidence:")
                print(f"  {res.decision.score:.1f}% ({res.decision.level})")

                print("\nEvidence:")
                for ev in res.decision.evidence:
                    sign = "+" if ev.score > 0 else ""
                    print(f"  {sign}{ev.score:.0f} {ev.explanation}")

                print("\nAction:")
                print(f"  {res.decision.action}")

                if res.proposed_comic:
                    print("\nChanges:")
                    for fld in res.fields_to_change:
                        print(f"  - {fld}")
            else:
                print("\nCandidate:")
                print("  None")
                print("\nConfidence:")
                print(f"  {res.decision.score:.1f}% ({res.decision.level})")
                print("\nAction:")
                print(f"  {res.decision.action}")

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
