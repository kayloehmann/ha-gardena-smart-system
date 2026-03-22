# Contributing

Thanks for your interest in contributing to the Gardena Smart System integration for Home Assistant!

## Development Setup

1. Clone the repository
2. Create a virtual environment: `python -m venv .venv && source .venv/bin/activate`
3. Install dependencies:
   ```bash
   pip install -e ./aiogardenasmart -e ./aioautomower
   pip install pytest pytest-asyncio pytest-cov pytest-homeassistant-custom-component mypy ruff
   ```

## Running Tests

```bash
pytest -q
```

With coverage:

```bash
pytest --cov --cov-report=term-missing
```

## Linting

```bash
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/
```

## Type Checking

```bash
mypy custom_components/gardena_smart_system/
```

## Pull Requests

- Create a feature branch from `main`
- Include tests for new functionality
- Ensure all CI checks pass (lint, tests, mypy, hassfest)
- Keep PRs focused — one feature or fix per PR

## Architecture

The integration supports two Husqvarna APIs via separate coordinators:

- **Gardena Smart System API** — `coordinator.py` + `GardenaCoordinator`
- **Automower Connect API** — `automower_coordinator.py` + `AutomowerCoordinator`

Both use WebSocket for real-time updates with REST polling as fallback. Entity platforms are split by API type (e.g., `sensor.py` for Gardena, `automower_sensor.py` for Automower).
