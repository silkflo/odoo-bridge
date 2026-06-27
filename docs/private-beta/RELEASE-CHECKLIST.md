# Odoo Bridge — Private Beta Release Checklist

*Internal engineering checklist (uses “STYD” as shorthand for Speak To Your
Database). Complete this before issuing a private‑beta build to a new customer.
Record actual values in the “Result” column for each release.*

| Release date | Build / commit | Operator |
|---|---|---|
| `YYYY‑MM‑DD` | `<git sha>` | `<name>` |

---

## 1. Versions

| Item | Expected | Result |
|---|---|---|
| Odoo series | 19.0 | ☐ |
| Odoo Bridge module version (`__manifest__.py`) | `19.0.0.4.0` | ☐ |
| STYD API / app release (deployed) | `<release / commit>` | ☐ |
| Bridge repo | `silkflo/odoo-bridge-v2` @ `main` | ☐ |
| STYD app repo | `silkflo/universal-db-ai` @ `main` | ☐ |

## 2. Bridge health test

- [ ] `…/styd_bridge/v1/health` returns `{"ok": true}` with a valid token.
- [ ] Without a token / with a wrong token → unauthorized (not a data leak).
- [ ] With the Bridge disabled in Settings → `bridge_disabled`.
- [ ] **Bridge Status** page shows *enabled* + *token configured*.

## 3. Live evaluation

- [ ] Read‑only bridge live eval run on the target Odoo:
      `npm run eval:odoo:phase-5h-b-bridge-live -- 1`
- [ ] **Result: 24 PASS, 0 WARN, 0 FAIL** (record actual): `____ PASS / ____ WARN / ____ FAIL`

## 4. Demo‑readiness rehearsal

- [ ] Offline rehearsal: `npm run demo:odoo:bridge-readiness` → **DEMO READY**.
- [ ] Every demo prompt: **Source: Odoo Bridge**, supported = **High (0.9)**,
      unsupported = safe message, **no SQL**, **no DB block**, **no secret**.

## 5. UI smoke test (bridge thread)

- [ ] Create a thread with source **Odoo Bridge — `<host>`**.
- [ ] `count customers` → answer, **Source: Odoo Bridge**, High (0.9).
- [ ] `total unpaid amount` → total, **Source: Odoo Bridge**.
- [ ] `total sales for Azure Interior` (real customer) → **Source: Odoo Bridge**
      (not Source: Database).
- [ ] An unsupported question → safe “not supported yet” message, still Odoo Bridge.
- [ ] **“How this answer was calculated”** names the model + operation and states
      **no SQL executed**.

## 6. Demo question set

- [ ] Run the full set in [SUPPORTED-QUESTIONS.md](SUPPORTED-QUESTIONS.md) against the
      target Odoo; spot‑check totals/counts against Odoo native views.

## 7. Security checks

- [ ] Token shown **once** on generate/rotate; not retrievable afterward.
- [ ] Odoo stores token **hash only** (no plaintext in params, status page, or logs).
- [ ] STYD stores token **encrypted at rest**; token never appears in answers / meta /
      provenance / logs (grep clean).
- [ ] Allow‑listed models only; non‑allow‑listed model request → rejected.
- [ ] Credential/security fields never returned (spot‑check `res.partner`).
- [ ] No write path reachable (create/update/delete rejected).
- [ ] Access mode reported as `sudo_company_scoped`; company boundary respected.
- [ ] HTTPS enforced on the Odoo base URL.

## 8. Rollback notes

- [ ] Previous module build archived (folder + version recorded) for quick re‑deploy.
- [ ] Rollback = re‑copy previous `styd_odoo_bridge`, restart Odoo, **Update Apps
      List**, **Upgrade** module to prior version.
- [ ] **Revoke token** in Connection Setup to immediately disable the Bridge if needed
      (this disables the Bridge as a safe default).
- [ ] In STYD, the bridge connection can be removed/disabled without affecting normal
      database connections.
- [ ] Confirm no schema migration is required to roll back (module is read‑only;
      config is stored in `ir.config_parameter`).

## 9. Known limitations (must be disclosed to the beta customer)

- [ ] Fixed, deterministic question set only (no free‑form analytics).
- [ ] Read‑only; no writes of any kind.
- [ ] **Company‑scoped** (`sudo_company_scoped`) — **not** per‑user record‑rule
      enforcement yet.
- [ ] Odoo **19.0 self‑hosted only**; **Odoo Online not supported**.
- [ ] Allow‑listed models only (customers, products, sales orders, invoices, lines).
- [ ] Beta build — interfaces/questions/versions may change between builds.

---

### Sign‑off

| Check | Owner | Status |
|---|---|---|
| Engineering validation (sections 1–7) | `<name>` | ☐ |
| Security review (section 7) | `<name>` | ☐ |
| Customer‑facing docs reviewed (README/INSTALL/SECURITY/SUPPORTED) | `<name>` | ☐ |
| Approved to issue private‑beta build | `<name>` | ☐ |

> Reminder: do **not** publish to the Odoo marketplace, do **not** mark
> production‑ready, and do **not** commit/deploy from this documentation step.
