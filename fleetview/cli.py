"""`fleetview` entry point: TUI (no subcommand), pull, snapshot, reconcile."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .collector import FleetCollector
from .config_loader import ConfigError, load_config
from .pull import passes_ci_gates, pull_output
from .reconcile import format_report, reconcile
from .snapshot import DEFAULT_PATH, build_snapshot, write_snapshot

DEPRECATED_WARNING = "fleetview pull: --config/--token/--connection-mode are ignored (SSH transport)"
DEFAULT_PROFILE = r"C:\Users\Owner\.admin\profiles\WOPR3.json"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fleetview", description="Fleet dashboard over SSH + Rust Sentinel")
    sub = p.add_subparsers(dest="cmd")

    pull = sub.add_parser("pull", help="sentinelctl-compatible JSON health pull")
    pull.add_argument("--ci", action="store_true")
    pull.add_argument("--container-match", default="")
    pull.add_argument("--servers", default="", help="comma-separated server ids")
    pull.add_argument("--watch-seconds", type=int, default=0)
    pull.add_argument("--iterations", type=int, default=1)
    pull.add_argument("--config", default=None, help=argparse.SUPPRESS)
    pull.add_argument("--token", default=None, help=argparse.SUPPRESS)
    pull.add_argument("--connection-mode", default=None, help=argparse.SUPPRESS)

    snap = sub.add_parser("snapshot", help="write the fleet container snapshot")
    snap.add_argument("--out", default=str(DEFAULT_PATH))

    rec = sub.add_parser("reconcile", help="report drift between snapshot and profile")
    rec.add_argument("--snapshot", default=str(DEFAULT_PATH))
    rec.add_argument("--profile", default=None)
    return p


def _filter_servers(cfg, ids: str):
    if not ids:
        return cfg
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    known = {s.id: s for s in cfg.servers}
    unknown = [i for i in wanted if i not in known]
    if unknown:
        raise ConfigError(f"unknown server id(s): {', '.join(unknown)}")
    return replace(cfg, servers=[known[i] for i in wanted])


async def _pull(cfg, args) -> int:
    collector = FleetCollector(cfg)
    ci_fail = False
    loops = max(1, args.iterations) if args.watch_seconds > 0 else 1
    match = args.container_match or None
    try:
        for i in range(loops):
            out = pull_output(await collector.poll(True), match)
            if args.watch_seconds == 0:
                print(json.dumps(out, indent=2))
            else:
                print(json.dumps(out, separators=(",", ":")), flush=True)
            if args.ci and not passes_ci_gates(out["results"], bool(match)):
                ci_fail = True
            if i < loops - 1:
                await asyncio.sleep(args.watch_seconds)
    finally:
        await collector.close()
    return 1 if ci_fail else 0


async def _snapshot(cfg, out: Path) -> int:
    collector = FleetCollector(cfg)
    try:
        snaps = await collector.poll(True)
    finally:
        await collector.close()
    data = build_snapshot(snaps, datetime.now(timezone.utc))
    write_snapshot(out, data)
    n = sum(len(s["stacks"]) for s in data["servers"].values())
    print(f"{out.expanduser()}: {len(data['servers'])} servers, {n} stacks")
    for s in snaps:
        if s.error:
            print(f"  {s.server.id}: {s.error}", file=sys.stderr)
    return 0


def _reconcile(args) -> int:
    profile_path = Path(args.profile or os.environ.get("WOPR3_PROFILE") or DEFAULT_PROFILE)
    try:
        snapshot = json.loads(Path(args.snapshot).expanduser().read_text(encoding="utf-8"))
        profile = json.loads(profile_path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"fleetview reconcile: {e}", file=sys.stderr)
        return 0
    print(format_report(reconcile(snapshot, profile)), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "reconcile":
        return _reconcile(args)
    try:
        cfg = load_config()
        if args.cmd == "pull":
            if args.config is not None or args.token is not None or args.connection_mode is not None:
                print(DEPRECATED_WARNING, file=sys.stderr)
            cfg = _filter_servers(cfg, args.servers)
            return asyncio.run(_pull(cfg, args))
        if args.cmd == "snapshot":
            return asyncio.run(_snapshot(cfg, Path(args.out)))
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        return 2

    from .tui import run_tui  # imported lazily: headless commands never load Textual
    return run_tui(cfg)
