"""Command line: python -m kit {prizes,doctor,plan,cost,run}."""

import argparse
import json
import sys
from datetime import date

from . import doctor, ledger, plan, prizes


def cmd_prizes(args):
    snapshot = prizes.load()
    if args.json:
        print(json.dumps(snapshot, indent=2))
    else:
        today = date.fromisoformat(args.today) if args.today else None
        print(prizes.format_table(snapshot, today))
    return 0


def cmd_doctor(args):
    report, worst = doctor.format_report(doctor.run_checks(disk_path=args.disk))
    print(report)
    return 1 if worst == doctor.FAIL else 0


def cmd_plan(args):
    try:
        print(plan.first_letters(args.scroll, batch=args.batch))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def cmd_cost(args):
    total = plan.cost(args.gpu_hours, args.rate, args.cpu_hours, args.cpu_rate, args.storage)
    print(f"${total:.2f}")
    return 0


def cmd_run(args):
    root = args.root
    try:
        if args.action == "init":
            path, _ = ledger.init(args.slug, args.scroll, args.question, args.readout,
                                  root=root, villa_commit=args.villa_commit)
            print(f"created {path} (status planned, readout rule hashed)")
        elif args.action == "status":
            record = ledger.set_status(args.slug, args.status, args.note, args.announced, root=root)
            print(f"{record['slug']}: {record['status']}")
        elif args.action == "cost":
            record = ledger.add_cost(args.slug, args.usd, args.what, root=root)
            print(f"{record['slug']}: total ${ledger.total_cost(record):.2f}")
        elif args.action == "check":
            problems = ledger.check(args.slug, root=root)
            for problem in problems:
                print(f"problem: {problem}")
            if problems:
                return 1
            print(f"{args.slug}: ok")
        elif args.action == "list":
            for record in ledger.list_runs(root):
                print(f"{record['slug']:<28} {record['scroll']:<12} {record['status']:<10} ${ledger.total_cost(record):.2f}")
    except ledger.LedgerError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m kit", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prizes", help="open prizes from the dated snapshot")
    p.add_argument("--json", action="store_true")
    p.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    p.set_defaults(func=cmd_prizes)

    p = sub.add_parser("doctor", help="check GPU, disk, tools and villa paths")
    p.add_argument("--disk", default=".", help="path whose free space to check")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("plan", help="print a First Letters run plan for an eligible scroll")
    p.add_argument("scroll", help="e.g. PHerc0826")
    p.add_argument("--batch", type=int, default=4, help="inference batch size (1 for small GPUs)")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("cost", help="estimate run cost in USD")
    p.add_argument("--gpu-hours", type=float, required=True)
    p.add_argument("--rate", type=float, required=True, help="USD per GPU hour")
    p.add_argument("--cpu-hours", type=float, default=0.0)
    p.add_argument("--cpu-rate", type=float, default=0.0)
    p.add_argument("--storage", type=float, default=0.0, help="flat storage or egress USD")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("run", help="local experiment ledger (experiments/, gitignored)")
    p.add_argument("--root", default=str(ledger.DEFAULT_ROOT))
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("init")
    a.add_argument("slug")
    a.add_argument("--scroll", required=True)
    a.add_argument("--question", required=True)
    a.add_argument("--readout", required=True, help="what will count as ink, written before looking")
    a.add_argument("--villa-commit")
    a = actions.add_parser("status")
    a.add_argument("slug")
    a.add_argument("status", choices=ledger.STATUSES)
    a.add_argument("--note", default="")
    a.add_argument("--announced", action="store_true", help="the prize result was officially announced")
    a = actions.add_parser("cost")
    a.add_argument("slug")
    a.add_argument("--usd", type=float, required=True)
    a.add_argument("--what", required=True)
    a = actions.add_parser("check")
    a.add_argument("slug")
    actions.add_parser("list")
    p.set_defaults(func=cmd_run)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
