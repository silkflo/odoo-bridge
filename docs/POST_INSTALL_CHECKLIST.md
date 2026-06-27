# STYD Odoo Bridge — Post-Install Checklist

## Module installation

- [ ] `styd_odoo_bridge` is present in Apps
- [ ] the module is installed successfully
- [ ] there is no installation traceback in the Odoo logs

## Settings UI

- [ ] the Settings page loads without Owl/UI errors
- [ ] the STYD logo/icon displays correctly
- [ ] the STYD Bridge section is visible
- [ ] the **Enable STYD Bridge** option is visible
- [ ] the **STYD Bridge Token** field is visible
- [ ] the **STYD Connector Owner** field is visible

## Configuration

- [ ] the bridge is enabled
- [ ] the bridge token is saved
- [ ] the connector owner is selected
- [ ] the Odoo settings save successfully

## Bridge endpoint tests

- [ ] `/styd_bridge/v1/health` returns `ok: true`
- [ ] `/styd_bridge/v1/security/snapshot` returns JSON
- [ ] the database header works correctly in multi-database setups

## Snapshot contents

- [ ] connector owner appears correctly
- [ ] allowed companies are present
- [ ] default company is present
- [ ] groups list is present
- [ ] model access snapshot is present
- [ ] security flags are present

## Speak to your Database integration

- [ ] the Odoo base URL is entered in the workspace Odoo settings
- [ ] the bridge token matches the token saved in Odoo
- [ ] the Odoo database name is entered if required
- [ ] bridge sync succeeds
- [ ] the connector owner is visible in the workspace Odoo settings
- [ ] the company scope is visible in the workspace Odoo settings
- [ ] the bridge status is connected or healthy

## Final validation

- [ ] secure mode uses bridge metadata
- [ ] fallback mode is not used when the bridge is healthy
- [ ] there are no broken images remaining