#!/usr/bin/env python3
"""Native acceptance probe: read-only unless --allow-write is explicit.

Run with PYTHONPATH=src python tools/accept_macos_output.py on a Mac.
Reads can trigger macOS Automation permission prompts. It never launches an
app or emits mouse/key events. No success is claimed for unavailable features.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
import math
import sys

from triki_controller.output.macos_audio import NativeMacOSAudio


def level(text):
    value = float(text)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("level must be finite and in [0, 1]")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="no native calls, safe on Linux")
    parser.add_argument("--allow-write", action="store_true", help="authorize only explicit writes below")
    parser.add_argument("--system-level", type=level)
    parser.add_argument("--player", choices=("Music", "Spotify"))
    parser.add_argument("--player-level", type=level)
    parser.add_argument("--transport", choices=("play_pause", "next_track", "previous_track"))
    args = parser.parse_args(argv)
    writes = args.system_level is not None or args.player_level is not None or args.transport
    if writes and not args.allow_write:
        parser.error("writes require --allow-write; default is read-only")
    if (args.player_level is not None or args.transport) and not args.player:
        parser.error("player writes/transport require --player")
    if args.dry_run:
        print(json.dumps({"mode": "dry-run", "native_validated": False,
                          "detail": "no native calls/output; run read-only probe on macOS"}))
        return 0
    if sys.platform != "darwin":
        print(json.dumps({"mode": "read-only", "native_validated": False,
                          "error": "native acceptance requires a macOS host"}))
        return 2
    adapter = NativeMacOSAudio()
    results = {"mode": "explicit-write" if writes else "read-only", "checks": {}}
    failed = False
    def check(name, fn):
        nonlocal failed
        try:
            results["checks"][name] = {"ok": True, "value": fn()}
        except Exception as exc:
            failed = True
            results["checks"][name] = {"ok": False, "error": str(exc)}
    def endpoint_metadata():
        endpoint, current = adapter.read_system_endpoint()
        return {"endpoint": asdict(endpoint), "level": current,
                "api": "CoreAudio main output scalar; no AppleScript fallback"}
    check("system_endpoint_read", endpoint_metadata)
    try:
        players = adapter.list_players()
        results["checks"]["running_players"] = {"ok": True, "value": players}
        for player in players:
            check(f"{player}_read", lambda player=player: adapter.read_player(player))
    except Exception as exc:
        failed = True
        results["checks"]["running_players"] = {"ok": False, "error": str(exc)}
    try:
        import Quartz
        results["checks"]["mouse_post_access"] = {
            "ok": bool(Quartz.CGPreflightPostEventAccess()), "event_posted": False}
    except Exception as exc:
        results["checks"]["mouse_post_access"] = {"ok": False, "error": str(exc),
                                                   "event_posted": False}
    if args.system_level is not None:
        check("system_write_verified", lambda: adapter.write_system(args.system_level))
    if args.player_level is not None:
        check("player_write_verified", lambda: adapter.write_player(args.player, args.player_level))
    if args.transport:
        check("transport_appleevent_reply", lambda: adapter.transport(args.player, args.transport))
    results["scope"] = "audio query/write results only; mouse delivery and virtual HID not validated"
    print(json.dumps(results, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
