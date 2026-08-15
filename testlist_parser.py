#!/bin/env python3.12
"""
regress_parser.py
-----------------
Reads a two-level YAML regression configuration file and produces a list of
Job objects — one per domain (i.e. one per index position within each entry).

If an entry has n domains (determined by the length of its longest list
attribute), n Jobs are created with names suffixed _1 .. _n.
Single-domain entries produce one Job with no suffix.

Attribute rules per Job:
  - List-valued YAML attr   — indexed to this domain's position (scalar)
  - Scalar YAML attr        — same value on every Job for this entry
  - Absent attr             — None
  - Global attrs            — applied to every Job; if the entry also defines
    the same key, values are merged (global first).  Keys ending in _args are
    split into token lists and concatenated; other keys concatenate as strings.

Special key "global":
  Top-level entry named "global" is not turned into a Job.  Its second-level
  keys are defaults on every Job.  When a test entry also sets a global key,
  the entry-specific value is appended after the global value.

The string literal "None" in YAML (e.g. sd: None) stays as Python None.
"""

from __future__ import annotations

import yaml
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Optional

from regress_utils import split_to_list

GLOBAL_KEY = "global"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_none(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "None":
        return None
    return value


def _is_args_key(key: str) -> bool:
    return key.endswith("_args")


def _to_arg_list(value: Any) -> list:
    """Normalize an args value to a list of tokens."""
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return split_to_list(value)


def _merge_values(global_val: Any, entry_val: Any, *, as_list: bool = False) -> Any:
    """Merge global and entry values: entry appends after global when both set."""
    if as_list:
        return _to_arg_list(global_val) + _to_arg_list(entry_val)
    if entry_val is None:
        return global_val
    if global_val is None:
        return entry_val
    return f"{global_val} {entry_val}"


def _all_keys(data: dict, global_attrs: dict) -> list[str]:
    """Superset of every second-level key across all non-global entries,
    plus every key from the global entry."""
    seen: set[str] = set(global_attrs.keys())
    for entry_name, entry in data.items():
        if entry_name == GLOBAL_KEY:
            continue
        if isinstance(entry, dict):
            seen.update(entry.keys())
    return sorted(seen)


# ---------------------------------------------------------------------------
# Dynamic Job dataclass
# ---------------------------------------------------------------------------

def _make_job_class(entry_keys: list[str], global_keys: list[str]) -> type:
    """
    Build a Job dataclass with:
      - name         : str        (top-level key, possibly suffixed)
      - entry_keys   : Optional[Any]   scalar per domain, default None
      - global_keys  : Optional[Any]   plain scalar from global, default None
        (global keys not already in entry_keys are appended)
    """
    annotations: dict[str, Any] = {"name": str}
    defaults: dict[str, Any] = {}

    all_field_keys = list(entry_keys)
    for k in global_keys:
        if k not in all_field_keys:
            all_field_keys.append(k)

    for key in all_field_keys:
        annotations[key] = Optional[Any]
        defaults[key] = None

    cls = type("Job", (), {"__annotations__": annotations, **defaults})
    job_cls = dataclass(cls)

    def _repr(self) -> str:
        parts = [f"Job(name={self.name!r}"]
        for f in fields(self):
            if f.name == "name":
                continue
            parts.append(f"  {f.name}={getattr(self, f.name)!r}")
        return ",\n".join(parts) + "\n)"

    job_cls.__repr__ = _repr
    return job_cls


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_jobs(path: str | Path) -> list:
    """
    Parse *path* and return one Job per domain across all non-global entries.

    Entries with n>1 domains produce n Jobs named <key>_1 .. <key>_n.
    Single-domain entries produce one Job named <key> (no suffix).
    """
    raw: dict = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError("Top-level YAML value must be a mapping.")

    # Extract global attrs (empty if no global entry)
    global_attrs: dict = {}
    if GLOBAL_KEY in raw:
        global_entry = raw[GLOBAL_KEY]
        if not isinstance(global_entry, dict):
            raise ValueError("'global' entry must be a mapping.")
        global_attrs = {k: _coerce_none(v) for k, v in global_entry.items()}

    entry_keys  = [k for k in _all_keys(raw, global_attrs)
                   if k not in global_attrs]
    global_keys = list(global_attrs.keys())
    JobCls      = _make_job_class(entry_keys, global_keys)

    jobs: list = []

    for entry_name, attrs in raw.items():
        if entry_name == GLOBAL_KEY:
            continue

        if not isinstance(attrs, dict):
            raise ValueError(
                f"Second-level value for '{entry_name}' must be a mapping."
            )

        # n = length of longest list attribute (minimum 1)
        n = max(
            (len(v) for v in attrs.values() if isinstance(v, list)),
            default=1,
        )

        for i in range(n):
            suffix = f"_{i + 1}" if n > 1 else ""
            kwargs: dict[str, Any] = {"name": f"{entry_name}{suffix}"}

            for key in entry_keys:
                raw_val = attrs.get(key)
                if isinstance(raw_val, list):
                    val = _coerce_none(raw_val[i]) if i < len(raw_val) else None
                else:
                    val = _coerce_none(raw_val)
                kwargs[key] = _to_arg_list(val) if _is_args_key(key) else val

            for key in global_keys:
                raw_val = attrs.get(key)
                if isinstance(raw_val, list):
                    entry_val = _coerce_none(raw_val[i]) if i < len(raw_val) else None
                elif key in attrs:
                    entry_val = _coerce_none(raw_val)
                else:
                    entry_val = None
                kwargs[key] = _merge_values(
                    global_attrs[key], entry_val, as_list=_is_args_key(key)
                )

            jobs.append(JobCls(**kwargs))

    # for debug
    # for  j in jobs:
    #     print(repr(j))
    #     print()

    return jobs


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    yaml_path = sys.argv[1] if len(sys.argv) > 1 else "regress.yaml"
    job_list  = load_jobs(yaml_path)

    print(f"Loaded {len(job_list)} job(s) from '{yaml_path}':\n")
    for j in job_list:
        print(repr(j))
        print()
