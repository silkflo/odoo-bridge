# Speak To Your Database — Odoo Bridge Private Beta

> **Status: Private / Controlled Beta.** This package is shared with a small set of
> invited customers for evaluation. It is **not** a public release, it is **not** on
> the Odoo marketplace, and it should **not** be treated as production‑ready. Please
> read the [Beta disclaimer](#beta-disclaimer) before installing.

Validated module version: **`19.0.0.4.0`** · Odoo series: **19.0** · Mode: **read‑only**

---

## What it is

The **Odoo Bridge** is a security‑focused, **read‑only** connector that lets **Speak To Your
Database** answer a fixed set of deterministic business questions from your Odoo
data — through the Odoo ORM, **without exposing your database credentials and
without running SQL against Odoo**.

You install a small Odoo module (`styd_odoo_bridge`) on your own Odoo server. The
module exposes a narrow, allow‑listed, token‑authenticated read API. Speak To Your
Database calls that API to read only what it needs to answer a supported question,
and returns a plain‑language answer with a clear **Source: Odoo Bridge** label.

The Bridge is deliberately small. It is a controlled read path — not a general query
engine, not a write channel, and not a replacement for Odoo reporting.

## Who it is for

- Existing or prospective **Speak To Your Database** customers who run a
  **self‑hosted Odoo 19** instance (on‑premise, VPS, or Docker) and have invited
  beta access.
- Operated by an **Odoo administrator** or trusted technical owner who can install a
  server addon and manage a connection token.
- Teams that want quick, plain‑language answers to common sales / invoicing /
  customer questions without granting raw database access.

## Current beta status

- **Controlled private beta.** Functionality is intentionally limited to a
  deterministic, allow‑listed question set (see
  [Supported questions](SUPPORTED-QUESTIONS.md)).
- Validated in controlled testing on Odoo 19 with module `19.0.0.4.0`:
  - read‑only bridge evaluation: **24 checks passed, 0 warnings, 0 failures**;
  - demo‑readiness rehearsal: **all demo prompts pass** (Source: Odoo Bridge, high
    confidence, no SQL, no credential exposure).
- Interfaces, supported questions, and version numbers **may change** during the
  beta. Expect to re‑install or upgrade the module between beta builds.

## Supported Odoo version

- **Validated for this beta:** Odoo **19.0**, module folder `19.0/styd_odoo_bridge`,
  version **`19.0.0.4.0`**.
- The repository also contains module folders for Odoo 15.0–18.0, but **only 19.0 is
  part of this validated private‑beta package.** Use another series only if Speak To
  Your Database support explicitly asks you to.
- **Odoo Online (odoo.com‑hosted) is not supported** in this beta — it does not allow
  installing custom server addons. A self‑hosted Odoo instance is required.

## What it can answer today

Deterministic, read‑only questions over a small set of standard Odoo models
(customers, products, sales orders, quotations, invoices). Examples:

- counts — e.g. *count customers*, *count unpaid invoices*;
- lists — e.g. *show customers*, *show recent quotations*, *sales orders this month*;
- totals — e.g. *total unpaid amount*, *total sales this month*;
- customer‑specific — e.g. *orders for Azure Interior*, *total sales for Azure Interior*.

See the full list and the exact phrasing that is recognised in
[SUPPORTED-QUESTIONS.md](SUPPORTED-QUESTIONS.md).

## What it cannot answer yet

- Anything requiring a **write** (create / update / delete / confirm / post). The
  Bridge is read‑only by design.
- **Free‑form analytics** or arbitrary SQL‑style queries.
- **General knowledge** questions (the Bridge answers only from your Odoo data).
- Models **outside the allow‑list** (the beta covers customers, products, sales
  orders, invoices and their lines only) or **custom modules**.
- Per‑user / per‑record‑rule scoping (the beta uses **company‑scoped** access — see
  [Security model](#security-model)).

Unsupported questions return a safe, clearly‑labelled “not supported yet” message —
they never fall back to SQL or to your normal database connection.

## Security model

Short version (full detail in [SECURITY.md](SECURITY.md)):

- **Read‑only ORM** access — no SQL is sent from Speak To Your Database to Odoo, and
  no create / update / delete is possible through the Bridge.
- **Allow‑listed models and fields** — only a small set of standard business models
  is readable; credential and security fields are blocked from being returned.
- **Token‑authenticated** — every request carries a bearer token. The token is
  stored **only as a SHA‑256 hash** in Odoo (hash‑at‑rest) and is **encrypted
  server‑side** in Speak To Your Database. The raw token is shown **once** at setup
  and never again.
- **Company‑scoped** — the current beta runs in `sudo_company_scoped` mode: results
  follow the connector’s Odoo company scope. This is a company‑level boundary, **not**
  per‑user record‑rule enforcement (planned for a later release).

## Install overview

1. Copy the `19.0/styd_odoo_bridge` module into a custom addons folder on your Odoo
   server and ensure its **parent** folder is in `addons_path`.
2. Restart Odoo, **Update Apps List**, then install **Speak To Your Database Bridge**.
3. Open **Speak To Your Database Bridge → Connection Setup**, **Generate token**, and
   copy it (shown once).
4. In **Settings**, enable the Bridge, choose the connector owner, and **Save**.
5. Paste the token (and your Odoo base URL) into Speak To Your Database and sync.

Step‑by‑step instructions: [INSTALLATION.md](INSTALLATION.md).

## Setup overview

- The **token** is generated, rotated, and revoked from the **Connection Setup**
  screen — never typed into Settings, and stored only as a hash.
- **Settings** controls only *Enable Bridge* and the *Connector Owner*.
- Use **Bridge Status** and **Access Logs** (under the same menu) to confirm the
  Bridge is live and to review recent read activity.
- In Speak To Your Database, select **Odoo Bridge** as the chat source for a thread,
  then ask a supported question. Answers are labelled **Source: Odoo Bridge**.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Module not visible in Apps | Apps list not refreshed / wrong addons path | Update Apps List; confirm the **parent** of `styd_odoo_bridge` is in `addons_path`; restart Odoo |
| Health check returns `bridge_disabled` | Bridge not enabled / not saved | Settings → enable the Bridge → **Save** |
| Requests return *unauthorized* | Token mismatch | Re‑generate the token in Connection Setup and re‑paste it into Speak To Your Database |
| Wrong database answered | Multi‑DB Odoo server | Ensure the configured Odoo database name is correct |
| Answer shows *Source: Database* (not Odoo Bridge) | Thread not using the Bridge connection | Start a thread whose source is **Odoo Bridge** |
| “Not supported yet” message | Question outside the beta set | Rephrase using a [supported question](SUPPORTED-QUESTIONS.md) |

For install, token, and connection setup, follow [INSTALLATION.md](INSTALLATION.md).
The repository root [`README.md`](../../README.md) and the older `docs/INSTALL_*`
guides may help with host / Docker setup, but they **predate this private beta’s
Connection Setup token flow** — defer to [INSTALLATION.md](INSTALLATION.md) for
token and Settings steps.

## Support / contact

- This is an **invitation‑only** beta. For help, **reply to the private‑beta
  invitation** you received, or contact the Speak To Your Database representative who
  provisioned your access.
- When reporting an issue, please include: Odoo series + module version
  (`19.0.0.4.0`), the exact question you asked, the **Source** label shown, and a
  screenshot of **Bridge Status**. **Never** include the raw token in a report.
- Support email: `<your-private-beta-contact-email>` *(provided with your invite)*.

## Beta disclaimer

This software is provided for **private beta evaluation only**, on an “as‑is” basis,
with **no warranty** and **no uptime or data guarantees**. It is **not
production‑ready** and should be evaluated on non‑critical data or a copy where
possible. Features, APIs, supported questions, and version numbers may change or be
removed without notice during the beta. Do not redistribute this package or publish
it to the Odoo marketplace. Use is subject to the terms of your beta agreement with
Speak To Your Database.

---

### Package contents

| File | Purpose |
|---|---|
| [`README.md`](README.md) | This overview (start here) |
| [`INSTALLATION.md`](INSTALLATION.md) | Step‑by‑step install, token, and connection setup |
| [`SECURITY.md`](SECURITY.md) | Security model, token handling, access scope |
| [`SUPPORTED-QUESTIONS.md`](SUPPORTED-QUESTIONS.md) | Supported and unsupported questions |
| [`RELEASE-CHECKLIST.md`](RELEASE-CHECKLIST.md) | Internal pre‑beta release checklist |

*Internal note: “STYD” is internal shorthand for Speak To Your Database and is used
only in internal/engineering documents, never in customer‑facing copy.*
