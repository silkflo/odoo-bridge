"""Hash a legacy plaintext bridge token in place on module upgrade.

Existing installs may still hold the bridge token in clear text
(styd_odoo_bridge.token). This moves it to hash-at-rest storage
(styd_odoo_bridge.token_hash) without changing the token itself, so the
Speak To Your Database connection keeps working with no action from the
customer. Safe to run more than once. The token is never logged.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    if env["styd.odoo.bridge.service"]._migrate_legacy_token_to_hash():
        _logger.info(
            "STYD bridge: the legacy plaintext bridge token was moved to "
            "hash-at-rest storage; existing connections are unaffected."
        )
