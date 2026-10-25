# Speak To Your Database Odoo Bridge — Post-Install Checklist

## Module installation

- [ ] `styd_odoo_bridge` is present in Apps
- [ ] the module is installed successfully
- [ ] there is no installation traceback in the Odoo logs

## Settings UI

- [ ] the Settings page loads without Owl/UI errors
- [ ] the Speak To Your Database logo/icon displays correctly
- [ ] the Speak To Your Database Bridge section is visible
- [ ] the **Enable Speak To Your Database Bridge** option is visible
- [ ] the read-only **Token Configured** indicator is visible (no token field)
- [ ] the **Speak To Your Database Connector Owner** field is visible

## Connection Setup

- [ ] **Speak To Your Database → Connection Setup** opens
- [ ] **Generate Token** shows the token once; it is not shown again after leaving the page
- [ ] **Rotate Token** issues a new token; the old one is rejected (`unauthorized`)
- [ ] **Revoke Token** clears the token and disables the bridge

## Configuration

- [ ] the bridge is enabled
- [ ] a token has been generated (**Token Configured** is on)
- [ ] the connector owner is selected
- [ ] the settings save successfully

## Bridge endpoint tests

- [ ] `/styd_bridge/v1/health` returns `ok: true` and `bridge_version` `0.3.0`
- [ ] `/styd_bridge/v1/security/snapshot` returns JSON
- [ ] the database header works correctly in multi-database setups

## Snapshot contents

- [ ] connector owner appears correctly
- [ ] allowed companies are present
- [ ] default company is present
- [ ] groups list is present
- [ ] model access snapshot is present
- [ ] security flags are present

## Speak To Your Database integration

- [ ] the Odoo base URL is entered in the workspace Odoo settings
- [ ] the bridge token is the one generated in Connection Setup
- [ ] the Odoo database name is entered if required
- [ ] bridge sync succeeds
- [ ] the connector owner is visible in the workspace Odoo settings
- [ ] the company scope is visible in the workspace Odoo settings
- [ ] the bridge status is connected or healthy

## After an upgrade from 0.9.x or older

- [ ] the module version is `<series>.0.10.0` (e.g. `16.0.0.10.0`)
- [ ] the existing Speak To Your Database connection still works without re-entering the token
- [ ] **Token Configured** is on and no legacy-token warning is shown in Connection Setup

## Final validation

- [ ] secure mode uses bridge metadata
- [ ] fallback mode is not used when the bridge is healthy
- [ ] there are no broken images remaining