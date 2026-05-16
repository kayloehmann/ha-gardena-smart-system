# Gardena Smart System for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/kayloehmann/ha-gardena-smart-system)](https://github.com/kayloehmann/ha-gardena-smart-system/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-blue)](https://www.home-assistant.io/)
[![License](https://img.shields.io/github/license/kayloehmann/ha-gardena-smart-system)](https://github.com/kayloehmann/ha-gardena-smart-system/blob/main/LICENSE)
[![Quality Scale](https://img.shields.io/badge/Quality%20Scale-Platinum-blueviolet)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
[![mypy](https://img.shields.io/badge/type%20checked-mypy%20strict-blue)](https://mypy-lang.org/)
[![Test Coverage](https://img.shields.io/badge/coverage-99%25-brightgreen)](https://github.com/kayloehmann/ha-gardena-smart-system)

A Home Assistant custom integration for **Husqvarna smart garden devices** — supporting both the **Gardena Smart System API** and the **Automower Connect API** through a single integration. Real-time WebSocket push with automatic polling fallback.

> **📖 Full documentation lives in the [Wiki](https://github.com/kayloehmann/ha-gardena-smart-system/wiki) — available in English and German / Vollständige Dokumentation im [Wiki](https://github.com/kayloehmann/ha-gardena-smart-system/wiki) — auf Englisch und Deutsch.**

> **⚠️ Breaking change in v2.0.0 — the integration domain was renamed `gardena_smart_system` → `gardena_smart_system_ng`** (required for HACS default-catalog inclusion; the old domain is taken by another integration). There is no automatic migration: delete the old entry, update to 2.0.0, delete the orphaned `custom_components/gardena_smart_system/` folder, restart, and re-add the integration with the same credentials. Full steps in the [CHANGELOG](CHANGELOG.md#200---2026-05-16).
>
> **⚠️ Breaking Change in v2.0.0 — die Integrations-Domain wurde umbenannt von `gardena_smart_system` zu `gardena_smart_system_ng`** (erforderlich für die Aufnahme in den HACS-Default-Katalog; die alte Domain ist von einer anderen Integration belegt). Es gibt keine automatische Migration: alten Eintrag löschen, auf 2.0.0 aktualisieren, den verwaisten Ordner `custom_components/gardena_smart_system/` löschen, neu starten und die Integration mit denselben Zugangsdaten neu hinzufügen. Vollständige Schritte im [CHANGELOG](CHANGELOG.md#200---2026-05-16).

---

## English

### Quickstart

1. **Get Husqvarna API credentials.** Go to the [Husqvarna Developer Portal](https://developer.husqvarnagroup.cloud), create an Application (redirect URI `https://localhost`), and enable the **Gardena Smart System API** and/or **Automower Connect API**. Note the **Application Key** and **Application Secret**.
2. **Install via HACS.** Open HACS → Integrations → search for *Gardena Smart System* → Download → restart Home Assistant. *(If not listed: add `https://github.com/kayloehmann/ha-gardena-smart-system` as a custom repository, category Integration.)*
3. **Add the integration.** Go to **Settings → Devices & Services → Add Integration** → search *Gardena Smart System* → enter your Application Key and Secret → choose the API (Gardena or Automower).

To use both APIs, add the integration twice with the same credentials.

### Documentation

| Topic | Link |
|-------|------|
| Installation | [Wiki / Installation](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Installation-EN) |
| Configuration | [Wiki / Configuration](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Configuration-EN) |
| Supported Devices | [Wiki / Supported Devices](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Supported-Devices-EN) |
| Entities & Services | [Wiki / Entities and Services](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Entities-and-Services-EN) |
| API Rate Limits | [Wiki / API Rate Limits](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/API-Rate-Limits-EN) |
| MQTT Bridge | [Wiki / MQTT Bridge](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/MQTT-Bridge-EN) |
| Automation Examples | [Wiki / Automation Examples](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Automation-Examples-EN) |
| Limitations | [Wiki / Limitations](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Limitations-EN) |
| Troubleshooting | [Wiki / Troubleshooting](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Troubleshooting-EN) |
| Contributing | [Wiki / Contributing](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Contributing-EN) |

---

## Deutsch

### Schnellstart

1. **Husqvarna-API-Zugangsdaten anlegen.** Auf das [Husqvarna Developer Portal](https://developer.husqvarnagroup.cloud) gehen, eine Application erstellen (Redirect-URI `https://localhost`) und die **Gardena Smart System API** und/oder die **Automower Connect API** aktivieren. **Application Key** und **Application Secret** notieren.
2. **Über HACS installieren.** HACS → Integrationen → nach *Gardena Smart System* suchen → Herunterladen → Home Assistant neu starten. *(Nicht gelistet? `https://github.com/kayloehmann/ha-gardena-smart-system` als Custom Repository der Kategorie Integration hinzufügen.)*
3. **Integration hinzufügen.** **Einstellungen → Geräte & Dienste → Integration hinzufügen** → *Gardena Smart System* suchen → Application Key und Secret eingeben → API auswählen (Gardena oder Automower).

Um beide APIs zu nutzen, die Integration zweimal mit denselben Zugangsdaten hinzufügen.

### Dokumentation

| Thema | Link |
|-------|------|
| Installation | [Wiki / Installation](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Installation-DE) |
| Konfiguration | [Wiki / Konfiguration](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Configuration-DE) |
| Unterstützte Geräte | [Wiki / Unterstützte Geräte](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Supported-Devices-DE) |
| Entities & Services | [Wiki / Entities und Services](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Entities-and-Services-DE) |
| API-Rate-Limits | [Wiki / API-Rate-Limits](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/API-Rate-Limits-DE) |
| MQTT-Bridge | [Wiki / MQTT-Bridge](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/MQTT-Bridge-DE) |
| Automatisierungsbeispiele | [Wiki / Automatisierungsbeispiele](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Automation-Examples-DE) |
| Einschränkungen | [Wiki / Einschränkungen](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Limitations-DE) |
| Fehlerbehebung | [Wiki / Fehlerbehebung](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Troubleshooting-DE) |
| Mitwirken | [Wiki / Mitwirken](https://github.com/kayloehmann/ha-gardena-smart-system/wiki/Contributing-DE) |

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
