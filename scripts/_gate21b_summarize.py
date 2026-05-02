#!/usr/bin/env python3
"""Gate 2.1b summary computer.

For each cell directory under results/gate21b_h100_saturation_20260502/,
parse:
  - benchmarks/summary.json    -> p99 TTFT per quiet, post-warmup
  - <cell>_engine_metrics.csv  -> in-flight peak across the cell
Compute aggregate quiet p99 (median across 7 quiets, median across seeds).

Usage:
    python3 _gate21b_summarize.py results/gate21b_h100_saturation_20260502
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import tarfile
from pathlib import Path


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def parse_cell_summary(summary_path: Path) -> dict:
    """Pull per-tenant TTFT p99 from a benchmark summary.json.

    Schema (benchmark_n_tenant_single_model.py):
      - flooder: dict with count_ok / count_err / ttft_p50_ms / ttft_p99_ms / ttft_max_ms
      - quiet_aggregate: dict, same keys
      - quiet_per_tenant: { "quiet_0": dict, ..., "quiet_6": dict }
    """
    if not summary_path.exists():
        return {}
    data = json.loads(summary_path.read_text())
    out: dict = {"quiet_p99_per_tenant_ms": {}}

    flood = data.get("flooder", {}) or {}
    out["flooder_count_ok"] = flood.get("count_ok")
    out["flooder_count_err"] = flood.get("count_err")
    out["flooder_p99_ms"] = flood.get("ttft_p99_ms")
    out["flooder_p50_ms"] = flood.get("ttft_p50_ms")

    qagg = data.get("quiet_aggregate", {}) or {}
    out["quiet_agg_p99_ms"] = qagg.get("ttft_p99_ms")
    out["quiet_agg_p50_ms"] = qagg.get("ttft_p50_ms")
    out["quiet_agg_count_ok"] = qagg.get("count_ok")
    out["quiet_agg_count_err"] = qagg.get("count_err")

    for name, summ in (data.get("quiet_per_tenant") or {}).items():
        ttft_p99 = (summ or {}).get("ttft_p99_ms")
        if ttft_p99 is not None and ttft_p99 > 0:
            out["quiet_p99_per_tenant_ms"][name] = ttft_p99
    out["wall_time_s"] = data.get("wall_time_s")
    return out


def parse_engine_metrics(csv_path: Path) -> dict:
    if not csv_path.exists():
        return {}
    in_flight = []
    waiting = []
    with csv_path.open() as fh:
        r = csv.DictReader(fh)
        for row in r:
            try:
                rv = float(row.get("num_requests_running", "NaN"))
                if not math.isnan(rv):
                    in_flight.append(rv)
            except ValueError:
                pass
            try:
                wv = float(row.get("num_requests_waiting", "NaN"))
                if not math.isnan(wv):
                    waiting.append(wv)
            except ValueError:
                pass
    return {
        "in_flight_peak": max(in_flight) if in_flight else float("nan"),
        "in_flight_p50": _percentile(in_flight, 0.5) if in_flight else float("nan"),
        "in_flight_p99": _percentile(in_flight, 0.99) if in_flight else float("nan"),
        "waiting_peak": max(waiting) if waiting else float("nan"),
        "samples": len(in_flight),
    }


def extract_summary_from_tar(tar_path: Path, dest: Path) -> Path | None:
    if not tar_path.exists():
        return None
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tf:
        for m in tf.getmembers():
            if m.name.endswith("benchmarks/summary.json") or m.name.endswith(
                "/summary.json"
            ):
                tf.extract(m, dest)
                return dest / m.name
    return None


def main(root: Path) -> int:
    cells = []
    for tar in sorted(root.glob("cell*.tar.gz")):
        cell_name = tar.stem  # e.g. cellA_seed0
        local_extract = root / "_extracted" / cell_name
        summary_path = extract_summary_from_tar(tar, local_extract)
        per_request_csv = None
        # Pull all CSVs for the per_request artifact
        with tarfile.open(tar, "r:gz") as tf:
            for m in tf.getmembers():
                if m.name.endswith(".csv") and "tenant_" in m.name:
                    tf.extract(m, local_extract)

        summ = parse_cell_summary(summary_path) if summary_path else {}
        metrics_path = root / f"{cell_name}_engine_metrics.csv"
        metrics = parse_engine_metrics(metrics_path)
        cells.append(
            {
                "name": cell_name,
                "summary_path": str(summary_path) if summary_path else None,
                "metrics_path": str(metrics_path) if metrics_path.exists() else None,
                **summ,
                **metrics,
            }
        )

    # Aggregate per arm.
    out = {"cells": cells, "agg": {}}
    for arm in ("cellA", "cellB"):
        arm_cells = [c for c in cells if c["name"].startswith(arm)]
        if not arm_cells:
            continue
        all_p99s = []
        for c in arm_cells:
            per_tenant = c.get("quiet_p99_per_tenant_ms", {})
            if not per_tenant:
                continue
            # median across the 7 quiets for THIS seed
            seed_med = statistics.median(per_tenant.values())
            all_p99s.append(seed_med)
        if all_p99s:
            out["agg"][arm] = {
                "median_across_seeds_quiet_p99_ms": statistics.median(all_p99s),
                "min_seed_quiet_p99_ms": min(all_p99s),
                "max_seed_quiet_p99_ms": max(all_p99s),
                "n_seeds": len(all_p99s),
            }

    if "cellA" in out["agg"] and "cellB" in out["agg"]:
        a = out["agg"]["cellA"]["median_across_seeds_quiet_p99_ms"]
        b = out["agg"]["cellB"]["median_across_seeds_quiet_p99_ms"]
        out["agg"]["ratio_A_over_B"] = a / b if b else float("nan")

    print(json.dumps(out, indent=2, default=str))
    summary_out = root / "summary.json"
    summary_out.write_text(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
