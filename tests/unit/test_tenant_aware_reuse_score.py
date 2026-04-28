"""Pin the W4-W6 tenant-aware reuse_score semantics (strict-xfail until impl).

Each test asserts a strict inequality that fails on the W1 stub (which strips
`policy`) and will pass once the W4 implementation lands. With `strict=True`,
the day W4 lands these flip xfail -> xpass and CI fails the build until the
implementer clears the marker.

# T2 — issue #103, RFC at docs/rfcs/T2-tenant-aware-eviction.md
"""

from __future__ import annotations

import time

import pytest

from kvwarden.cache.manager import CacheBlock, TenantPolicy


def _block(
    tenant_id: str | None,
    *,
    access_count: int = 10,
    age_s: float = 0.0,
    now: float | None = None,
) -> CacheBlock:
    """Helper: build a CacheBlock with a chosen tenant + freshness."""
    if now is None:
        now = time.monotonic()
    return CacheBlock(
        block_id=f"b-{tenant_id or 'anon'}",
        model_id="m",
        request_id="r",
        tier="gpu",
        num_tokens=16,
        access_count=access_count,
        last_access_time=now - age_s,
        tenant_id=tenant_id,
    )


@pytest.mark.xfail(reason="T2 W4-W6 semantics", strict=True)
def test_flooder_weight_scales_score_down() -> None:
    """A flooder block at weight=0.1 must score strictly below a quiet peer."""
    now = time.monotonic()
    policy = TenantPolicy(tenant_weights={"flooder": 0.1, "quiet": 1.0})
    flooder = _block("flooder", now=now)
    quiet = _block("quiet", now=now)
    assert flooder.reuse_score(now, policy=policy) < 0.5 * quiet.reuse_score(
        now, policy=policy
    )


@pytest.mark.xfail(reason="T2 W4-W6 semantics", strict=True)
def test_unknown_tenant_defaults_to_weight_one() -> None:
    """A tenant_id absent from `tenant_weights` falls back to weight 1.0."""
    now = time.monotonic()
    policy = TenantPolicy(tenant_weights={"flooder": 0.1})
    mystery = _block("mystery", now=now)
    flooder = _block("flooder", now=now)
    # weight(mystery)=1.0, weight(flooder)=0.1 -> mystery should score ~10x
    assert mystery.reuse_score(now, policy=policy) > 5.0 * flooder.reuse_score(
        now, policy=policy
    )


@pytest.mark.xfail(reason="T2 W4-W6 semantics", strict=True)
def test_none_tenant_id_defaults_to_weight_one() -> None:
    """A block with `tenant_id=None` falls back to weight 1.0 (graceful)."""
    now = time.monotonic()
    policy = TenantPolicy(tenant_weights={"flooder": 0.1})
    anon = _block(None, now=now)
    flooder = _block("flooder", now=now)
    assert anon.reuse_score(now, policy=policy) > 5.0 * flooder.reuse_score(
        now, policy=policy
    )


@pytest.mark.xfail(reason="T2 W4-W6 semantics", strict=True)
def test_eviction_order_flooder_before_quiet() -> None:
    """Under shared base (same recency/freq), flooder scores below quiet.

    `_evict_from_tier` sorts by `reuse_score`, lowest first, so the flooder
    block evicts before the quiet one once W4 lands.
    """
    now = time.monotonic()
    policy = TenantPolicy(tenant_weights={"flooder": 0.1, "quiet": 1.0})
    flooder = _block("flooder", now=now)
    quiet = _block("quiet", now=now)
    assert flooder.reuse_score(now, policy=policy) < quiet.reuse_score(
        now, policy=policy
    )


@pytest.mark.xfail(reason="T2 W4-W6 semantics", strict=True)
def test_recency_dominance_recent_flooder_beats_stale_quiet() -> None:
    """Tenant weight scales but does not override recency.

    A 0.1× flooder that was just touched should still beat a quiet block that's
    been stale for 10 minutes. Anti-XPASS rider asserts policy did something.
    """
    now = time.monotonic()
    policy = TenantPolicy(tenant_weights={"flooder": 0.1, "quiet": 1.0})
    recent_flooder = _block("flooder", access_count=10, age_s=0, now=now)
    stale_quiet = _block("quiet", access_count=10, age_s=600, now=now)
    weighted = recent_flooder.reuse_score(now, policy=policy)
    unweighted = recent_flooder.reuse_score(now)
    assert weighted > stale_quiet.reuse_score(now, policy=policy)
    assert weighted < unweighted  # confirms policy actually scaled the score


@pytest.mark.xfail(reason="T2 W4-W6 semantics", strict=True)
def test_frequency_dominance_frequent_flooder_beats_rare_quiet() -> None:
    """Tenant weight scales but does not override access_count.

    A 0.1× flooder accessed 1000× should still beat a quiet block accessed
    once. Anti-XPASS rider asserts policy did something.
    """
    now = time.monotonic()
    policy = TenantPolicy(tenant_weights={"flooder": 0.1, "quiet": 1.0})
    frequent_flooder = _block("flooder", access_count=1000, age_s=120, now=now)
    rare_quiet = _block("quiet", access_count=1, age_s=0, now=now)
    weighted = frequent_flooder.reuse_score(now, policy=policy)
    unweighted = frequent_flooder.reuse_score(now)
    assert weighted > rare_quiet.reuse_score(now, policy=policy)
    assert weighted < unweighted  # confirms policy actually scaled the score


@pytest.mark.xfail(reason="T2 W4-W6 semantics", strict=True)
def test_zero_weight_tenant_evicts_first_unconditionally() -> None:
    """A zero-weight tenant's blocks score below any positive-weight peer.

    Even when the zero-weight block is recent and frequent, it should evict
    first because 0 * anything = 0.
    """
    now = time.monotonic()
    policy = TenantPolicy(tenant_weights={"banned": 0.0, "quiet": 1.0})
    banned = _block("banned", access_count=100, age_s=0, now=now)
    quiet = _block("quiet", access_count=2, age_s=60, now=now)
    assert banned.reuse_score(now, policy=policy) < quiet.reuse_score(
        now, policy=policy
    )


@pytest.mark.xfail(reason="T2 W4-W6 semantics", strict=True)
def test_vip_weight_above_one_holds_blocks_longer() -> None:
    """A VIP tenant with weight=2.0 retains blocks past where they'd evict.

    VIP block is somewhat stale (base score ~ 96% of quiet's), but the 2× boost
    flips the eviction order so VIP wins.
    """
    now = time.monotonic()
    policy = TenantPolicy(tenant_weights={"vip": 2.0, "quiet": 1.0})
    vip = _block("vip", access_count=10, age_s=120, now=now)
    quiet = _block("quiet", access_count=10, age_s=0, now=now)
    assert vip.reuse_score(now, policy=policy) > quiet.reuse_score(now, policy=policy)


@pytest.mark.xfail(reason="T2 W4-W6 semantics", strict=True)
def test_policy_application_is_deterministic_across_calls() -> None:
    """Repeat calls with the same policy + clock yield the same score.

    Pins that policy application is a pure function of (block, now, policy).
    Today: passes trivially. Post-W4: must continue to hold so this xfail
    flips at the same moment as the others (clean sweep for the implementer).
    """
    now = time.monotonic()
    policy = TenantPolicy(tenant_weights={"flooder": 0.1})
    flooder = _block("flooder", now=now)
    quiet = _block("quiet", now=now)
    s1 = flooder.reuse_score(now, policy=policy)
    s2 = flooder.reuse_score(now, policy=policy)
    # Pin determinism AND that policy actually changed something vs no-policy.
    assert s1 == s2
    assert s1 < quiet.reuse_score(now, policy=policy)
