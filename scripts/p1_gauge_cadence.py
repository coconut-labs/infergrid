#!/usr/bin/env python3
"""
T2 P1 gauge cadence probe. Runs on the pod, loopback to vLLM.

Two coroutines for `duration_s` seconds:
  * load: issues /v1/completions at `load_rps` to drive cache occupancy.
  * scrape: hits /metrics at `scrape_hz` and records (t, gauge_value) tuples.

Output: --out JSON with the raw timeline plus distribution of time-between-
distinct-gauge-values. The orchestrator reads this and the gauge is judged
"updates >= 1 Hz" iff p95 of inter-distinct-update interval is <= 1.0s.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import time
from typing import Optional

import aiohttp

GAUGE_LINE_RE = re.compile(
    r'^vllm:kv_cache_usage_perc\{[^}]*\}\s+([0-9.eE+\-]+)', re.MULTILINE
)


async def scrape_metrics(session: aiohttp.ClientSession, base: str) -> Optional[float]:
    try:
        async with session.get(f"{base}/metrics", timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
            text = await resp.text()
            m = GAUGE_LINE_RE.search(text)
            if m:
                return float(m.group(1))
            return None
    except Exception:
        return None


async def post_completion(session: aiohttp.ClientSession, base: str, model: str, idx: int) -> None:
    body = {
        "model": model,
        "prompt": (
            f"Tell me a short story about a robot named {idx}. "
            f"Keep it under 50 tokens. Story:"
        ),
        "max_tokens": 32,
        "temperature": 0.0,
    }
    try:
        async with session.post(
            f"{base}/v1/completions",
            json=body,
            timeout=aiohttp.ClientTimeout(total=15.0),
        ) as resp:
            await resp.read()
    except Exception:
        pass


async def load_loop(session, base: str, model: str, rps: float, duration_s: float) -> int:
    interval = 1.0 / rps
    deadline = time.monotonic() + duration_s
    inflight: list[asyncio.Task] = []
    i = 0
    while time.monotonic() < deadline:
        inflight.append(asyncio.create_task(post_completion(session, base, model, i)))
        i += 1
        await asyncio.sleep(interval)
    await asyncio.gather(*inflight, return_exceptions=True)
    return i


async def scrape_loop(session, base: str, hz: float, duration_s: float) -> list[tuple[float, Optional[float]]]:
    interval = 1.0 / hz
    deadline = time.monotonic() + duration_s
    samples: list[tuple[float, Optional[float]]] = []
    t0 = time.monotonic()
    while time.monotonic() < deadline:
        sample_t = time.monotonic() - t0
        v = await scrape_metrics(session, base)
        samples.append((sample_t, v))
        # bound jitter
        next_t = sample_t + interval
        sleep_for = max(0.0, next_t - (time.monotonic() - t0))
        await asyncio.sleep(sleep_for)
    return samples


def analyze(samples: list[tuple[float, Optional[float]]]) -> dict:
    """Distribution of time between distinct gauge values."""
    valid = [(t, v) for t, v in samples if v is not None]
    distinct_intervals = []
    last_t = None
    last_v = None
    for t, v in valid:
        if last_v is None or v != last_v:
            if last_t is not None:
                distinct_intervals.append(t - last_t)
            last_t = t
            last_v = v
    summary = {
        "samples_total": len(samples),
        "samples_with_value": len(valid),
        "distinct_value_count": 1 + len(distinct_intervals),
        "distinct_intervals_n": len(distinct_intervals),
    }
    if distinct_intervals:
        intervals_sorted = sorted(distinct_intervals)

        def pct(p: float) -> float:
            n = len(intervals_sorted)
            idx = max(0, min(n - 1, int(round(p / 100.0 * (n - 1)))))
            return intervals_sorted[idx]

        summary.update({
            "interval_min_s": min(distinct_intervals),
            "interval_max_s": max(distinct_intervals),
            "interval_p50_s": pct(50),
            "interval_p95_s": pct(95),
            "interval_p99_s": pct(99),
            "interval_mean_s": statistics.mean(distinct_intervals),
        })
    if valid:
        vals = [v for _, v in valid]
        summary["gauge_value_min"] = min(vals)
        summary["gauge_value_max"] = max(vals)
        summary["gauge_value_first"] = vals[0]
        summary["gauge_value_last"] = vals[-1]
    return summary


async def main_async(args: argparse.Namespace) -> int:
    timeout = aiohttp.ClientTimeout(total=20.0)
    # No SSL verify: short-lived RunPod proxy endpoint, IP and pod-id known.
    # Mac Python 3.13 ships without default CAs which would otherwise block
    # every request silently. The on-pod loopback path doesn't hit this.
    connector = aiohttp.TCPConnector(limit=64, ssl=False)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        load_task = asyncio.create_task(
            load_loop(session, args.url, args.model, args.load_rps, args.duration_s)
        )
        scrape_task = asyncio.create_task(
            scrape_loop(session, args.url, args.scrape_hz, args.duration_s)
        )
        sent, samples = await asyncio.gather(load_task, scrape_task)

    analysis = analyze(samples)
    out = {
        "params": {
            "url": args.url,
            "model": args.model,
            "duration_s": args.duration_s,
            "scrape_hz": args.scrape_hz,
            "load_rps": args.load_rps,
        },
        "load_requests_sent": sent,
        "samples": [{"t": t, "v": v} for t, v in samples],
        "analysis": analysis,
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)
    print(json.dumps(analysis, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--duration-s", type=float, default=60.0)
    p.add_argument("--scrape-hz", type=float, default=4.0)
    p.add_argument("--load-rps", type=float, default=4.0)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
