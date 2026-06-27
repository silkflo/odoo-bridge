import secrets

from odoo import api, fields, models


class StydOdooBridgeSetupWizard(models.TransientModel):
    """Admin-friendly Connection Setup + token lifecycle.

    Lets a system admin enable/disable the bridge, pick the connector owner, and
    generate / rotate / revoke the bridge token -- without using SQL.

    Token handling (hash-at-rest):
      - A new token is strong random (secrets.token_urlsafe, 32 bytes entropy).
      - Only its SHA-256 hash is stored (styd_odoo_bridge.token_hash); any legacy
        plaintext token (styd_odoo_bridge.token) is cleared on generate/rotate.
      - The raw token is shown EXACTLY ONCE, right after generation, via a
        non-stored field computed from the action context -- it is never written
        to a database column, a config parameter, the status page, or the logs.
    """

    _name = "styd.odoo.bridge.setup.wizard"
    _description = "Speak To Your Database Bridge Connection Setup"

    # Editable configuration (reflects current values via default_get)
    bridge_enabled = fields.Boolean(string="Bridge Enabled")
    connector_owner_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Connector Owner",
        domain="[('share', '=', False)]",
    )

    # Read-only state
    token_configured = fields.Boolean(
        string="Token Configured",
        compute="_compute_token_state",
    )
    legacy_plaintext_token_present = fields.Boolean(
        string="Legacy Plaintext Token Present",
        compute="_compute_token_state",
    )
    base_url = fields.Char(string="Bridge Base URL", compute="_compute_token_state")

    # One-time generated token: non-stored, derived from the action context so it
    # is NEVER persisted to the database.
    generated_token = fields.Char(
        string="Generated Token",
        compute="_compute_generated_token",
    )
    has_generated_token = fields.Boolean(compute="_compute_generated_token")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        service = self.env["styd.odoo.bridge.service"]
        try:
            res["bridge_enabled"] = service._get_bridge_enabled()
        except Exception:
            res["bridge_enabled"] = False
        try:
            res["connector_owner_user_id"] = service._get_connector_owner_user_id() or False
        except Exception:
            res["connector_owner_user_id"] = False
        return res

    @api.depends_context("uid")
    def _compute_token_state(self):
        service = self.env["styd.odoo.bridge.service"]
        for record in self:
            try:
                record.token_configured = service._token_is_configured()
            except Exception:
                record.token_configured = False
            try:
                record.legacy_plaintext_token_present = service._has_legacy_plaintext_token()
            except Exception:
                record.legacy_plaintext_token_present = False
            try:
                record.base_url = service._get_base_url() or False
            except Exception:
                record.base_url = False

    @api.depends_context("generated_token")
    def _compute_generated_token(self):
        token = self.env.context.get("generated_token") or ""
        for record in self:
            record.generated_token = token or False
            record.has_generated_token = bool(token)

    def _compute_display_name(self):
        for record in self:
            record.display_name = "Speak To Your Database — Connection Setup"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _icp(self):
        return self.env["ir.config_parameter"].sudo()

    def _persist_settings(self):
        """Persist enable/disable + connector owner from the wizard fields."""
        self.ensure_one()
        icp = self._icp()
        icp.set_param(
            "styd_odoo_bridge.enabled",
            "True" if self.bridge_enabled else "False",
        )
        icp.set_param(
            "styd_odoo_bridge.connector_owner_user_id",
            str(self.connector_owner_user_id.id or ""),
        )

    def _reopen(self, generated_token=None):
        """Reopen the wizard. If generated_token is given it is passed via the
        context only (never stored) so the form can show it exactly once."""
        action = {
            "type": "ir.actions.act_window",
            "name": "Connection Setup",
            "res_model": self._name,
            "view_mode": "form",
            "view_id": self.env.ref(
                "styd_odoo_bridge.view_styd_bridge_setup_wizard_form"
            ).id,
            "target": "current",
        }
        if generated_token:
            action["context"] = {"generated_token": generated_token}
        return action

    def _issue_new_token(self):
        """Create a strong random token, store ONLY its hash, clear any legacy
        plaintext token, and return the reopen action carrying the raw token in
        the context for one-time display."""
        service = self.env["styd.odoo.bridge.service"]
        token = secrets.token_urlsafe(32)
        icp = self._icp()
        icp.set_param("styd_odoo_bridge.token_hash", service._hash_token(token))
        # Hash-at-rest: remove any legacy plaintext token now that a hash exists.
        icp.set_param("styd_odoo_bridge.token", "")
        return self._reopen(generated_token=token)

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_save_settings(self):
        self.ensure_one()
        self._persist_settings()
        return self._reopen()

    def action_generate_token(self):
        self.ensure_one()
        self._persist_settings()
        return self._issue_new_token()

    def action_rotate_token(self):
        self.ensure_one()
        self._persist_settings()
        return self._issue_new_token()

    def action_revoke_token(self):
        self.ensure_one()
        icp = self._icp()
        icp.set_param("styd_odoo_bridge.token_hash", "")
        icp.set_param("styd_odoo_bridge.token", "")
        # Revoking the token disables the bridge as a safe default.
        icp.set_param("styd_odoo_bridge.enabled", "False")
        return self._reopen()

    def action_open_bridge_status(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "styd_odoo_bridge.action_styd_bridge_status"
        )

    def action_open_access_logs(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "styd_odoo_bridge.action_styd_bridge_access_log"
        )
