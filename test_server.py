#!/bin/env python3.12

import subprocess
import re
from dataclasses import dataclass, field
from typing import Optional
from regress import resourceFactory, resource

def parse_emulator_status(factory: resourceFactory, output: str) -> list[resource]:
    """
    Parse the output of the test_server command and return a list of resource objects.
 
    Resources extracted:
      - system_info         : emulator, hardware, configmgr, system_status
      - cluster             : cluster ids and their CCD status
      - board_<id>          : domain ids per board and their statuses
      - domains             : domains
      - t_pod_available     : available T-Pods
      - t_pod_unavailable   : unavailable T-Pods
      - t_pod_locked        : locked T-Pods
      - t_pod_reserved      : reserved T-Pods
      - hdsb_available      : available HDSBs
    """
    resources: list[resource] = []
    lines = output.splitlines()
 
    # ------------------------------------------------------------------ #
    # 1. System header line                                                #
    # ------------------------------------------------------------------ #
    header_line = lines[0] if lines else ""
    header_map = {}
    for key, pattern in [
        ("Emulator",  r"Emulator:\s*(\S+)"),
        ("Hardware",  r"Hardware:\s*([\w\s]+?)(?=\s{2,}|\s*Configmgr:)"),
        ("Configmgr", r"Configmgr:\s*(\S+?)(?=\s*System Status:|$)"),
        ("System_Status", r"System Status:\s*(\S+)"),
    ]:
        m = re.search(pattern, header_line)
        header_map[key] = m.group(1).strip() if m else "UNKNOWN"
 
    resources.append(resource(
        "system_info",
        list(header_map.keys()),
        list(header_map.values()),
    ))
 
    # ------------------------------------------------------------------ #
    # 2. Boards and domains                                                #
    # ------------------------------------------------------------------ #
    # Collect per-board domain rows
    current_board: Optional[str] = None
    current_board_status: Optional[str] = None
    board_domains: dict[str, list] = {}        # board_id -> [domain_id, ...]
    domains: list[str] = []
    domain_ids: list[str] = []
    cluster_ids: list[str] = []
    cluster_statuses: list[str] = []
    board_ids: list[str] = []
    board_statuses: list[str] = []
 
    in_domain_table = False
 
    for line in lines[1:]:
        # Cluster line
        m = re.match(r"Cluster\s+(\d+)\s+has\s+\d+\s+boards\s+CCD:\s*(\S+)", line)
        if m:
            cluster_ids.append(m.group(1))
            cluster_statuses.append(m.group(2))
            in_domain_table = False
            continue
 
        # Board line
        m = re.match(r"Board\s+(\d+)\s+has\s+\d+\s+domains\s+Board:\s*(\S+)", line)
        if m:
            current_board = m.group(1)
            current_board_status = m.group(2)
            board_ids.append(current_board)
            board_statuses.append(current_board_status)
            board_domains[current_board] = []
            in_domain_table = False
            continue
 
        # Domain header row - skip
        if re.match(r"\s*Domain\s+Owner\s+PID", line):
            in_domain_table = True
            continue
 
        # Domain data row
        if in_domain_table and current_board:
            m = re.match(
                r"\s*(\d+\.\d+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
                line,
            )
            if m:
                domain_id = m.group(1)
                owner     =  "FREE" if (m.group(2) == "NONE") else "RESERVED"
                board_domains[current_board].append(domain_id)
                domain_ids.append(domain_id)
                domains.append(owner)
 
    # Cluster resource
    if cluster_ids:
        resources.append(factory.create_resource("cluster", cluster_ids, cluster_statuses))
 
    # Board resource (all boards, with their online/offline status)
    if board_ids:
        resources.append(factory.create_resource("board", board_ids, board_statuses))
 
    # Aggregated domain owner / design resources
    if domain_ids:
        resources.append(factory.create_resource("domains",  domain_ids, domains))

    # ------------------------------------------------------------------ #
    # 3. T-Pod / HDSB sections                                            #
    # ------------------------------------------------------------------ #
    def extract_items(label: str) -> list[str]:
        """Return list of tokens after 'label: ' on its line, or [] for NONE."""
        pattern = rf"^{re.escape(label)}:\s*(.+)$"
        for line in lines:
            m = re.match(pattern, line.strip())
            if m:
                val = m.group(1).strip()
                if val.upper() == "NONE":
                    return []
                return [t.strip() for t in val.split(",") if t.strip()]
        return []
 
    # Map each label to its canonical status string
    pod_sections = [
        ("Available T-Pods",   "AVAILABLE"),
        ("Unavailable T-Pods", "UNAVAILABLE"),
        ("Locked T-Pods",      "LOCKED"),
        ("Reserved T-Pods",    "RESERVED"),
        ("Available HDSB",     "AVAILABLE"),
        ("Unavailable HDSB",   "UNAVAILABLE"),
        ("Locked HDSB",        "LOCKED"),
        ("Reserved HDSB",      "RESERVED"),
    ]

    pod_ids: list[str] = []
    pod_statuses: list[str] = []
    
    # Build pod_name -> status mapping (labels are disjoint sets)
    pod_status: dict[str, str] = {}
    for label, status in pod_sections:
        for pod_name in extract_items(label):
            pod_status[pod_name] = status

    for pod_name, status in pod_status.items():
        pod_ids.append(pod_name)
        pod_statuses.append(status)
    resources.append(factory.create_resource("tpods", pod_ids, pod_statuses))

    return resources
 
 
def run_test_server(factory: resourceFactory, command: str = "test_server") -> list[resource]:
    """
    Run the test_server command and return parsed resource objects.
 
    Parameters
    ----------
    command : str
        The shell command to execute (default: "test_server").
        Override for testing, e.g. pass "cat test_status.txt".
 
    Returns
    -------
    list[palResource]
        Parsed emulator status as resource objects.
 
    Raises
    ------
    RuntimeError
        If the command exits with a non-zero return code.
    """
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command '{command}' failed with exit code {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )
    return parse_emulator_status(factory, result.stdout)
 
