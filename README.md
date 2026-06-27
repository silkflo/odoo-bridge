# Speak To Your Database Odoo Bridge

The Odoo 19.0 bridge module (`styd_odoo_bridge`) for **Speak To Your Database**.

The bridge lets Speak To Your Database read safe Odoo metadata such as users, companies, permissions, installed modules, models, fields, and capability information. It is used to make Speak To Your Database safer and more accurate when answering Odoo questions.

The bridge is **read-only**. It uses the Odoo ORM, sends no SQL to Odoo, and does **not** write, create, update, or delete records.

---

## Supported Odoo versions

| Odoo version | How to connect | Status |
|---|---|---|
| Odoo 19.0 | `19.0/styd_odoo_bridge` | Bridge module validated / marketplace baseline |
| Odoo 18.0 | Direct database connection for now | Bridge planned |
| Odoo 17.0 | Direct database connection for now | Bridge planned |
| Odoo 16.0 | Direct database connection for now | Bridge planned |
| Odoo 15.0 | Direct database connection for now | Bridge planned |

> ⚠️ **Do not install the Odoo 19 bridge on older Odoo versions.** The module is validated only against Odoo 19.0. For Odoo 15–18, use a secured direct database connection (see Path B below) until a matching bridge module is released.

---

## Choose your setup path

### Path A — Odoo 19.0 (bridge)

1. Install `19.0/styd_odoo_bridge` on your Odoo server.
2. Configure the bridge in Odoo (enable it, choose the connector owner, generate a token).
3. Connect in Speak To Your Database under `/settings?tab=odoo`.

### Path B — Odoo 15–18 (direct database connection)

1. The bridge module is **not validated** for these versions yet.
2. Use a secured **direct database connection** instead.
3. Configure it under `/settings?tab=connections`.
4. Use **read-only** database credentials and network restrictions.

### Path C — Odoo Online

1. The bridge is **not supported** on Odoo Online — custom Python modules cannot be installed there.
2. A direct database connection is usually **not available** on Odoo Online either.
3. If you are unsure about your hosting, contact us.

---

## What the bridge provides

The bridge exposes safe metadata to Speak To Your Database, including:

- Odoo version and edition
- installed modules
- user directory
- allowed companies
- default company
- company labels
- user access summary
- readable model permissions
- model and field metadata
- Odoo capability snapshot

The bridge does **not** expose uncontrolled raw business data, and it never modifies anything in Odoo. It is designed as a trusted, read-only metadata and security layer.

---

## Path A — Odoo 19.0 bridge installation

The installation has four main steps:

1. Copy the `19.0/styd_odoo_bridge` folder to a custom addons directory.
2. Confirm the custom addons parent directory is included in Odoo's `addons_path`.
   - For standard self-hosted Odoo, this may require editing `odoo.conf`.
   - For Docker Odoo, this usually means confirming the mounted addons folder is visible inside the container and already listed in `addons_path`.
3. Restart Odoo, then install / activate the bridge from the Odoo Apps screen.
4. Open the connection setup in Odoo, enable the bridge, choose the connector owner, generate a token, and save.

---

### 1. Copy the bridge module

Install the Odoo 19.0 module folder, `19.0/styd_odoo_bridge`.

#### Recommended: clone the bridge repository on the Odoo server

```bash
cd /tmp
rm -rf odoo-bridge
git clone https://github.com/silkflo/odoo-bridge.git

sudo mkdir -p /opt/odoo/custom-addons
sudo rm -rf /opt/odoo/custom-addons/styd_odoo_bridge
sudo cp -r /tmp/odoo-bridge/19.0/styd_odoo_bridge /opt/odoo/custom-addons/styd_odoo_bridge

sudo chown -R odoo:odoo /opt/odoo/custom-addons/styd_odoo_bridge
sudo chmod -R 755 /opt/odoo/custom-addons/styd_odoo_bridge
```

The final path should be:

```text
/opt/odoo/custom-addons/styd_odoo_bridge
```

Inside that folder, you should see:

```text
__manifest__.py
controllers/
models/
security/
views/
static/
```

---

### 2. Add the module parent folder to `addons_path`

Odoo must be configured to scan the **parent folder** that contains the `styd_odoo_bridge` module folder.

#### Standard self-hosted installation

Edit your Odoo config file.

Common location:

```bash
sudo nano /etc/odoo/odoo.conf
```

Add the custom addons **parent folder** to `addons_path`.

Example:

```ini
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/opt/odoo/custom-addons
```

Important:

```text
Correct:
addons_path = ...,/opt/odoo/custom-addons

Wrong:
addons_path = ...,/opt/odoo/custom-addons/styd_odoo_bridge
```

Odoo scans a directory that contains modules. It should find the `styd_odoo_bridge` folder inside `/opt/odoo/custom-addons`.

Restart Odoo:

```bash
sudo systemctl restart odoo
```

If your service name is different, use the service name used by your Odoo installation.

#### Docker installation note

If Odoo runs in Docker, the same rule applies, but the path in `addons_path` must be the path **inside the Odoo container**, not only the host path.

First inspect the running container:

```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}"

docker inspect YOUR_ODOO_CONTAINER --format '{{json .Mounts}}' | python3 -m json.tool

docker exec -it YOUR_ODOO_CONTAINER bash -lc 'cat /etc/odoo/odoo.conf'
```

Example Docker setup:

```text
Host path:
 /opt/odoo-secure/addons

Container path:
 /mnt/extra-addons

Module path on host:
 /opt/odoo-secure/addons/styd_odoo_bridge

Module path inside container:
 /mnt/extra-addons/styd_odoo_bridge

addons_path inside container:
 /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons
```

In this example, `addons_path` is correct because it includes the parent folder `/mnt/extra-addons`, and Odoo can find the module inside it.

Important:

```text
Correct inside Docker:
addons_path = /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons

Wrong:
addons_path = /mnt/extra-addons/styd_odoo_bridge,/usr/lib/python3/dist-packages/odoo/addons
```

Do not copy the module only into a temporary container filesystem if the container may be recreated later. Prefer a host folder mounted into the Odoo container, or a persistent Docker volume used as a custom addons folder.

Restart the Odoo container:

```bash
docker restart YOUR_ODOO_CONTAINER
```

If you use Docker Compose:

```bash
docker compose restart odoo
```

---

### 3. Find and activate the bridge in Odoo

Log into Odoo as an administrator.

#### 3.1 Open Apps

Go to:

```text
Apps
```

#### 3.2 Enable developer mode if needed

If you cannot find the module, enable developer mode.

You can usually do this by opening:

```text
https://your-odoo-domain.com/web?debug=1
```

Then go back to:

```text
Apps
```

#### 3.3 Update the Apps List

In the Apps screen, click:

```text
Update Apps List
```

Confirm the update.

This step is required after copying a new module into the addons folder.

#### 3.4 Search for the bridge

Search for:

```text
Speak To Your Database
```

or:

```text
styd_odoo_bridge
```

If you do not see the module:

- make sure you are in `Apps`
- make sure the Apps List was updated
- remove filters such as `Official Apps`
- search again for `Speak To Your Database`
- verify that the module folder is in the addons path
- restart Odoo and update the Apps List again

#### 3.5 Activate the module

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

After activation, the module page should show the bridge as installed.

---

### 4. Configure the bridge in Odoo

Installing the module is not enough. The bridge must also be configured and enabled in Odoo.

1. In Odoo, open `Speak To Your Database → Connection Setup`.
2. **Enable the bridge.**
3. **Choose the connector owner** — the Odoo user whose trusted security scope will be used as the connector-owner snapshot. Usually this should be an Odoo administrator or the user responsible for connecting Speak To Your Database.
4. Click `Generate Token` (or `Rotate Token` if you are replacing an existing token).
5. **Copy the token shown once.** It is displayed a single time — store it securely.
6. **Save configuration.**

If the bridge is not enabled and saved, Speak To Your Database will receive:

```json
{
  "ok": false,
  "error": "bridge_disabled",
  "detail": "STYD bridge is disabled in Odoo settings."
}
```

---

### 5. Test the bridge health endpoint

After saving the configuration, test the health endpoint.

Replace:

- `https://your-odoo-domain.com` with your Odoo URL
- `your-bridge-token` with the token generated in the connection setup
- `your_database_name` with your Odoo database name

```bash
curl --location 'https://your-odoo-domain.com/styd_bridge/v1/health' \
  --header 'Authorization: Bearer your-bridge-token' \
  --header 'X-Odoo-Database: your_database_name'
```

Expected response:

```json
{
  "ok": true,
  "bridge_version": "0.2.0",
  "odoo_version": "19.0-20260421",
  "odoo_series": "19.0",
  "edition": "community",
  "database_uuid": "...",
  "server_time_utc": "...",
  "supported_features": [
    "security_snapshot_v1",
    "odoo_user_directory_v1",
    "odoo_capability_snapshot_v1"
  ]
}
```

If you receive `bridge_disabled`, go back to the Odoo connection setup, enable the bridge, generate a token, and save.

---

### 6. Connect in Speak To Your Database

After the health endpoint works:

1. Open `/settings?tab=odoo` in Speak To Your Database.
2. Paste the Odoo base URL.
3. Paste the bridge token.
4. Enter the database name if needed.
5. Click `Test connection`.
6. Click `Save connection`.

After connecting, Speak To Your Database should display:

- bridge status
- connector owner
- available Odoo users
- company labels
- user rights summary
- mapping options for workspace members

---

## Path B — Direct database connection (Odoo 15–18)

For Odoo 15.0, 16.0, 17.0, and 18.0, the bridge module is not validated yet. Use a **secured, read-only direct database connection** instead.

1. Configure the connection under `/settings?tab=connections`.
2. Use a **dedicated read-only database user** — not a broad admin database account.
3. Restrict network access. Use one or more of: IP allow-list, VPN, SSH tunnel, or a read replica.
4. Do **not** use broad admin DB credentials.

Important limitations:

- A direct database connection does **not** reproduce exact Odoo per-user record rules.
- Access is controlled by **database permissions** and **Speak To Your Database workspace restrictions**, not by Odoo's native row-level security.

A direct database fallback is acceptable only when it is secured and read-only.

---

## Endpoints

The bridge exposes the following read-only endpoints:

- `/styd_bridge/v1/health`
- `/styd_bridge/v1/security/snapshot`
- `/styd_bridge/v1/users/directory`
- `/styd_bridge/v1/users/search`
- `/styd_bridge/v1/capabilities`
- `/styd_bridge/v1/models`
- `/styd_bridge/v1/models/<model>/fields`
- `/styd_bridge/v1/search-read`
- `/styd_bridge/v1/read-group`

### Example: user directory endpoint

```bash
curl --location 'https://your-odoo-domain.com/styd_bridge/v1/users/directory' \
  --header 'Authorization: Bearer your-bridge-token' \
  --header 'X-Odoo-Database: your_database_name'
```

Expected response includes:

```json
{
  "bridge_version": "0.2.0",
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

### Example: security snapshot endpoint

```bash
curl --location 'https://your-odoo-domain.com/styd_bridge/v1/security/snapshot' \
  --header 'Authorization: Bearer your-bridge-token' \
  --header 'X-Odoo-Database: your_database_name'
```

Expected response includes:

```json
{
  "bridge_version": "0.2.0",
  "snapshot_version": 1,
  "instance": {
    "odoo_version": "...",
    "odoo_series": "...",
    "edition": "community"
  },
  "company_scope": {
    "allowed_company_ids": [1],
    "default_company_id": 1,
    "companies": [
      {
        "id": 1,
        "name": "My Company"
      }
    ]
  },
  "model_access": {},
  "security_flags": {}
}
```

---

## Troubleshooting

### The module is not visible in Apps

Check:

1. Did you copy the `19.0/styd_odoo_bridge` folder onto an Odoo 19.0 server?
2. Is the folder named exactly `styd_odoo_bridge`?
3. Is the parent folder in `addons_path`?
4. Did you restart Odoo?
5. Did you click **Update Apps List**?
6. Did you remove filters such as `Official Apps`?
7. Did you search for `Speak To Your Database`?

Verify the files:

```bash
ls -la /opt/odoo/custom-addons/styd_odoo_bridge
```

### The bridge endpoint returns `bridge_disabled`

The module is installed, but the bridge was not enabled in the Odoo connection setup.

Fix:

1. In Odoo, open `Speak To Your Database → Connection Setup`
2. Enable the bridge
3. Choose the connector owner
4. Click `Generate Token`
5. Copy the token shown once
6. Save configuration

### The bridge endpoint returns unauthorized

Check that the token in the request matches the token saved in the Odoo connection setup.

```bash
curl --location 'https://your-odoo-domain.com/styd_bridge/v1/health' \
  --header 'Authorization: Bearer your-bridge-token' \
  --header 'X-Odoo-Database: your_database_name'
```

### The wrong database is used

Send the database name with:

```text
X-Odoo-Database: your_database_name
```

This is especially important on Odoo servers hosting multiple databases.

### Odoo Online

Odoo Online does not allow installation of custom server modules, so the bridge cannot be installed there. A direct database connection is usually unavailable on Odoo Online as well. If you are unsure about your hosting, contact us.

---

## Beta and security notes

- The current beta is **company-scoped through the connector owner**. Per-user record-rule parity is **not guaranteed yet**.
- The bridge is **read-only**: it uses the Odoo ORM, sends no SQL to Odoo, and never writes, creates, updates, or deletes records.
- A direct database fallback (Odoo 15–18) is acceptable only when it is **secured and read-only**, with a dedicated read-only DB user and restricted network access. It does not reproduce exact Odoo per-user permissions.
- Use a strong bridge token, store it securely, and use HTTPS in production.
- The bridge should be installed only by an Odoo administrator or trusted developer.
- The bridge exposes metadata used for security and planning, not uncontrolled raw business data.
- Speak To Your Database may further restrict access through workspace restrictions.
- Effective access is:

```text
trusted Odoo scope ∩ Speak To Your Database workspace restrictions
```
