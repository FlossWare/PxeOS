#!/usr/bin/env python3
"""Benchmark script for PxeOS concurrent PXE boot requests.

Simulates N concurrent PXE boot requests against the FastAPI test client
(in-process, no network) to measure throughput and latency under load.

Usage::

    python scripts/benchmark_pxe.py [--concurrency 100] [--rounds 3]

Requires the ``pxeos`` package to be installed (or on sys.path).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

# Ensure the project root is on sys.path when run as a script.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _make_mac(index: int) -> str:
    """Generate a deterministic MAC address from an index."""
    b = index.to_bytes(3, "big")
    return f"aa:bb:cc:{b[0]:02x}:{b[1]:02x}:{b[2]:02x}"


def _setup_app(num_hosts: int, tmp_dir: Path):
    """Configure the FastAPI app with *num_hosts* host rules."""
    from pxeos.api import init_app
    from pxeos.config import PxeOSConfig
    from pxeos.matcher import HostMatcher
    from pxeos.models import HostRule
    from pxeos.registry import PluginRegistry

    data_dir = tmp_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    distro_dir = tmp_dir / "distros"
    distro_dir.mkdir(parents=True, exist_ok=True)

    rules = [
        HostRule(
            profile=f"bench-{i}",
            os_family="fedora",
            os_version="40",
            mac=_make_mac(i),
        )
        for i in range(num_hosts)
    ]

    registry = PluginRegistry()
    registry.load_builtins()
    config = PxeOSConfig(
        data_dir=data_dir,
        distro_root=distro_dir,
        server_host="127.0.0.1",
        server_port=8443,
    )
    matcher = HostMatcher(rules)
    init_app(registry, config, matcher)

    from pxeos.api import app
    return app


def _benchmark_endpoint(
    app,
    endpoint_fn,
    concurrency: int,
    num_hosts: int,
) -> Dict:
    """Run concurrent requests and collect latency data."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    latencies: List[float] = []
    errors = 0

    def single_request(idx: int):
        mac = _make_mac(idx % num_hosts)
        url = endpoint_fn(mac)
        start = time.perf_counter()
        resp = client.get(url)
        elapsed = time.perf_counter() - start
        return elapsed, resp.status_code

    with ThreadPoolExecutor(max_workers=min(concurrency, 64)) as pool:
        futures = {
            pool.submit(single_request, i): i
            for i in range(concurrency)
        }
        for future in as_completed(futures):
            try:
                elapsed, status = future.result()
                if 200 <= status < 300:
                    latencies.append(elapsed)
                else:
                    errors += 1
            except Exception:
                errors += 1

    if not latencies:
        return {
            "requests": concurrency,
            "successes": 0,
            "errors": errors,
            "error_rate": 1.0,
        }

    latencies.sort()
    total_time = sum(latencies)
    return {
        "requests": concurrency,
        "successes": len(latencies),
        "errors": errors,
        "error_rate": round(errors / concurrency, 4),
        "total_time_s": round(total_time, 4),
        "requests_per_sec": round(len(latencies) / total_time, 2) if total_time > 0 else 0,
        "p50_ms": round(latencies[len(latencies) // 2] * 1000, 2),
        "p95_ms": round(latencies[int(len(latencies) * 0.95)] * 1000, 2),
        "p99_ms": round(latencies[int(len(latencies) * 0.99)] * 1000, 2),
        "min_ms": round(min(latencies) * 1000, 2),
        "max_ms": round(max(latencies) * 1000, 2),
        "mean_ms": round(statistics.mean(latencies) * 1000, 2),
        "stdev_ms": round(statistics.stdev(latencies) * 1000, 2) if len(latencies) > 1 else 0,
    }


def run_benchmark(
    concurrency: int = 100,
    rounds: int = 3,
    num_hosts: int = 50,
) -> Dict:
    """Run the full benchmark suite.

    Returns a dict with results for each endpoint and round.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="pxeos-bench-") as tmp:
        tmp_dir = Path(tmp)
        app = _setup_app(num_hosts, tmp_dir)

        endpoints = {
            "boot": lambda mac: f"/api/v1/boot/{mac}",
            "autoinstall": lambda mac: f"/api/v1/autoinstall/{mac}",
        }

        results: Dict = {"concurrency": concurrency, "rounds": rounds, "endpoints": {}}

        for ep_name, ep_fn in endpoints.items():
            round_results = []
            for r in range(rounds):
                data = _benchmark_endpoint(app, ep_fn, concurrency, num_hosts)
                round_results.append(data)
            results["endpoints"][ep_name] = round_results

        return results


def print_report(results: Dict) -> None:
    """Print a human-readable benchmark report."""
    print(f"\n{'=' * 60}")
    print(f"PxeOS Benchmark Report")
    print(f"Concurrency: {results['concurrency']}  Rounds: {results['rounds']}")
    print(f"{'=' * 60}")

    for ep_name, rounds in results["endpoints"].items():
        print(f"\n--- {ep_name.upper()} endpoint ---")
        for i, r in enumerate(rounds):
            if "p50_ms" not in r:
                print(f"  Round {i + 1}: ALL ERRORS ({r.get('errors', '?')})")
                continue
            print(
                f"  Round {i + 1}: "
                f"{r['requests_per_sec']} req/s | "
                f"p50={r['p50_ms']}ms p95={r['p95_ms']}ms p99={r['p99_ms']}ms | "
                f"errors={r['errors']}"
            )

    print(f"\n{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark PxeOS concurrent PXE boot handling",
    )
    parser.add_argument(
        "--concurrency", "-c", type=int, default=100,
        help="Number of concurrent requests per round (default: 100)",
    )
    parser.add_argument(
        "--rounds", "-r", type=int, default=3,
        help="Number of rounds per endpoint (default: 3)",
    )
    parser.add_argument(
        "--hosts", "-n", type=int, default=50,
        help="Number of distinct host rules (default: 50)",
    )
    args = parser.parse_args()

    results = run_benchmark(
        concurrency=args.concurrency,
        rounds=args.rounds,
        num_hosts=args.hosts,
    )
    print_report(results)


if __name__ == "__main__":
    main()
