#!/usr/bin/env python3
"""Native Windows Core Audio acceptance. Read-only unless --allow-write is given."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import sys


def level(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("volume must be finite and between 0 and 1")
    return value


def main(argv=None, *, adapter_factory=None, platform=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate request only; no native API calls")
    parser.add_argument("--allow-write", action="store_true", help="Explicitly permit changing audio volume")
    parser.add_argument("--player-index", type=int, default=0)
    parser.add_argument("--player-level", type=level)
    parser.add_argument("--system-level", type=level)
    args = parser.parse_args(argv)
    writes = args.player_level is not None or args.system_level is not None
    if writes and not args.allow_write:
        parser.error("volume changes require --allow-write; default acceptance is read-only")
    if args.player_index < 0:
        parser.error("--player-index must be nonnegative")
    if args.dry_run:
        print(json.dumps({"status": "request-validated-only", "native_tested": False,
                          "writes_requested": writes, "native_calls": 0}))
        return 0
    if (platform or sys.platform) != "win32":
        parser.error("native acceptance requires Windows; --dry-run only validates arguments")
    if adapter_factory is None:
        from triki_controller.output.windows_audio import PycawAudioAdapter
        adapter_factory = PycawAudioAdapter
    adapter = None
    report = {"platform": "win32", "read_only": not writes, "audio_only": True,
              "ble_tested": False, "input_tested": False}
    try:
        adapter = adapter_factory()
        players = tuple(sorted(adapter.sessions(), key=lambda player: player.key))
        endpoint = adapter.default_endpoint()
        report["players_before"] = [asdict(player) for player in players]
        report["system_before"] = asdict(endpoint)
        if args.player_level is not None:
            if args.player_index >= len(players):
                raise RuntimeError("selected player does not exist; start playback, then rerun the read-only probe")
            selected = players[args.player_index]
            adapter.set_player(selected.key, args.player_level)
            after = next((player for player in adapter.sessions() if player.key == selected.key), None)
            if after is None or abs(after.volume - args.player_level) > .02:
                raise RuntimeError("player volume readback did not confirm the requested value")
            report["player_after"] = asdict(after)
        if args.system_level is not None:
            adapter.set_endpoint(endpoint.key, args.system_level)
            after = adapter.default_endpoint()
            if after.key != endpoint.key or abs(after.volume - args.system_level) > .02:
                raise RuntimeError("system endpoint/volume readback did not confirm the requested value")
            report["system_after"] = asdict(after)
        report["status"] = "audio-query-or-explicit-write-confirmed"
        report["physical_controller_tested"] = False
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        print(json.dumps(report, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if adapter is not None:
            adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
