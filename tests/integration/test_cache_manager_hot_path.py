"""Pin the eventual router -> cache_manager hot-path wiring (skip until W4).

These tests assume per-request `allocate_block` / `access_block` calls flow
from the router with a `tenant_id` tag. That wiring does not exist today —
the router only calls `free_blocks_for_model` and `snapshot`. Bodies are
skeletal; the skip marker keeps CI green until W4 wires them.

# T2 — issue #103, RFC at docs/rfcs/T2-tenant-aware-eviction.md
"""

from __future__ import annotations

import pytest

from kvwarden.cache.manager import CacheManager, TenantPolicy


def _make_manager() -> CacheManager:
    return CacheManager(
        tier_capacities_gb={"gpu": 0.001, "cpu": 0.01, "ssd": 0.1},
        block_size_tokens=16,
    )


@pytest.mark.skip(reason="T2 W4 hot-path wiring")
def test_tagged_request_propagates_tenant_id_to_block() -> None:
    """End-to-end: a request tagged with tenant_id results in a block carrying
    that tenant_id in CacheManager's internal state."""
    cm = _make_manager()
    # TODO(T2-W4): wire router -> cache_manager.allocate_block per request.
    # Once wired, the router will hash the prompt prefix into block_id and
    # forward the tenant_id from the admission-controller context.
    block = cm.allocate_block(
        "b1", "model-a", "req-1", num_tokens=16, tenant_id="flooder"
    )
    assert block is not None
    assert block.tenant_id == "flooder"


@pytest.mark.skip(reason="T2 W4 hot-path wiring")
def test_same_tenant_same_prefix_reuses_block() -> None:
    """Two requests from the same tenant sharing a prompt prefix should hit
    the same block on the second pass (or bump access_count via access_block)."""
    cm = _make_manager()
    # TODO(T2-W4): router hashes prefix -> block_id; second request with the
    # same prefix should call cm.access_block(block_id) instead of allocating
    # a fresh one. For now, simulate the pattern with explicit IDs.
    cm.allocate_block(
        "prefix-hash-A", "model-a", "req-1", num_tokens=16, tenant_id="quiet"
    )
    block = cm.access_block("prefix-hash-A")
    assert block is not None
    assert block.access_count == 2


@pytest.mark.skip(reason="T2 W4 hot-path wiring")
def test_capacity_pressure_evicts_flooder_before_quiet() -> None:
    """Two tenants competing under capacity pressure: flooder's blocks evict
    first when a non-empty TenantPolicy is wired into _evict_from_tier."""
    cm = _make_manager()
    policy = TenantPolicy(tenant_weights={"flooder": 0.1, "quiet": 1.0})
    # TODO(T2-W4): wire CacheManager to consult `policy` during _evict_from_tier.
    # The construction signature for that wiring is undecided — likely a
    # `policy=` kwarg on CacheManager.__init__ or a setter. RFC pending.
    # TODO(T2-W4): allocate flooder + quiet blocks, push past capacity, assert
    # flooder blocks were the ones evicted.
    del cm, policy  # silence unused-var while skipped


@pytest.mark.skip(reason="T2 W4 hot-path wiring")
def test_snapshot_includes_per_tenant_block_counts() -> None:
    """`CacheManager.snapshot()` should expose per-tenant block counts once
    the hot path is tagging blocks. The snapshot key is undecided (likely
    `tenant_blocks` parallel to `model_blocks`); RFC pending."""
    cm = _make_manager()
    # TODO(T2-W4): allocate blocks across two tenants, then check
    # snap["tenant_blocks"] == {"flooder": N, "quiet": M}.
    snap = cm.snapshot()
    assert "tenant_blocks" in snap  # key name pending RFC sign-off
