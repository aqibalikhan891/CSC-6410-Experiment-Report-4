#!/usr/bin/env python3
"""CSC6410 Experiment 4: measure core-facing transmit bytes for one UDP run.

Run from the existing fat-tree Mininet CLI (do not start another Mininet):
    py __import__('ecmp_measure').run(net, 16, 1)

Arguments: net (Mininet object), number of parallel flows, repetition (1/2/3).
"""

import csv
from datetime import datetime, timezone
from pathlib import Path
import time

CORE_LINKS = {
    "a00-eth3": "c00",
    "a00-eth4": "c01",
    "a01-eth3": "c10",
    "a01-eth4": "c11",
}
WORKDIR = Path("/work")
RESULTS_PATH = WORKDIR / "ecmp_results.csv"


def read_tx_bytes(interface):
    """Read the cumulative Linux transmit-byte counter for one interface."""
    path = Path("/sys/class/net") / interface / "statistics/tx_bytes"
    return int(path.read_text().strip())


def snapshot():
    return {interface: read_tx_bytes(interface) for interface in CORE_LINKS}


def run(net, flows, repetition, duration=20):
    """Send N UDP flows, measure the four core links, and store raw evidence."""
    if flows not in (4, 8, 16, 32):
        raise ValueError("flows must be one of 4, 8, 16, 32")
    if repetition not in (1, 2, 3):
        raise ValueError("repetition must be 1, 2, or 3")
    if duration < 1:
        raise ValueError("duration must be at least one second")

    h000 = net.get("h000")
    h300 = net.get("h300")
    print(f"\n=== ECMP: N={flows} UDP flows; run={repetition}; duration={duration}s ===", flush=True)

    # Stop a previous iperf server, then start a UDP server at the receiving host.
    h300.cmd("pkill -x iperf >/dev/null 2>&1 || true")
    h300.cmd("iperf -s -u > /work/iperf_server.log 2>&1 &")
    time.sleep(1)

    before = snapshot()
    print("TX counters before:", before, flush=True)
    cmd = f"iperf -c 10.3.0.2 -u -b 1M -P {flows} -t {duration}"
    print("h000$ " + cmd, flush=True)
    iperf_output = h000.cmd(cmd + " 2>&1")
    after = snapshot()

    # Keep the original client output intact as reproducible assignment evidence.
    log_path = WORKDIR / f"iperf_N{flows}_run{repetition}.txt"
    log_path.write_text("h000$ " + cmd + "\n" + iperf_output)
    print("\niperf output (last 12 lines):", flush=True)
    print("\n".join(iperf_output.splitlines()[-12:]), flush=True)
    print("Complete iperf output:", log_path, flush=True)

    if "connect failed" in iperf_output.lower() or "command not found" in iperf_output.lower():
        print("ERROR: iperf failed; do not use this trial as valid data.", flush=True)
        return
    if not any("bits/sec" in line for line in iperf_output.splitlines()):
        print("WARNING: no iperf throughput summary was detected; inspect the saved log.", flush=True)

    deltas = {name: after[name] - before[name] for name in CORE_LINKS}
    total = sum(deltas.values())
    if total <= 0 or any(value < 0 for value in deltas.values()):
        print("ERROR: invalid counter deltas; inspect switch interfaces.", flush=True)
        return

    busiest_share = 100 * max(deltas.values()) / total
    max_to_mean = 4 * max(deltas.values()) / total
    print("\nCore-facing link counters:", flush=True)
    print(f"{'Interface':<12} {'Core':<5} {'Before':>14} {'After':>14} {'Delta bytes':>14} {'Share':>9}", flush=True)
    for name, core in CORE_LINKS.items():
        print(f"{name:<12} {core:<5} {before[name]:>14,} {after[name]:>14,} "
              f"{deltas[name]:>14,} {100*deltas[name]/total:>8.2f}%", flush=True)
    print(f"TOTAL delta bytes: {total:,}", flush=True)
    print(f"Busiest link share: {busiest_share:.2f}%", flush=True)
    print(f"Max/mean traffic ratio: {max_to_mean:.3f}", flush=True)

    fieldnames = ["recorded_utc", "flows", "repetition", "duration_s", "interface", "core",
                  "before_bytes", "after_bytes", "delta_bytes", "share_pct",
                  "busiest_share_pct", "max_to_mean"]
    needs_header = not RESULTS_PATH.exists() or RESULTS_PATH.stat().st_size == 0
    with RESULTS_PATH.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if needs_header:
            writer.writeheader()
        for name, core in CORE_LINKS.items():
            writer.writerow({
                "recorded_utc": datetime.now(timezone.utc).isoformat(),
                "flows": flows,
                "repetition": repetition,
                "duration_s": duration,
                "interface": name,
                "core": core,
                "before_bytes": before[name],
                "after_bytes": after[name],
                "delta_bytes": deltas[name],
                "share_pct": round(100 * deltas[name] / total, 4),
                "busiest_share_pct": round(busiest_share, 4),
                "max_to_mean": round(max_to_mean, 5),
            })
    print(f"Saved CSV results: {RESULTS_PATH}\n", flush=True)
