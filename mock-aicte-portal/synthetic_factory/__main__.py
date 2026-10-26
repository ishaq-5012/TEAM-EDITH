"""PowerShell-friendly command line entry point."""

import argparse
import json
import sys
from pathlib import Path

from .factory import DEFAULT_ROOT, clean, generate, input_guide, report, safe_run, validate
from .universe import SCENARIOS


def main(argv=None):
    p = argparse.ArgumentParser(description="Generate fictional AICTE-style document packages")
    sub = p.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate", help="Create a new isolated run")
    g.add_argument("--all", action="store_true")
    g.add_argument("--category", action="append", help="Category slug; repeat to select several")
    g.add_argument("--case", choices=SCENARIOS, help="Generate only one scenario/application package")
    g.add_argument("--institutions-per-category", type=int, choices=(1, 2, 3), default=3)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--as-of", default="2026-10-25")
    g.add_argument("--replace-generated-run", action="store_true")
    g.add_argument("--shared-institution", action="store_true", help="Reuse one fictional institution across selected categories as alternative demo scenarios")
    for name in ("validate", "report", "inputs", "list", "clean"):
        sub.add_parser(name)
    for command in sub.choices.values():
        command.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
        command.add_argument("--run", default="seed-42")
    args = p.parse_args(argv)
    try:
        run = safe_run(args.output_root, args.run)
        if args.command == "generate":
            if args.all and args.category:
                p.error("Use --all or --category, not both")
            cases = [args.case] if args.case else list(SCENARIOS[:args.institutions_per_category])
            run = generate(args.output_root, args.run, args.seed, args.category, cases,
                           args.as_of, args.replace_generated_run, args.shared_institution)
            print(json.dumps(dict(run=str(run), generation=report(run)), indent=2))
        elif args.command == "validate":
            result = validate(run)
            print(json.dumps({k: v for k, v in result.items() if k != "results"}, indent=2))
            if result["failed"]:
                return 1
        elif args.command == "report":
            print(json.dumps(report(run), indent=2))
        elif args.command == "inputs":
            print(input_guide(run))
        elif args.command == "list":
            print(str(run))
            for item in sorted(run.glob("applications/*/*/scenario_manifest.json")):
                print(item.parent.relative_to(run).as_posix())
        elif args.command == "clean":
            print("Removed marked generated run" if clean(args.output_root, args.run) else "Run does not exist")
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
