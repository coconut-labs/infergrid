#!/usr/bin/env python3
"""Discriminator test for the real-TTFT fix in benchmark_multi_model.py.

The bug (caveat C2 in results/CORRECTIONS.md): the bench harness was timing
TTFT to the first SSE `data: ...` line, not to the first chunk that actually
contained non-empty `choices[0].text`. Over localhost the gap is ~5 ms; over
network it is the round-trip latency. Reported TTFTs were therefore SSE
first-frame RTTs, not the metric a paper or LP screenshot should use.

This test:
    1. Spawns mock_engine.py with --delay-first-content-s 0.5, which emits
       an empty-text SSE preamble immediately, then sleeps 500 ms before the
       first real-content chunk.
    2. Drives the actual MultiModelBenchmarkClient._send_request code path.
    3. Asserts TTFT > 400 ms.

If the bug returns (someone moves the first_token_time assignment back above
the non-empty-text check), this test reports ~5-50 ms and fails.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from benchmark_multi_model import MultiModelBenchmarkClient  # noqa: E402


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


async def wait_ready(url: str, timeout_s: float = 10.0) -> None:
    end = time.time() + timeout_s
    async with aiohttp.ClientSession() as s:
        while time.time() < end:
            try:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=1)) as r:
                    if r.status == 200:
                        return
            except Exception:
                pass
            await asyncio.sleep(0.1)
    raise RuntimeError(f"mock not ready at {url} after {timeout_s}s")


async def measure_ttft(base_url: str, model: str) -> float:
    client = MultiModelBenchmarkClient(
        base_url=base_url, concurrency=1, timeout_s=30, max_tokens=8
    )
    sem = asyncio.Semaphore(1)
    async with aiohttp.ClientSession() as session:
        m = await client._send_request(session, 0, model, "hello", 8, sem)
    if m.error:
        raise RuntimeError(f"bench request error: {m.error}")
    return m.ttft_ms


async def main() -> int:
    port = free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(HERE / "mock_engine.py"),
            "--port", str(port),
            "--model", "discriminator-model",
            "--ok-latency-s", "0.05",
            "--delay-first-content-s", "0.5",
            "--log-level", "WARNING",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        await wait_ready(f"{base_url}/v1/models", timeout_s=10.0)
        ttft_ms = await measure_ttft(base_url, "discriminator-model")
        print(f"discriminator ttft_ms = {ttft_ms:.1f}")
        if ttft_ms <= 400.0:
            print(
                f"FAIL: REAL-TTFT REGRESSION. ttft_ms={ttft_ms:.1f} but mock "
                "delays first non-empty content by 500 ms. The harness is "
                "timing the empty SSE preamble as the first token (caveat C2)."
            )
            return 1
        print("OK: real-TTFT discriminator passed (>400ms with 500ms delay)")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
