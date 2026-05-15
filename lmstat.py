#!/bin/env python3.12

import subprocess
import re
from regress import resourceFactory, resource

# Matches lines like:
# Users of Palladium_Z1_Domain:  (Total of 96 licenses issued;  Total of 8 licenses in use)
_USERS_RE = re.compile(
    r"^Users of (\S+):\s+\(Total of (\d+) licenses? issued;\s+Total of (\d+) licenses? in use\)"
)

def parse_lmstat(factory: resourceFactory, output: str) -> list[resource]:
    """
    Parse the output of `lmstat -a` and return one resource per license feature.

    Each resource has:
        name   = feature name  (e.g. Palladium_Z1_Domain)
        values = [available_count, in_use_count]   (ints)
        status = ['AVAILABLE',     'USED']
    """
    resources: list = []

    for line in output.splitlines():
        m = _USERS_RE.match(line.strip())
        if m:
            name    = m.group(1)
            issued  = int(m.group(2))
            in_use  = int(m.group(3))
            available = issued - in_use

            resources.append(factory.create_resource(
                name,
                [available, in_use],
                ["AVAILABLE", "USED"],
                "license"
            ))

    return resources


def run_lmstat(factory: resourceFactory, command: str = "lmstat -a") -> list[resource]:
    """
    Run the lmstat command and return parsed license resources.

    Parameters
    ----------
    command : str
        Shell command to execute (default: "lmstat -a").
        Override for testing, e.g. "cat lmstat.txt".

    Returns
    -------
    list[palResource]

    Raises
    ------
    RuntimeError
        If the command exits with a non-zero return code.
    """
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command '{command}' failed with exit code {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )
    return parse_lmstat(result.stdout)


# ------------------------------------------------------------------ #
# Quick demo                                                           #
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    resources = run_lmstat()
    for r in resources:
        print(r)
