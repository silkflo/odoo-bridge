from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    styd_bridge_enabled = fields.Boolean(
        string="Enable Speak To Your Database Bridge",
        help="Enable the Speak To Your Database security bridge endpoints for this Odoo database.",
    )

    styd_bridge_token = fields.Char(
        string="Speak To Your Database Bridge Token",
        help="Bearer token used by Speak To Your Database to authenticate to the Odoo bridge.",
    )

    styd_bridge_connector_owner_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Speak To Your Database Connector Owner",
        help="Odoo user whose trusted security scope will be used as the initial connector-owner snapshot.",
    )

    def get_values(self):
        res = super().get_values()
        icp = self.env["ir.config_parameter"].sudo()

        raw_connector_owner_user_id = icp.get_param(
            "styd_odoo_bridge.connector_owner_user_id",
            default="",
        )

        connector_owner_user_id = False
        if raw_connector_owner_user_id:
            try:
                connector_owner_user_id = int(raw_connector_owner_user_id)
            except Exception:
                connector_owner_user_id = False

        res.update(
            styd_bridge_enabled=str(
                icp.get_param("styd_odoo_bridge.enabled", default="False")
            ).lower() in ("1", "true", "yes", "on"),
            styd_bridge_token=icp.get_param(
                "styd_odoo_bridge.token",
                default="",
            ),
            styd_bridge_connector_owner_user_id=connector_owner_user_id,
        )
        return res

    def set_values(self):
        super().set_values()
        icp = self.env["ir.config_parameter"].sudo()

        for record in self:
            icp.set_param(
                "styd_odoo_bridge.enabled",
                "True" if record.styd_bridge_enabled else "False",
            )
            icp.set_param(
                "styd_odoo_bridge.token",
                record.styd_bridge_token or "",
            )
            icp.set_param(
                "styd_odoo_bridge.connector_owner_user_id",
                str(record.styd_bridge_connector_owner_user_id.id or ""),
            )