# Changelog

All notable changes to the Gardena Smart System integration for Home Assistant.

## [1.7.1] - 2026-04-04

### Fixed
- **Remaining duration sensor crash on upgrade** — accessing `duration_timestamp` on a `ValveService` from the old `aiogardenasmart==0.1.2` library caused an `AttributeError`, preventing the sensor entity from being created (showed `restored: True` / `unavailable`). Sensor code now uses defensive `getattr()` for backward compatibility.
- **Bumped `aiogardenasmart` to 0.1.3** — ensures HA reinstalls the library with the new `duration_timestamp` field after a HACS update

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
