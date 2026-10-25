# Speak To Your Database Odoo Bridge — Self-Hosted Installation Guide

## Overview

This guide explains how to install the `styd_odoo_bridge` module on a self-hosted Odoo instance.

This module enables a trusted security bridge between Odoo and Speak To Your Database.

## Supported environments

- Self-hosted Odoo 15.0, 16.0, 17.0, 18.0, 19.0, or 20.0 with server access (use the module folder matching
  your Odoo major version, e.g. `20.0/styd_odoo_bridge` for Odoo 20.0)
- Custom addons path available
- Odoo admin access
- Developer mode available in the Odoo UI

> **Odoo Online (Custom plan): use an API key.** Odoo Online (odoo.com) cannot install custom server modules, so this module cannot run there. On the Custom plan, connect Odoo Online to Speak To Your Database with an Odoo API key instead — no module needed.

## Module name

Technical module name:

`styd_odoo_bridge`

## Expected module structure

```text
styd_odoo_bridge/
├── __init__.py
├── __manifest__.py
├── controllers/
├── models/
├── security/
├── static/
│   └── description/
│       └── icon.png
└── views/
```

## 1. Copy the module to the server

Place the module folder inside a custom addons directory on the Odoo server.

Example target:

```text
/opt/odoo/custom-addons/styd_odoo_bridge
```

From your local machine, copy the module folder to the server with `scp`:

```bash
scp -r ./styd_odoo_bridge YOUR_SERVER_USER@YOUR_SERVER_IP:/tmp/styd_odoo_bridge
```

Then connect to the server and move it into the Odoo custom addons directory:

```bash
ssh YOUR_SERVER_USER@YOUR_SERVER_IP
sudo mkdir -p /opt/odoo/custom-addons
sudo rm -rf /opt/odoo/custom-addons/styd_odoo_bridge
sudo mv /tmp/styd_odoo_bridge /opt/odoo/custom-addons/styd_odoo_bridge
```

Replace:

- `YOUR_SERVER_USER` with your SSH user, for example `root` or `odoo`
- `YOUR_SERVER_IP` with your server IP address

After copying, the server should look like this:

```text
/opt/odoo/custom-addons/
└── styd_odoo_bridge
    ├── __init__.py
    ├── __manifest__.py
    ├── controllers/
    ├── models/
    ├── security/
    ├── static/
    └── views/
```

## 2. Add the custom addons path to Odoo config

Edit your Odoo config file and add the parent folder to `addons_path`.

Most self-hosted Odoo installations use this config file:

```text
/etc/odoo/odoo.conf
```

First, check that the config file exists:

```bash
ls -l /etc/odoo/odoo.conf
```

Create a backup before editing:

```bash
sudo cp /etc/odoo/odoo.conf /etc/odoo/odoo.conf.backup
```

Check the current `addons_path` value:

```bash
grep '^addons_path' /etc/odoo/odoo.conf
```

Open the config file:

```bash
sudo nano /etc/odoo/odoo.conf
```

Then update `addons_path` so it includes `/opt/odoo/custom-addons`.

Example:

```ini
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/opt/odoo/custom-addons
```

Save and exit nano:

```text
CTRL + O
ENTER
CTRL + X
```

After saving, verify that the config was updated:

```bash
grep '^addons_path' /etc/odoo/odoo.conf
```

Important:

- add the parent folder: `/opt/odoo/custom-addons`
- do **not** point `addons_path` directly to `/opt/odoo/custom-addons/styd_odoo_bridge`

Why:
- Odoo scans a directory that contains modules
- inside that directory, it finds module folders such as `styd_odoo_bridge`

So this is correct:

```text
addons_path = ...,/opt/odoo/custom-addons
```

And this is wrong:

```text
addons_path = ...,/opt/odoo/custom-addons/styd_odoo_bridge
```

At this point, the required server-side install commands are:

```bash
sudo mkdir -p /opt/odoo/custom-addons
sudo cp /etc/odoo/odoo.conf /etc/odoo/odoo.conf.backup
sudo nano /etc/odoo/odoo.conf
grep '^addons_path' /etc/odoo/odoo.conf
sudo chown -R odoo:odoo /opt/odoo/custom-addons
sudo chmod 755 /opt/odoo/custom-addons
sudo find /opt/odoo/custom-addons -type d -exec chmod 755 {} \;
sudo find /opt/odoo/custom-addons -type f -exec chmod 644 {} \;
sudo systemctl restart odoo.service
sudo systemctl status odoo.service --no-pager
```

## 3. Fix permissions

Example:

```bash
sudo chown -R odoo:odoo /opt/odoo/custom-addons
sudo chmod 755 /opt/odoo/custom-addons
sudo find /opt/odoo/custom-addons -type d -exec chmod 755 {} \;
sudo find /opt/odoo/custom-addons -type f -exec chmod 644 {} \;
```

What each line does:

- `sudo chown -R odoo:odoo /opt/odoo/custom-addons`
  - makes the Odoo system user the owner of the custom addons folder and everything inside it

- `sudo chmod 755 /opt/odoo/custom-addons`
  - ensures Odoo can enter and read the parent addons folder

- `sudo find /opt/odoo/custom-addons -type d -exec chmod 755 {} \;`
  - gives all subfolders the right permissions so Odoo can open them

- `sudo find /opt/odoo/custom-addons -type f -exec chmod 644 {} \;`
  - gives all files read permissions so Odoo can load Python, XML, CSV, and image files

## 4. Restart Odoo

Example:

```bash
sudo systemctl restart odoo.service
sudo systemctl status odoo.service --no-pager
```

## 5. Install the module

### Option A — Odoo UI

1. Enable developer mode
2. Open **Apps**
3. Click **Update Apps List**
4. Search for `Speak To Your Database Odoo Bridge` or `styd_odoo_bridge`
5. Click **Activate**

### Option B — CLI

```bash
sudo -u odoo /usr/bin/python3 /usr/bin/odoo --config /etc/odoo/odoo.conf -d YOUR_DATABASE -i styd_odoo_bridge --stop-after-init
sudo systemctl restart odoo.service
```

Replace `YOUR_DATABASE` with the target Odoo database name.

## 6. Configure the module in Odoo (Connection Setup)

Open **Speak To Your Database → Connection Setup**.

1. Set **Bridge Enabled** to allow the bridge endpoints to respond.
2. Choose the **Connector Owner**: the Odoo user whose trusted scope will be used for the
   connector-owner snapshot.
3. Click **Save Settings**.
4. Click **Generate Token** (or **Rotate Token** to replace an existing one) and copy the token shown.
   It is displayed **once**; Odoo stores only its SHA-256 hash. You will paste it into Speak To Your
   Database.

**Revoke Token** clears the token and disables the bridge.

**Settings → Speak To Your Database** shows the enable switch, the connector owner, and a read-only
**Token Configured** indicator. The token itself is never shown or typed there.

## 7. Health check

If your Odoo server hosts multiple databases, include the `X-Odoo-Database` header.

Example:

```bash
curl -H "Authorization: Bearer YOUR_REAL_TOKEN" -H "X-Odoo-Database: YOUR_DATABASE" http://127.0.0.1:8069/styd_bridge/v1/health
```

Expected result:

```json
{
  "ok": true
}
```

## 8. Security snapshot test

```bash
curl -H "Authorization: Bearer YOUR_REAL_TOKEN" -H "X-Odoo-Database: YOUR_DATABASE" http://127.0.0.1:8069/styd_bridge/v1/security/snapshot
```

Expected result:
- connector owner
- company scope
- groups
- model access
- security flags

## 9. Connect from Speak To Your Database

In the **workspace Odoo settings** in Speak To Your Database:

- enter the Odoo base URL
- paste the bridge token generated in Connection Setup
- enter the Odoo database name if required
- run bridge sync

## Upgrade the module later

When the module code changes:

```bash
sudo -u odoo /usr/bin/python3 /usr/bin/odoo --config /etc/odoo/odoo.conf -d YOUR_DATABASE -u styd_odoo_bridge --stop-after-init
sudo systemctl restart odoo.service
```

**Upgrading from an earlier bridge release (0.9.x or older):** earlier 15.0–18.0 packages stored the token
in plain text in Settings. The upgrade hashes that token in place automatically, so your existing Speak To
Your Database connection keeps working with the same token — nothing to re-enter. After the upgrade the
token can no longer be read back from Odoo; rotate it in Connection Setup if you need a new copy.

## Uninstall

Use the Odoo Apps UI or uninstall from Odoo shell if needed.
