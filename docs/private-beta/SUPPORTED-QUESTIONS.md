# Odoo Bridge — Supported Questions (Private Beta)

The Odoo Bridge answers a **fixed, deterministic** set of read‑only business
questions. This is intentional for the beta: every supported question maps to a
known, allow‑listed Odoo read, so answers are predictable and safe.

**How to read this list**

- Use the phrasings below. Close variations often work, but the **supported set is
  fixed** for the beta — if a question isn’t recognised, you’ll get a safe “not
  supported yet” message (still labelled **Source: Odoo Bridge**), never a guess.
- **`Azure Interior`** is an example customer name. Replace it with a real customer in
  your Odoo data. If the name matches one customer, it is used; if it matches several,
  the Bridge asks you to pick; if none, it says so — it never silently guesses.
- All answers are **read‑only** and labelled **Source: Odoo Bridge**, typically with
  **Confidence: High (0.9)**.

---

## Supported questions

### Counts

```text
count customers
count products
count unpaid invoices
```

### Lists

```text
show customers
show products
show recent quotations
sales orders this month
confirmed sales orders this month
draft quotations this month
overdue invoices
invoices due soon
```

### Totals

```text
total unpaid amount
total overdue amount
total sales this month
```

### Rankings

```text
top customers by revenue
```

### Customer‑specific (replace “Azure Interior” with a real customer)

```text
orders for Azure Interior
quotations for Azure Interior
invoices for Azure Interior
unpaid invoices for Azure Interior
total unpaid amount for Azure Interior
total sales for Azure Interior
total sales this month for Azure Interior
```

---

## What a good answer looks like

For a supported question you should see:

- **Source: Odoo Bridge**
- **Confidence: High (0.9)** (a number is exact, a list shows the matching rows)
- a **“How this answer was calculated”** panel that names the Odoo model, the
  read‑only operation (`search_read` / `read_group`), any filter applied, and
  confirms **no SQL was executed**.

---

## Not supported (today)

These are intentionally out of scope for the private beta. They return a safe
“not supported yet” message and **never** fall back to SQL or your normal database
connection:

- **Writing data** — create / update / delete / confirm / post / cancel any Odoo
  record. The Bridge is read‑only.
- **General knowledge** — questions not answerable from your Odoo data
  (e.g. *“how tall is Mount Everest”*).
- **Free‑form / SQL‑style analytics** — arbitrary cross‑model joins, custom
  aggregations, or unrestricted query building.
- **Non‑allow‑listed models** — anything beyond customers, products, sales orders,
  invoices, and their lines (e.g. users, settings, mail, attachments, HR).
- **Custom modules / custom models** — not readable unless explicitly added to the
  allow‑list in a later, code‑level release.
- **Custom model discovery** — the Bridge does not browse or expose arbitrary models
  on request.
- **Odoo Online (odoo.com‑hosted)** — custom server addons can’t be installed there,
  so the Bridge cannot run on Odoo Online in this beta.

---

## Tips

- Keep questions in the **shape** shown above (an action + an object, optionally
  `… this month` or `… for <Customer>`).
- If a customer‑specific question returns a “please choose” prompt, the name matched
  more than one customer — use a more specific name.
- Found a question you expected to work but didn’t? It’s useful beta feedback —
  include the exact wording when you report it (see
  [README → Support](README.md#support--contact)).
