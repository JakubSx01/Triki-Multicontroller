# Independent media-favorites/profile-switch review

## Initial verdict: REQUEST_CHANGES

**Parent resolution:** R1/R2 now pass unchanged independent reproductions after unique-owner-first discovery and generation-owned mute/capability invalidation. R3 is fixed through the public observational `active_media_favorite()` query, separate current-session/next-start labels and effective gesture disabling. Explicit Auto/same-pin choice clears startup priority in both editors. Quadratic discovery was replaced with a linear batch catalogue; observational calls release the session lock. Final protected display suite: **585 passed, 89 subtests passed, three hardware cases excluded**. Unchanged independent review reproductions: **11 passed**. New linear-catalogue probes: **14 passed**. Linux frozen build/GUI smoke exited 0. These reproduced blockers are closed; native target-app/hardware acceptance remains unavailable. Tk discovery is still synchronous and can wait on O(N) bounded subprocess timeouts, not an asynchronous responsiveness guarantee.

Reviewed actual working-tree sources against baseline `1b2fad1` and `docs/media-favorites-plan.md`, not implementation-agent completion claims. Two reproduced MPRIS safety defects block publication. A separate effective-target UX discrepancy remains. This review only writes this document and scratch reproductions; no product/test-source edits, commits, pushes, native input or BLE access.

Review mode: independent agent code/specification review. Jev was not called; no provider installation or external paid review request was made.

## Blocking findings

### R1 — P1: DesktopEntry and captured owner can belong to different applications

Locations: `src/triki_controller/output/mpris_volume.py:114-124`, `:504-513`, `:824-843`.

Favorite resolution reads DesktopEntry through the mutable well-known name, then separately resolves its unique D-Bus owner. A different application can inherit that name between these operations. The later `_exec` owner check only compares against the already incorrectly captured replacement owner; it does not establish that this owner's DesktopEntry matches the favorite.

Inert reproduction: an alias reports `wanted.desktop`, then is replaced by owner `:1.99` with `unrelated.desktop` before GetNameOwner. `apply_transport('next_track')` returns success and records:

```text
[(':1.99', 'unrelated.desktop', 'Next')]
```

This directly contradicts fail-closed routing. Unique-owner writes are necessary but insufficient without tying discovery to that same owner. Resolve the owner first, read identity using that unique destination, and retain/check the same generation through the operation; mutable-alias reads must not qualify a different owner. Add regression coverage for replacement between DesktopEntry and owner lookup, not only replacement immediately before the final write.

### R2 — P1: Favorite restart retains the previous owner's mute restoration state

Locations: `src/triki_controller/output/mpris_volume.py:166-172`, `:510-513`, `:655-704`.

A generation change calls `reset_player()`, which clears baseline translation but not `_muted`, `_saved_volume`, or per-name writable/stream capability caches. After muting the original favorite at 80%, restarting it with the same app identity at 20%, and pressing mute once, the new instance is unmuted/restored to the old instance's 80% instead of being muted:

```text
[(':1.11', 'wanted.desktop', 0.8)]
```

Old mute state also causes `apply_level()` to skip changes while the restarted application is actually unmuted. Invalidate all generation-owned state, including mute restoration and capability conclusions, on disappearance, ambiguity and owner replacement. Do not reuse old-instance restore levels for a fresh owner. Keep selection preference separate from these ephemeral caches.

### R3 — P2: Effective favorite target is still presented as Auto

Locations: `src/triki_controller/gui/control_options.py:_show_selected_player` (around lines 233-245), `src/triki_controller/runtime/emulator.py:470-474`.

With `media_player=None` and an active startup favorite, the menu reads `Automatycznie` and the gesture toggle is enabled, although output capabilities select the favorite token. The final source adds a hint saying the favorite *may* block gestures and asks the user to explicitly choose Auto. That is an improvement over the initial unconditional gesture claim, but it still does not expose the actual current session routing state.

The inert real-Tk reproduction asserts a disabled gesture editor while the effective favorite is pinned; it fails with `menu='Automatycznie', gesture_state='normal'`. This is an explicit UX acceptance oracle, not a claim that disabling is the only valid design: alternatively display an accurate favorite/pending target state and distinguish the stored gesture preference from whether cycling currently works. Do not describe the active target as unqualified Auto when backend selection remains pinned. The parent should reconcile the exact accepted interaction with the UI owner.

## Initially reproduced integration defect, now repaired

Initially, four real-Tk cases failed: explicit reselect of unchanged Auto and unchanged legacy manual player in both device and configurator views retained `startup_media_favorite`. The direct session API already cleared it correctly. Cause: `_choose_player` only emitted a draft, while `ControllerSession.apply_settings` selected only changed values.

During review, the assigned integration owner added `on_player_select` and routed both desktop editors through the explicit session selection API. Revalidation of the four original UI cases plus the direct-session control: **5 passed**. Do not retain the initial failure as an open blocker. `tests/test_explicit_favorite_override_ui.py` also passed in the final combined run.

## Executed evidence

All commands run from `/home/jakub/Desktop/Projekty/Triki-Multicontroller` with:

```bash
PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 DISPLAY=:0 \
/home/jakub/.hermes/cache/scratch/triki-shell-system-venv/bin/python \
/home/jakub/.hermes/cache/scratch/media-review/run_inert.py
```

The launcher replaces real `evdev.UInput`, `bleak.BleakClient` and `bleak.BleakScanner` with hard denials. Reproduction fixtures use real Tk but only TraceOutput/scalar native fakes, temporary settings paths, and patched `askyesno=True`; no connect action is invoked.

### Original focused regression suite

Append:

```bash
-q tests/test_control_runtime.py tests/test_control_transaction_regressions.py \
tests/test_media_selection.py tests/test_windows_audio.py tests/test_macos_output.py \
tests/test_mpris_volume.py tests/test_gui_session.py tests/test_control_options_gui.py \
tests/test_native_media_baseline.py tests/test_native_output_lifecycle.py \
tests/test_native_desktop_packaging.py tests/test_desktop_packaging.py \
-k 'not test_mouse_steering_and_media_roundtrip and not test_uinput_media_routes_volume_to_mpris and not test_uinput_transport_falls_back_when_mpris_rejects'
```

Result: **229 passed, 2 deselected, 32 subtests passed**. An initial invocation omitted the exclusions: the guard correctly blocked two UInput hardware cases (229 passed, two safety-denial failures); these were not product regressions and no real input device was created.

### Final independent reproductions plus integration-owner tests

Append:

```bash
-q /home/jakub/.hermes/cache/scratch/media-review/test_mpris_races.py \
/home/jakub/.hermes/cache/scratch/media-review/repro.py \
tests/test_explicit_favorite_override_ui.py
```

Final result: **3 failed, 22 passed**. Failures are R1, R2 and the stricter R3 UX oracle. Positive controls confirm that a stable matching owner receives a uniquely addressed Next call, absent busctl fails closed without writes, and explicit same-value session/UI overrides now clear startup priority. Full receipt: `/home/jakub/.hermes/cache/scratch/media-review/final-repros.log`.

Scratch files: `run_inert.py`, `repro.py`, `test_mpris_races.py`, and the receipt above. The fake bus models owner/identity replacement deterministically; it does not execute subprocesses or contact D-Bus.

## Code-quality concerns and remaining gates

- Favorite discovery is synchronous in the Tk callback path. `refresh_players()` obtains descriptors for every player; each MPRIS descriptor enumerates every DesktopEntry again and each property lookup has a 1.5-second timeout. This produces quadratic property calls and holds the session lock during subprocess waits. A stalled bus can freeze UI and block the sample worker for substantially longer than one command timeout. Batch immutable catalog observations once, or move bounded discovery off the UI thread while retaining generation validation. This is source-backed analysis, not a measured real-bus timing claim.
- Schema-1 optional parsing, detached descriptor copies and explicit favorite-save plumbing were inspected. Original focused settings/runtime/native lifecycle tests pass, but those passes do not cover the new owner/mute cases above.
- No frozen artifact was built or relocated in this review. The passing packaging unit tests are not proof that busctl/playerctl/pactl are present on a release user's machine. Missing-busctl fail-closed behavior has an inert positive control; external binary dependencies and native Windows/macOS acceptance remain release gates.
- Full parent suite, protected configurator callback normalization, final connected/pending-profile UI coverage and native platform/hardware certification are not claimed complete here. No hash replacement or protected-test edits were made.
- Working-tree files changed concurrently by other owners. MPRIS source blob during the reproduced failures was `af2aab3b21780ac30d6260cd311a56a8cedca3dc`; GUI findings were re-read after the explicit-selection callback appeared and after its policy hint changed. Re-run these receipts after fixes before approving v0.1.3.
