# Odoo Bridge — Installation Guide (Private Beta)

This guide installs the **Speak To Your Database Bridge** module on a self‑hosted
Odoo 19 server and connects it to Speak To Your Database. It covers a controlled
private‑beta build (module **`19.0.0.7.0`**). Please read [SECURITY.md](SECURITY.md)
before going live.

> The Bridge is **read‑only**. Installing it does not allow Speak To Your Database to
> change, create, or delete anything in Odoo.

---

## 1. Requirements

- **Self-hosted Odoo (15.0-19.0)** (Community or Enterprise) that you control
  (on-premise, VPS, or Docker). **Odoo Online is not supported** — it does not allow
  custom server addons.
- Odoo **administrator** access and the ability to edit `addons_path` / restart Odoo.
- **HTTPS** on the Odoo instance (strongly recommended; required for any real‑data
  use). The bridge token is a bearer secret and must travel over TLS.
- Network reachability from Speak To Your Database to your Odoo base URL.
- A running, licensed **Speak To Your Database** workspace with **Odoo Bridge** beta
  access enabled.

## 2. Odoo version

Validated bridge packages are available for Odoo 15.0, 16.0, 17.0, 18.0, and 19.0.
Use the module folder that matches your Odoo major version:

```text
15.0/styd_odoo_bridge
16.0/styd_odoo_bridge
17.0/styd_odoo_bridge
18.0/styd_odoo_bridge
19.0/styd_odoo_bridge
```

Install only the package that matches your Odoo major version. Do not mix series.

## 3. Install the module from the addon folder (manual)

Use the `styd_odoo_bridge` module folder provided with your private beta
invitation, either as a zip file or folder, and copy it so its **parent** directory
is on the Odoo addons path.

If you have repository access, you can instead clone it:

```bash
# On the Odoo server
cd /tmp
rm -rf odoo-bridge
git clone https://github.com/silkflo/odoo-bridge.git

# Copy ONLY your Odoo major version's module into your custom addons directory
sudo mkdir -p /opt/odoo/custom-addons
sudo rm -rf /opt/odoo/custom-addons/styd_odoo_bridge
sudo cp -r /tmp/odoo-bridge/19.0/styd_odoo_bridge /opt/odoo/custom-addons/styd_odoo_bridge
sudo chown -R odoo:odoo /opt/odoo/custom-addons/styd_odoo_bridge
sudo chmod -R 755 /opt/odoo/custom-addons/styd_odoo_bridge
```

Ensure the **parent** folder is in `addons_path` (edit `odoo.conf`):

```ini
; Correct — point at the PARENT directory that CONTAINS styd_odoo_bridge
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/opt/odoo/custom-addons
```

```text
Correct:  addons_path = ...,/opt/odoo/custom-addons
Wrong:    addons_path = ...,/opt/odoo/custom-addons/styd_odoo_bridge
```

**Docker:** the path in `addons_path` must be the path **inside the container**
(e.g. `/mnt/extra-addons`), and the module must be on a mounted host folder or a
persistent volume so it survives container recreation. The repository root
[`README.md`](../../README.md) and [`docs/INSTALL_SELF_HOSTED.md`](../INSTALL_SELF_HOSTED.md)
may still help with host / Docker / `addons_path` details — but their **token /
Settings** steps predate this private beta. For token setup, follow **§6–§7 below**
(the Connection Setup wizard); do **not** follow the older “enter the token in
Settings” flow.

Restart Odoo:

```bash
sudo systemctl restart odoo        # or: docker restart <odoo_container>
```

## 4. Update the Apps List

1. Log into Odoo as an administrator.
2. Open **Apps**. If you don’t see developer options, enable developer mode
   (`/web?debug=1`).
3. Click **Update Apps List** and confirm. *(Required after copying a new module.)*
4. Remove the **Apps** filter (so non‑official modules show) and search
   `Speak To Your Database` (the technical module name is `styd_odoo_bridge`).

## 5. Install / upgrade the module

- **First install:** open **Speak To Your Database Bridge** and click **Activate /
  Install**.
- **Upgrading a beta build:** copy the new `19.0/styd_odoo_bridge` over the old one,
  restart Odoo, **Update Apps List**, then on the module click **Upgrade**. Confirm
  the version reads **`19.0.0.7.0`** (Apps → module → technical info).

```bash
# Optional CLI upgrade (self-hosted)
odoo-bin -u styd_odoo_bridge -d <your_db> --stop-after-init
```

## 6. Generate / rotate the bridge token

The token is managed from the **Connection Setup** screen and is stored **only as a
hash** — it is never shown in Settings and never written to logs.

1. Open **Speak To Your Database Bridge → Connection Setup**.
2. Set **Connector Owner** (an internal Odoo user whose company scope the Bridge
   uses — typically an administrator).
3. Click **Generate token**.
4. **Copy the token now** — it is displayed **exactly once**. If you lose it, you must
   rotate to get a new one.

To **rotate** (replace) the token later, click **Rotate token** and re‑copy. To
**revoke**, click **Revoke token** — this clears the token and disables the Bridge as
a safe default.

> Keep the token secret. Treat it like a password. Anyone with the token and your
> Odoo URL can make the same read‑only, allow‑listed requests.

## 7. Enable the Bridge in Settings

1. Open **Settings** and search `Speak To Your Database` (or `Bridge`).
2. Tick **Enable Speak To Your Database Bridge**.
3. Confirm the **Connector Owner** is set.
4. Click **Save**. *(Without Save, the Bridge stays disabled.)*

## 8. Test the connection (Odoo side)

Use **Bridge Status** (under the Speak To Your Database Bridge menu) to confirm the
Bridge is enabled and a token is configured. You can also call the health endpoint
directly:

```bash
curl --location 'https://your-odoo-domain.com/styd_bridge/v1/health' \
  --header 'Authorization: Bearer YOUR_BRIDGE_TOKEN' \
  --header 'X-Odoo-Database: your_database_name'
```

A healthy response is `{"ok": true, ...}`. If you get `bridge_disabled`, re‑check
step 7 (enable + Save). If you get *unauthorized*, the token does not match — rotate
and re‑copy.

## 9. Copy the token into Speak To Your Database

1. Open Speak To Your Database → workspace **Settings → Connections**.
2. Select / create the Odoo connection.
3. Enter your **Odoo base URL** (e.g. `https://your-odoo-domain.com`).
4. Paste the **same token** generated in step 6.
5. Save / **Sync**. The token is stored **encrypted at rest** on the Speak To Your
   Database side and is never displayed again.

## 10. Select **Odoo Bridge** as the chat source

1. Start a **new chat thread**.
2. For the thread **source / connection**, choose **Odoo Bridge —
   `<your-odoo-host>`**.
3. The thread is now bound to the read‑only Bridge. Every answer in it is labelled
   **Source: Odoo Bridge** and never falls back to a SQL/database path.

## 11. Ask supported questions

Try a few from [SUPPORTED-QUESTIONS.md](SUPPORTED-QUESTIONS.md), for example:

```text
count customers
show recent quotations
sales orders this month
total unpaid amount
total sales for Azure Interior
```

A good answer shows **Source: Odoo Bridge**, **Confidence: High (0.9)**, and a “How
this answer was calculated” panel that names the Odoo model, the read‑only operation,
and confirms no SQL was run. An unsupported question returns a safe “not supported
yet” message (still labelled Odoo Bridge).

---

### Quick verification checklist

- [ ] Module shows version `19.0.0.7.0` in Apps.
- [ ] `…/styd_bridge/v1/health` returns `{"ok": true}`.
- [ ] Bridge **enabled** and **saved** in Settings; connector owner set.
- [ ] Token generated, copied once, pasted into Speak To Your Database, synced.
- [ ] A bridge thread answers `count customers` with **Source: Odoo Bridge**.
- [ ] An unsupported question returns the safe “not supported yet” message.
