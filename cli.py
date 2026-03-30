"""Command-line interface for the job tracker and pipeline."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from logging_config import setup_logging
from tracker import get_applied_jobs, get_stats, init_db, search_jobs, update_status

setup_logging()


def cmd_stats(args: argparse.Namespace) -> None:
    stats = get_stats()
    print(f"\n{'-' * 40}")
    print("  Job Digest Tracker")
    print(f"{'-' * 40}")
    print(f"  Total jobs seen:  {stats['total_seen']}")
    print("\n  Funnel:")
    for status, count in stats["by_status"].items():
        bar = "#" * min(count, 30)
        print(f"    {status:<14} {count:>4}  {bar}")
    print("\n  Top sources:")
    for source, count in stats["top_sources"].items():
        print(f"    {source:<20} {count}")
    print("\n  Recent jobs:")
    for job in stats["recent"]:
        print(f"    [{job['score']:>3}] {job['title'][:35]:<35} @ {job['company'][:20]}")
    print()


def cmd_list(args: argparse.Namespace) -> None:
    jobs = search_jobs(status=args.status, limit=args.limit)
    if not jobs:
        print("No jobs found.")
        return

    print(f"\n{'-' * 80}")
    for job in jobs:
        score = job.get("score", 0)
        status = job.get("status", "")
        print(f"  [{score:>3}] [{status:<12}] {job['title'][:40]:<40} @ {job['company'][:20]}")
        print(f"         {job['url'][:70]}")
        print()


def cmd_applied(args: argparse.Namespace) -> None:
    jobs = get_applied_jobs()
    if not jobs:
        print("No applications yet.")
        return

    print(f"\n  Applied jobs ({len(jobs)}):")
    print(f"{'-' * 60}")
    for job in jobs:
        applied_at = str(job.get("applied_at", "") or "")[:10]
        print(f"  {applied_at:<10}  {job['title'][:40]} @ {job['company']}")
        print(f"             {job['url'][:60]}")


def cmd_apply(args: argparse.Namespace) -> None:
    update_status(args.url, "applied", args.notes or "")
    print(f"Marked as applied: {args.url[:60]}")


def cmd_skip(args: argparse.Namespace) -> None:
    update_status(args.url, "skipped")
    print(f"Skipped: {args.url[:60]}")


def cmd_status(args: argparse.Namespace) -> None:
    update_status(args.url, args.new_status, args.notes or "")


def cmd_search(args: argparse.Namespace) -> None:
    jobs = search_jobs(query=args.query, limit=args.limit)
    if not jobs:
        print(f"No jobs matching '{args.query}'")
        return

    for job in jobs:
        print(
            f"  [{job.get('score', 0):>3}] [{job.get('status', ''):^12}] "
            f"{job['title'][:35]} @ {job['company'][:20]}"
        )
        print(f"         {job['url'][:70]}\n")


def cmd_run(args: argparse.Namespace) -> None:
    from main import run_pipeline

    asyncio.run(run_pipeline())


def main() -> None:
    parser = argparse.ArgumentParser(prog="job-digest")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("stats", help="Show funnel stats")

    list_parser = sub.add_parser("list", help="List tracked jobs")
    list_parser.add_argument("--status", default="", help="Filter by status")
    list_parser.add_argument("--limit", type=int, default=20)

    sub.add_parser("applied", help="List applied jobs")

    apply_parser = sub.add_parser("apply", help="Mark a job as applied")
    apply_parser.add_argument("url")
    apply_parser.add_argument("--notes", default="")

    skip_parser = sub.add_parser("skip", help="Mark a job as skipped")
    skip_parser.add_argument("url")

    status_parser = sub.add_parser("status", help="Update a job status")
    status_parser.add_argument("url")
    status_parser.add_argument(
        "new_status",
        choices=sorted(["new", "skipped", "applied", "interviewing", "rejected", "offer"]),
    )
    status_parser.add_argument("--notes", default="")

    search_parser = sub.add_parser("search", help="Search tracked jobs")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=20)

    sub.add_parser("run", help="Run the pipeline now")

    args = parser.parse_args()
    commands = {
        "stats": cmd_stats,
        "list": cmd_list,
        "applied": cmd_applied,
        "apply": cmd_apply,
        "skip": cmd_skip,
        "status": cmd_status,
        "search": cmd_search,
        "run": cmd_run,
    }

    command = commands.get(args.command)
    if command is None:
        parser.print_help()
        return

    command(args)


if __name__ == "__main__":
    init_db()
    main()
