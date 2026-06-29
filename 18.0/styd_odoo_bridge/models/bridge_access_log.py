from odoo import fields, models


class StydOdooBridgeAccessLog(models.Model):
    _name = "styd.odoo.bridge.access.log"
    _description = "Speak To Your Database Bridge Access Log"
    _order = "id desc"
    _rec_name = "endpoint"

    # NOTE: This model is written only by the bridge controller, on a separate
    # cursor, as the superuser. The UI / ACL keep it strictly read-only so admins
    # cannot create, edit, or delete audit rows by hand. Every field is also
    # marked readonly as defence in depth.
    #
    # SAFETY CONTRACT (do not break in later phases):
    #   - Never store the raw bridge token.
    #   - Never store the Authorization header.
    #   - Never store business row data or prompts.
    #   - Keep "detail" short and safe.

    endpoint = fields.Char(
        string="Endpoint",
        readonly=True,
        index=True,
        help="Bridge route that was called, e.g. /styd_bridge/v1/health.",
    )
    method = fields.Char(
        string="HTTP Method",
        readonly=True,
    )
    outcome = fields.Selection(
        selection=[
            ("granted", "Granted"),
            ("denied", "Denied"),
            ("error", "Error"),
        ],
        string="Outcome",
        readonly=True,
        index=True,
        help="granted = served, denied = auth/config rejection, error = internal failure.",
    )
    reason_code = fields.Char(
        string="Reason Code",
        readonly=True,
        index=True,
        help="Short machine code, e.g. ok, bridge_disabled, bridge_token_missing, "
             "unauthorized, snapshot_build_failed.",
    )
    http_status = fields.Integer(
        string="HTTP Status",
        readonly=True,
    )
    source_ip = fields.Char(
        string="Source IP",
        readonly=True,
    )
    token_fingerprint = fields.Char(
        string="Token Fingerprint",
        readonly=True,
        help="Non-reversible fingerprint of the presented token "
             "(short hash + last 4 chars). Never the raw token.",
    )
    detail = fields.Char(
        string="Detail",
        readonly=True,
        help="Short, safe detail. Never contains tokens, headers, or business data.",
    )
