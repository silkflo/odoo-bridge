# Odoo Bridge — Security Note (Private Beta)

This note describes the security model of the **Speak To Your Database Bridge**
module as validated for the private beta (module **`19.0.0.7.0`**, Odoo 19). It is
written to be honest about both the protections in place **and** the current
boundaries. Please read it before connecting the Bridge to live data.

---

## Design principle

The Bridge is a **narrow, read‑only, allow‑listed** read path into Odoo. It is built
so that the worst case is *“an allow‑listed business record was read”* — never a
write, never a credential disclosure, never arbitrary query execution.

## 1. Read‑only ORM access

- All Bridge data access goes through the **Odoo ORM**, using read operations only:
  list reads (`search_read`), counts, and aggregations (`read_group`).
- There is **no write path**. The Bridge performs **no** create, update, delete,
  confirm, post, or other state‑changing operation, and exposes no endpoint that
  could.

## 2. No SQL from Speak To Your Database to Odoo

- Speak To Your Database **does not send SQL** to Odoo through the Bridge. It calls a
  small, fixed set of read endpoints with structured parameters (model, domain
  filter, fields, grouping), which the module validates and runs via the ORM.
- The answer’s “How this answer was calculated” panel explicitly states that **no SQL
  was executed** and names the Odoo model and read operation used.

## 3. No write / create / update / delete

- The module’s read API cannot mutate data. Requests that imply a write are not
  supported and are rejected.
- Unsupported or unsafe requests return a structured, safe error — never a partial
  write and never a fallback to a broader query.

## 4. Allow‑listed models

Only a small set of standard business models is readable in this beta:

```text
res.partner          (customers / contacts)
sale.order           (sales orders & quotations)
account.move         (invoices / credit notes)
account.move.line    (invoice lines)
product.template     (products)
product.product      (product variants)
```

Any model **outside this allow‑list** (for example `res.users`,
`ir.config_parameter`, `mail.*`, `ir.attachment`, HR, or custom modules) is
**rejected**. Adding a model to the allow‑list is a deliberate, code‑level change —
it cannot be requested at runtime.

## 5. Allow‑listed fields

- Only **safe field types** may be returned or filtered: text, numeric/monetary,
  boolean, date/datetime, selection, and single relations (`many2one`). Heavy or
  unbounded types — binary, `one2many`, `many2many` — are excluded to bound payloads
  and avoid pulling large/relational blobs.
- Aggregations are restricted to **stored numeric / monetary** fields with a small
  set of functions (`sum`, `avg`, `min`, `max`) and validated grouping. A
  non‑numeric, non‑stored, or non‑allowed field cannot be aggregated.

## 6. Credential / security fields are blocked

- Any field whose name signals a secret is **never returned**, even on an
  allow‑listed model. Blocked name patterns include (case‑insensitive substrings):

  ```text
  password, passwd, token, api_key, secret, oauth,
  reset, signup, private_key, access_token, refresh_token
  ```

- “auth”‑like names are treated as credential hints, with narrow exceptions for
  genuine business words (e.g. `author_id`, `authorized_*`, `authority_id`) so that
  real fields stay usable while `auth_token`‑style secrets remain blocked.

## 7. Token handling — hash‑at‑rest in Odoo

- The bridge token is **strong random** (generated with `secrets.token_urlsafe`).
- Odoo stores **only the SHA‑256 hash** of the token (hash‑at‑rest). The raw token is
  **never** written to a database column, a configuration parameter, the Bridge
  Status page, or the logs.
- The raw token is shown **exactly once**, immediately after you generate or rotate
  it in **Connection Setup**. After that it cannot be retrieved — if lost, you must
  **rotate** to issue a new one. **Revoking** clears the hash and disables the Bridge.

## 8. Token handling — encrypted server‑side in Speak To Your Database

- On the Speak To Your Database side, the token you paste is stored **encrypted at
  rest** and used **server‑side only**. It is never exposed to the browser, never
  printed in answers, and never returned in answer metadata or provenance.
- Combined with hash‑at‑rest in Odoo, this means the **plaintext token exists only**
  in transit (over TLS) and for the one‑time display at generation.

## 9. The token is never shown again after setup

- There is no “view token” action anywhere — by design. Treat the one‑time display as
  your only copy. Rotate freely; rotation is cheap and safe.

## 10. Company‑scoped access mode (`sudo_company_scoped`)

- The current beta runs every read in **`sudo_company_scoped`** mode. Reads execute
  with elevated rights but are **bounded to the connector owner’s Odoo company
  scope**, and further restricted to the allow‑listed models/fields above.

### What this means

- Results follow the **company boundary** of the configured connector owner: data
  from companies outside that scope is not returned.
- The exposure surface is bounded to **read‑only, allow‑listed, non‑credential
  business data** within that company scope.

### What this does **not** mean

- It is **not** per‑user Odoo permission enforcement. Within the allowed company
  scope, the Bridge does **not** yet apply individual users’ **record rules** or
  per‑model ACLs. Two users who both use a Bridge thread see the same
  company‑scoped data, regardless of their personal Odoo restrictions.
- Treat the Bridge as a **company‑level** read connector for the beta. If your
  threat model requires per‑user/record‑rule parity, hold off on sensitive data
  until the stricter mode below ships.

## 11. Roadmap — stricter user / record‑rule mode

A future release is planned to add a stricter execution mode that honours
**per‑user permissions and record rules** (rather than company‑scoped sudo), so that
Bridge answers respect each user’s individual Odoo access. This is **not** part of the
current beta and no date is committed. Until then, the `sudo_company_scoped` behaviour
in section 10 applies.

---

## Operational recommendations

- Always run Odoo over **HTTPS**; the token is a bearer secret.
- Use a **dedicated internal user** as the connector owner, scoped to the company
  whose data you intend to expose.
- **Rotate** the token if it may have been exposed, and when offboarding.
- Review **Access Logs** (Speak To Your Database Bridge → Access Logs) periodically;
  every Bridge request is audited with an outcome and a token *fingerprint* (not the
  token itself).
- Never paste the raw token into a support ticket, chat, or screenshot.
