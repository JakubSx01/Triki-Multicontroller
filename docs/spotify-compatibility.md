# Spotify compatibility — v0.1.5

## Evidence and scope

User requested an internet-informed fix, no further tests, push main and release. No test suite, GUI smoke or playback writes were run for this change. Existing three-platform workflow builds packages; archive/source/hash checks are packaging verification, not behavioral acceptance.

Read-only local discovery returned no players from playerctl and no Spotify D-Bus owner or local audio stream. Therefore the user's exact failing Spotify version and failing action cannot be reproduced or confirmed here. Scope is native Spotify desktop on Linux, not Windows/macOS, Spotify Web or remote Spotify Connect/API integration.

Primary sources retrieved online:
- https://github.com/altdesktop/playerctl/issues/246 — maintainer comment on 2021-09-03 notes Spotify volume support limitations; a user comment on 2022-07-14 reports newer Spotify supports MPRIS volume. These historical reports do NOT prove current Spotify universally lacks MPRIS volume.
- https://github.com/altdesktop/playerctl/blob/master/README.md — Spotify discovery can depend on shared desktop session D-Bus environment. Do not change the user's compositor/session configuration as part of the application fix.
- https://specifications.freedesktop.org/mpris-spec/latest/Player_Interface.html — MPRIS Player Volume interface.

## Change

Native names spotify / spotify.instance* route volume reads and writes to the existing PipeWire/Pulse app-stream adapter. This provides compatibility independent of Spotify's MPRIS Volume implementation and baselines actual stream gain, not a potentially unavailable/stub MPRIS number. MPRIS remains responsible for transport. Favorite generation/unique-owner checks remain intact. Stream mapping remains owner-PID/descendant based, never application label or system default sink.

Missing local stream returns an explanatory error rather than success. Diagnostics show actual stream volume or a local-playback requirement. No user settings or new Spotify account credentials are needed. No test pass claims from v0.1.4 apply to this untested change.
