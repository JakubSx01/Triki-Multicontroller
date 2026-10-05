# Media favorites / connected switching — final parent verification

## Implemented contract

- Optional schema-1 `media_favorite={platform,app_id,label}`; explicit Save, detached copies and legacy settings compatibility.
- Stable startup preference: Windows executable path, macOS bundle ID, MPRIS DesktopEntry. Missing/ambiguous identities fail closed, retry later, never use guessed labels/PIDs or wrong-player/global substitution.
- Explicit current-session Auto or same manual pin clears startup priority. Favorite draft changes/refresh/collect do not alter current priority, audio baseline or output activation.
- Public observational active-favorite query drives separate current-session and next-start labels; gesture editor reflects effective pin while preserving stored preference.
- Connected device function selector and menu/configuration navigation retain BLE session/task/connection epoch. Old inputs are released, final mount/profile installed offline and output reopened once; failed edits preserve accepted settings and Off/retryable cleanup.
- Favorite MPRIS discovery captures unique owner before reading metadata. Identity, Volume, writes and PipeWire process-tree mapping address that owner. Generation changes invalidate mute restoration/capability caches; no prior-instance volume restoration.
- Batch favorite discovery replaces quadratic UI enumeration: 30-player inert probe records one list,30DesktopEntry reads,60owner checks. Session observation releases its main lock; batches never authorize routing/writes. Tk refresh remains synchronous with O(N) per-command timeout waits.
- UI polish uses ui-ux-pro-max and bundled Phosphor icons: dark surfaces, visible keyboard focus, descriptive star state, responsive function selector/status/action grid, scroll-to-focus and persistent Save.

## Real executed evidence

- Full parent protected display suite: **585 passed,89subtests passed,3hardware-writing cases excluded**,60.73s. UInput denied globally; missing Bleak in this test interpreter means no actual BLE integration. Dirty-close dialogs patched. JUnit `/home/jakub/.hermes/cache/scratch/triki-v013-final.xml`.
- Unchanged independent review reproducers: **11 passed**,5.57s, with hard-denied real UInput/Bleak boundaries. R1/R2/P2 findings closed by the parent; original red report retained in `media-favorites-review.md` with resolution update.
- Parent UI selection after effective-target fixes: **51 passed**. Final full suite includes all eight new modules and original legacy GUI hash protection. Only four precise new callback lines normalized; original builder hashes unchanged.
- One initial full run failed solely because its new fixture modeled mutable aliases but not unique-owner metadata. Updated the fake bus to return DesktopEntry/Volume for uniquely addressed destinations; assertions unchanged. Dedicated safety tests and independent owner-race reproducers remain intact.
- Linux frozen build `tools/build_desktop.py --target linux --smoke`: exit0; archive `packaging/dist/TrikiController-linux-x86_64.tar.gz`. Native CI and relocated artifact receipts verified separately after committing.
- Final rendered minimum-window screenshot inspected: `/home/jakub/.hermes/cache/scratch/triki-v013-effective-favorite-620x700.png`. Effective Spotify priority label/disabledgesture visible; Auto remains the saved selection, not unqualified actual-routing status. Scrollable options intentionally show a subset; persistent Save/function/navigation remain reachable. Status/sample values are explicitly inert fixture values, not physical hardware evidence. Earlier520×600menu screenshot also inspected.
- Actual user settings SHA-256 matches the verified v0.1.2 baseline. No product workflow/configuration files changed, no test user-settings writes. `git diff --check` clean.

## Delivery limitations

Windows/macOS adapter verification is offline. Physical BLE, actual target-app consumption and native Windows/macOS GUI/audio still require acceptance. Windows favorite transport cannot address a particular application and therefore blocks global play/next/previous; per-app volume remains available. macOS ARM64/ad-hoc signing only. Linux favorite discovery needs external busctl plus session D-Bus/DesktopEntry; pip/frozen packaging does not supply these external utilities.
