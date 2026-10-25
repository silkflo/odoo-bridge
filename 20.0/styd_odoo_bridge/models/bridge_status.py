from odoo import api, fields, models


class StydOdooBridgeStatus(models.TransientModel):
    """Read-only "Bridge Status / Trust" dashboard.

    Every field is computed (non-stored) from the live configuration, the
    bridge service, and the access-log aggregates, so each time an admin opens
    the page they see the current state. The model writes nothing and exposes
    no secrets: the bridge token is reported only as a boolean (configured or
    not) -- the raw token value is never read into a field. There is
    deliberately NO search view for this model, so the Odoo 19 search-view
    constraints cannot apply here.
    """

    _name = "styd.odoo.bridge.status"
    _description = "Speak To Your Database Bridge Status / Trust Page"

    # --- 1. Bridge health ---------------------------------------------
    bridge_enabled = fields.Boolean(
        string="Bridge Enabled",
        compute="_compute_status",
    )
    token_configured = fields.Boolean(
        string="Token Configured",
        compute="_compute_status",
    )
    legacy_token_present = fields.Boolean(
        string="Legacy Token Present",
        compute="_compute_status",
    )
    connector_owner_display = fields.Char(
        string="Connector Owner",
        compute="_compute_status",
    )
    bridge_version = fields.Char(string="Bridge Version", compute="_compute_status")
    odoo_version = fields.Char(string="Odoo Version", compute="_compute_status")
    odoo_series = fields.Char(string="Odoo Series", compute="_compute_status")
    odoo_edition = fields.Char(string="Odoo Edition", compute="_compute_status")
    database_uuid = fields.Char(string="Database UUID", compute="_compute_status")
    supported_features = fields.Char(
        string="Supported Features",
        compute="_compute_status",
    )

    # --- 4. Audit summary ---------------------------------------------
    audit_last_access = fields.Datetime(
        string="Latest Access",
        compute="_compute_status",
    )
    audit_total_count = fields.Integer(string="Total Requests", compute="_compute_status")
    audit_granted_count = fields.Integer(string="Granted", compute="_compute_status")
    audit_denied_count = fields.Integer(string="Denied", compute="_compute_status")
    audit_error_count = fields.Integer(string="Errors", compute="_compute_status")

    def _compute_display_name(self):
        # Show a clean, user-facing title in the breadcrumb / header instead of
        # the technical "styd.odoo.bridge.status,NewId_..." that Odoo derives for
        # an unnamed transient record.
        for record in self:
            record.display_name = "Speak To Your Database — Bridge Status & Trust"

    @api.depends_context("uid")
    def _compute_status(self):
        """Populate every field from live data.

        Each section is guarded independently so a failure in one source can
        never blank the rest of the page or raise to the UI.
        """
        service = self.env["styd.odoo.bridge.service"]
        access_log = self.env["styd.odoo.bridge.access.log"].sudo()

        for record in self:
            # 1. Bridge enabled / token-configured (boolean only; never the token)
            try:
                record.bridge_enabled = service._get_bridge_enabled()
            except Exception:
                record.bridge_enabled = False
            try:
                record.token_configured = service._token_is_configured()
            except Exception:
                record.token_configured = False
            try:
                record.legacy_token_present = service._has_legacy_plaintext_token()
            except Exception:
                record.legacy_token_present = False

            # Connector owner display name (or "Not configured")
            try:
                owner_id = service._get_connector_owner_user_id()
                owner = self.env["res.users"].sudo().browse(owner_id) if owner_id else None
                if owner and owner.exists():
                    record.connector_owner_display = owner.display_name
                else:
                    record.connector_owner_display = "Not configured"
            except Exception:
                record.connector_owner_display = "Not configured"

            # Versions / edition / database identity
            try:
                record.bridge_version = service.BRIDGE_VERSION or False
            except Exception:
                record.bridge_version = False
            try:
                record.odoo_version = service._get_odoo_version() or False
            except Exception:
                record.odoo_version = False
            try:
                record.odoo_series = service._get_odoo_series() or False
            except Exception:
                record.odoo_series = False
            try:
                record.odoo_edition = service._get_edition() or False
            except Exception:
                record.odoo_edition = False
            try:
                record.database_uuid = service._get_database_uuid() or False
            except Exception:
                record.database_uuid = False
            try:
                record.supported_features = ", ".join(service.get_supported_features() or []) or False
            except Exception:
                record.supported_features = False

            # 4. Audit summary aggregates (read-only counts + latest access)
            try:
                record.audit_total_count = access_log.search_count([])
                record.audit_granted_count = access_log.search_count([("outcome", "=", "granted")])
                record.audit_denied_count = access_log.search_count([("outcome", "=", "denied")])
                record.audit_error_count = access_log.search_count([("outcome", "=", "error")])
                latest = access_log.search([], order="create_date desc", limit=1)
                record.audit_last_access = latest.create_date if latest else False
            except Exception:
                record.audit_total_count = 0
                record.audit_granted_count = 0
                record.audit_denied_count = 0
                record.audit_error_count = 0
                record.audit_last_access = False

    def action_refresh_status(self):
        """Reload the status page only -- no side effects."""
        return {
            "type": "ir.actions.act_window",
            "name": "Bridge Status",
            "res_model": self._name,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_access_logs(self):
        """Open the existing read-only access-log list view."""
        return self.env["ir.actions.actions"]._for_xml_id(
            "styd_odoo_bridge.action_styd_bridge_access_log"
        )

    def action_open_connection_setup(self):
        """Open the Connection Setup page (token generate / rotate / revoke)."""
        return self.env["ir.actions.actions"]._for_xml_id(
            "styd_odoo_bridge.action_styd_bridge_setup"
        )
