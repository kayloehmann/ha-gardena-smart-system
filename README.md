# Gardena Smart System for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/kayloehmann/ha-gardena-smart-system)](https://github.com/kayloehmann/ha-gardena-smart-system/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-blue)](https://www.home-assistant.io/)
[![License](https://img.shields.io/github/license/kayloehmann/ha-gardena-smart-system)](https://github.com/kayloehmann/ha-gardena-smart-system/blob/main/LICENSE)
[![Quality Scale](https://img.shields.io/badge/Quality%20Scale-Platinum-blueviolet)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
[![mypy](https://img.shields.io/badge/type%20checked-mypy%20strict-blue)](https://mypy-lang.org/)
[![Test Coverage](https://img.shields.io/badge/coverage-99%25-brightgreen)](https://github.com/kayloehmann/ha-gardena-smart-system)

A Home Assistant custom integration for **Husqvarna smart garden devices** — supporting both the **Gardena Smart System API** and the **Automower Connect API** through a single integration. Device states are updated in real time via cloud WebSocket connections, with automatic fallback to polling if the connection is interrupted.

## Supported Devices

### Gardena Smart System API

| Device | Platform(s) | Description |
|--------|-------------|-------------|
| **Smart Sensor** | `sensor` | Soil moisture, soil temperature, ambient temperature, light intensity |
| **Smart Water Control** | `valve`, `sensor`, `binary_sensor` | Single-valve irrigation controller with open/close and timed watering |
| **Smart Irrigation Control** | `valve`, `sensor`, `binary_sensor` | Multi-zone irrigation controller (up to 6 valves) |
| **Smart Power Adapter** | `switch`, `sensor`, `binary_sensor` | Smart power outlet with on/off and timed control |
| **SILENO Mower** | `lawn_mower`, `sensor`, `binary_sensor` | Robotic lawn mower with start, dock, pause, and schedule override |

All Gardena devices also expose common diagnostic sensors (battery level, RF signal strength) when the device reports them.

### Automower Connect API

| Device | Platform(s) | Description |
|--------|-------------|-------------|
| **Husqvarna Automower** | `lawn_mower`, `sensor`, `binary_sensor`, `switch`, `number`, `device_tracker`, `calendar`, `event` | Full-featured robotic mower with GPS tracking, mowing schedules, work areas, stay-out zones, headlight control, cutting height adjustment, and state-transition events |

> **Note:** SILENO mowers are supported through the Gardena Smart System API (above), not through the Automower Connect API. The Automower API is for Husqvarna Automower models (e.g., 305, 315, 405X, 435X AWD, 450X, NERA). Automowers do **not** require a Gardena Smart Gateway — they connect directly to the Husqvarna cloud.

## Prerequisites

Before installing this integration, you need to create an application on the Husqvarna Developer Portal to obtain API credentials.

1. Go to the [Husqvarna Developer Portal](https://developer.husqvarnagroup.cloud) and create an account (or sign in with your existing Husqvarna account).
2. Navigate to **My Applications** and click **Create Application**.
3. Give it a name (e.g. "Home Assistant") and set the redirect URI to `https://localhost`.
4. Under **Connected APIs**, enable the APIs you want to use:
   - **Gardena Smart System API** — for Gardena sensors, valves, power sockets, and SILENO mowers
   - **Automower Connect API** — for Husqvarna Automower robotic mowers
   - You can enable both on the same application.
5. Note the **Application Key** (Client ID) and **Application Secret** — you will need both during setup in Home Assistant.

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant UI.
2. Go to **Integrations** and click the three-dot menu in the top right corner.
3. Select **Custom repositories**.
4. Enter `https://github.com/kayloehmann/ha-gardena-smart-system` as the repository URL and select **Integration** as the category.
5. Click **Add**, then find "Gardena Smart System" in HACS and click **Download**.
6. Restart Home Assistant.

### Manual Installation

1. Download the latest release from the [GitHub releases page](https://github.com/kayloehmann/ha-gardena-smart-system/releases).
2. Copy the `custom_components/gardena_smart_system` folder into your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.

## Configuration

This integration is configured entirely through the Home Assistant UI. No YAML configuration is needed.

1. Go to **Settings > Devices & Services > Add Integration**.
2. Search for "Gardena Smart System" and select it.
3. Enter your **Application Key (Client ID)** and **Application Secret** from the Husqvarna Developer Portal.
4. **Select the API** you want to connect:
   - **Gardena Smart System** — for Gardena devices (sensors, valves, power sockets, SILENO mowers)
   - **Automower Connect** — for Husqvarna Automower robotic mowers
5. For the **Gardena Smart System API**: if your account has multiple gardens (locations), you will be prompted to select which one to add. If you only have one garden, it is selected automatically.
6. For the **Automower Connect API**: all mowers linked to your Husqvarna account are discovered automatically.

### Using Both APIs

To use both Gardena and Automower devices, **add the integration twice** — once selecting "Gardena Smart System" and once selecting "Automower Connect". Both use the same application credentials.

### Re-authentication

If your credentials expire or become invalid, Home Assistant will prompt you to re-authenticate. Go to the integration page, click **Reconfigure**, and enter your updated credentials.

### Removing the Integration

1. Go to **Settings > Devices & Services**.
2. Find the "Gardena Smart System" integration entry you want to remove.
3. Click the three-dot menu and select **Delete**.
4. All entities and devices created by this entry will be removed from Home Assistant.

If you installed via HACS, you can also uninstall the integration entirely:

1. Open HACS, go to **Integrations**.
2. Find "Gardena Smart System" and click **Remove**.
3. Restart Home Assistant.

## Entities

### Gardena Sensors

| Entity | Device Class | Unit | Category | Default |
|--------|-------------|------|----------|---------|
| Battery | `battery` | % | Diagnostic | Enabled |
| Battery state | `enum` | -- | Diagnostic | Enabled |
| Signal strength | -- | % | Diagnostic | **Disabled** |
| Soil moisture | `moisture` | % | -- | Enabled |
| Soil temperature | `temperature` | °C | -- | Enabled |
| Ambient temperature | `temperature` | °C | -- | Enabled |
| Light intensity | `illuminance` | lx | -- | Enabled |
| Operating hours (mower) | -- | h | Diagnostic | **Disabled** |
| Mower activity | -- | -- | Diagnostic | Enabled |
| Last error code | -- | -- | Diagnostic | **Disabled** |
| Power socket remaining time | `duration` | s | -- | Enabled |
| Power socket last error | -- | -- | Diagnostic | **Disabled** |

### Gardena Binary Sensors

| Entity | Device Class | Category | Default |
|--------|-------------|----------|---------|
| Battery low | `battery` | Diagnostic | Enabled |
| Valve error | `problem` | Diagnostic | **Disabled** |
| Mower error | `problem` | Diagnostic | Enabled |
| RF link | `connectivity` | Diagnostic | Enabled |

### Gardena Valve

| Entity | Device Class | Features |
|--------|-------------|----------|
| Valve | `water` | Open, Close |

One valve entity is created per physical valve. Smart Water Control devices have a single valve, while Smart Irrigation Control devices create one valve entity per zone. Opening a valve starts watering for 60 minutes (default). Use the `start_watering` service for a custom duration.

### Gardena Switch

| Entity | Device Class |
|--------|-------------|
| Power | `outlet` |

Created for Gardena Smart Power Adapter devices. Supports turn on (indefinitely), turn off, and timed on via the `turn_on_for` service.

### Gardena Lawn Mower

| Entity | Features |
|--------|----------|
| Mower | Start mowing, Dock, Pause |

Created for Gardena SILENO robotic mowers. Reports current activity: mowing, docked, paused, or error. Exposes `activity`, `last_error_code`, and `battery_state` as extra state attributes for use in frontend cards and automations.

---

### Automower Lawn Mower

| Entity | Features |
|--------|----------|
| Mower | Start mowing, Dock, Pause |

Created for Husqvarna Automower robotic mowers. Reports current activity mapped to Home Assistant states:

| Automower Activity | HA State |
|-------------------|----------|
| MOWING, LEAVING, GOING_HOME | Mowing |
| CHARGING, PARKED_IN_CS | Docked |
| (state = PAUSED) | Paused |
| STOPPED_IN_GARDEN, (state = ERROR/FATAL_ERROR) | Error |

**Extra state attributes** exposed on the lawn mower entity:

| Attribute | Description | Always present |
|-----------|-------------|---------------|
| `activity` | Raw Automower activity (e.g., `MOWING`, `CHARGING`, `PARKED_IN_CS`) | Yes |
| `state` | Raw Automower state (e.g., `IN_OPERATION`, `PAUSED`, `ERROR`) | Yes |
| `mode` | Mower mode (e.g., `MAIN_AREA`, `SECONDARY_AREA`) | Yes |
| `error_code` | Numeric error code | Only when non-zero |
| `restricted_reason` | Why the mower is restricted (e.g., `WEEK_TIMER`, `PARK_OVERRIDE`) | Only when active |
| `override_action` | Active override (e.g., `FORCE_PARK`, `FORCE_MOW`) | Only when active |

### Automower Sensors

| Entity | Device Class | Unit | Category | Default |
|--------|-------------|------|----------|---------|
| Battery | `battery` | % | Diagnostic | Enabled |
| Cutting height | -- | -- | -- | Enabled |
| Next start | `timestamp` | -- | -- | Enabled |
| Total cutting time | -- | h | Diagnostic | Enabled |
| Total charging time | -- | h | Diagnostic | Enabled |
| Charging cycles | -- | -- | Diagnostic | Enabled |
| Collisions | -- | -- | Diagnostic | Enabled |
| Total drive distance | -- | m | Diagnostic | Enabled |
| Blade usage time | -- | h | Diagnostic | Enabled |
| Total running time | -- | h | Diagnostic | Enabled |
| Total searching time | -- | h | Diagnostic | Enabled |
| Activity | `enum` | -- | Diagnostic | Enabled |
| State | `enum` | -- | Diagnostic | Enabled |
| Inactive reason | -- | -- | Diagnostic | Enabled |
| Restricted reason | `enum` | -- | Diagnostic | Enabled |
| Error code | -- | -- | Diagnostic | Enabled |
| Last error time | `timestamp` | -- | Diagnostic | Enabled |
| Schedule override | `enum` | -- | Diagnostic | Enabled |
| Last seen | `timestamp` | -- | Diagnostic | Enabled |

Time-based statistics (cutting time, charging time, blade usage, running time, searching time) are reported by the API in seconds and converted to hours for display.

### Automower Binary Sensors

| Entity | Device Class | Category |
|--------|-------------|----------|
| Error | `problem` | Diagnostic |
| Connected | `connectivity` | Diagnostic |

**Error** is on when the mower is in `ERROR` or `FATAL_ERROR` state. **Connected** reflects the mower's cloud connectivity.

### Automower Switches

| Entity | Description |
|--------|-------------|
| Headlight | Turn headlights always on or always off |
| Stay-out zone: *{name}* | Enable or disable individual stay-out zones |
| Work area: *{name}* | Enable or disable individual work areas |

Headlight, stay-out zone, and work area switches are only created if the mower model supports them (capability-based).

### Automower Select Controls

| Entity | Options | Description |
|--------|---------|-------------|
| Headlight mode | Always on, Always off, Evening only, Evening and night | Fine-grained headlight mode control |

The headlight mode select complements the simple on/off headlight switch with all four modes supported by the mower.

### Automower Number Controls

| Entity | Range | Step | Description |
|--------|-------|------|-------------|
| Cutting height | 1--9 | 1 | Global cutting height setting |
| Cutting height: *{work area}* | 0--100% | 1 | Per-work-area cutting height percentage |

Work area cutting height entities are only created if the mower supports work areas.

### Automower Device Tracker

| Entity | Source Type | Default |
|--------|-------------|---------|
| Position | GPS | **Disabled** |

Shows the mower's latitude and longitude from the most recent GPS position. Only created for mower models with GPS capability. **Disabled by default** for privacy — enable it manually in the entity settings if you want GPS tracking.

### Automower Calendar

| Entity | Description |
|--------|-------------|
| Mowing schedule | Read-only calendar showing scheduled mowing tasks |

Each schedule task appears as a calendar event with the summary "Mowing" (or "Mowing (*work area name*)" for work-area-specific schedules).

### Automower Button

| Entity | Description |
|--------|-------------|
| Confirm error | Acknowledge and clear the current mower error |

### Event Entities

Both Gardena and Automower devices expose event entities for state transitions, useful for automations.

| Entity | Events |
|--------|--------|
| Gardena Mower event | started_cutting, stopped, leaving, searching, charging, parked, paused, error, error_cleared |
| Gardena Valve event | started_watering, stopped_watering, error, error_cleared |
| Gardena Power socket event | turned_on, turned_off, error, error_cleared |
| Automower event | started_mowing, stopped, going_home, charging, leaving, parked, paused, error, error_cleared |

### Hub Diagnostic Sensors

Each config entry creates a virtual "hub" device with integration-level diagnostic sensors.

| Entity | Description | Category |
|--------|-------------|----------|
| Device count | Number of devices managed by this entry | Diagnostic |
| Polling interval | Current polling interval in seconds | Diagnostic |

## Services

The integration registers three custom services for Gardena devices.

### `gardena_smart_system.start_watering`

Start watering a valve for a specific duration, overriding any active schedule.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | entity | Yes | A `valve` entity from this integration |
| `duration` | number | Yes | Duration in minutes (1--1440) |

```yaml
service: gardena_smart_system.start_watering
target:
  entity_id: valve.garden_valve_1
data:
  duration: 30
```

### `gardena_smart_system.turn_on_for`

Turn on a smart power socket for a specific duration.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | entity | Yes | A `switch` entity from this integration |
| `duration` | number | Yes | Duration in minutes (1--1440) |

```yaml
service: gardena_smart_system.turn_on_for
target:
  entity_id: switch.garden_power_socket
data:
  duration: 120
```

### `gardena_smart_system.override_schedule`

Force the mower to mow for a specific duration, ignoring its configured schedule.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | entity | Yes | A `lawn_mower` entity from this integration |
| `duration` | number | Yes | Duration in minutes (1--480) |

```yaml
service: gardena_smart_system.override_schedule
target:
  entity_id: lawn_mower.sileno_mower
data:
  duration: 60
```

### `gardena_smart_system.park_until_further_notice`

Park the mower indefinitely. It will stay in the charging station until manually resumed.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | entity | Yes | A `lawn_mower` entity from this integration |

```yaml
service: gardena_smart_system.park_until_further_notice
target:
  entity_id: lawn_mower.automower_450x_mower
```

### `gardena_smart_system.resume_schedule`

Resume the mower's automatic mowing schedule.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | entity | Yes | A `lawn_mower` entity from this integration |

```yaml
service: gardena_smart_system.resume_schedule
target:
  entity_id: lawn_mower.automower_450x_mower
```

## Use Cases & Automation Examples

### Water the garden when soil is dry

```yaml
automation:
  - alias: "Water when soil moisture drops below 30%"
    trigger:
      - platform: numeric_state
        entity_id: sensor.smart_sensor_moisture
        below: 30
    condition:
      - condition: time
        after: "06:00:00"
        before: "09:00:00"
    action:
      - service: gardena_smart_system.start_watering
        target:
          entity_id: valve.garden_valve_1
        data:
          duration: 20
```

### Send a notification when the Automower has an error

```yaml
automation:
  - alias: "Notify on Automower error"
    trigger:
      - platform: state
        entity_id: binary_sensor.automower_450x_error
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "Automower Error"
          message: >
            The mower reported an error.
            State: {{ state_attr('lawn_mower.automower_450x_mower', 'state') }}
            Error code: {{ state_attr('lawn_mower.automower_450x_mower', 'error_code') }}
```

### Park the mower when rain is expected

```yaml
automation:
  - alias: "Park mower before rain"
    trigger:
      - platform: numeric_state
        entity_id: sensor.openweathermap_forecast_precipitation_probability
        above: 80
    condition:
      - condition: state
        entity_id: lawn_mower.automower_450x_mower
        state: "mowing"
    action:
      - service: lawn_mower.dock
        target:
          entity_id: lawn_mower.automower_450x_mower
```

### Track mower blade usage and notify for replacement

```yaml
automation:
  - alias: "Notify when blades need replacement"
    trigger:
      - platform: numeric_state
        entity_id: sensor.automower_450x_blade_usage_time
        above: 200
    action:
      - service: notify.mobile_app
        data:
          title: "Blade replacement needed"
          message: "The Automower blades have been running for over 200 hours. Consider replacing them."
```

## Data Updates

Both APIs use the same architecture: real-time WebSocket push with REST polling fallback. Each API has its own independent connection and rate limit budget.

### Gardena Smart System API (~3,000 requests/month)

#### Startup (on every HA restart or integration reload)

| # | API Call | Purpose |
|---|---------|---------|
| 1 | `POST /oauth2/token` | Acquire an OAuth2 access token |
| 2 | `GET /locations/{id}` | Fetch all devices and their current state |
| 3 | `POST /websocket` | Request a WebSocket URL for real-time updates |
| 4 | WebSocket connect | Open the persistent connection for push updates |

That is **3 REST calls + 1 WebSocket connection** per startup.

#### Normal operation (WebSocket connected)

| API Call | Frequency | Purpose |
|---------|-----------|---------|
| `GET /locations/{id}` | Every **6 hours** | Health-check poll — verifies the device list is in sync |
| `POST /oauth2/token` | Every **~55 minutes** | Token refresh (tokens expire after 1 hour) |
| WebSocket messages | Continuous (push) | All device state updates arrive here at zero REST cost |

Daily total: **~4 polls + ~24 token refreshes = ~28 requests/day** — roughly **28% of the daily budget**.

#### Fallback operation (WebSocket down)

| API Call | Frequency | Purpose |
|---------|-----------|---------|
| `GET /locations/{id}` | Every **30 minutes** | Poll for device state |
| `POST /oauth2/token` | Every **~55 minutes** | Token refresh |

Daily total: **~48 polls + ~24 token refreshes = ~72 requests/day** — roughly **72% of the daily budget**.

### Automower Connect API (~10,000 requests/month)

#### Startup

| # | API Call | Purpose |
|---|---------|---------|
| 1 | `POST /oauth2/token` | Acquire an OAuth2 access token (shared auth) |
| 2 | `GET /mowers` | Fetch all mowers and their current state |
| 3 | WebSocket connect | Open the persistent connection for push updates |

#### Normal operation (WebSocket connected)

| API Call | Frequency | Purpose |
|---------|-----------|---------|
| `GET /mowers` | Every **6 hours** | Health-check poll |
| `POST /oauth2/token` | Every **~55 minutes** | Token refresh |
| WebSocket messages | Continuous (push) | All mower state updates |

Daily total: **~4 polls + ~24 token refreshes = ~28 requests/day** — roughly **8% of the daily budget**.

#### Fallback operation (WebSocket down)

| API Call | Frequency | Purpose |
|---------|-----------|---------|
| `GET /mowers` | Every **15 minutes** | Poll for mower state |
| `POST /oauth2/token` | Every **~55 minutes** | Token refresh |

Daily total: **~96 polls + ~24 token refreshes = ~120 requests/day** — roughly **36% of the daily budget**.

### Rate-limited state (both APIs)

After receiving HTTP 429, both coordinators back off to **1-hour polling** until the next successful response restores the normal interval.

### User-triggered commands

| API Call | Frequency | Purpose |
|---------|-----------|---------|
| `PUT /command/{id}` (Gardena) | On demand, **min 5 seconds apart** | Valve, switch, mower commands |
| `POST /mowers/{id}/actions` (Automower) | On demand, **min 5 seconds apart** | Mower actions (start, pause, park) |
| `PATCH /mowers/{id}/settings` (Automower) | On demand, **min 5 seconds apart** | Cutting height, headlight, stay-out zones |

Each button press or automation action is one API call. The 5-second throttle prevents rapid-fire sequences from burning quota.

## API Rate Limits

### How This Integration Stays Within Limits

| Strategy | Detail |
|----------|--------|
| **WebSocket-first architecture** | Device state updates arrive in real time via persistent WebSocket connections. REST API polling is only a fallback. |
| **Adaptive polling interval** | When WebSocket is connected: **6-hour** health-check only. When WebSocket drops: **30 min** (Gardena) / **15 min** (Automower). |
| **Rate limit backoff** | If the API returns HTTP 429, polling backs off to **1 hour** and restores automatically after a successful response. |
| **Command throttling** | A minimum **5-second interval** is enforced between consecutive commands to prevent automations from rapid-firing API calls. |
| **Independent budgets** | The Gardena API (~3,000/month) and Automower API (~10,000/month) have separate rate limits. Using one does not affect the other. |

### Tips for Avoiding Rate Limits

- **Don't restart Home Assistant frequently.** Each restart triggers a full API poll and a new WebSocket connection request.
- **Avoid rapid-fire automations.** If you have automations that send multiple commands in a loop, add delays between them. The integration enforces a 5-second minimum, but longer pauses are better for quota.
- **Don't reuse your API key across multiple systems.** If you use the same Husqvarna application credentials in another smart home platform alongside Home Assistant, they share the same quota. Create a separate application on the Husqvarna Developer Portal for each system.
- **Use one integration instance per API.** Each additional instance adds its own polling and WebSocket overhead.
- **Monitor for rate limit warnings.** Check the Home Assistant logs for messages containing "Rate limited" — this applies to both APIs.

### What Happens When Rate Limited

1. The integration logs a warning (e.g., `Rate limited by Gardena API, backing off to 1:00:00`).
2. The polling interval increases to 1 hour.
3. Existing entity states remain available (cached from the last successful update and WebSocket messages).
4. Commands may fail until the rate limit resets.
5. After a successful API response, the normal polling interval is restored automatically.

## Known Limitations

- **Cloud-only**: Both APIs communicate through the Husqvarna cloud. An active internet connection is required.
- **API rate limits**: See the [API Rate Limits](#api-rate-limits) section above.
- **Valve position**: Gardena valves do not report percentage-based position — only open/closed state.
- **Mower GPS (Gardena)**: The Gardena Smart System API does not expose GPS coordinates. GPS tracking is available only for Automower devices via the Automower Connect API.
- **Calendar (Automower)**: The mowing schedule calendar is read-only. To modify schedules, use the Husqvarna Automower app.
- **SILENO via Automower API**: SILENO mowers are only supported through the Gardena Smart System API, not the Automower Connect API.

## Troubleshooting

### "Invalid credentials" during setup

- Double-check that you are entering the **Application Key** and **Application Secret** from the Husqvarna Developer Portal (not your Husqvarna account username/password).
- Verify that your Gardena/Husqvarna account is linked properly.

### "API access denied" during setup

- Ensure the correct API is connected to your application in the Husqvarna Developer Portal:
  - For Gardena devices: enable the **Gardena Smart System API**
  - For Automower: enable the **Automower Connect API**

### "Automower Connect API is not connected" during setup

- Go to the [Husqvarna Developer Portal](https://developer.husqvarnagroup.cloud), open your application, and enable the **Automower Connect API** under Connected APIs.

### Devices show as unavailable

- **Gardena devices**: The device may be out of RF range of the Gardena Smart Gateway. Check that the gateway is powered on and connected to your network.
- **Automower**: The mower may be out of cellular/Wi-Fi range. Check connectivity in the Husqvarna Automower app.
- Battery-powered devices may go offline when the battery is depleted.

### "Real-time connection lost" repair issue

This indicates the WebSocket connection to the Husqvarna cloud has failed. The integration continues to work via polling but updates will be delayed.

- Check your Home Assistant host's internet connection.
- Check the [Husqvarna service status](https://status.husqvarnagroup.cloud) for outages.
- The connection is retried automatically. The repair issue resolves itself once reconnected.

### Commands fail with "Failed to send command"

- The device may be temporarily unreachable. Wait a moment and try again.
- If the error persists, check the Home Assistant logs for details.
- Verify the device is online in the Gardena Smart App or Husqvarna Automower app.

### "Commands are being sent too quickly"

- The integration enforces a 5-second minimum interval between commands to protect the API quota.
- If you see this in automations, add a `delay` step between consecutive service calls.

### "Rate limited" in logs

- The Husqvarna API has temporarily blocked your API key due to too many requests.
- The integration automatically backs off and will recover on its own.
- If this happens frequently, review your automations and restart habits. See [API Rate Limits](#api-rate-limits) for tips.

## Code Quality

This integration targets the [Home Assistant Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/) at the **Platinum** level.

| Tier | Rules | Status |
|------|-------|--------|
| Bronze | 19 | Passed (2 N/A for custom integrations) |
| Silver | 10 | Passed |
| Gold | 22 | Passed (2 N/A: `discovery` / `discovery-update-info` — cloud API, no local discovery) |
| Platinum | 3 | Passed |

Key quality features:

- **99% test coverage** across 489 automated tests
- **mypy --strict** passes with zero errors on all 23 source files
- **PEP 561** compliant (`py.typed` markers on both client libraries)
- **Full async** codebase — no blocking I/O in the event loop
- **WebSocket session injection** — `aiohttp.ClientSession` provided by Home Assistant, not created internally
- **Diagnostics** with sensitive data redaction (credentials, serial numbers, GPS coordinates, device names)
- **Security hardening** — STRIDE threat model audit, WebSocket error isolation, log truncation, OAuth token revocation on shutdown
- **Repair issues** for WebSocket connection loss
- **Stale device cleanup** — devices removed from the API are automatically removed from the HA device registry
- **Translated exceptions** — all error messages use the HA translation framework

## Translations

The integration is fully translated into **30 languages** with 191 strings each:

| Language | Code | Language | Code |
|----------|------|----------|------|
| English | `en` | Portuguese (BR) | `pt-BR` |
| German | `de` | Russian | `ru` |
| French | `fr` | Ukrainian | `uk` |
| Dutch | `nl` | Czech | `cs` |
| Swedish | `sv` | Slovak | `sk` |
| Italian | `it` | Hungarian | `hu` |
| Spanish | `es` | Romanian | `ro` |
| Danish | `da` | Greek | `el` |
| Polish | `pl` | Bulgarian | `bg` |
| Portuguese | `pt` | Finnish | `fi` |
| Norwegian | `nb` | Croatian | `hr` |
| Slovenian | `sl` | Estonian | `et` |
| Latvian | `lv` | Lithuanian | `lt` |
| Turkish | `tr` | Catalan | `ca` |
| Chinese (Simplified) | `zh-Hans` | Chinese (Traditional) | `zh-Hant` |
| Japanese | `ja` | | |

Translations cover all entity names, config flow text, options, services, error messages, and enum state labels.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
