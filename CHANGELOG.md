# Changelog

All notable changes to the Gardena Smart System integration for Home Assistant.

## [1.12.5] - 2026-04-21

### Fixed
- **WebSocket handshake kill-switch for server-side denials.** Signed WS URLs rejected by the Husqvarna/AWS gateway with HTTP `410`/`403`/`429` at handshake were previously treated like any other transient `ClientError`: the reconnect loop fetched a fresh WS URL from REST (burning rate-limit budget), got rejected again, retried, and so on. A persistent account block produced 91 WS handshake failures and 478 rate-limit warnings in 12 hours (see `base_coordinator.py:594`). After `WS_HANDSHAKE_DENIAL_THRESHOLD` consecutive 4xx handshake rejections the WS subsystem is now suspended for `WS_KILL_SWITCH_COOLDOWN` (1 h); REST polling continues. A loud log line points the user at rotating the Developer Portal application. The counter only clears when a real device update confirms the stream is healthy — `ws_connect()` returning synchronously is not enough, because the listen task may fail milliseconds later.
- **`_rate_limit_hits` no longer resets on the first successful poll.** A single 200 response after a 60-min cooldown is not proof the API has recovered. The counter now clears only after `RATE_LIMIT_RESET_SUCCESS_THRESHOLD` consecutive successes; a fresh 429 zeros progress toward that threshold. Eliminates the saw-tooth `#1 → #2 → … → #6 → reset → #1` pattern in the logs during persistent-block scenarios.
- **Repair notification no longer fires on transient WS drops (issue #17).** Every `_on_ws_error` call used to create a HA repair issue, so a single brief disconnect (auto-reconnected in seconds) surfaced a visible WARNING in the UI that then disappeared on its own, while a genuine outage left it pinned for hours — matching matthias1403's exact symptoms. The issue is now only created once `_ws_consecutive_failures` reaches `WS_REPAIR_ISSUE_THRESHOLD` (3, aligned with the first `_WS_COOLDOWN_SCHEDULE` step) or the handshake kill-switch is active. Successful reconnects still clear the issue as before.

### Added
- `WS_HANDSHAKE_DENIAL_THRESHOLD`, `WS_KILL_SWITCH_COOLDOWN`, `WS_HANDSHAKE_DENIAL_STATUSES`, `RATE_LIMIT_RESET_SUCCESS_THRESHOLD`, `WS_REPAIR_ISSUE_THRESHOLD` constants in `const.py`.

## [1.12.4] - 2026-04-20

### Fixed
- **Availability transition baseline now seeded in `async_added_to_hass`.** The v1.12.2 move of transition logging from the `available` property into `_handle_coordinator_update` left `_was_available` as `None` through the initial state write (which no longer has a side effect). The first real offline/online transition then matched the "initial check" early-return and was silently swallowed. Both `GardenaEntity` and `AutomowerEntity` now prime `_was_available = self.available` in `async_added_to_hass`.

## [1.12.3] - 2026-04-20

### Fixed
- **Restored fast-path skip in `_async_start_websocket`.** v1.12.2 removed the `.locked()` pre-check, which changed the behavior of a concurrent second caller from "skip immediately" to "queue on the lock". The existing `test_concurrent_ws_connect_skipped` test deadlocked under the new semantics (the test held `connect_release` until after the second call, which now blocked on the lock instead of early-returning). Both the `.locked()` pre-check **and** the `self._ws_connected` double-check under the lock are now in place — TOCTOU-safe and preserves the original skip semantics.

## [1.12.2] - 2026-04-19

### Changed
- **`available` property is now side-effect free.** Device online/offline transitions were logged inside the property, which Home Assistant reads every time a UI client reads an entity attribute — so the log message and internal state mutation fired far more often than the actual transition. The transition-logging moved to `_handle_coordinator_update`, which runs exactly once per coordinator update. Applies to both `GardenaEntity` and `AutomowerEntity`.
- **`# type: ignore[unreachable]` guards removed across 17 files.** The pattern `if coordinator.data is None: return  # type: ignore[unreachable]` lied to mypy — `DataUpdateCoordinator.data` is genuinely `None` during `async_config_entry_first_refresh`. Replaced with the equivalent truthy check `if not coordinator.data: return` (and the `_device` property uses `(self.coordinator.data or {}).get(…)`), which mypy understands without any ignores.
- **MQTT command-handler tasks now carry a name.** Inbound MQTT commands dispatched as `hass.async_create_task(…)` now include `name=f"gardena_mqtt_command_{device_id}"` for easier tracing.
- **WebSocket-connect lock cleaned up.** The `.locked()` pre-check (TOCTOU-prone) was replaced with an unconditional acquire plus a `self._ws_connected` double-check under the lock. Strictly race-free; behaviour identical.
- **Config-flow error tuple precomputed.** `_GARDENA_ERROR_TYPES = tuple(_GARDENA_ERROR_MAP)` at module level replaces three per-call `tuple(_GARDENA_ERROR_MAP)` rebuilds.

## [1.12.1] - 2026-04-19

### Security
- **Reauth and reconfigure now revoke the access token before returning.** `async_step_user` already revoked its OAuth token on completion (v1.10+), but `async_step_reauth_confirm` and `async_step_reconfigure` went through `_async_test_gardena` / `_async_test_automower` without the same cleanup. Every failed or successful re-credential test left a live access token on the Husqvarna auth server until it expired naturally. Both helpers now wrap the test in `try: … finally: await auth.async_revoke_token()`.

### Fixed
- **MQTT bridge retries on startup failure.** When Home Assistant loads the MQTT integration *after* Gardena (common on cold boot), the first `_async_start_mqtt_bridge` call failed and the bridge stayed disabled until HA was restarted. The coordinator now retries at most once every 5 minutes on subsequent polls.
- **`_mqtt_bridge` sentinel typed correctly.** The three-valued `None | False | MqttBridge` pattern (typed as `Any`) is gone. `_mqtt_bridge: MqttBridge | None = None`, with a separate `_mqtt_bridge_next_check: float` throttle for the retry interval. Removes the `hasattr(self._mqtt_bridge, "async_stop")` type-dodge in `async_shutdown`.

### Changed
- MQTT publish background tasks now have descriptive names (`<domain>_mqtt_publish_all`, `<domain>_mqtt_publish_device`) for easier debug/profiling.

## [1.12.0] - 2026-04-19

### Changed
- **Exception handling narrowed.** Several `except Exception` catchalls in critical paths were replaced with precise type tuples:
  - `base_coordinator._async_start_websocket_locked`, `_async_stop_stale_websocket`, and `async_shutdown` now only catch `(aiohttp.ClientError, TimeoutError, OSError)` around WS connect, disconnect, and token-revoke — unexpected library bugs surface as real errors instead of being silently swallowed.
  - `mqtt_bridge.async_publish_device_state` and `async_publish_availability` catch `HomeAssistantError` only — retained topics heal on the next publish anyway.
  - `coordinator._async_handle_mqtt_command` uses the narrow throttle exception (`HomeAssistantError`) and domain exception (`GardenaException`); other errors now propagate and are visible in logs.
  - `config_flow.async_step_user` + `_async_test_gardena` + `_async_test_automower` now catch the domain error types explicitly via a lookup table; all other exceptions still fall through to the `"unknown"` error key but are logged with full traceback at `exception` level instead of being hidden.
- **ConfigFlow error mapping extracted.** The six-branch `if/elif` ladder that mapped `GardenaAuthenticationError`, `GardenaForbiddenError`, `GardenaRateLimitError`, `GardenaConnectionError` to translation keys was duplicated twice (user step + Gardena-credentials test) and a third variant sat in the Automower test. All three now read from a single `dict[type[Exception], str]` (`_GARDENA_ERROR_MAP` at module level; the Automower map is local to the lazy-imported method). Adding a new mapped exception is a one-line change per map.

### aiogardenasmart library (0.1.8 → 0.1.9)
- **`GardenaClient` caches static request headers.** `Authorization-Provider`, `X-Api-Key`, `Accept`, and `Content-Type` never change across the life of a client; they are now built once in `__init__` and only the per-request `Authorization` token is rebuilt. Eliminates redundant dict construction on every REST call.
- **`_parse_devices` uses `setdefault`.** Six `if base_device_id not in devices: devices[base_device_id] = Device(...)` patterns collapsed into a single `devices.setdefault(...)`.
- **`GardenaWebSocket._apply_service_update` rewritten as a dispatch table.** The five-branch `if/elif` cascade for singleton services (common, mower, valve_set, sensor, power_socket) now reads from `_SINGLETON_SERVICES: dict[ServiceType, tuple[attr_name, service_cls]]`. Valves remain a special case because they live in a dict keyed by service ID. Adding a new singleton service is a one-line change.
- **Two pre-existing mypy warnings cleared.** `models._attr_timestamp` now returns a properly typed `str | None` and the stale `# type: ignore[unreachable]` on the locked fast-path in `auth.py` is removed.

### Developer Notes
- Pure refactor + error-handling-hygiene release. All **591 integration tests** and **104 library tests** still pass. No UI-visible behaviour change — but unexpected failures will now surface as real errors instead of being silently swallowed.

## [1.11.0] - 2026-04-19

### Changed
- **Command path unified in the entity base classes.** `valve.py`, `switch.py`, `lawn_mower.py`, `automower_button.py`, `automower_switch.py`, `automower_select.py`, `automower_number.py`, and `automower_lawn_mower.py` previously each duplicated the same throttle → budget-increment → try/except-auth/exception → raise-translated-error boilerplate around every API call — ~25 lines per call site, ten call sites. The shared pattern now lives in `GardenaEntity._async_execute_command` (Gardena side) and `AutomowerEntity._async_execute_command` (Automower side), with per-platform exception mapping. Call sites now read as a single line: `await self._async_execute_command(client_method, *args, **kwargs)`. Net change: **~180 lines of duplication removed**. Behaviour is unchanged — the pessimistic budget-increment-before-await guarantee from v1.10.4 is preserved.
- **MQTT command handler rewritten as a dispatch table.** `GardenaCoordinator._async_handle_mqtt_command` used a six-branch `if/elif` cascade with near-identical `await self._client.async_send_command(…)` calls. Replaced with `_MQTT_DISPATCH: dict[str, tuple[control_type, command, needs_duration]]` and a single dispatch call — adding a new MQTT action is now a single-line change. The redundant `_MQTT_ACTIONS` set is removed (membership is now `in self._MQTT_DISPATCH`).
- `automower_lawn_mower.py` command handler also gets the same treatment: the five-branch `if/elif` inside the try/except is replaced with `_COMMAND_METHODS: dict[str, str]` and a `getattr` lookup against the client.

### Developer Notes
- Pure refactor release. No functional or UI-visible change; all existing tests pass unchanged as the behavioural contract (throttle first, count second, dispatch third, on-success state update) is identical to v1.10.4.

## [1.10.4] - 2026-04-19

### Fixed
- **API budget counter drifted below real usage under failure load.** `api_budget.increment()` used to run only after a successful API call, so polls that raised `GardenaConnectionError`, `GardenaRateLimitError`, or server-side 5xx were never counted locally — yet Husqvarna counts every attempt against the monthly quota. With the counter under-reporting, the 5 %-auto-stop safety net introduced in 1.10.2 would trigger too late (or never) during a failure storm. Increment now happens **before** the outbound call in all call sites: REST polls (`base_coordinator._async_update_data`), WebSocket URL fetches (`_async_start_websocket`), MQTT inbound commands (`coordinator._async_handle_mqtt_command`), entity commands (valve, switch, lawn_mower, automower_switch, automower_select, automower_button, automower_number, automower_lawn_mower). Pessimistic accounting matches server-side reality and makes auto-stop protective rather than decorative.
- **Double token refresh under concurrent load.** `GardenaAuth.async_ensure_valid_token` had no mutex, so a simultaneous REST call and WebSocket connect (or watchdog reconnect + poll cycle) could both observe `is_token_valid == False`, fire two parallel POSTs to the auth endpoint, consume two quota units, and leave the old refresh_token invalidated by Husqvarna's server. Added an `asyncio.Lock` with double-checked locking: the fast path still returns the cached token without acquiring the lock, and the slow path serializes refreshes so only one HTTP round-trip happens per expiry cycle.
- **Secrets leaked to debug logs.** `GardenaClient._async_request` logged the full request body at DEBUG level and on 4xx warnings, which exposed JSON command payloads (service IDs, schedule data) in `home-assistant.log` whenever users enabled debug logging — a common request in GitHub issue triage. Replaced with body-size-only logs; credentials (`client_secret`, `refresh_token`, `access_token`) continue to be redacted in diagnostics via `async_redact_data`.

### Added
- **Auto-stop now also gates WebSocket connects.** When the monthly budget is exhausted, `_async_start_websocket` now returns immediately before fetching a fresh WS URL. Previously the REST-poll gate (added in 1.10.2) was the only checkpoint, leaving `_async_get_ws_url` as a quota leak path during exhaustion.
- 4 new tests: `test_poll_increments_budget_even_on_connection_error`, `test_poll_increments_budget_on_rate_limit`, `test_start_websocket_aborts_when_exhausted` (all `tests/components/gardena_smart_system/test_coordinator.py`), and `test_parallel_callers_share_single_refresh` (`aiogardenasmart/tests/test_auth.py`). Total **725 tests** passing.

## [1.10.3] - 2026-04-19

### Changed
- **Power socket switch now renders as a single toggle instead of two separate on/off buttons.** The switch entity previously declared `assumed_state = True` because it waited for a confirming WebSocket event from the Gardena cloud before updating its local state — during that window the state was considered "assumed", so Home Assistant rendered two separate buttons (the only UI that can represent an assumed state unambiguously). The switch now applies an **optimistic local state update** immediately after the API call succeeds: `START_SECONDS_TO_OVERRIDE` flips `activity` to `TIME_LIMITED_ON` (with updated `duration` / `duration_timestamp`) and `STOP_UNTIL_NEXT_TASK` flips it to `OFF`. The subsequent WebSocket event simply reconfirms the state. With the state now trustworthy immediately, `assumed_state` has been removed and HA renders a normal toggle. Mirrors the valve optimistic-update fix shipped in 1.9.1.
- 4 new switch tests: `assumed_state` flag is absent, `turn_on` / `turn_off` / `turn_on_for` flip the HA state and the underlying device activity immediately.

## [1.10.2] - 2026-04-18

### Added
- **Auto-stop safety net when the monthly API budget is nearly exhausted** — once the remaining budget drops below **5 %** (i.e. fewer than 500 of the 10 000 monthly requests remain), the coordinator automatically pauses all outbound API activity: REST polls raise `UpdateFailed`, WebSocket (re)connect attempts are suppressed, and user-issued commands are rejected with the new translated error `api_budget_exhausted`. Normal operation resumes automatically when the calendar month rolls over — or the user can create a fresh Husqvarna application to reset the budget. This prevents runaway scenarios (e.g. an unforeseen reconnect storm or library bug) from exhausting the budget 100 % and forcing Husqvarna to hard-block the key for the rest of the month.
- 6 new coordinator tests: `is_exhausted` true/false around the threshold, reset on month rollover, `_async_update_data` raises `UpdateFailed` when exhausted, `check_command_throttle` raises `HomeAssistantError` with the `api_budget_exhausted` translation key, and confirmation that throttle still works below the threshold.
- New exception translation key `api_budget_exhausted` in `strings.json`, `translations/en.json`, and `translations/de.json` (other languages fall back to English until translated).

## [1.10.1] - 2026-04-12

### Fixed
- **WebSocket reconnect storm burning through the API rate-limit budget** — when Husqvarna's WebSocket endpoint started rejecting signed connection URLs with HTTP 410 (URL consumed/expired), the library's inner reconnect loop retried the *same dead URL* up to 5 times with exponential backoff (30s → 60s → 120s → 240s → 480s). Each outer reconnect attempt then fetched a fresh WS URL via REST, and every poll cycle also tried to start the WebSocket again. Result: hundreds of wasted REST calls per day, repeated HTTP 429 rate limiting, and the integration entering 1-hour backoff windows.
  - **Library fix** — `aiogardenasmart` and `aioautomower` WebSocket clients no longer retry inside `_async_listen_loop`. Any failure is escalated to the caller's `on_error` callback immediately. WebSocket URLs are single-use; retrying the same URL is pointless and amplifies failures.
  - **Circuit breaker in the coordinator** — after 3 consecutive WebSocket start failures, the integration enters a 15-minute cooldown during which no new connection attempts are made (REST polling continues). After 5 failures the cooldown grows to 30 min, after 7+ to 60 min. A successful connection resets the counter. The cooldown guards both the reconnect loop and the regular poll cycle, so the poll cycle no longer triggers new WS attempts during the cooldown. Auth errors bypass the cooldown and trigger reauth instead.
  - **Reconnect schedule tightened** — outer reconnect loop reduced from 6 attempts over ~50 min (30/60/120/300/600/1800 s) to 3 attempts over ~20 min (60/300/900 s). The circuit breaker handles longer outages.
  - 6 new coordinator tests covering failure counter increment, cooldown activation at thresholds, escalation, guard in `_async_start_websocket`, reconnect loop abort when cooldown is active, and counter reset on successful connection.

## [1.10.0] - 2026-04-11

### Added
- **API budget tracking** — two new hub diagnostic sensors: **API requests this month** (total count with `month` and `budget` attributes) and **API budget remaining** (percentage). Every API request — polls, WebSocket URL fetches, and device commands — is counted and persisted across restarts using `Store.async_delay_save`. The counter resets automatically at the start of each calendar month. Budget assumes 10,000 requests/month per API (the standard Husqvarna limit when the key is used exclusively for Home Assistant).
- Sensor translations for `hub_api_requests_month` and `hub_api_budget_remaining` in all **31 languages**.
- Icons: `mdi:counter` for API requests, `mdi:chart-donut` for budget remaining.
- 12 new tests for `ApiBudgetTracker` (572 tests total): initial state, increment, remaining percent, floor at zero, month property, month rollover reset, persistence across load, stale data reset, budget property, coordinator integration, poll increment.

## [1.9.1] - 2026-04-11

### Fixed
- **Valve UI stayed "closed" after a successful open command** — the integration waited for the WebSocket event to update the valve state, but that event can arrive with a noticeable delay or, rarely, be lost entirely if the WebSocket was silently dropped. Valve commands now apply an **optimistic local state update** immediately after the API call succeeds: `START_SECONDS_TO_OVERRIDE` flips `activity` to `MANUAL_WATERING` (with updated remaining-duration timestamp) and `STOP_UNTIL_NEXT_TASK` flips it to `CLOSED`. The subsequent WebSocket event simply reconfirms the state. This also means the 2-valve concurrent-open preflight check correctly sees the freshly-opened sibling valve when the next command is issued.
- **Command throttle too strict** — the previous throttle rejected any command sent within 5 seconds of the previous one, so opening two irrigation valves back-to-back from the UI immediately surfaced as "commands are being sent too quickly". Replaced with a **token-bucket** model: the bucket holds **10 tokens** and refills at 1 token every `MIN_COMMAND_INTERVAL_SECONDS` (= 5 s). Users can fire up to 10 commands in a burst (e.g. opening several valves, running a short automation sequence) before the throttle kicks in, while the long-term steady-state rate is still capped at one command per 5 seconds — so the monthly API quota remains protected.

## [1.9.0] - 2026-04-11

### Added
- **Preflight check for Smart Irrigation Control** — Smart Irrigation Control devices allow at most **2 valves open simultaneously** per controller. Opening a third valve is now rejected locally before the API call with a translated error (`too_many_open_valves`), so the user gets an immediate, actionable message instead of a generic "command failed". The check only applies to multi-zone irrigation controllers (devices with a `VALVE_SET` service); standalone Smart Water Control devices are not subject to the limit. A valve that is already open is not counted against itself, so re-opening an active valve remains allowed.
- New translation key `too_many_open_valves` shipped in **all 31 supported languages**.
- **5 new valve tests** (556 tests total) covering: third valve refused, `start_watering` service also refused, re-opening an already open valve, second valve allowed, standalone Water Control unaffected.

### Changed
- `manifest.json` now declares `"quality_scale": "platinum"` — the integration has met the Platinum tier requirements since 1.7.x; this makes the declaration explicit in the manifest so Home Assistant surfaces the badge natively.

## [1.7.8] - 2026-04-05

### Added
- **Contract tests** (5 new tests, 526 total) — catch float-vs-integer regressions at three layers:
  - `aiogardenasmart`: verifies float params are coerced to `int` in the serialized body bytes, `data.id` == service_id, Content-Type header has no charset suffix
  - `test_valve.py` / `test_switch.py`: float option values produce integer `seconds`

### Fixed
- **Defensive float coercion** in `aiogardenasmart.async_send_command` — numeric params are now explicitly cast to `int` before serialization, regardless of call site
- Bumped `aiogardenasmart` to 0.1.8

## [1.7.7] - 2026-04-05

### Fixed
- **HTTP 400 "No schema matches" on valve open and power socket turn-on** — `config_entry.options.get()` returns numeric values as `float` in Home Assistant. The Gardena API schema strictly requires integers: `3600` is accepted, `3600.0` is rejected. Added `int()` cast when reading `default_watering_minutes` (valve) and `default_socket_minutes` (power socket) from options.

## [1.7.6] - 2026-04-05

### Added
- **Warning-level diagnostic logging** — when the Gardena API returns HTTP 400, the exact request body bytes and full response are logged at `WARNING` level (visible without enabling debug mode). Used to diagnose the float/integer issue.
- Bumped `aiogardenasmart` to 0.1.7

## [1.7.5] - 2026-04-05

### Fixed
- **HTTP 400 on commands (attempt 2)** — switched from `data=str` to `data=bytes` in the aiohttp request to prevent aiohttp from appending `; charset=utf-8` to the `Content-Type: application/vnd.api+json` header
- Bumped `aiogardenasmart` to 0.1.6

## [1.7.4] - 2026-04-05

### Fixed
- **HTTP 400 on commands (attempt 1)** — changed `data.id` in command payloads from a random UUID to the actual `service_id`. The Gardena API v2 requires `data.id` to match the service being controlled.
- Bumped `aiogardenasmart` to 0.1.5

## [1.7.3] - 2026-04-05

### Fixed
- **Translation formatting errors** (`MISSING_VALUE` from formatjs) — `data_description` strings for `mqtt_topic_prefix` and `mqtt_subscribe_commands` used `{device_id}` and `{prefix}` as example text. The HA frontend's ICU message format interpreted these as template variables. Replaced with `<device_id>` and `<prefix>` across all 31 translation files.

## [1.7.2] - 2026-04-04

### Fixed
- **Command sending (HTTP 400)** — aiohttp's `json=` parameter silently overrode our `Content-Type: application/vnd.api+json` header with `application/json`, causing the Gardena API to reject commands with "No schema matches". Now uses `data=json.dumps()` with explicit headers, matching the [py-smart-gardena](https://github.com/py-smart-gardena/py-smart-gardena) reference implementation.
- Bumped `aiogardenasmart` to 0.1.4

## [1.7.1] - 2026-04-04

### Fixed
- **Remaining duration sensor crash on upgrade** — accessing `duration_timestamp` on a `ValveService` from the old `aiogardenasmart==0.1.2` library caused an `AttributeError`, preventing the sensor entity from being created (showed `restored: True` / `unavailable`). Sensor code now uses defensive `getattr()` for backward compatibility.
- **CI version sync check** — new CI job ensures `aiogardenasmart` version in `pyproject.toml` matches `manifest.json` requirements

## [1.7.0] - 2026-04-04

### Fixed
- **Remaining duration survives restart** — valve and power socket countdown sensors now use the API-provided `duration_timestamp` to compute the correct end time (`timestamp + duration`) instead of `now + duration`. Previously, a HA restart or integration reload would reset the countdown as if watering had just started.

### Added
- **WebSocket watchdog** — a periodic health check (every 60s) detects silently-dead WebSocket connections. If no message is received for 5 minutes, the connection is forcibly closed and a reconnect + immediate data refresh is triggered. This prevents the integration from appearing "frozen" when the WS dies without triggering an error.
- `duration_timestamp` field on `ValveService` and `PowerSocketService` in the `aiogardenasmart` client library
- `last_message_time` property on `GardenaWebSocket` for watchdog monitoring
- 4 new WebSocket watchdog tests (524 tests total)

## [1.6.0] - 2026-04-03

### Added
- **MQTT state bridge** — optionally mirrors all Gardena device states to a local MQTT broker in real time
  - Enable via Options Flow (Settings → Devices & Services → Gardena → Configure)
  - Configurable topic prefix (default: `gardena`)
  - Publishes full device state as JSON on every WebSocket push and poll update
  - Publishes device availability (`online`/`offline`) with retain flag
  - Accepts inbound commands via MQTT (`start_watering`, `stop_watering`, `turn_on`, `turn_off`, `park`, `resume`)
  - Requires the Home Assistant MQTT integration to be configured (soft dependency)
- 18 new tests for MQTT bridge (520 tests total)

## [1.5.12] - 2026-04-03

### Changed
- **No more trailing space** in single-valve entity names — translation strings now use `"Name{zone}"` with the space moved into the placeholder value (` Rasen vorne` for multi-valve, `""` for single-valve)
- **DRY refactoring:** Zone name resolution extracted into shared `resolve_zone_placeholder()` helper in `entity.py` — replaces 4 identical code blocks across `sensor.py` and `gardena_event.py`

### Added
- 2 new tests: valve event no-duplicate on duration change, single-valve event placeholder (502 tests total)

### Updated
- All 31 translation files + `strings.json` updated to remove space before `{zone}` placeholder

## [1.5.11] - 2026-04-02

### Fixed
- **Single-valve devices** (Smart Water Control) no longer show literal `{zone}` in entity names — translation placeholders are now always set
- **Duration change while watering** — sending a new `START_SECONDS_TO_OVERRIDE` command while a valve or power socket is active now correctly updates the countdown end time

### Added
- 8 new tests for duration-change detection, power socket state tracking, and single-valve placeholder handling (500 tests total)

## [1.5.10] - 2026-04-02

### Fixed
- **Remaining duration countdown now shows correct end time** — the Gardena API sends the initial set duration (not remaining), so the end time is now computed once when the valve/socket opens and kept stable until it closes

## [1.5.9] - 2026-04-02

### Fixed
- WebSocket now **auto-reconnects** with exponential backoff (30s → 1m → 2m → 5m → 10m → 30m) when the connection drops — no manual restart or repair action needed

## [1.5.8] - 2026-04-01

### Changed
- **Breaking:** Remaining duration sensors (valve and power socket) now use `SensorDeviceClass.TIMESTAMP` instead of `DURATION` — the HA frontend displays a **live countdown** that ticks down in real time between API updates

## [1.5.7] - 2026-04-01

### Changed
- Valve entities now show a **single toggle** instead of two separate open/close buttons — the actual valve state is known via WebSocket, so `assumed_state` is no longer needed

## [1.5.6] - 2026-04-01

### Changed
- Remaining duration sensors (valve and power socket) now show **0** instead of "Unknown" when the device is inactive — clearer state for dashboards and automations

## [1.5.5] - 2026-03-31

### Changed
- **Breaking:** Gardena mower sensors renamed for consistency: "Mower activity" → "Activity", "Mower state" → "State", "Mower error" → "Error" (entity IDs change accordingly)

### Removed
- **Breaking:** Power socket switch no longer exposes `activity` and `duration` as state attributes — use the dedicated `power_socket_state` and `power_socket_remaining_duration` sensor entities instead
- **Breaking:** Automower lawn mower no longer exposes `activity`, `state`, `mode`, `error_code`, `restricted_reason`, and `override_action` as state attributes — use the dedicated sensor entities instead

## [1.5.4] - 2026-03-30

### Improved
- Complete `strings.json` — added all missing translation keys (valve sensors, power socket error, hub sensors, event entities with event_type translations)
- Icons for 16 previously icon-less entities (valve state, battery state, hub sensors, all event entities, and more)

### Changed
- Valve error binary sensor is now **enabled by default** (safety-relevant signal)

## [1.5.3] - 2026-03-30

### Improved
- Per-valve sensors and events now display the actual valve name from the Gardena API (e.g. "Remaining watering time Rasen vorne") instead of generic "Zone 1" labels
- Falls back to "Zone X" when no API name is available
- Updated all 31 translation files to remove redundant localized "zone" word

## [1.5.2] - 2026-03-29

### Fixed
- Per-zone valve sensors now include zone number in entity names ([#9](https://github.com/kayloehmann/ha-gardena-smart-system/issues/9))
- Remaining duration sensors reset to unavailable when device is off/closed ([#10](https://github.com/kayloehmann/ha-gardena-smart-system/issues/10))
- Bumped CI actions to Node.js 24 compatible versions
- Fixed ruff format and mypy strict across all source files

## [1.5.1] - 2026-03-29

### Fixed
- Guard `async_revoke_token` in coordinator shutdown to prevent crash if token is already expired

## [1.5.0] - 2026-03-29

### Added
- Event entities for Gardena devices (mower, valve, power socket state transitions)
- Graduated rate-limit backoff: 5 min → 10 → 20 → 40 → 60 min (replaces rigid 1h cooldown)

### Changed
- Typed `GardenaConfigEntry` with generic coordinator parameter
- Hub entity constructors typed with `BaseSmartSystemCoordinator`
- Removed `extra_state_attributes` from Gardena lawn mower and valve entities (replaced by dedicated sensor entities)

## [1.4.0] - 2026-03-29

### Added
- Shared `BaseSmartSystemCoordinator` base class extracted from both coordinators (~200 lines of duplicated logic unified)
- 5 new sensors: mower state, power socket state, valve state (per zone), valve set error code, Automower operating mode

### Changed
- `GardenaCoordinator` reduced from 294 to ~80 lines
- `AutomowerCoordinator` reduced from 265 to ~70 lines
- Public properties replace private attribute access (`ws_connected`, `last_command_time`, `stale_miss_counts`)

## [1.3.1] - 2026-03-28

### Fixed
- Coordinator crash when data is None on first update
- Translation diacritics in Czech, Slovak, and other languages
- Added 27 coverage tests for edge cases

## [1.3.0] - 2026-03-28

### Added
- 22 new translations for full European + Asian coverage (30 languages total)
- Security hardening from STRIDE threat model audit (WebSocket error isolation, log truncation, OAuth token revocation)
- 6 new features including battery state enum sensor, power socket remaining duration, and more

## [1.2.0] - 2026-03-27

### Added
- Hub dashboard entities: device count and polling interval sensors per config entry
- Virtual "hub" device in the device registry for integration-level diagnostics

## [1.1.0] - 2026-03-27

### Added
- Automower schedule override number entity
- Automower work area switches and cutting height per work area
- Automower confirm error button
- Translations for all 7 initially supported languages

## [1.0.0] - 2026-03-26

### Added
- Automower event entities for state transition tracking
- 99% test coverage (422 tests)
- 5 new features completing the Automower platform

### Changed
- First stable release

## [0.9.0] - 2026-03-26

### Added
- Automower event entities for mower state transitions (started_mowing, stopped, charging, parked, error, etc.)

## [0.8.0] - 2026-03-26

### Improved
- Maximized test coverage to 99% (367 tests, 2 unreachable lines remaining)

## [0.7.0] - 2026-03-25

### Added
- Comprehensive test coverage for repair flow, init, and entity guards
- Translations for fr, nl, sv, it, es, da, pl + German

## [0.6.0] - 2026-03-24

### Added
- 7 language translations (French, Dutch, Swedish, Italian, Spanish, Danish, Polish)
- German translation

## [0.5.0] - 2026-03-22

### Added
- Automower GPS device tracker (disabled by default for privacy)
- Automower mowing schedule calendar (read-only)
- Automower headlight mode select control
- Automower cutting height number control
- Automower stay-out zone switches

## [0.4.0] - 2026-03-22

### Added
- Platinum quality scale compliance (strict typing, diagnostics, repair flows)
- Gold quality scale features (stale device cleanup, reconfiguration flow)

## [0.3.0] - 2026-03-22

### Added
- Improved UX with entity categories, device classes, and proper defaults
- Additional sensors for Gardena devices
- Entity hardening with availability checks

## [0.2.0] - 2026-03-21

### Added
- **Automower Connect API** support — full-featured Husqvarna Automower integration
- Lawn mower, sensor, binary sensor, and switch platforms for Automower
- Dual-API architecture (Gardena + Automower through single integration)

## [0.1.0] - 2026-03-18

### Added
- Initial release
- Gardena Smart System API support (sensors, valves, power sockets, SILENO mowers)
- OAuth2 authentication via Husqvarna Developer Portal
- Real-time WebSocket updates with polling fallback
- Adaptive polling, command throttling, and rate limit handling
- Config flow with multi-location support

[1.7.1]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.7.1
[1.7.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.7.0
[1.6.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.6.0
[1.5.12]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.12
[1.5.11]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.11
[1.5.10]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.10
[1.5.9]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.9
[1.5.8]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.8
[1.5.7]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.7
[1.5.6]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.6
[1.5.5]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.5
[1.5.4]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.4
[1.5.3]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.3
[1.5.2]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.2
[1.5.1]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.1
[1.5.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.5.0
[1.4.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.4.0
[1.3.1]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.3.1
[1.3.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.3.0
[1.2.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.2.0
[1.1.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.1.0
[1.0.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v1.0.0
[0.9.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v0.9.0
[0.8.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v0.8.0
[0.7.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v0.7.0
[0.6.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v0.6.0
[0.5.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v0.5.0
[0.4.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v0.4.0
[0.3.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v0.3.0
[0.2.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v0.2.0
[0.1.0]: https://github.com/kayloehmann/ha-gardena-smart-system/releases/tag/v0.1.0
