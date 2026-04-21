# Rename plan — `infergrid` → `gpufair`

**Status:** READY. Do not execute until the two in-flight agents (reproduce-hero bench, RTX 4090 consumer run) have landed their PRs. This doc is the playbook; `rename_sequence.md` is the copy-paste runbook.

**Decision already made** in `docs/naming/infergrid_name_audit.md`. Rationale not re-audited here.

---

## 1. Naming rules (the sed map)

There are **five** spelling forms in the tree. Replacement order matters — do the hyphen/underscore and PascalCase first so a bulk lowercase pass doesn't swallow them.

| Rank | Old form             | New form          | Context                                            | Examples                                                     |
| ---- | -------------------- | ----------------- | -------------------------------------------------- | ------------------------------------------------------------ |
| 1    | `infer-grid`         | `gpufair`         | npm-style hyphen (audit doc only, cosmetic)        | `pypi.org/pypi/infer-grid/json` → `pypi.org/pypi/gpufair/json` |
| 2    | `infer_grid`         | `gpufair`         | snake-case (audit doc only)                        | same as above                                                |
| 3    | `InferGrid`          | `GPUFair`         | PascalCase prose (README titles, docstrings)       | `"InferGrid -- tenant-fair LLM…"` → `"GPUFair -- tenant-fair LLM…"` |
| 4    | `INFERGRID_`         | `GPUFAIR_`        | env vars only — **anchored to trailing underscore** | `INFERGRID_TELEMETRY_URL` → `GPUFAIR_TELEMETRY_URL`          |
| 5    | `infergrid`          | `gpufair`         | everything else (lowercase: imports, URLs, pkg)    | `src/infergrid/` → `src/gpufair/`                            |

**Brand capitalization decision.** `GPUFair` (capital G-P-U, capital F, rest lowercase) is the chosen PascalCase form. This is the form that matches how people say the word — "GPU-fair" — and mirrors "GitHub", "OpenAI". Do **not** use `Gpufair` or `GPUFAIR` in prose.

**Full-word boundary hazards.** `infergrid` appears as a substring inside commit SHAs in `pip_freeze.txt` files (`#egg=infergrid`) — those files are frozen evidence, see Section 5 exclusions. No other natural substring collisions.

---

## 2. Scope — what gets rewritten

Only files in one of these classes:
- `src/**` (Python package)
- `tests/**`
- `docs/**` (excluding `docs/naming/infergrid_name_audit.md` — the audit is evidence, keep the name it was written under)
- `configs/**`
- `benchmarks/**`
- `scripts/**`
- `profiling/**`
- `dashboards/**`
- `telemetry-worker/**` (code + docs; the live D1 database is a separate user-side migration — see `user_checklist.md`)
- `docker/**`
- Top-level: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `pyproject.toml`, `requirements-gpu.txt`, `research_roadmap.md`, `.gitignore`
- `.github/**` (workflows + issue templates + PR template)

---

## 3. Explicit exclusions — **do not** rewrite

These paths are historical evidence. Rewriting corrupts reproducibility.

- **`results/**`** — every `.log`, `.json`, `.txt`, `.md`, `.yaml` under `results/`. These are committed outputs of gates that ran under the `infergrid` name. They are the record.
- **`docs/naming/infergrid_name_audit.md`** — the audit doc. Keep the filename and contents unchanged. It references the old name *because* it is the audit of the old name.
- **`PROGRESS.md`** — historical PR log entries are brand-archaeology. Leave them. (This PR's task spec also excludes PROGRESS.md.)
- **`infergrid_results_*.tar.gz`** (top-level tarballs) — frozen artifacts.
- **`*.egg-info/`**, **`__pycache__/`**, **`.ruff_cache/`**, **`.pytest_cache/`** — generated; the rename will regenerate them.
- **Commit history / git SHAs** — never rewrite.

---

## 4. Sequence — the order of operations

Each step gates on the previous. Do not parallelize.

### 4a. Pre-gate (founder, out-of-band)
1. **Domains purchased** (`gpufair.org`, `.com`, `.ai`, `.dev`) — `user_checklist.md` item 1.
2. **PyPI `gpufair` reserved** via `twine upload` of a 0.0.1 stub — `user_checklist.md` item 2.
3. **npm `gpufair` + `@gpufair` scope reserved** — `user_checklist.md` item 3.
4. **Twitter/X handles reserved** — `user_checklist.md` item 4.
5. **GitHub org repo rename** (`coconut-labs/infergrid` → `coconut-labs/gpufair`, `coconut-labs/infergrid-root` → `coconut-labs/gpufair-root`) — `user_checklist.md` item 5. GitHub's 301 redirects mean the tree rename can proceed before or after this step; placing it before means the new URLs in docs point at a repo that already answers under the new name.

### 4b. In-flight merges (blocking)
6. `feat/bench-reproduce-hero` lands to `main`. The branch's PR references the old name; that's fine — step 4d sweeps it.
7. The RTX 4090 consumer run (branch name TBD — the task references `results/consumer-4090-20260421` but that branch did not yet exist as of 2026-04-21 15:36 UTC) lands to `main`.

### 4c. Sanity — clean tree
8. `git fetch origin && git checkout main && git pull --ff-only`. Working tree empty.

### 4d. The sweep (one branch, one PR)
9. `git checkout -b rename/infergrid-to-gpufair`.
10. Run `rename_sequence.md` top-to-bottom. It does sed passes 1→5 in order, then the directory rename, then the pyproject edits, then the manual-review targets (docstrings, YAML comments).
11. `pytest tests/unit/ -v --tb=short` — imports must resolve under `gpufair`.
12. `ruff check src/ tests/` and `ruff format --check src/ tests/` — CI parity.
13. `git grep -iE 'InferGrid|infergrid|INFERGRID'` — should only return hits in the **excluded** paths (Section 3). If any hit is outside Section 3, fix and re-run.
14. Commit in logical chunks (directory rename, sed sweep, pyproject, configs, docs) so the diff is reviewable.
15. Open PR `rename: infergrid → gpufair (tree sweep)`. Reference this plan doc.

### 4e. Post-merge cutover
16. **PyPI deprecate**: publish `infergrid==0.1.3` whose README says the package moved. See `user_checklist.md` item 7.
17. **Cloudflare Worker cutover**: deploy `gpufair-telemetry` worker, update LP's `WAITLIST_API` to the new subdomain, then take down `infergrid-telemetry`. See `user_checklist.md` item 6.
18. **DNS cutover**: point `gpufair.org` at the same Vercel deployment that currently serves `infergrid.org`. See `user_checklist.md` item 8.
19. **Send Samuel Bell a heads-up** using `docs/naming/email_samuel_bell.md`.

---

## 5. Per-file sed targets

The table below lists every file in-scope (excluding Section 3 exclusions) that matches one of the five forms. Counts are from `git grep -c` on `origin/main` at commit `a9353da`.

### 5a. Python package — `src/infergrid/`

Directory rename: `src/infergrid/` → `src/gpufair/` (whole-tree `git mv`).

| File                                              | Form(s)                     | Hits | Replacement notes                                         |
| ------------------------------------------------- | --------------------------- | ---- | --------------------------------------------------------- |
| `src/infergrid/__init__.py`                       | `InferGrid`, `infergrid`    | 2    | Docstring + `version("infergrid")` → `version("gpufair")` |
| `src/infergrid/cli.py`                            | `infergrid`                 | 58   | Manpage URLs + CLI name string; keep CLI entry-point name `gpufair` (see ambiguity #1) |
| `src/infergrid/_manpages.py`                      | `InferGrid`, `infergrid`    | 35   | URLs to `github.com/coconut-labs/gpufair/...`             |
| `src/infergrid/_telemetry.py`                     | `INFERGRID_`, `infergrid`   | 9    | `INFERGRID_TELEMETRY` → `GPUFAIR_TELEMETRY`, `INFERGRID_TELEMETRY_URL` → `GPUFAIR_TELEMETRY_URL`; and the default telemetry URL constant |
| `src/infergrid/_bench/__init__.py`                | `infergrid`                 | 2    | Module docstring                                          |
| `src/infergrid/_bench/hero.py`                    | `infergrid`                 | 10   | CLI name in usage strings, repo URL                       |
| `src/infergrid/_bench/compare.py`                 | `infergrid`                 | —    | Check during sweep                                        |
| `src/infergrid/_bench/pod.py`                     | `INFERGRID_`, `infergrid`   | 4    | `INFERGRID_AUTO_SERVE` → `GPUFAIR_AUTO_SERVE` env name    |
| `src/infergrid/cache/__init__.py`                 | `infergrid`                 | 2    | Module docstring                                          |
| `src/infergrid/cache/manager.py`                  | `infergrid`                 | 1    | Import path / docstring                                   |
| `src/infergrid/common/__init__.py`                | `infergrid`                 | 5    | Module docstring                                          |
| `src/infergrid/common/config.py`                  | `infergrid`                 | 7    |                                                          |
| `src/infergrid/common/metrics.py`                 | `infergrid`                 | 15   | Prometheus metric `namespace=infergrid` → `namespace=gpufair` — **this changes label names and is a breaking change for any dashboard consuming the old metric names**; the dashboards JSON in `dashboards/` is in-tree and updated in the same PR. External users: called out in PyPI 0.1.3 deprecation README. |
| `src/infergrid/engines/__init__.py`               | `infergrid`                 | 4    |                                                          |
| `src/infergrid/engines/base.py`                   | `INFERGRID_`, `infergrid`   | 4    | `INFERGRID_ENGINE_LOG_DIR` → `GPUFAIR_ENGINE_LOG_DIR`, `INFERGRID_DEV_SKIP_ENGINE_LAUNCH` → `GPUFAIR_DEV_SKIP_ENGINE_LAUNCH` |
| `src/infergrid/engines/sglang_adapter/__init__.py`| `infergrid`                 | 1    |                                                          |
| `src/infergrid/engines/sglang_adapter/adapter.py` | `infergrid`                 | 1    |                                                          |
| `src/infergrid/engines/vllm_adapter/__init__.py`  | `infergrid`                 | 1    |                                                          |
| `src/infergrid/engines/vllm_adapter/adapter.py`   | `infergrid`                 | 1    |                                                          |
| `src/infergrid/router/__init__.py`                | `infergrid`                 | 3    |                                                          |
| `src/infergrid/router/router.py`                  | `INFERGRID_`, `infergrid`   | 13   | `INFERGRID_STREAM_MAX_DURATION_S` → `GPUFAIR_STREAM_MAX_DURATION_S` |
| `src/infergrid/router/admission.py`               | `infergrid`                 | 5    |                                                          |
| `src/infergrid/tenant/__init__.py`                | `infergrid`                 | 2    |                                                          |
| `src/infergrid/tenant/manager.py`                 | `infergrid`                 | 1    |                                                          |

### 5b. Tests — `tests/unit/`

| File                                               | Hits | Notes                              |
| -------------------------------------------------- | ---- | ---------------------------------- |
| `tests/unit/test_admission.py`                     | 1    | `from infergrid...` import         |
| `tests/unit/test_bench_hero.py`                    | 8    | (added by in-flight reproduce-hero branch — will be on `main` before sweep) |
| `tests/unit/test_cache_manager.py`                 | 1    |                                    |
| `tests/unit/test_metrics.py`                       | 31   | Metric name assertions — update    |
| `tests/unit/test_metrics_ttft.py`                  | 4    |                                    |
| `tests/unit/test_multi_model.py`                   | 3    |                                    |
| `tests/unit/test_router.py`                        | 10   |                                    |
| `tests/unit/test_router_ensure_model_loaded_race.py` | 4  |                                    |
| `tests/unit/test_router_health_gating.py`          | 4    |                                    |
| `tests/unit/test_telemetry.py`                     | 29   | `INFERGRID_TELEMETRY*` env mocks   |
| `tests/unit/test_tenant_manager.py`                | 1    |                                    |
| `tests/unit/test_tenant_priority.py`               | 2    |                                    |
| `tests/unit/test_tenant_token_bucket.py`           | 1    |                                    |

### 5c. Configs — `configs/`

| File                                            | Hits | Brand-text only? |
| ----------------------------------------------- | ---- | ---------------- |
| `configs/gate0_multi_model.yaml`                | 1    | Comment          |
| `configs/gate2_fairness_drr.yaml`               | 1    | Comment          |
| `configs/gate2_fairness_drr_cap16.yaml`         | 1    | Comment          |
| `configs/gate2_fairness_drr_ratelimit.yaml`     | 1    | Comment          |
| `configs/gate2_fairness_fifo.yaml`              | 2    | Comment          |
| `configs/gate2_multi_tenant.yaml`               | 1    | Comment          |
| `configs/gate23_fairness_70b_tp4.yaml`          | 1    | Comment          |
| `configs/quickstart_fairness.yaml`              | 3    | Comment + example command |

No YAML *key* references the brand — hits are all in comments. Pure sed is safe.

### 5d. Benchmarks and scripts

| File                                             | Hits | Notes                         |
| ------------------------------------------------ | ---- | ----------------------------- |
| `benchmarks/scripts/benchmark_admission.py`      | 11   |                               |
| `benchmarks/scripts/benchmark_chat_rag_burst.py` | 2    |                               |
| `benchmarks/scripts/benchmark_multi_model.py`    | 11   |                               |
| `benchmarks/scripts/benchmark_n_tenant_single_model.py` | 1 |                             |
| `benchmarks/scripts/benchmark_two_tenant_single_model.py` | 3 |                           |
| `benchmarks/scripts/mock_engine.py`              | 1    |                               |
| `benchmarks/scripts/repro_gate0_stall.sh`        | 7    | `INFERGRID_*` env exports     |
| `benchmarks/scripts/run_baseline_comparison.py`  | 1    |                               |
| `benchmarks/scripts/smoke_bench.sh`              | 12   | `INFERGRID_*` env exports     |
| `scripts/cloud_benchmark.sh`                     | 2    |                               |
| `scripts/cost_cap_smoke.sh`                      | 1    |                               |
| `scripts/gate_pod_bootstrap.sh`                  | 10   | Clone URL + env exports       |
| `scripts/gate1_dress_rehearsal.sh`               | 11   |                               |
| `scripts/gate2_fairness_dress_rehearsal.sh`      | 6    |                               |
| `scripts/generate_launch_chart_v3.py`            | 2    | Title strings                 |
| `scripts/gpu_monitor.py`                         | 2    |                               |
| `scripts/provision_runpod.py`                    | 12   | Default `--repo-url`          |
| `scripts/run_all_baselines.sh`                   | 3    |                               |
| `scripts/run_multi_model_demo.sh`                | 25   | `INFERGRID_*` env vars + `INFERGRID_CMD` + `python -m infergrid` invocation → `python -m gpufair` |
| `scripts/setup_gpu_env.sh`                       | 5    |                               |
| `scripts/setup_venv.sh`                          | 6    | `INFERGRID_VENV` env var      |
| `scripts/summarize_results.py`                   | 1    |                               |
| `scripts/track_d_runner.sh`                      | 8    |                               |
| `profiling/analysis/scheduling_overhead_analysis.ipynb` | 1 | Notebook markdown cell      |
| `profiling/scripts/profile_sglang_scheduler.py`  | 1    |                               |
| `profiling/scripts/profile_vllm_scheduler.py`    | 1    |                               |
| `profiling/scripts/profiling_utils.py`           | 1    |                               |

### 5e. Docs (top-level + `docs/`)

| File                                                      | Hits | Notes                                                    |
| --------------------------------------------------------- | ---- | -------------------------------------------------------- |
| `README.md`                                               | 34   | Title, badges, repo URL, domain `infergrid.org` → `gpufair.org` |
| `CONTRIBUTING.md`                                         | 9    | Clone URL                                                |
| `SECURITY.md`                                             | 2    |                                                          |
| `research_roadmap.md`                                     | 6    |                                                          |
| `docs/demo_script.md`                                     | 18   |                                                          |
| `docs/gap_analysis_verification_april2026.md`             | 1    |                                                          |
| `docs/inference_orchestration_gaps_report.md`             | 4    |                                                          |
| `docs/metrics_audit_20260421.md`                          | 40   | Prometheus metric-name audit — metric-namespace rename flows in here |
| `docs/phase_b_roadmap.md`                                 | 14   |                                                          |
| `docs/phase1_findings.md`                                 | 3    |                                                          |
| `docs/pitch.md`                                           | 9    | Repo URL + product title                                 |
| `docs/reproduce_hero.md`                                  | 6    | (added by in-flight reproduce-hero branch)               |
| `docs/strategic_analysis.md`                              | 16   |                                                          |
| `docs/tuning_guide.md`                                    | 18   |                                                          |
| `docs/launch/faq.md`                                      | 8    |                                                          |
| `docs/launch/gate0_launch_post.md`                        | 14   |                                                          |
| `docs/launch/gate1_runbook.md`                            | 7    |                                                          |
| `docs/launch/gate2_design.md`                             | 10   |                                                          |
| `docs/launch/gate2_fairness_runbook.md`                   | 9    |                                                          |
| `docs/launch/one_pager.md`                                | 8    |                                                          |
| `docs/launch/show_hn.md`                                  | 4    |                                                          |
| `docs/launch/twitter_thread.md`                           | 8    |                                                          |
| `docs/launch/why_not_upstream.md`                         | 9    |                                                          |
| `docs/privacy/telemetry.md`                               | 12   | `INFERGRID_TELEMETRY` env                                |
| `docs/runbooks/secrets.md`                                | 11   |                                                          |

**Exclusion reiterated:** `docs/naming/infergrid_name_audit.md` is **not** rewritten.

### 5f. Infrastructure / build

| File                                    | Hits | Notes                                                                |
| --------------------------------------- | ---- | -------------------------------------------------------------------- |
| `pyproject.toml`                        | 6    | `name = "infergrid"` → `"gpufair"`; `[project.scripts] infergrid = "infergrid.cli:main"` → `gpufair = "gpufair.cli:main"`; all `[project.urls]` repo URLs |
| `requirements-gpu.txt`                  | 1    | Comment header                                                       |
| `.gitignore`                            | 1    | Any `infergrid/` entry → `gpufair/`                                  |
| `docker/docker-compose.yml`             | 1    | Comment header                                                       |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | 4    | Title templates                                                      |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | 3 |                                                                     |
| `.github/ISSUE_TEMPLATE/config.yml`     | 1    | Discussions URL                                                      |
| `.github/workflows/ci.yml`              | 0    | **No brand text** — CI references `src/` and `tests/` by path, not by package name. Badge in README is renamed because its URL path changes. |
| `.github/PULL_REQUEST_TEMPLATE.md`      | 0    | Verify during sweep                                                  |

### 5g. telemetry-worker

| File                                    | Hits | Notes                                                                |
| --------------------------------------- | ---- | -------------------------------------------------------------------- |
| `telemetry-worker/README.md`            | 8    | Product name + wrangler d1 command examples                          |
| `telemetry-worker/schema.sql`           | 3    | Comment headers                                                      |
| `telemetry-worker/src/index.ts`         | 1    | Comment header                                                       |
| `telemetry-worker/wrangler.toml`        | 3    | **Requires operator action, not pure sed.** `name = "infergrid-telemetry"` → `"gpufair-telemetry"` changes the deployed Worker URL. `database_name = "infergrid-telemetry"` and `database_id = ...` point at a **live D1 database** — creating a new D1 named `gpufair-telemetry` is a data-migration decision (new DB vs. rename-in-place via Cloudflare dashboard). See `user_checklist.md` item 6. |

### 5h. Dashboards

| File                                      | Hits | Notes                                                                |
| ----------------------------------------- | ---- | -------------------------------------------------------------------- |
| `dashboards/infergrid-fairness.json`      | 11   | **File rename**: `infergrid-fairness.json` → `gpufair-fairness.json`. Grafana panel titles + queries reference `infergrid_*` Prometheus metric names. |
| `docs/grafana/infergrid-overview.json`    | 10   | **File rename**: `infergrid-overview.json` → `gpufair-overview.json`. Same metric-name references. |

---

## 6. pyproject.toml — precise edits

| Line  | Old                                                            | New                                                            |
| ----- | -------------------------------------------------------------- | -------------------------------------------------------------- |
| 2     | `name = "infergrid"`                                           | `name = "gpufair"`                                             |
| 3     | `version = "0.1.2"`                                            | `version = "0.1.0"` (fresh line on PyPI; old 0.1.3 stub lives under `infergrid`) |
| 4     | `description = "...InferGrid..."`                              | Keep tagline but drop the old brand from it if present        |
| 29    | `Homepage = "https://github.com/coconut-labs/infergrid"`       | `Homepage = "https://github.com/coconut-labs/gpufair"`         |
| 30    | `Documentation = ".../infergrid#readme"`                        | `Documentation = ".../gpufair#readme"`                         |
| 31    | `Repository = ".../infergrid"`                                  | `Repository = ".../gpufair"`                                   |
| 32    | `Issues = ".../infergrid/issues"`                               | `Issues = ".../gpufair/issues"`                                |
| 58    | `infergrid = "infergrid.cli:main"`                              | `gpufair = "gpufair.cli:main"`                                 |

**Entry point ambiguity:** the task invites the question — do we keep `infergrid` as a deprecated CLI alias? Default answer in this plan: **no**. Rationale: the deprecated PyPI `infergrid==0.1.3` README redirects users to `pip install gpufair`, which is simpler than maintaining two binaries in one package. Flag this for founder review — adding an alias is a one-line `[project.scripts]` entry if desired.

---

## 7. Prometheus metrics — the breaking edge

`src/infergrid/common/metrics.py` defines metrics under a `namespace="infergrid"` argument. The sweep renames the namespace. **Downstream effect**: every label in scraped Prometheus data becomes `gpufair_*` instead of `infergrid_*`. Consumers:

1. **In-tree dashboards** (`dashboards/infergrid-fairness.json`, `docs/grafana/infergrid-overview.json`) — updated in the same PR.
2. **External users of the PyPI `infergrid` package** — get the old labels under the old package name (unchanged). The 0.1.3 deprecation stub has no engine code, just a README; installed bases don't break.
3. **Grafana dashboards not in the tree** (none known) — call out in the 0.1.3 deprecation README and in the PyPI `gpufair` 0.1.0 release notes.

---

## 8. In-flight PR handling

Branches open at the time this plan was drafted:
- `feat/bench-reproduce-hero` — contains `src/infergrid/_bench/`, `tests/unit/test_bench_hero.py`, `docs/reproduce_hero.md`. Lands under the old name. Sweep picks it up.
- RTX 4090 consumer run — task spec names it `results/consumer-4090-20260421`, but as of 2026-04-21 15:36 UTC no such branch existed locally or on origin. **Ambiguity: verify branch name at sweep time.** The branch almost certainly writes to `results/**`, which is Section 3-excluded from the rename, so even if the directory name bakes in the old brand (`results/consumer-4090-*`) it does not need to be rewritten — `results/**` is the historical record.

**PR body action**: on each in-flight PR, the PR body copy under the old name is fine. No retroactive edit. The landing-sweep PR supersedes.

---

## 9. CI — no changes needed in workflow yaml

`.github/workflows/ci.yml` was reviewed on `origin/main`. The workflow:
- checks out the repo
- installs via `pip install -e ".[dev]"` (resolves from `pyproject.toml`, which carries the new name after the sweep)
- runs `pytest tests/unit/`
- runs `ruff check src/ tests/` and `ruff format --check src/ tests/`

No brand string in the workflow itself. **However**, the README CI badge URL (`https://github.com/coconut-labs/infergrid/actions/workflows/ci.yml/badge.svg`) changes when the GitHub repo is renamed — handled in the `README.md` sed pass.

---

## 10. Post-sweep verification

After the sweep PR lands, run:

```bash
# Must return nothing except Section 3 exclusions
git grep -iE 'InferGrid|infergrid|INFERGRID|infer-grid|infer_grid' -- \
    ':(exclude)results/' \
    ':(exclude)docs/naming/infergrid_name_audit.md' \
    ':(exclude)PROGRESS.md' \
    ':(exclude)*.tar.gz'
```

If any hit survives, add to this plan's excluded list with a reason or fix.

---

## 11. Related docs

- `docs/naming/infergrid_name_audit.md` — the original decision memo.
- `docs/naming/rename_sequence.md` — the copy-paste bash playbook.
- `docs/naming/user_checklist.md` — founder-only manual steps.
- `docs/naming/email_samuel_bell.md` — courtesy email draft.
