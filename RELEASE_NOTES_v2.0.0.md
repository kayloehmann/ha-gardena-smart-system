# v2.0.0 — Integration domain renamed (BREAKING)

> Draft for the GitHub release body. Paste into the v2.0.0 release, then this file can be deleted.

## ⚠️ Breaking change — read before updating

The integration domain changed from `gardena_smart_system` to **`gardena_smart_system_ng`**.

**Why:** Required to be accepted into the HACS default catalog. The `gardena_smart_system` domain is already taken there by the older `py-smart-gardena/hass-gardena-smart-system` integration, and two integrations cannot share a domain — HACS installs both into the same `custom_components/` folder and they overwrite each other.

**Impact:** Home Assistant has no automatic migration across a domain change. The display name (*Gardena Smart System*) and your Husqvarna API credentials are unchanged, but the old config entry, its entities, and their history are tied to the old domain and will not carry over. This is a one-time reconfiguration.

## Migration steps

1. Note your **Application Key** and **Application Secret** (Husqvarna Developer Portal) — you will re-enter them.
2. **Settings → Devices & Services** → open the old *Gardena Smart System* entry → **Delete**.
3. Update to **2.0.0** in HACS (installs the new `custom_components/gardena_smart_system_ng/` folder). Delete the now-orphaned `custom_components/gardena_smart_system/` folder manually, then restart Home Assistant.
4. **Add Integration → Gardena Smart System** → re-enter Application Key/Secret → pick the API (Gardena and/or Automower) as before.
5. Update automations/scripts/dashboards referencing old entity IDs. Tip: rename the re-created entities back to their previous entity IDs so existing automations keep working untouched.

## Changed

- Renamed integration domain `gardena_smart_system` → `gardena_smart_system_ng` across the component, tests, CI, and documentation. No functional or behavioural change beyond the domain itself.

Full details: [CHANGELOG](CHANGELOG.md#200---2026-05-16)
