"""No method of this module may be called over RPC by a user who may not use it.

The calls go through what Odoo's /web/dataset/call_kw and XML-RPC run:
``get_public_method`` (refuses private names) then ``api.call_kw``, as an
ordinary internal user.
"""

import inspect

from odoo import Command
from odoo.api import call_kw
from odoo.exceptions import AccessError
from odoo.service.model import get_public_method
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

MODULE_PREFIX = "odoo.addons.styd_odoo_bridge."

# Every public method this module defines on an Odoo model, and why it is safe.
REVIEWED_PUBLIC = {
    "styd.odoo.bridge.setup.wizard": {
        "default_get", "action_save_settings", "action_generate_token", "action_rotate_token",
        "action_revoke_token", "action_open_access_logs",
    },
    "styd.odoo.bridge.channel.wizard": {
        "default_get", "action_refresh", "action_show_code", "action_cancel_code", "action_unpair",
        "action_rotate", "action_forget",
    },
    "res.config.settings": {"get_values", "set_values"},
}
MODULE_MODELS = (
    "styd.odoo.bridge.service", "styd.odoo.bridge.orm", "styd.odoo.bridge.setup.wizard",
    "styd.odoo.bridge.channel.wizard", "styd.odoo.bridge.channel", "styd.odoo.bridge.pairing",
    "styd.odoo.bridge.channel.seen", "styd.odoo.bridge.access.log", "res.config.settings",
)
# The service and ORM entry points that were public before (read with sudo inside).
FORMER_PUBLIC = {
    "styd.odoo.bridge.service": [
        ("get_supported_features", []), ("build_health_payload", []), ("build_security_snapshot_payload", []),
        ("build_user_directory_snapshot_payload", []), ("build_user_search_payload", ["a"]),
        ("build_capability_snapshot_payload", []),
    ],
    "styd.odoo.bridge.orm": [
        ("orm_list_models", []), ("orm_model_fields", ["res.partner"]), ("orm_search_read", ["res.partner"]),
        ("orm_read_group", ["res.partner"]),
    ],
}


@tagged("post_install", "-at_install")
class TestRpcAccess(TransactionCase):
    def setUp(self):
        super().setUp()
        self.icp = self.env["ir.config_parameter"].sudo()
        self.icp.set_param("styd_odoo_bridge.enabled", "True")
        self.icp.set_param("styd_odoo_bridge.connector_owner_user_id", str(self.env.ref("base.user_admin").id))
        self.user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "STYD ordinary", "login": "styd_rpc_ordinary",
            "groups_id": [Command.set([self.env.ref("base.group_user").id])],
        })
        self.admin = self.env.ref("base.user_admin")

    def rpc(self, user, model, method, args=(), kwargs=None):
        Model = self.env[model].with_user(user)
        get_public_method(Model, method)
        return call_kw(Model, method, list(args), dict(kwargs or {}))

    def ids_args(self, model, method):
        """What a client sends: no ids for an @api.model method, else an ids list
        (an installed app may turn res.config.settings.get_values into @api.model)."""
        fn = getattr(type(self.env[model]), method)
        return [] if getattr(fn, "_api", None) == "model" else [[]]

    def assertRefused(self, model, method, args=(), kwargs=None):
        """Refused: private or missing (AttributeError), or an access error."""
        try:
            self.rpc(self.user, model, method, args, kwargs)
        except (AccessError, AttributeError):
            return
        self.fail("%s.%s is callable over RPC by an ordinary user" % (model, method))

    # -- inventory --------------------------------------------------------------
    def _module_public_methods(self, model):
        out = set()
        for cls in type(self.env[model]).mro():
            if not (getattr(cls, "__module__", "") or "").startswith(MODULE_PREFIX):
                continue
            for name, value in vars(cls).items():
                if not name.startswith("_") and inspect.isfunction(value):
                    out.add(name)
        return out

    def test_01_every_public_method_is_reviewed(self):
        """A new public method must be reviewed (and guarded) before it ships."""
        for model in MODULE_MODELS:
            self.assertEqual(self._module_public_methods(model), REVIEWED_PUBLIC.get(model, set()), model)

    # -- the service and the ORM: sudo readers, never reachable --------------------
    def test_10_service_and_orm_entry_points_are_not_rpc(self):
        for model, calls in FORMER_PUBLIC.items():
            for method, args in calls:
                self.assertRefused(model, method, [[]] + args)
                self.assertRefused(model, "_" + method, [[]] + args)

    # -- wizards: every button refused for a non-admin -----------------------------
    def test_20_setup_wizard(self):
        wizard = self.env["styd.odoo.bridge.setup.wizard"].with_user(self.admin).create({})
        token_hash = self.icp.get_param("styd_odoo_bridge.token_hash")
        for method in sorted(REVIEWED_PUBLIC["styd.odoo.bridge.setup.wizard"] - {"default_get"}):
            self.assertRefused("styd.odoo.bridge.setup.wizard", method, [wizard.ids])
        self.assertRefused("styd.odoo.bridge.setup.wizard", "default_get", [["bridge_enabled", "base_url"]])
        self.assertEqual(self.icp.get_param("styd_odoo_bridge.enabled"), "True", "not switched off")
        self.assertEqual(self.icp.get_param("styd_odoo_bridge.token_hash"), token_hash, "token untouched")

    def test_21_channel_wizard(self):
        wizard = self.env["styd.odoo.bridge.channel.wizard"].with_user(self.admin).create({})
        for method in sorted(REVIEWED_PUBLIC["styd.odoo.bridge.channel.wizard"] - {"default_get"}):
            self.assertRefused("styd.odoo.bridge.channel.wizard", method, [wizard.ids])
        self.assertRefused("styd.odoo.bridge.channel.wizard", "default_get", [["owner_user_id", "pairings_html"]])

    def test_22_settings(self):
        self.assertRefused("res.config.settings", "get_values", self.ids_args("res.config.settings", "get_values"))
        self.assertRefused("res.config.settings", "set_values", [[]])
        self.assertEqual(self.icp.get_param("styd_odoo_bridge.enabled"), "True")

    def test_23_secret_tables_and_log(self):
        for model in ("styd.odoo.bridge.pairing", "styd.odoo.bridge.channel.seen", "styd.odoo.bridge.access.log"):
            self.assertRefused(model, "search_read", [[]])

    # -- the admin keeps working -------------------------------------------------------
    def test_30_admin_still_allowed(self):
        values = self.rpc(self.admin, "styd.odoo.bridge.setup.wizard", "default_get", [["bridge_enabled"]])
        self.assertTrue(values["bridge_enabled"])
        values = self.rpc(self.admin, "res.config.settings", "get_values",
                          self.ids_args("res.config.settings", "get_values"))
        self.assertTrue(values["styd_bridge_enabled"])
        wizard = self.env["styd.odoo.bridge.channel.wizard"].with_user(self.admin).create({})
        self.assertEqual(self.rpc(self.admin, "styd.odoo.bridge.channel.wizard", "action_refresh",
                                  [wizard.ids])["res_model"], "styd.odoo.bridge.channel.wizard")
