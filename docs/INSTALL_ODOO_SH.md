# Speak To Your Database Odoo Bridge — Odoo.sh Installation Guide

## Overview

This guide explains how to deploy `styd_odoo_bridge` on **Odoo.sh**.

Odoo.sh is best handled through Git-based deployment:

1. Add the correct bridge module folder to your Odoo.sh Git repository.
2. Push the branch.
3. Let Odoo.sh build and deploy.
4. Install / Activate the module from Odoo Apps.
5. Open **Speak To Your Database → Connection Setup**: enable the bridge, choose the connector owner, and save.
6. Generate the bridge token and copy it (shown once).
7. Test the bridge endpoints.
8. Sync the bridge from Speak To Your Database.

---

## Supported Odoo versions

Use the bridge folder matching your Odoo version.

| Odoo version | Module folder |
|---|---|
| Odoo 15 | `15.0/styd_odoo_bridge` |
| Odoo 16 | `16.0/styd_odoo_bridge` |
| Odoo 17 | `17.0/styd_odoo_bridge` |
| Odoo 18 | `18.0/styd_odoo_bridge` |
| Odoo 19 | `19.0/styd_odoo_bridge` |
| Odoo 20 | `20.0/styd_odoo_bridge` |

Example:

```text
If your Odoo.sh project runs Odoo 18.0, use:
18.0/styd_odoo_bridge
```

Do **not** install the wrong version folder unless instructed by Speak To Your Database support.

> **Odoo Online (Custom plan): use an API key.** Odoo Online (odoo.com) cannot install custom server modules, so this module cannot run there. On the Custom plan, connect Odoo Online to Speak To Your Database with an Odoo API key instead — no module needed.

---

## Module name

Technical module name:

```text
styd_odoo_bridge
```

Display name in Odoo:

```text
Speak To Your Database Odoo Bridge
```

---

## Recommended repository structure

Example:

```text
repo-root/
└── addons/
    └── styd_odoo_bridge/
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

You can place the module in another custom addons folder if your Odoo.sh project is configured to load it.

---

## 1. Add the correct version module to your repository

Copy the `styd_odoo_bridge` folder matching your Odoo version into your Odoo.sh repository.

Example for Odoo 18:

```text
18.0/styd_odoo_bridge
```

Recommended target in your Odoo.sh repository:

```text
addons/styd_odoo_bridge
```

After copying, your repository should contain:

```text
addons/styd_odoo_bridge/__manifest__.py
addons/styd_odoo_bridge/controllers/
addons/styd_odoo_bridge/models/
addons/styd_odoo_bridge/security/
addons/styd_odoo_bridge/views/
addons/styd_odoo_bridge/static/
```

---

## 2. Commit and push

Example:

```bash
git add .
git commit -m "Add Speak To Your Database Odoo Bridge module"
git push origin YOUR_BRANCH
```

Replace `YOUR_BRANCH` with the Odoo.sh branch you want to deploy.

---

## 3. Let Odoo.sh build the branch

After pushing:

1. Open your Odoo.sh project.
2. Select the branch.
3. Wait for the build to finish.
4. Make sure the build is successful.
5. Open the Odoo deployment for that branch.

If the build fails, check the Odoo.sh build logs for Python, XML, manifest, or dependency errors.

---

## 4. Install / activate the module in Odoo

After deployment, log into Odoo as an administrator.

### 4.1 Enable developer mode if needed

If you cannot find the module, enable developer mode.

You can usually open:

```text
https://YOUR_ODOO_SH_DOMAIN/web?debug=1
```

Then go back to **Apps**.

### 4.2 Open Apps

Go to:

```text
Apps
```

### 4.3 Update the Apps List

Click:

```text
Update Apps List
```

Confirm the update.

This step is required after adding a new module to the repository.

### 4.4 Search for the bridge

Search for:

```text
Speak To Your Database
```

or:

```text
Speak To Your Database Odoo Bridge
```

or:

```text
styd_odoo_bridge
```

If the module is not visible:

- remove filters such as `Official Apps`
- make sure you are viewing all apps/modules
- confirm that the module was deployed in the Odoo.sh branch
- confirm that the module folder is named exactly `styd_odoo_bridge`
- update the Apps List again
- refresh the page and search `Speak To Your Database`

### 4.5 Activate / install the module

Open:

```text
Speak To Your Database Odoo Bridge
```

Click:

```text
Activate
```

or:

```text
Install
```

depending on your Odoo version.

After this step, the module is installed, but the bridge is not active yet.

---

## 5. Set up the connection in Odoo (Connection Setup)

Installing the module is not enough. You must set up the connection in Odoo.

### 5.1 Open Connection Setup

Go to:

```text
Speak To Your Database → Connection Setup
```

### 5.2 Enable the bridge and choose the connector owner

1. Set **Bridge Enabled**.
2. Choose the **Connector Owner**: the Odoo user whose trusted security scope will be used as the
   connector-owner snapshot. Usually an Odoo administrator or the Odoo user responsible for
   connecting Speak To Your Database.
3. Click **Save Settings**.

### 5.3 Generate the bridge token

Click **Generate Token** (or **Rotate Token** if you are replacing an existing token).

Copy the token shown on the page. It is displayed **once** — store it securely. Odoo stores only its
SHA-256 hash, so it cannot be shown again; if you lose it, rotate it.

You will paste this token into Speak To Your Database.

**Revoke Token** clears the token and disables the bridge.

### 5.4 What the Settings page shows

**Settings → Speak To Your Database** shows **Enable Speak To Your Database Bridge**, the
**Connector Owner**, and a read-only **Token Configured** indicator. The token itself is never shown
or typed there.

If the bridge is not enabled and saved, Speak To Your Database will receive:

```json
{
  "ok": false,
  "error": "bridge_disabled",
  "detail": "Speak To Your Database bridge is disabled in Odoo settings."
}
```

### 5.5 Upgrading from an earlier bridge release

Earlier 15.0–18.0 packages (0.9.x and older) stored the token in plain text in Settings. Upgrading the
module hashes that token in place automatically, so your existing Speak To Your Database connection
keeps working with the same token — nothing to re-enter. After the upgrade the token can no longer be
read back from Odoo; rotate it if you need a new copy.

On Odoo.sh, pushing the new module version triggers this upgrade automatically on deploy.

---

## 6. Verify the bridge health endpoint

If your Odoo.sh instance hosts multiple databases, include the `X-Odoo-Database` header.

Replace:

- `YOUR_ODOO_SH_DOMAIN` with your Odoo.sh domain
- `YOUR_REAL_TOKEN` with the token generated in Connection Setup
- `YOUR_DATABASE` with your Odoo database name

```bash
curl --location 'https://YOUR_ODOO_SH_DOMAIN/styd_bridge/v1/health' \
  --header 'Authorization: Bearer YOUR_REAL_TOKEN' \
  --header 'X-Odoo-Database: YOUR_DATABASE'
```

Expected result:

```json
{
  "ok": true,
  "bridge_version": "0.3.0",
  "odoo_version": "...",
  "odoo_series": "...",
  "edition": "community",
  "database_uuid": "...",
  "server_time_utc": "...",
  "timezone": "Europe/Paris",
  "supported_features": [
    "security_snapshot_v1",
    "odoo_user_directory_v1",
    "odoo_capability_snapshot_v1",
    "tz_aware_v1"
  ]
}
```

If the response returns `bridge_disabled`, go back to **Speak To Your Database → Connection Setup**, enable the bridge, choose the connector owner, and click **Save Settings**.

---

## 7. Verify the user directory endpoint

```bash
curl --location 'https://YOUR_ODOO_SH_DOMAIN/styd_bridge/v1/users/directory' \
  --header 'Authorization: Bearer YOUR_REAL_TOKEN' \
  --header 'X-Odoo-Database: YOUR_DATABASE'
```

Expected response includes:

```json
{
  "bridge_version": "0.3.0",
  "snapshot_version": 1,
  "generated_at_utc": "...",
  "users": [
    {
      "odoo_user_id": 2,
      "login": "admin@example.com",
      "name": "Admin",
      "email": "admin@example.com",
      "is_active": true,
      "allowed_company_ids": [1],
      "default_company_id": 1,
      "rights_summary": {
        "accounting": true,
        "sales": true,
        "inventory": true,
        "multi_company": false
      }
    }
  ]
}
```

---

## 8. Verify the security snapshot endpoint

```bash
curl --location 'https://YOUR_ODOO_SH_DOMAIN/styd_bridge/v1/security/snapshot' \
  --header 'Authorization: Bearer YOUR_REAL_TOKEN' \
  --header 'X-Odoo-Database: YOUR_DATABASE'
```

Expected response includes:

- connector owner
- company scope
- company labels
- groups
- model access
- security flags
- supported features
- Odoo version and series

---

## 9. Connect from Speak To Your Database

In the **workspace Odoo settings** in Speak To Your Database:

1. Enter the Odoo base URL.
2. Paste the bridge token generated in Connection Setup.
3. Enter the Odoo database name if required.
4. Run **Sync bridge**.

After sync, Speak To Your Database should display:

- bridge status
- connector owner
- available Odoo users
- company labels
- user rights summary
- mapping options for workspace members

---

## Upgrade the module later

When the bridge module code changes:

1. Commit the changes to the Odoo.sh repository.
2. Push the branch again.
3. Let Odoo.sh rebuild the branch.
4. Upgrade the module from Apps if needed.

In Odoo:

```text
Apps → Speak To Your Database Odoo Bridge → Upgrade
```

Then verify:

```text
/styd_bridge/v1/health
```

---

## Troubleshooting

### The module is not visible in Apps

Check:

1. Did you copy the folder matching your Odoo version?
2. Is the folder named exactly `styd_odoo_bridge`?
3. Was the branch deployed successfully by Odoo.sh?
4. Did you enable developer mode?
5. Did you click **Update Apps List**?
6. Did you remove filters such as `Official Apps`?
7. Did you search for `Speak To Your Database`?

### The bridge endpoint returns `bridge_disabled`

The module is installed, but the bridge was not enabled.

Fix:

1. Go to **Speak To Your Database → Connection Setup**.
2. Set **Bridge Enabled**.
3. Choose the connector owner.
4. Click **Save Settings**.
5. If no token is configured yet, click **Generate Token** and copy it.

### The bridge endpoint returns unauthorized

Check that the token in your request is the one generated in Connection Setup. Odoo stores only a
hash of the token, so it cannot be shown again: if unsure, click **Rotate Token** and update the token in
Speak To Your Database.

Example:

```bash
curl --location 'https://YOUR_ODOO_SH_DOMAIN/styd_bridge/v1/health' \
  --header 'Authorization: Bearer YOUR_REAL_TOKEN' \
  --header 'X-Odoo-Database: YOUR_DATABASE'
```

### The wrong database is used

Send the database name with:

```text
X-Odoo-Database: YOUR_DATABASE
```

This is especially important on multi-database Odoo.sh deployments.

---

## Notes

- Odoo.sh is supported.
- Odoo Online cannot install custom Python modules: on the Custom plan, connect it with an Odoo API key instead — no module needed.
- The bridge token is stored only as a SHA-256 hash in Odoo.
- Use HTTPS in production.
- Use a strong bridge token.
- Store the token securely.
- The bridge exposes security and metadata context, not uncontrolled raw business data.
- Effective Speak To Your Database access is:

```text
trusted Odoo scope ∩ Speak To Your Database workspace restrictions
```
