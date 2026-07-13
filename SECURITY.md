# Security Policy

## Scope

This policy covers:

- The `gardena_smart_system_ng` custom component under `custom_components/`.
- The vendored `aiogardenasmart` library under `aiogardenasmart/`.
- The vendored `aiohusqvarna` library under `aiohusqvarna/`.

Out of scope: the Husqvarna Smart System / Authentication API itself, Home Assistant core, HACS, and any local MQTT broker used by the optional MQTT bridge.

## Supported Versions

Only the latest minor release line receives security fixes. Always run the newest release from HACS.

| Version | Supported          |
| ------- | ------------------ |
| 1.12.x  | :white_check_mark: |
| < 1.12  | :x:                |

## Reporting a Vulnerability

Please report suspected vulnerabilities **privately** via GitHub Security Advisories:

<https://github.com/kayloehmann/ha-gardena-smart-system/security/advisories/new>

Do **not** open a public issue, PR, or HACS forum post before a fix is released.

You can expect:

- An initial acknowledgement within **7 days**.
- A triage outcome (accepted / not applicable / duplicate) within **14 days**.
- For accepted reports: a coordinated disclosure timeline and, where possible, credit in the release notes.

This integration is maintained as a best-effort open-source project; there is no commercial SLA.

## Sensitive Data Handled by the Integration

| Data | Storage | Handling |
| --- | --- | --- |
| Husqvarna `client_id` / `client_secret` | Home Assistant config entry | Never logged. Treat like a password. Use a dedicated Husqvarna Developer Portal application per HA instance. |
| OAuth access & refresh tokens | In-memory only | Refreshed automatically via the Husqvarna auth endpoint. Revoked on entry removal, reauth, reconfigure, and config-flow cancel. |
| `X-Api-Key` HTTP header | In-memory only | Equals `client_id`; redacted from logs. |
| Location IDs, device serials, service IDs | HA state | Redacted from the HA diagnostics download (`client_id`, `client_secret`, `serial`, `serial_number`, `location_id`, `name`, `latitude`, `longitude`). Still review diagnostics before attaching them to a public issue. |
| API request bodies | Not logged at `DEBUG` | Command payloads are elided from logs to avoid leaking service IDs alongside the `X-Api-Key`. |

All REST traffic uses HTTPS; WebSocket connections use `wss://`. No third-party telemetry is sent by the integration.

## Optional MQTT Bridge

When the MQTT bridge is enabled in options, the integration publishes device state to the configured topic prefix and (optionally) subscribes to `<prefix>/<device_id>/command`. Broker security is the user's responsibility:

- Never expose the MQTT broker to the internet without authentication and TLS.
- While command subscription is enabled, **any** publisher on the broker can trigger watering, power-socket, or mower commands. Restrict publish ACLs on the broker.
- If you only need read-only state mirroring, disable "subscribe to commands" in the integration options.

## Hardening Recommendations

- Use a dedicated Husqvarna Developer Portal application per Home Assistant installation so that credentials can be rotated independently.
- Review HA diagnostics before attaching them to GitHub issues.
- Delete the integration entry when no longer needed; this revokes the active access token.
- Rotate the Husqvarna application secret if a diagnostics file, log, or token is ever shared unredacted.

## Dependencies

The integration pins specific versions of the vendored `aiogardenasmart` and `aiohusqvarna` libraries, and transitively `aiohttp`. Security-relevant CVEs in those dependencies will trigger a patch release.

The `CHANGELOG.md` lists all releases; entries that address a security issue are marked **Security**.
