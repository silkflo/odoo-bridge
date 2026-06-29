# Speak To Your Database Odoo Bridge

The Odoo Bridge module (`styd_odoo_bridge`) for **Speak To Your Database**.

The bridge gives Speak To Your Database a controlled, read-only path into Odoo through the Odoo ORM. It helps Speak To Your Database read safe Odoo metadata and supported business records so answers can be planned, validated, and explained more reliably.

The bridge is **read-only**. It uses the Odoo ORM, sends **no SQL to Odoo**, and does **not** write, create, update, or delete records.

---

## Supported Odoo versions

| Odoo version | Bridge module folder    | Status                                   | Recommended path                        |
| ------------ | ----------------------- | ---------------------------------------- | --------------------------------------- |
| Odoo 19.0    | `19.0/styd_odoo_bridge` | Marketplace baseline / validated release | Use the bridge                          |
| Odoo 18.0    | `18.0/styd_odoo_bridge` | Beta tester folder available             | Bridge beta or direct database fallback |
| Odoo 17.0    | `17.0/styd_odoo_bridge` | Beta tester folder available             | Bridge beta or direct database fallback |
| Odoo 16.0    | `16.0/styd_odoo_bridge` | Beta tester folder available             | Bridge beta or direct database fallback |
| Odoo 15.0    | `15.0/styd_odoo_bridge` | Beta tester folder available             | Bridge beta or direct database fallback |

> ⚠️ **Odoo 19.0 is the validated marketplace baseline.**
> The Odoo 15.0, 16.0, 17.0, and 18.0 folders are available for beta testers and early adopters, but they are **not marketplace-validated yet** after the latest bridge and answer-engine upgrades. If you are not participating in beta validation for those versions, use a secured direct database connection instead.

> ⚠️ **Install only the folder matching your Odoo major version.**
> Do not install the Odoo 19.0 bridge folder on Odoo 15.0, 16.0, 17.0, or 18.0.

---

## Choose your setup path

### Path A — Odoo 19.0 marketplace bridge

For Odoo 19.0 users, the recommended path is the official Odoo Bridge module.

1. Install the Speak To Your Database Odoo Bridge from the Odoo Apps marketplace.
2. Configure the bridge in Odoo.
3. Connect it in Speak To Your Database under [Settings → Odoo](https://speaktoyourdatabase.com/settings?tab=odoo).

Manual GitHub installation is also available for self-hosted deployments, Odoo.sh deployments, development, review, and advanced users.

---

### Path B — Odoo 15.0–18.0 bridge beta

For Odoo 15.0, 16.0, 17.0, and 18.0, matching bridge folders are available in this repository for beta testers.

Use the matching folder only:

```text
15.0/styd_odoo_bridge
16.0/styd_odoo_bridge
17.0/styd_odoo_bridge
18.0/styd_odoo_bridge
```

These versions have bridge folders available for early validation, but full prompt/answer behavior should be revalidated after the latest bridge and answer-engine upgrades.

Use this path if:

* you are comfortable testing the bridge before marketplace validation for your Odoo version;
* you can verify install, health, connection, and supported questions in your own environment;
* you understand that behavior may still change before official release for that Odoo series.

---

### Path C — Direct database fallback

For Odoo 15.0–18.0 users who do not want to test the bridge beta yet, use a secured direct PostgreSQL/database connection instead.

Configure it in Speak To Your Database under [Settings → Connections](https://speaktoyourdatabase.com/settings?tab=connections).

This fallback must use:

* a dedicated read-only database user;
* restricted network access;
* IP allow-listing, VPN, SSH tunnel, or read replica where appropriate;
* no broad admin database credentials.

---

### Path D — Odoo Online

The bridge is **not supported** on Odoo Online because custom Python server modules cannot be installed there.

A direct database connection is usually not available on Odoo Online either.

If you are unsure what is possible for your Odoo hosting plan, contact us.

---

## What the bridge provides

The bridge exposes safe read-only metadata and supported Odoo access paths to Speak To Your Database, including:

* Odoo version and edition
* installed modules
* bridge health
* user directory
* user search
* allowed companies
* default company
* company labels
* user access summary
* readable model permissions
* model and field metadata
* capability snapshot
* supported read-only search and aggregation endpoints

The bridge does **not** expose uncontrolled raw business data, and it never modifies anything in Odoo. It is designed as a trusted, read-only metadata and connector layer.

---

## What the bridge does not do

The bridge does not:

* create a new business interface inside Odoo;
* write, create, update, delete, or mutate Odoo records;
* send SQL to Odoo;
* expose database credentials to Speak To Your Database;
* give invited workspace users automatic access to everything the connector owner can access;
* guarantee exact per-user Odoo record-rule parity in the current beta.

In the current beta, bridge access is company-scoped through the configured connector owner. Speak To Your Database may reduce access further through workspace restrictions.

---

## Installation overview

For a manual bridge installation, the installation has four main steps:

1. Copy the correct `styd_odoo_bridge` folder to a custom addons directory.
2. Confirm the custom addons parent directory is included in Odoo's `addons_path`.
3. Restart Odoo, then install or activate the bridge from the Odoo Apps screen.
4. Open the connection setup in Odoo, enable the bridge, choose the connector owner, generate a token, and save.

For Odoo 19.0 marketplace users, the marketplace installation replaces the manual copy step. The Odoo Apps marketplace provides the module **package**; an Odoo administrator still installs it like any other third-party module (there is no one-click marketplace install).

### Detailed guides

Step-by-step guides are available in the [`docs/`](docs) folder:

* Self-hosted Odoo — [`docs/INSTALL_SELF_HOSTED.md`](docs/INSTALL_SELF_HOSTED.md)
* Odoo.sh — [`docs/INSTALL_ODOO_SH.md`](docs/INSTALL_ODOO_SH.md)
* Post-install checklist — [`docs/POST_INSTALL_CHECKLIST.md`](docs/POST_INSTALL_CHECKLIST.md)

---

## 1. Copy the bridge module

Use the folder matching your Odoo major version.

Examples:

```text
Odoo 19.0 → 19.0/styd_odoo_bridge
Odoo 18.0 → 18.0/styd_odoo_bridge
Odoo 17.0 → 17.0/styd_odoo_bridge
Odoo 16.0 → 16.0/styd_odoo_bridge
Odoo 15.0 → 15.0/styd_odoo_bridge
```

### Recommended manual install from GitHub

Replace `19.0` with your Odoo major version only if you are intentionally testing that beta bridge version.

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

For an Odoo 17 beta test, for example, use:

```bash
sudo cp -r /tmp/odoo-bridge/17.0/styd_odoo_bridge /opt/odoo/custom-addons/styd_odoo_bridge
```

The final path should be:

```text
/opt/odoo/custom-addons/styd_odoo_bridge
```

Inside that folder, you should see:

```text
__manifest__.py
__init__.py
controllers/
models/
security/
views/
static/
```

---

## 2. Add the module parent folder to `addons_path`

Odoo must be configured to scan the **parent folder** that contains the `styd_odoo_bridge` module folder.

### Standard self-hosted installation

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

Correct:

```text
addons_path = ...,/opt/odoo/custom-addons
```

Wrong:

```text
addons_path = ...,/opt/odoo/custom-addons/styd_odoo_bridge
```

Odoo scans a directory that contains modules. It should find the `styd_odoo_bridge` folder inside `/opt/odoo/custom-addons`.

Restart Odoo:

```bash
sudo systemctl restart odoo
```

If your service name is different, use the service name used by your Odoo installation.

---

### Docker installation note

If Odoo runs in Docker, the same rule applies, but the path in `addons_path` must be the path **inside the Odoo container**, not only the host path.

Inspect the running container:

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

Correct inside Docker:

```text
addons_path = /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons
```

Wrong:

```text
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

## 3. Find and activate the bridge in Odoo

Log into Odoo as an administrator.

### 3.1 Open Apps

Go to:

```text
Apps
```

### 3.2 Enable developer mode if needed

If you cannot find the module, enable developer mode.

You can usually do this by opening:

```text
https://your-odoo-domain.com/web?debug=1
```

Then go back to:

```text
Apps
```

### 3.3 Update the Apps List

In the Apps screen, click:

```text
Update Apps List
```

Confirm the update.

This step is required after copying a new module into the addons folder.

### 3.4 Search for the bridge

Search for:

```text
Speak To Your Database
```

or:

```text
styd_odoo_bridge
```

If you do not see the module:

* make sure you are in `Apps`;
* make sure the Apps List was updated;
* remove filters such as `Official Apps`;
* search again for `Speak To Your Database`;
* verify that the module folder is in the addons path;
* restart Odoo and update the Apps List again.

### 3.5 Activate the module

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

## 4. Configure the bridge in Odoo

Installing the module is not enough. The bridge must also be configured and enabled in Odoo.

1. In Odoo, open:

```text
Speak To Your Database → Connection Setup
```

2. Enable the bridge.
3. Choose the connector owner — the Odoo user whose trusted security scope will be used as the connector-owner snapshot.
4. Click `Generate Token`, or `Rotate Token` if you are replacing an existing token.
5. Copy the token shown once. It is displayed a single time — store it securely.
6. Save configuration.

If the bridge is not enabled and saved, Speak To Your Database may receive:

```json
{
  "ok": false,
  "error": "bridge_disabled",
  "detail": "Speak To Your Database bridge is disabled in Odoo settings."
}
```

The exact wording may vary by bridge version.

---

## 5. Test the bridge health endpoint

After saving the configuration, test the health endpoint.

Replace:

* `https://your-odoo-domain.com` with your Odoo URL
* `your-bridge-token` with the token generated in the connection setup
* `your_database_name` with your Odoo database name, if your Odoo server hosts multiple databases

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

Exact values depend on your Odoo version and bridge release.

If you receive `bridge_disabled`, go back to the Odoo connection setup, enable the bridge, generate a token, and save.

---

## 6. Connect in Speak To Your Database

After the health endpoint works:

1. Open [Settings → Odoo](https://speaktoyourdatabase.com/settings?tab=odoo) in Speak To Your Database.
2. Paste the Odoo base URL.
3. Paste the bridge token.
4. Enter the database name if needed.
5. Click `Test connection`.
6. Click `Save connection`.

After connecting, Speak To Your Database should display:

* bridge status
* connector owner
* available Odoo users
* company labels
* user rights summary
* mapping options for workspace members
* Odoo version, edition, and bridge version when available

---

## Direct database fallback for Odoo 15.0–18.0

For Odoo 15.0, 16.0, 17.0, and 18.0 users who do not want to test the bridge beta yet, use a secured, read-only direct database connection instead.

Configure the connection under [Settings → Connections](https://speaktoyourdatabase.com/settings?tab=connections).

Use:

* a dedicated read-only database user;
* restricted network access;
* IP allow-listing, VPN, SSH tunnel, or read replica where appropriate.

Do **not** use:

* the Odoo application superuser;
* broad admin database credentials;
* a database account that can write, update, delete, or manage schema.

Important limitations:

* A direct database connection does **not** reproduce exact Odoo per-user record rules.
* Access is controlled by database permissions and Speak To Your Database workspace restrictions, not by Odoo's native record rules.
* Direct database fallback is acceptable only when it is secured, read-only, and intentionally scoped.

---

## Endpoints

The bridge exposes the following read-only endpoints:

```text
/styd_bridge/v1/health
/styd_bridge/v1/security/snapshot
/styd_bridge/v1/users/directory
/styd_bridge/v1/users/search
/styd_bridge/v1/capabilities
/styd_bridge/v1/models
/styd_bridge/v1/models/<model>/fields
/styd_bridge/v1/search-read
/styd_bridge/v1/read-group
```

The `/models`, `/models/<model>/fields`, `/search-read`, and `/read-group` endpoints are provided by the **Odoo 19.0** bridge. The Odoo 15.0–18.0 bridges expose the health, security snapshot, user directory, user search, and capabilities endpoints.

Every endpoint requires a valid bridge token sent as:

```text
Authorization: Bearer your-bridge-token
```

For multi-database Odoo servers, include:

```text
X-Odoo-Database: your_database_name
```

Use HTTPS in production.

---

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

---

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

1. Did you copy the correct version folder for your Odoo major version?
2. Is the folder named exactly `styd_odoo_bridge` after copying?
3. Is the parent folder in `addons_path`?
4. Did you restart Odoo?
5. Did you click **Update Apps List**?
6. Did you remove filters such as `Official Apps`?
7. Did you search for `Speak To Your Database`?

Verify the files:

```bash
ls -la /opt/odoo/custom-addons/styd_odoo_bridge
```

You should see:

```text
__manifest__.py
__init__.py
controllers/
models/
security/
views/
static/
```

---

### The bridge endpoint returns `bridge_disabled`

The module is installed, but the bridge was not enabled in the Odoo connection setup.

Fix:

1. In Odoo, open `Speak To Your Database → Connection Setup`.
2. Enable the bridge.
3. Choose the connector owner.
4. Click `Generate Token`.
5. Copy the token shown once.
6. Save configuration.

---

### The bridge endpoint returns unauthorized

Check that the token in the request matches the token saved in the Odoo connection setup.

```bash
curl --location 'https://your-odoo-domain.com/styd_bridge/v1/health' \
  --header 'Authorization: Bearer your-bridge-token' \
  --header 'X-Odoo-Database: your_database_name'
```

If unsure, rotate the token in Odoo and update it in Speak To Your Database.

---

### The wrong database is used

Send the database name with:

```text
X-Odoo-Database: your_database_name
```

This is especially important on Odoo servers hosting multiple databases.

---

### Odoo 15.0–18.0 bridge beta behavior is inconsistent

The older-version bridge folders are available for beta validation, but full prompt/answer behavior should be revalidated after the latest upgrades.

If you encounter inconsistent behavior:

1. Confirm the bridge health endpoint works.
2. Confirm the user directory endpoint works.
3. Confirm the security snapshot endpoint works.
4. Confirm the connection is saved in Speak To Your Database.
5. Test a small set of supported business questions.
6. Report the issue with your Odoo version, edition, bridge version, and the question asked.

If you are not participating in beta validation, use the direct database fallback instead.

---

### Odoo Online

Odoo Online does not allow installation of custom server modules, so the bridge cannot be installed there.

A direct database connection is usually unavailable on Odoo Online as well.

If you are unsure about your hosting, contact us.

---

## Beta and security notes

* Odoo 19.0 is the validated marketplace baseline.
* Odoo 15.0–18.0 bridge folders are available for beta testers and early adopters, but are not marketplace-validated yet.
* The current beta is company-scoped through the connector owner. Per-user record-rule parity is not guaranteed yet.
* The bridge is read-only: it uses the Odoo ORM, sends no SQL to Odoo, and never writes, creates, updates, or deletes records.
* The Odoo 19.0 bridge records a read-only access log (audit trail) of bridge requests in Odoo, storing only a non-reversible token fingerprint — never the raw token or business data.
* Direct database fallback is acceptable only when it is secured and read-only, with a dedicated read-only database user and restricted network access.
* Direct database fallback does not reproduce exact Odoo per-user permissions.
* Use a strong bridge token, store it securely, and use HTTPS in production.
* The bridge should be installed only by an Odoo administrator or trusted developer.
* The bridge exposes metadata and supported read-only Odoo access used for security and planning, not uncontrolled database access.
* Speak To Your Database may further restrict access through workspace restrictions.

Effective access in bridge mode is:

```text
trusted Odoo company scope ∩ Speak To Your Database workspace restrictions
```

Effective access in direct database fallback mode is:

```text
database user permissions ∩ Speak To Your Database workspace restrictions
```

---

## License

This module is licensed under LGPL-3.
