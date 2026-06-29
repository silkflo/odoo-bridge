# Speak To Your Database Odoo Bridge — Self-Hosted Installation Guide

## Overview

This guide explains how to install the `styd_odoo_bridge` module on a self-hosted Odoo instance.

This module enables a trusted security bridge between Odoo and Speak To Your Database.

## Supported environments

- Self-hosted Odoo with server access
- Custom addons path available
- Odoo admin access
- Developer mode available in the Odoo UI

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

## 6. Configure the module in Odoo

Open **Settings** and search for `Speak To Your Database`.

Configure:

- **Enable Speak To Your Database Bridge**
- **Speak To Your Database Bridge Token**
- **Speak To Your Database Connector Owner**

Notes:

- **Enable Speak To Your Database Bridge**
  - turn this on to allow the bridge endpoints to respond

- **Speak To Your Database Bridge Token**
  - enter any secret string you choose
  - use a long random value
  - example:
    - `styd-bridge-7f92c1b9-very-secret`
  - you must use the exact same token later in Speak To Your Database

- **Speak To Your Database Connector Owner**
  - choose the Odoo user whose trusted scope will be used for the connector-owner snapshot

Then save.

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
- enter the same bridge token you saved in Odoo
- enter the Odoo database name if required
- run bridge sync

## Upgrade the module later

When the module code changes:

```bash
sudo -u odoo /usr/bin/python3 /usr/bin/odoo --config /etc/odoo/odoo.conf -d YOUR_DATABASE -u styd_odoo_bridge --stop-after-init
sudo systemctl restart odoo.service
```

## Uninstall

Use the Odoo Apps UI or uninstall from Odoo shell if needed.
