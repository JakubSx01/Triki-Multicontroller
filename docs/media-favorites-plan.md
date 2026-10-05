# Media favorites, connected function switching and desktop polish

Baseline: `main` / v0.1.2 at `1b2fad1191052b4933a2feca3ca8af4b2822269f`.
Working branch: `feat/media-favorites-profile-switch`.
User authorizes implementation, UI/UX fixes, README reconciliation, push to main and a new release after validation.

## Behavior contract

- One media favorite, represented by a star and a visible text/state explanation. It is a startup preference, distinct from a temporary running-session player override.
- Favorite changes use the existing settings draft and explicit **Zapisz** workflow. The UI must state that saving remembers the preference for the next application start. No hidden save of unrelated dirty settings.
- Optional `GuiSettings.media_favorite` mapping keeps schema 1 backward compatibility. Older settings remain valid; all reconstruction/collect/save paths preserve the new field.
- A fresh session resolves the stored favorite before media output activation; explicit current-session manual/Auto choices override it until restart. Resolve stable application identity, not merely a process PID/creation time or transient MPRIS instance suffix.
- Missing or ambiguous favorites remain visible and fail closed; do not silently pick another player or global transport. Late appearance/restart must resolve without initial volume writes or range loss.
- `ControllerSession.favorite_media_descriptor(player_id)` is observational and supplies the descriptor for the GUI. Invalid or ambiguous identity produces a useful error, not a guessed match.
- Function changes reuse the existing BLE transport, task, connection epoch and stream. Release old held inputs, apply the correct mounting/profile and rearm once. Profile-edit failures remain Off with retryable owned cleanup.
- Navigation back to menu/configuration preserves BLE. Only explicit disconnect/application shutdown closes transport. Dirty-navigation cancellation has no side effects.
- Device UI has an accessible function selector, stable connection status, visible keyboard focus, readable dark contrast and persistent favorite state. Use existing Phosphor icons; no emoji icons. Preserve legacy configurator controls.

## Verification and delivery gates

- TDD core and real-Tk UI tests. Inert output/native adapters; deny real `evdev.UInput` globally and exclude known hardware-writing cases.
- Verify saved-favorite → fresh session, temporarily overridden target, missing/late/restarted favorite, ambiguity, Windows changing PIDs, legacy settings, detached settings copies and no observation writes.
- Verify connected function cycles, menu/device/config transitions, pending-connect races, unchanged BLE identity/connect counts, continued samples, input release, failed cleanup and retry.
- Use ui-ux-pro-max UX searches and inspect rendered desktop screenshots at minimum window sizes; measure contrast and keyboard reachability.
- Run original display suite, independent focused review and regression reproducers. Update Polish README to actual final behavior.
- Commit approved source/tests/docs only, push main, run native GitHub Actions at the exact source SHA, verify all complete bundles and their hashes, smoke-test relocated Linux archive, publish stable v0.1.3 with explicit target and read-back verification.
- Report physical BLE and Windows/macOS target-app acceptance separately; offline tests/builds are not hardware certification.
