from odoo import _, fields, models
from odoo.exceptions import UserError


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

    # Outbound channel (connect without opening a port).
    styd_bridge_channel_restrict_group = fields.Boolean(
        string="Only members of the STYD group",
        config_parameter="styd_odoo_bridge.channel_restrict_to_group",
        help="Off (default): Speak To Your Database may answer as any active internal Odoo "
             "user, administrators included. On: only as users in the group "
             "'Speak To Your Database: member'.",
    )
    styd_bridge_channel_ca_bundle = fields.Char(
        string="Custom CA bundle (outbound channel)",
        config_parameter="styd_odoo_bridge.channel_ca_bundle",
        help="Path of a PEM file of trusted certificate authorities, for a proxy that "
             "inspects TLS. Empty: the system's authorities. The certificate is always checked.",
    )

    def _compute_styd_bridge_token_configured(self):
        service = self.env["styd.odoo.bridge.service"]
        for record in self:
            try:
                record.styd_bridge_token_configured = service._token_is_configured()
            except Exception:
                record.styd_bridge_token_configured = False

    def get_values(self):
        # Public on res.config.settings (the core's default_get calls it after its
        # own access check): check here too, as this override reads with sudo.
        self.check_access_rights("read")
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
        from .bridge_channel import resolve_verify
        self.check_access_rights("write")
        for record in self:
            try:
                resolve_verify(record.styd_bridge_channel_ca_bundle)
            except ValueError as exc:
                raise UserError(_("Custom CA bundle: %s", exc))
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
