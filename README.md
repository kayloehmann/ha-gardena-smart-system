# Gardena Smart System for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/kayloehmann/ha-gardena-smart-system)](https://github.com/kayloehmann/ha-gardena-smart-system/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-blue)](https://www.home-assistant.io/)
[![License](https://img.shields.io/github/license/kayloehmann/ha-gardena-smart-system)](LICENSE)

A Home Assistant custom integration for **Gardena Smart System** devices using the [Husqvarna Gardena Smart System API v2](https://developer.husqvarnagroup.cloud/apis/GARDENA+smart+system+API). Device states are updated in real time via a cloud WebSocket connection, with automatic fallback to polling if the WebSocket connection is interrupted.

## Supported Devices

| Device | Platform(s) | Description |
|--------|-------------|-------------|
| **Gardena Smart Sensor** | `sensor` | Soil moisture, soil temperature, ambient temperature, light intensity |
| **Gardena Smart Water Control** | `valve`, `sensor`, `binary_sensor` | Single-valve irrigation controller with open/close and timed watering |
| **Gardena Smart Irrigation Control** | `valve`, `sensor`, `binary_sensor` | Multi-zone irrigation controller (up to 6 valves) |
| **Gardena Smart Power Adapter** | `switch`, `sensor`, `binary_sensor` | Smart power outlet with on/off and timed control |
| **Gardena Smart SILENO Mower** | `lawn_mower`, `sensor`, `binary_sensor` | Robotic lawn mower with start, dock, pause, and schedule override |

All devices also expose common diagnostic sensors (battery level, RF signal strength) when the device reports them.

## Prerequisites

Before installing this integration, you need to create an application on the Husqvarna Developer Portal to obtain API credentials.

1. Go to the [Husqvarna Developer Portal](https://developer.husqvarnagroup.cloud) and create an account (or sign in with your existing Husqvarna account).
2. Navigate to **My Applications** and click **Create Application**.
3. Give it a name (e.g. "Home Assistant") and set the redirect URI to `https://localhost`.
4. Under **Connected APIs**, enable the **Gardena Smart System API**.
5. Note the **Application Key** (Client ID) and **Application Secret** -- you will need both during setup in Home Assistant.

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
4. The integration validates your credentials against the Gardena API. If they are invalid, you will see an error and can re-enter them.
5. If your account has multiple gardens (locations), you will be prompted to select which one to add. If you only have one garden, it is selected automatically.
6. The integration creates device entries for all Gardena devices in the selected garden.

To add multiple gardens, repeat the process by adding the integration a second time and selecting a different location.

### Re-authentication

If your credentials expire or become invalid, Home Assistant will prompt you to re-authenticate. Go to the integration page, click **Reconfigure**, and enter your updated credentials.

## Entities

### Sensors

| Entity | Device Class | Unit | Category | Default |
|--------|-------------|------|----------|---------|
| Battery | `battery` | % | Diagnostic | Enabled |
| Signal strength | -- | % | Diagnostic | **Disabled** |
| Soil moisture | `moisture` | % | -- | Enabled |
| Soil temperature | `temperature` | C | -- | Enabled |
| Ambient temperature | `temperature` | C | -- | Enabled |
| Light intensity | `illuminance` | lx | -- | Enabled |
| Operating hours (mower) | -- | h | Diagnostic | **Disabled** |

**Battery** and **Signal strength** are available on all battery-powered devices. The soil/temperature/light sensors are created only for Gardena Smart Sensor devices. **Operating hours** is only available on mower devices.

### Binary Sensors

| Entity | Device Class | Category | Default |
|--------|-------------|----------|---------|
| Battery low | `battery` | Diagnostic | Enabled |
| Valve error | `problem` | Diagnostic | **Disabled** |
| Mower error | `problem` | Diagnostic | Enabled |

### Valve

| Entity | Device Class | Features |
|--------|-------------|----------|
| Valve | `water` | Open, Close |

One valve entity is created per physical valve. Gardena Smart Water Control devices have a single valve, while Gardena Smart Irrigation Control devices create one valve entity per zone.

Opening a valve starts watering for 60 minutes (default). Use the `start_watering` service for a custom duration.

### Switch

| Entity | Device Class |
|--------|-------------|
| Power | `outlet` |

Created for Gardena Smart Power Adapter devices. Supports turn on (indefinitely), turn off, and timed on via the `turn_on_for` service.

### Lawn Mower

| Entity | Features |
|--------|----------|
| Mower | Start mowing, Dock, Pause |

Created for Gardena SILENO robotic mowers. The entity reports the current activity: mowing, docked, paused, or error.

- **Start mowing** resumes the mower according to its schedule.
- **Dock** sends the mower back to its charging station until the next scheduled task.
- **Pause** parks the mower until further notice (overrides the schedule).

## Services

The integration registers three custom services for actions beyond the standard entity controls.

### `gardena_smart_system.start_watering`

Start watering a valve for a specific duration, overriding any active schedule.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | entity | Yes | A `valve` entity from this integration |
| `duration` | number | Yes | Duration in minutes (1--1440) |

**Example automation:**

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

**Example automation:**

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

**Example automation:**

```yaml
service: gardena_smart_system.override_schedule
target:
  entity_id: lawn_mower.sileno_mower
data:
  duration: 60
```

## Data Updates

The integration connects to the Gardena Smart System cloud via WebSocket for real-time push updates. When a device state changes (e.g., a valve opens, the mower starts), the update arrives within seconds.

If the WebSocket connection drops (network issues, Gardena service outage), the integration automatically falls back to polling every 60 seconds and creates a repair issue in Home Assistant to notify you. The repair issue is resolved automatically when the WebSocket connection is re-established.

## Known Limitations

- **Cloud-only**: The integration communicates with Gardena devices through the Husqvarna cloud. It requires an active internet connection and depends on Husqvarna's API availability.
- **API rate limits**: The Husqvarna Developer Platform enforces rate limits. Under normal operation (WebSocket-based updates) this is not a concern, but repeated restarts or configuration changes in quick succession may trigger rate limiting.
- **Valve position**: Gardena valves do not report percentage-based position. The valve entity reports only open/closed state.
- **Mower GPS**: The Gardena API does not expose GPS coordinates through the Smart System API.

## Troubleshooting

### "Invalid credentials" during setup

- Double-check that you are entering the **Application Key** and **Application Secret** from the Husqvarna Developer Portal (not your Husqvarna account username/password).
- Ensure the **Gardena Smart System API** is connected to your application on the developer portal.
- Verify that your Gardena account is linked to your Husqvarna account.

### Devices show as unavailable

- The device may be out of RF range of the Gardena Smart Gateway.
- Check that the Gardena Smart Gateway is powered on and connected to your network.
- Battery-powered devices may go offline when the battery is depleted.

### "Gardena real-time connection lost" repair issue

This indicates the WebSocket connection to the Gardena cloud has failed. The integration continues to work via polling (every 60 seconds) but updates will be delayed.

- Check your Home Assistant host's internet connection.
- Check the [Husqvarna service status](https://status.husqvarnagroup.cloud) for outages.
- The connection is retried automatically. The repair issue will resolve itself once the connection is restored.

### Commands fail with "Failed to send command"

- The device may be temporarily unreachable. Wait a moment and try again.
- If the error persists, check the Home Assistant logs for details.
- Verify the device is online in the Gardena Smart App.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
