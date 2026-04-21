# User checklist — `gpufair` rename, founder-only steps

Everything below requires either payment, a login, or a personal credential — no agent can execute these. Order matters for the items flagged **blocking**; the code sweep in `rename_sequence.md` can run in parallel with the non-blocking items.

Execute as Shrey Patel, `patelshrey77@gmail.com`. Whenever a command needs a token or password, it's your personal credential — never commit it.

---

## 1. Buy the four TLDs — **blocking, do first** (~20 min, $40–$120)

All four via Cloudflare Registrar. Single dashboard, at-cost pricing, no add-on upsells. Cloudflare supports `.org`, `.com`, `.ai`, and `.dev` (`.dev` lives in the Google Registry — Cloudflare is a reseller. Google Domains was sunset in 2024; its customers were migrated to Squarespace, which is not a recommended registrar for this).

Direct links (logged into the existing Cloudflare account that already holds `infergrid.org`):

- Dashboard: https://dash.cloudflare.com/ → Domain Registration → Register Domain
- Search `gpufair` once and Cloudflare shows availability for all four TLDs.

| Domain       | Approx cost (Cloudflare at-cost, 2026) | Purpose                                      |
| ------------ | --------------------------------------- | -------------------------------------------- |
| `gpufair.org`  | ~$11/yr | **Canonical landing page** — replaces `infergrid.org` |
| `gpufair.com`  | ~$10/yr | Defensive — prevent typo-domain squatters    |
| `gpufair.ai`   | ~$80/yr | AI-vertical defensive, often the first TLD folks try |
| `gpufair.dev`  | ~$13/yr | Developer-audience defensive                 |

Enable auto-renew on all four. Turn on Registrar Lock for each.

---

## 2. Reserve PyPI `gpufair` — **blocking** (~10 min)

Publish a 0.0.1 placeholder so nobody else grabs the name while the sweep is in flight.

```bash
# In a scratch dir — do NOT do this inside the main repo
mkdir -p /tmp/gpufair-stub && cd /tmp/gpufair-stub

cat > pyproject.toml <<'EOF'
[project]
name = "gpufair"
version = "0.0.1"
description = "Tenant-fair LLM inference orchestration on a single GPU. Placeholder — real package coming soon."
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
authors = [{name = "Shrey Patel", email = "patelshrey77@gmail.com"}]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"
EOF

cat > README.md <<'EOF'
# gpufair

Placeholder. Full package ships with 0.1.0. See https://gpufair.org.
EOF

mkdir -p src/gpufair && echo '__version__ = "0.0.1"' > src/gpufair/__init__.py

python -m pip install --upgrade build twine
python -m build
python -m twine upload dist/*
```

Username: `__token__`. Password: a PyPI API token scoped to this project (create at https://pypi.org/manage/account/token/; scope "Entire account" for the first upload, then narrow to "Project: gpufair" after the first release lands).

---

## 3. Reserve npm `gpufair` + `@gpufair` scope — **blocking** (~10 min)

Even though the project is Python, reserving the npm name + scope prevents someone from shipping an unrelated `npm install gpufair` that shows up in SERP for the brand.

```bash
mkdir -p /tmp/gpufair-npm-stub && cd /tmp/gpufair-npm-stub

cat > package.json <<'EOF'
{
  "name": "gpufair",
  "version": "0.0.1",
  "description": "Placeholder. Real package is Python — see https://pypi.org/project/gpufair/",
  "author": "Shrey Patel <patelshrey77@gmail.com>",
  "license": "MIT",
  "repository": { "type": "git", "url": "https://github.com/coconut-labs/gpufair" }
}
EOF

cat > README.md <<'EOF'
# gpufair

Placeholder. The real package is Python: `pip install gpufair` (once 0.1.0 ships). See https://gpufair.org.
EOF

npm login          # prompts email, password, OTP
npm publish --access public
```

Then reserve the scope. Scopes aren't reservable via a single command — npm creates the scope the first time you publish under it:

```bash
cd /tmp/gpufair-npm-stub
# Rename the package to @gpufair/placeholder in package.json:
#   "name": "@gpufair/placeholder"
npm publish --access public
```

This establishes `@gpufair` as a scope under your npm account. Future packages under `@gpufair/...` require your login.

---

## 4. Reserve Twitter/X handles — ~10 min, **not verifiable via curl**

x.com is a client-rendered SPA and returns HTTP 200 for every path, so handle availability can only be verified in a browser. Reserve in this order:

| Handle              | Purpose                                 |
| ------------------- | --------------------------------------- |
| `@gpufair`          | Primary brand                           |
| `@gpufair_ai`       | Defensive — many AI brands use `_ai`    |
| `@gpufair_hq`       | Defensive — "headquarters" pattern      |

For each:
1. https://x.com/i/flow/signup
2. Use `patelshrey77+gpufair@gmail.com`, `patelshrey77+gpufair_ai@gmail.com`, etc. (Gmail `+` aliases all land in your main inbox — legitimate, not a trick).
3. After account creation, go to Settings → Your account → Account information → Username and confirm.
4. Add a profile bio pointing at `https://gpufair.org` and set the profile image to the existing `infergrid.org` favicon — the LP will swap it when DNS cuts over.

If any handle is taken, fall back to `@gpufair_dev` / `@gpufairhq` (no underscore) / `@gpu_fair`.

---

## 5. Rename GitHub org repos — **blocking** (~5 min, non-destructive)

GitHub maintains permanent 301 redirects from the old names, so existing clone URLs, PR links, and badge URLs keep working. No rush to update every downstream reference, but the sweep PR does update the in-repo URLs.

```bash
# Primary repo
gh repo rename gpufair --repo coconut-labs/infergrid

# Landing-page repo
gh repo rename gpufair-root --repo coconut-labs/infergrid-root
```

Verify:

```bash
gh repo view coconut-labs/gpufair --json name,url
gh repo view coconut-labs/gpufair-root --json name,url

# Confirm redirects work (expect 301 → new URL):
curl -sI https://github.com/coconut-labs/infergrid | grep -i ^location
```

After the rename, update your local clone's origin:

```bash
# In this repo:
git remote set-url origin git@github.com:coconut-labs/gpufair.git
git remote set-url coconut git@github.com:coconut-labs/gpufair.git
git remote -v   # confirm
```

Update the Vercel project bound to `coconut-labs/infergrid-root`:
- Vercel dashboard → Project Settings → Git → Repository → re-link to `coconut-labs/gpufair-root`. Vercel follows the redirect automatically in most cases but re-linking is cleaner for the build log.

---

## 6. Cloudflare Worker cutover (~30 min)

The current Worker is `infergrid-waitlist.shrey77-wrk.workers.dev` and the telemetry Worker is `infergrid-telemetry.shrey77-wrk.workers.dev`. **There is no `wrangler rename` subcommand** — you deploy a new Worker under the new name and retire the old one.

For each Worker (waitlist + telemetry):

```bash
cd telemetry-worker   # adjust for waitlist worker repo

# 1. Edit wrangler.toml:
#      name = "infergrid-telemetry"   →   name = "gpufair-telemetry"
#      database_name = "infergrid-telemetry"   →   "gpufair-telemetry"

# 2. Create a fresh D1 database under the new name (telemetry only)
wrangler d1 create gpufair-telemetry
# Paste the returned database_id into wrangler.toml

# 3. Apply the schema to the new DB
wrangler d1 execute gpufair-telemetry --file=schema.sql

# 4. Deploy the renamed worker — assigns gpufair-telemetry.shrey77-wrk.workers.dev
wrangler deploy

# 5. Update the LP's WAITLIST_API in coconut-labs/gpufair-root:
#      window.WAITLIST_API = 'https://gpufair-waitlist.shrey77-wrk.workers.dev'
#    (This also fixes the outstanding pending-user-action where WAITLIST_API = '')

# 6. Keep the old Worker alive for ~30 days for any in-flight traffic, then:
wrangler delete --name infergrid-telemetry
wrangler delete --name infergrid-waitlist
#    And drop the old D1:
wrangler d1 delete infergrid-telemetry
```

**Data migration decision (telemetry D1)**: the existing `infergrid-telemetry` D1 holds opt-in install stats. Options:
- **Fresh start (recommended).** New DB, old data stays queryable under the old Worker until it's deleted. Telemetry is ephemeral anyway — 90-day retention sweep is in the cron.
- **Backfill.** `wrangler d1 export infergrid-telemetry --output dump.sql`, hand-edit the `CREATE TABLE` / row inserts if desired, `wrangler d1 execute gpufair-telemetry --file dump.sql`. Only worth it if there's install data you care about.

---

## 7. PyPI `infergrid` deprecation — after the sweep lands (~20 min)

Once `gpufair` 0.1.0 is live on PyPI (published from the sweep PR's tag), ship a final `infergrid==0.1.3` that is README-only, pointing users at the new name.

```bash
mkdir -p /tmp/infergrid-deprecate && cd /tmp/infergrid-deprecate

cat > pyproject.toml <<'EOF'
[project]
name = "infergrid"
version = "0.1.3"
description = "This package has moved. See README."
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
authors = [{name = "Shrey Patel", email = "patelshrey77@gmail.com"}]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"
EOF

cat > README.md <<'EOF'
# infergrid has moved to gpufair

This package has been renamed to **gpufair**. Install with:

```bash
pip install gpufair
```

See https://gpufair.org for the current release and documentation.

The rename was prompted by a naming collision with a senior commercial product
at https://infergrid.net. Details in
https://github.com/coconut-labs/gpufair/blob/main/docs/naming/.
EOF

mkdir -p src/infergrid
cat > src/infergrid/__init__.py <<'EOF'
import warnings
warnings.warn(
    "The 'infergrid' package has been renamed to 'gpufair'. "
    "Please `pip install gpufair` and `import gpufair` instead. "
    "See https://gpufair.org.",
    DeprecationWarning,
    stacklevel=2,
)
EOF

python -m build
python -m twine upload dist/*
```

Do not add any runtime code to the stub — a `DeprecationWarning` on import is loud enough and safe.

---

## 8. DNS cutover — `gpufair.org` → Vercel (~15 min, after the sweep)

Mirror the existing `infergrid.org` → Vercel config onto `gpufair.org`. The Vercel project is the `coconut-labs/gpufair-root` project (renamed in step 5).

1. Cloudflare dashboard → `gpufair.org` → DNS. Add records that match the existing `infergrid.org` records — for Vercel that is typically:
   - `A @ 76.76.21.21` (Vercel anycast)
   - `CNAME www cname.vercel-dns.com`
2. Vercel dashboard → the renamed project (`gpufair-root`) → Settings → Domains. Add `gpufair.org` and `www.gpufair.org`. Vercel will issue SSL automatically; expect propagation in <5 min.
3. Once DNS is live and the cert is green, set a 302 redirect on `infergrid.org` pointing at `gpufair.org`. In Cloudflare: Rules → Page Rules → Forwarding URL (302) `infergrid.org/*` → `https://gpufair.org/$1`. Keep it 302 (temporary) for 30 days, then convert to 301 (permanent) if everything looks good.
4. Hold `infergrid.org` in registration but **do not** let it expire — the redirect is the only thing keeping any existing inbound links alive.

---

## 9. Optional — USPTO trademark filing for `GPUFAIR` (~$350, own schedule)

Not blocking. First-to-file wins in the US, so filing earlier is better. Class 9 (downloadable software) + Class 42 (SaaS). Retain a flat-fee trademark filer like Cognition IP or Stacks Law if you want this done right, ~$800–$1,500 all-in. Skip if cash-constrained at launch — the rename itself de-risks the Samuel Bell collision, which was the actual legal exposure.

---

## 10. Final verification after everything ships

```bash
# All should resolve correctly
curl -sI https://gpufair.org | head -1
curl -sI https://infergrid.org | head -1      # expect 302 → gpufair.org
curl -sI https://github.com/coconut-labs/infergrid | grep -i ^location   # 301 → gpufair
pip index versions gpufair      # 0.1.0 available
pip index versions infergrid    # 0.1.3 deprecation stub
npm view gpufair                 # lists your placeholder
```

---

## Summary of blocking vs. non-blocking

**Blocking the code sweep** (do before running `rename_sequence.md`):
1. Domains purchased
2. PyPI `gpufair` reserved
3. npm `gpufair` + scope reserved

**Can happen in parallel with the code sweep**:
4. Twitter/X handles reserved
5. GitHub repo renames (GitHub's redirects mean order doesn't strictly matter, but earlier is cleaner)

**After the sweep lands**:
6. Cloudflare Worker cutover
7. PyPI `infergrid` 0.1.3 deprecation stub
8. DNS cutover
9. (Optional) USPTO filing
10. Final verification
