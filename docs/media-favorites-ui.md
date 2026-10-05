# Media favorites and connected desktop navigation

## Interaction contract

- The media editor separates the **current session player** from the **startup favorite**.
- Select a concrete player, then activate the Phosphor star with click, Space, or Enter. `Ulubiony` identifies the selected favorite; `Ustaw ulubiony` identifies an unselected candidate.
- Only the existing explicit **Zapisz** action persists the draft. The adjacent startup description says so. Starring a player does not change `media_player`, reconnect BLE, or arm output.
- `Automatycznie` cannot be starred. An unavailable saved favorite remains named and can be removed with **Usuń ulubiony**. A descriptor error is shown locally without replacing the previous favorite or guessing a stable identity from a Windows PID/display name.
- The session supplies `favorite_media_descriptor(player_id)`; the UI treats its `{platform, app_id, label}` result as observational metadata.

## Connected navigation

The device header offers a labeled **Funkcja** selector for all four existing functions. Switching functions reuses streaming/scanning/connecting BLE and preserves the window geometry. Keyboard focus returns to the selector after its controls rebuild.

**Menu** stops output only after dirty-change confirmation succeeds; it does not disconnect BLE. The menu displays the same connection status variable. Opening the configurator also leaves BLE intact. Relaunching a function on a streaming connection arms stopped output once; an already-running profile transaction is not armed again by the shell. Delayed device-launch callbacks check the current screen and connection intent. Explicit **Rozłącz**, **Zamknij**, and **Zatrzymaj sterowanie** retain their distinct meanings; Stop/Disconnect disable pending autostart intent.

## Desktop presentation

The approved dark shell and Phosphor outline family remain unchanged. UX guidance came from `ui-ux-pro-max` quick-reference accessibility, dark contrast, feedback and navigation sections; its mobile-only safe-area rules were not applied as desktop requirements. The original light configurator, mapping widgets, sliders and preview builders are preserved; the only configurator wiring addition passes the descriptor callback.

The shell uses available width rather than a fixed 640 px container. At 620 × 700, the favorite star, startup hint and persistent Save/action grid are visible. Additional control options remain scrollable. Focus rings, Space/Enter button activation, arrow-key selectors and scroll-to-focus support provide a keyboard path; status and selection use text in addition to color.

## Verification

`tests/test_favorite_ui.py` covers favorite draft changes, keyboard activation/focus, unavailable targets, Auto, error rollback, cross-profile collection and explicit save. `tests/test_device_switch_ui.py` covers dirty cancellation, connected/pending connection reuse, stale launch intent, narrow geometry, retained selector focus and exactly one TraceOutput open per function activation.

These tests use real Tk with TraceOutput/fake BLE and hard-deny `evdev.UInput`. Render screenshots use fixture connection/player values, not a claim of physical BLE or native Windows/macOS validation. The existing shell contrast and official icon-font integrity tests also run.

The legacy configurator byte-preservation guard must normalize only the added `favorite_descriptor=self.session.favorite_media_descriptor,` argument in `_build_config_editor`, just as it already normalizes the player-list callback. Do not replace the protected digests or weaken the guard globally.
