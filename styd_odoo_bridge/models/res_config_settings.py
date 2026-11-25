from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError

from .bridge_orm import model_check_access


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

    # Discuss assistant (off by default).
    styd_discuss_enabled = fields.Boolean(
        string="Discuss assistant",
        config_parameter="styd_odoo_bridge.discuss_enabled",
        help="Users can ask Speak To Your Database questions in Discuss: in a direct "
             "message to the bot, or by mentioning it in a channel. Answers use the asking "
             "user's own Odoo access rights.",
    )
    styd_discuss_audience = fields.Selection(
        selection=[
            ("all", "All internal users"),
            ("group", "Members of a group"),
            ("users", "Chosen users"),
        ],
        string="Who may ask",
        default="all",
        config_parameter="styd_odoo_bridge.discuss_audience",
    )
    styd_discuss_group_id = fields.Many2one(
        comodel_name="res.groups",
        string="Group that may ask",
        config_parameter="styd_odoo_bridge.discuss_group_id",
    )
    styd_discuss_user_ids = fields.Many2many(
        comodel_name="res.users",
        relation="styd_discuss_settings_user_rel",
        column1="settings_id",
        column2="user_id",
        string="Users who may ask",
        domain=[("share", "=", False)],
    )
    styd_discuss_answer_in_channel = fields.Boolean(
        string="Answer mentions in the channel",
        config_parameter="styd_odoo_bridge.discuss_answer_in_channel",
        help="Off (default): a mention in a channel or group is answered in a direct message to the "
             "asker, and one line in the channel says so. On: the answer is posted in the channel, "
             "where everyone in it can read it (HR questions are then refused).",
    )
    styd_discuss_pairing = fields.Selection(
        selection="_styd_discuss_pairing_selection",
        string="Workspace answering in Discuss",
        config_parameter="styd_odoo_bridge.discuss_pairing_id",
        help="Needed only when this Odoo is paired with several Speak To Your Database workspaces.",
    )
    styd_discuss_rate_user_hour = fields.Integer(
        string="Questions per user per hour",
        default=30,
        config_parameter="styd_odoo_bridge.discuss_rate_user_hour",
    )
    styd_discuss_rate_db_hour = fields.Integer(
        string="Questions per hour for this database",
        default=300,
        config_parameter="styd_odoo_bridge.discuss_rate_db_hour",
    )

    def _styd_discuss_pairing_selection(self):
        Pairing = self.env["styd.odoo.bridge.pairing"].sudo()
        return [(p.pairing_id, p.workspace_label or p.pairing_id)
                for p in Pairing.search([("state", "=", "active"), ("pairing_id", "!=", False)])]

    def _compute_styd_bridge_token_configured(self):
        service = self.env["styd.odoo.bridge.service"]
        for record in self:
            try:
                record.styd_bridge_token_configured = service._token_is_configured()
            except Exception:
                record.styd_bridge_token_configured = False

    def _styd_bridge_check_admin(self):
        """Buttons and form values are for Odoo administrators only: they run
        through sudo helpers, so an RPC call by anyone else is refused."""
        if not (self.env.su or self.env.user._is_system()):
            raise AccessError("Only an Odoo administrator can manage the Speak To Your Database Bridge.")

    def get_values(self):
        # Public on res.config.settings (the core's default_get calls it after its
        # own access check): check here too, as this override reads with sudo.
        model_check_access(self.browse(), "read")
        self._styd_bridge_check_admin()
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
        from .bridge_discuss import ICP_DISCUSS_USERS, _ids
        users = self.env["res.users"].sudo().browse(_ids(service._icp_get(ICP_DISCUSS_USERS, ""))).exists()
        res["styd_discuss_user_ids"] = [(6, 0, users.ids)]
        return res

    def set_values(self):
        from .bridge_channel import resolve_verify
        model_check_access(self.browse(), "write")
        self._styd_bridge_check_admin()
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
            from .bridge_discuss import ICP_DISCUSS_USERS
            service._icp_set(ICP_DISCUSS_USERS, ",".join(str(i) for i in record.styd_discuss_user_ids.ids))
            if record.styd_discuss_enabled:
                # The server opens each allowed user's chat with the bot.
                self.env["styd.discuss.question"].sudo()._open_chats()
