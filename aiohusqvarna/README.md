# aiohusqvarna

Async Python client for the [Husqvarna Automower Connect API v1](https://developer.husqvarnagroup.cloud/apis/automower-connect-api).

Built for and maintained alongside the
[`gardena_smart_system_ng`](https://github.com/kayloehmann/ha-gardena-smart-system)
Home Assistant integration, which uses it together with its sibling library
[`aiogardenasmart`](https://pypi.org/project/aiogardenasmart/) (GARDENA smart system API v2).
It shares the GARDENA OAuth2 authentication layer, so a single Husqvarna developer
application can drive both Automower and GARDENA devices.

> **Not to be confused with [`aioautomower`](https://pypi.org/project/aioautomower/).**
> That is a separate, unrelated project by Thomas55555, used by Home Assistant's
> built-in `husqvarna_automower` integration. The two libraries have different APIs
> and are not drop-in replacements for each other. This package was renamed from an
> internal `aioautomower` module precisely to remove that collision.

## Installation

```bash
pip install aiohusqvarna
```

## Usage

```python
import aiohttp
from aiogardenasmart.auth import GardenaAuth
from aiohusqvarna import AutomowerClient

async with aiohttp.ClientSession() as session:
    auth = GardenaAuth(client_id, client_secret, session)
    client = AutomowerClient(auth, session)

    mowers = await client.async_get_mowers()
    for mower in mowers:
        print(mower.name, mower.state)
```

A WebSocket client for real-time status updates is available via
`aiohusqvarna.websocket`.

## Features

- Automower Connect REST API v1 (mower list, status, commands)
- Real-time updates over the Automower Connect WebSocket
- Typed models (`py.typed`, mypy strict)
- Shared OAuth2 auth with `aiogardenasmart`

## License

Apache-2.0
