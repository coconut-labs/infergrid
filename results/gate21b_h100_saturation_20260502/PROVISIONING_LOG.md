# Gate 2.1b — Provisioning Log

## Pod attempts

|#|Pod ID|Machine ID|GPU type|Spin start (UTC)|Outcome|Wall (min)|Cost ($)|
|---|---|---|---|---|---|---:|---:|
|1|q4vw7kj8xt8wdt|lg4oogypa290|H100 SXM 80GB|2026-05-02 22:08:32|Terminated; runtime=null at 12 min (premature, retro)|11.5|0.57|
|2|4jc34h0vu9zbrq|lg4oogypa290|H100 SXM 80GB|2026-05-02 22:20:29|Terminated; runtime=null at 3.5 min (premature, retro)|3.5|0.17|
|3|qmflcgrv2vpxvt|lg4oogypa290|H100 SXM 80GB|2026-05-02 22:24:29|Terminated; runtime=null at 18 min (advisor patience boundary)|18.0|0.90|

Cumulative provisioning sunk cost: **$1.64**.

All three pods landed on machine `lg4oogypa290`. The first two were terminated prematurely (advisor retro: image-pull on a fresh node can take 10-15 min; terminating before that resets pull progress). Pod #3 was held to the 18-minute patience boundary per advisor guidance and the RunPod GraphQL API never produced a `runtime` block (no SSH ports, no in-pod state).

## What "runtime=null" likely indicated

`runtime: null` from RunPod's GraphQL `pod` query means the orchestration layer hasn't acknowledged the container as up. Likely root cause was a slow or hung image-pull of `runpod/pytorch:2.1.0-py3.10-cuda12.1.1-devel-ubuntu22.04` on the assigned machine. Image is multi-GB; a fresh node without it cached can take 10-15 min, but anything past 18 min suggests either a network-bound retry loop or a stuck pull. Without in-pod logs (no SSH ports → no observability) the cause stayed inferential.

## Why three attempts, not retried more

Task spec says "If H100 SXM SECURE not available at create time, fall back to H100 PCIe SECURE. Don't spin up SPOT for stability." H100 PCIe SECURE was unavailable at provision time (lowestPrice = null = no slot). H100 SXM SECURE returned the same machine `lg4oogypa290` on each `podFindAndDeployOnDemand` call — RunPod's scheduler kept routing to the same physical slot which was apparently not making progress past whatever stage gates `runtime` from null to populated. After three attempts on the same slot, escalating further is throwing good money after bad.

## Decision

Aborted at 22:42:30 UTC, total provisioning sunk **$1.64** of $5 cap. No bench cells run.
