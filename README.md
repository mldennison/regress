# Regress Test Framework

This repository now includes a `pytest` test harness for the `akRegress.main()` entry point.

## Install test dependency

```bash
python -m pip install pytest
```

## Run tests

```bash
python -m pytest -q
```

## What the harness validates

- `akRegress.main()` runs under `regress.test_mode = 1`.
- Dependency injection can override:
  - test list loading (`testlist_parser` behavior),
  - emulator resource provider (`test_server` behavior),
  - license provider (`lmstat` behavior).
- Different injected test lists and resource snapshots produce different scheduling behavior across runs.
