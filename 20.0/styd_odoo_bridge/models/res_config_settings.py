from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    styd_bridge_enabled = fields.Boolean(
        string="Enable Speak To Your Database Bridge",
        help="Enable the Speak To Your Database security bridge endpoints for this Odoo database.",
    )

    styd_bridge_connector_owner_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Speak To Your Database Connector Owner",
        help="Odoo user whose trusted security scope will be used as the initial connector-owner snapshot.",
    )

    # The raw token is NEVER exposed in Settings. It is generated, rotated, and
    # revoked from Speak To Your Database Bridge > Connection Setup and stored only as a hash.
    # Here we surface a read-only "configured" indicator only.
    styd_bridge_token_configured = fields.Boolean(
        string="Speak To Your Database Bridge Token Configured",
        compute="_compute_styd_bridge_token_configured",
        help="Whether a bridge token is configured. The token is generated and "
             "rotated from Speak To Your Database Bridge > Connection Setup and is never shown here.",
    )

    def _compute_styd_bridge_token_configured(self):
        service = self.env["styd.odoo.bridge.service"]
        for record in self:
            try:
                record.styd_bridge_token_configured = service._token_is_configured()
            except Exception:
                record.styd_bridge_token_configured = False

    def get_values(self):
        res = super().get_values()
        service = self.env["styd.odoo.bridge.service"]

        raw_connector_owner_user_id = service._icp_get(
            "styd_odoo_bridge.connector_owner_user_id",
            "",
        )

        connector_owner_user_id = False
        if raw_connector_owner_user_id:
            try:
                connector_owner_user_id = int(raw_connector_owner_user_id)
            except Exception:
                connector_owner_user_id = False

        res.update(
            styd_bridge_enabled=str(
                service._icp_get("styd_odoo_bridge.enabled", "False")
            ).lower() in ("1", "true", "yes", "on"),
            styd_bridge_connector_owner_user_id=connector_owner_user_id,
        )
        return res

    def set_values(self):
        super().set_values()
        service = self.env["styd.odoo.bridge.service"]

        # NOTE: the bridge token is intentionally NOT written here anymore; it is
        # managed only via the Connection Setup wizard (hash-at-rest).
        for record in self:
            service._icp_set(
                "styd_odoo_bridge.enabled",
                "True" if record.styd_bridge_enabled else "False",
            )
            service._icp_set(
                "styd_odoo_bridge.connector_owner_user_id",
                str(record.styd_bridge_connector_owner_user_id.id or ""),
            )
