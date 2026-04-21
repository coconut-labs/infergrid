"""Unit tests for Gate 2.2 --prompt-length-dist flag and sampler.

Covers the parse validator (shape + three fail-fast rules), the seed-stable
mixed-length sampler, the legacy (no-flag) path's backward compatibility,
and an end-to-end parse + sample smoke test that never fires HTTP.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

# Add the benchmark script dir so we can import the module under test.
_BENCH_SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent / "benchmarks" / "scripts"
)
sys.path.insert(0, str(_BENCH_SCRIPTS))

from benchmark_n_tenant_single_model import (  # noqa: E402
    PROMPTS,
    make_legacy_sampler,
    make_mixed_length_sampler,
    parse_prompt_length_dist,
)

# ---------------------------------------------------------------------------
# parse_prompt_length_dist — happy path + three fail-fast rules
# ---------------------------------------------------------------------------


class TestParsePromptLengthDist:
    def test_parses_valid_spec(self) -> None:
        spec = "64:0.4,512:0.3,2048:0.2,8192:0.1"
        result = parse_prompt_length_dist(spec)
        assert result == [(64, 0.4), (512, 0.3), (2048, 0.2), (8192, 0.1)]

    def test_parses_single_bucket(self) -> None:
        # Edge case: one length with p=1.0 is legal.
        assert parse_prompt_length_dist("128:1.0") == [(128, 1.0)]

    def test_tolerates_whitespace(self) -> None:
        spec = " 64 : 0.5 , 512 : 0.5 "
        assert parse_prompt_length_dist(spec) == [(64, 0.5), (512, 0.5)]

    def test_rejects_probabilities_summing_to_0_8(self) -> None:
        # Clearly wrong: 0.4 + 0.3 + 0.1 = 0.8, > 0.001 off from 1.0.
        with pytest.raises(ValueError, match="sum"):
            parse_prompt_length_dist("64:0.4,512:0.3,2048:0.1")

    def test_rejects_probabilities_slightly_over_tolerance(self) -> None:
        # 0.5 + 0.499 = 0.999, within tol. 0.5 + 0.495 = 0.995, NOT within tol.
        with pytest.raises(ValueError, match="sum"):
            parse_prompt_length_dist("64:0.5,512:0.495")

    def test_accepts_probabilities_at_tolerance_edge(self) -> None:
        # 0.5 + 0.4995 = 0.9995, within 0.001 tolerance.
        result = parse_prompt_length_dist("64:0.5,512:0.4995")
        assert len(result) == 2

    def test_rejects_non_numeric_length(self) -> None:
        with pytest.raises(ValueError, match="non-numeric length"):
            parse_prompt_length_dist("abc:0.5,512:0.5")

    def test_rejects_non_numeric_probability(self) -> None:
        with pytest.raises(ValueError, match="non-numeric probability"):
            parse_prompt_length_dist("64:xyz,512:0.5")

    def test_rejects_non_positive_length(self) -> None:
        with pytest.raises(ValueError, match="non-positive length"):
            parse_prompt_length_dist("0:0.5,512:0.5")

    def test_rejects_negative_length(self) -> None:
        with pytest.raises(ValueError, match="non-positive length"):
            parse_prompt_length_dist("-64:0.5,512:0.5")

    def test_rejects_empty_spec(self) -> None:
        with pytest.raises(ValueError):
            parse_prompt_length_dist("")

    def test_rejects_malformed_entry(self) -> None:
        with pytest.raises(ValueError, match="LEN:PROB"):
            parse_prompt_length_dist("64,512:0.5")


# ---------------------------------------------------------------------------
# make_mixed_length_sampler — seed stability + distribution correctness
# ---------------------------------------------------------------------------


class TestMixedLengthSampler:
    def test_seed_produces_stable_sequence(self) -> None:
        """Same seed → identical (prompt, length) sequence for bisection."""
        pairs = [(64, 0.4), (512, 0.3), (2048, 0.2), (8192, 0.1)]
        s1 = make_mixed_length_sampler(pairs, seed=42)
        s2 = make_mixed_length_sampler(pairs, seed=42)
        # The arrival rng passed in is ignored by the mixed-length sampler
        # (it has its own length_rng), so we can pass any rng.
        dummy = random.Random(0)
        seq1 = [s1(dummy) for _ in range(50)]
        seq2 = [s2(dummy) for _ in range(50)]
        assert seq1 == seq2, "same seed must produce same prompts + lengths"

    def test_different_seeds_diverge(self) -> None:
        pairs = [(64, 0.5), (512, 0.5)]
        s1 = make_mixed_length_sampler(pairs, seed=42)
        s2 = make_mixed_length_sampler(pairs, seed=43)
        dummy = random.Random(0)
        seq1 = [s1(dummy)[1] for _ in range(100)]
        seq2 = [s2(dummy)[1] for _ in range(100)]
        assert seq1 != seq2, "different seeds must produce different length sequences"

    def test_distribution_matches_requested_within_chi_squared(self) -> None:
        """1000 samples with 40/30/20/10 split; 64-token prompts should be ~40%.

        Chi-squared test at df=3, alpha=0.01 → critical ≈ 11.34.
        Under the null hypothesis (sampler is correct), the test stat is
        very unlikely to exceed this. Fail the test only on a truly skewed
        outcome.
        """
        pairs = [(64, 0.4), (512, 0.3), (2048, 0.2), (8192, 0.1)]
        sampler = make_mixed_length_sampler(pairs, seed=42)
        dummy = random.Random(0)
        n = 1000
        counts = {64: 0, 512: 0, 2048: 0, 8192: 0}
        for _ in range(n):
            _, sampled_len = sampler(dummy)
            counts[sampled_len] = counts.get(sampled_len, 0) + 1

        # Sanity: 64 should be within a reasonable window of 40%.
        frac_64 = counts[64] / n
        assert 0.35 <= frac_64 <= 0.45, (
            f"64-token fraction {frac_64:.3f} outside 35-45% for n=1000"
        )

        # Chi-squared goodness-of-fit
        expected = {64: 400.0, 512: 300.0, 2048: 200.0, 8192: 100.0}
        chi2 = sum(
            (counts[length] - expected[length]) ** 2 / expected[length]
            for length in expected
        )
        # df=3, alpha=0.01 critical value ≈ 11.345. Well above typical draws
        # from a correct sampler — this guards against a broken implementation.
        assert chi2 < 11.345, (
            f"chi-squared {chi2:.2f} exceeds df=3 alpha=0.01 critical (11.345); "
            f"counts={counts}"
        )

    def test_sampler_returns_positive_prompt_and_length(self) -> None:
        pairs = [(64, 0.5), (512, 0.5)]
        sampler = make_mixed_length_sampler(pairs, seed=7)
        dummy = random.Random(0)
        for _ in range(20):
            prompt, length = sampler(dummy)
            assert isinstance(prompt, str)
            assert len(prompt) > 0
            assert length in (64, 512)


# ---------------------------------------------------------------------------
# Legacy-path backward compat — unset flag must match pre-Gate-2.2 behavior
# ---------------------------------------------------------------------------


class TestLegacySampler:
    def test_legacy_matches_direct_rng_choice(self) -> None:
        """make_legacy_sampler(rng) must equal rng.choice(PROMPTS) exactly.

        This is the Gate 2.1 backward-compat guarantee: the same --seed
        produces the same prompt sequence as before the Gate 2.2 flag existed.
        """
        sampler = make_legacy_sampler()
        rng_a = random.Random(42)
        rng_b = random.Random(42)
        for _ in range(30):
            via_sampler, sampled_tokens = sampler(rng_a)
            via_direct = rng_b.choice(PROMPTS)
            assert via_sampler == via_direct
            assert sampled_tokens == 0  # legacy path records 0 tokens in CSV


# ---------------------------------------------------------------------------
# Integration smoke: end-to-end parse + sample without firing HTTP
# ---------------------------------------------------------------------------


class TestIntegrationSmoke:
    def test_parse_then_sample_end_to_end(self) -> None:
        """Parse a CLI-style flag and drive the sampler for a few iterations.

        Covers the full code path the harness exercises in ``main_async``
        before any network activity happens, minus argparse itself.
        """
        spec = "64:0.4,512:0.3,2048:0.2,8192:0.1"
        pairs = parse_prompt_length_dist(spec)
        assert pairs == [(64, 0.4), (512, 0.3), (2048, 0.2), (8192, 0.1)]

        sampler = make_mixed_length_sampler(pairs, seed=142)
        arrival_rng = random.Random(42)
        collected: list[tuple[str, int]] = []
        for _ in range(10):
            prompt, length = sampler(arrival_rng)
            collected.append((prompt, length))

        # Every draw produces a usable prompt and a length from the distribution
        valid_lengths = {64, 512, 2048, 8192}
        for prompt, length in collected:
            assert length in valid_lengths
            assert isinstance(prompt, str) and len(prompt) > 0
