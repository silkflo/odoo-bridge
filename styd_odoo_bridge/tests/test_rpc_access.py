"""No method of this module may be called over RPC by a user who may not use it.

Each call goes the way Odoo's /web/dataset/call_kw and XML-RPC go on this
version (the private-name gate, then call_kw), as an ordinary internal user
and as a portal user. Odoo 15 to 20.
"""

import inspect

from odoo import Command, release
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

try:  # 19+: one function gates and calls
    from odoo.service.model import call_kw as _service_call_kw
except ImportError:
    _service_call_kw = None
try:  # 16 to 18
    from odoo.service.model import get_public_method
except ImportError:
    get_public_method = None

MAJOR = int(release.version_info[0])
MODULE_PREFIX = "odoo.addons.styd_odoo_bridge."

SETUP_ACTIONS = {"action_save_settings", "action_generate_token", "action_rotate_token", "action_revoke_token"}
if MAJOR >= 17:
    SETUP_ACTIONS |= {"action_open_access_logs"}
if MAJOR >= 19:
    SETUP_ACTIONS |= {"action_open_bridge_status"}
STATUS_ACTIONS = {"action_refresh_status", "action_open_access_logs", "action_open_connection_setup"}

# Every public method this module defines on an Odoo model (each is guarded).
REVIEWED_PUBLIC = {
    "styd.odoo.bridge.setup.wizard": {"default_get"} | SETUP_ACTIONS,
    "res.config.settings": {"get_values", "set_values"},
}
MODULE_MODELS = ["styd.odoo.bridge.service", "styd.odoo.bridge.orm", "styd.odoo.bridge.setup.wizard",
                 "res.config.settings"]
if MAJOR >= 17:
    MODULE_MODELS.append("styd.odoo.bridge.access.log")
if MAJOR >= 19:
    MODULE_MODELS.append("styd.odoo.bridge.status")
    REVIEWED_PUBLIC["styd.odoo.bridge.status"] = set(STATUS_ACTIONS)

# The service and ORM entry points that were public before (they read with sudo).
FORMER_PUBLIC = {
    "styd.odoo.bridge.service": [
        ("get_supported_features", []), ("build_health_payload", []), ("build_security_snapshot_payload", []),
        ("build_user_directory_snapshot_payload", []), ("build_capability_snapshot_payload", []),
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
        self.admin = self.env.ref("base.user_admin")
        self.set_icp("styd_odoo_bridge.enabled", "True")
        self.set_icp("styd_odoo_bridge.connector_owner_user_id", str(self.admin.id))
        self.set_icp("styd_odoo_bridge.token_hash", "a" * 64)
        Users = self.env["res.users"].with_context(no_reset_password=True)
        gfield = "group_ids" if MAJOR >= 19 else "groups_id"
        self.internal = Users.create({
            "name": "STYD ordinary", "login": "styd_rpc_ordinary",
            gfield: [Command.set([self.env.ref("base.group_user").id])],
        })
        self.portal = Users.create({
            "name": "STYD portal", "login": "styd_rpc_portal",
            gfield: [Command.set([self.env.ref("base.group_portal").id])],
        })
        self.outsiders = (self.internal, self.portal)

    # Odoo 20 replaced get_param / set_param with get_str / set_str.
    def set_icp(self, key, value):
        return self.icp.set_str(key, value) if hasattr(self.icp, "set_str") else self.icp.set_param(key, value)

    def get_icp(self, key):
        return self.icp.get_str(key) if hasattr(self.icp, "get_str") else self.get_icp(key)

    # -- the RPC path of this version -------------------------------------------
    def rpc(self, user, model, method, args=(), kwargs=None):
        Model = self.env[model].with_user(user)
        args, kwargs = list(args), dict(kwargs or {})
        if _service_call_kw is not None:
            return _service_call_kw(Model, method, args, kwargs)
        if get_public_method is not None:
            get_public_method(Model, method)
        else:
            from odoo.models import check_method_name
            check_method_name(method)
        from odoo.api import call_kw
        return call_kw(Model, method, args, kwargs)

    def ids_args(self, model, method):
        """No ids for an @api.model method, else an ids list (an installed app
        may make res.config.settings.get_values an @api.model method)."""
        fn = getattr(type(self.env[model]), method)
        is_model = getattr(fn, "_api", None) == "model" or getattr(fn, "_api_model", False)
        return [] if is_model else [[]]

    def assertRefused(self, model, method, args=(), kwargs=None):
        """Refused for both outsiders: private or missing (AttributeError), or an access error."""
        for user in self.outsiders:
            try:
                self.rpc(user, model, method, args, kwargs)
            except (AccessError, AttributeError):
                continue
            self.fail("%s.%s is callable over RPC by %s" % (model, method, user.login))

    def form_spec(self, names):
        return {n: {} for n in names} if MAJOR >= 17 else {n: "1" for n in names}

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

    # -- the setup wizard: every button, the form values, revoke above all ----------
    def test_20_setup_wizard(self):
        wizard = self.env["styd.odoo.bridge.setup.wizard"].with_user(self.admin).create({})
        for method in sorted(SETUP_ACTIONS):
            self.assertRefused("styd.odoo.bridge.setup.wizard", method, [wizard.ids])
        self.assertRefused("styd.odoo.bridge.setup.wizard", "default_get", [["bridge_enabled", "base_url"]])
        self.assertRefused("styd.odoo.bridge.setup.wizard", "onchange",
                           [[], {}, [], self.form_spec(["bridge_enabled", "token_configured", "base_url"])])
        self.assertEqual(self.get_icp("styd_odoo_bridge.enabled"), "True", "not switched off")
        self.assertEqual(self.get_icp("styd_odoo_bridge.token_hash"), "a" * 64, "token not revoked")

    def test_21_status_page(self):
        if MAJOR < 19:
            self.skipTest("no status page before 19.0")
        page = self.env["styd.odoo.bridge.status"].with_user(self.admin).create({})
        for method in sorted(STATUS_ACTIONS):
            self.assertRefused("styd.odoo.bridge.status", method, [page.ids])
        self.assertRefused("styd.odoo.bridge.status", "onchange",
                           [[], {}, [], self.form_spec(["bridge_enabled", "database_uuid", "audit_total_count"])])

    def test_22_settings(self):
        self.assertRefused("res.config.settings", "get_values", self.ids_args("res.config.settings", "get_values"))
        self.assertRefused("res.config.settings", "set_values", [[]])
        self.assertEqual(self.get_icp("styd_odoo_bridge.enabled"), "True")

    def test_23_audit_log(self):
        if MAJOR < 17:
            self.skipTest("no audit log model before 17.0")
        self.assertRefused("styd.odoo.bridge.access.log", "search_read", [[]])

    # -- the admin keeps working -------------------------------------------------------
    def test_30_admin_still_allowed(self):
        values = self.rpc(self.admin, "styd.odoo.bridge.setup.wizard", "default_get", [["bridge_enabled"]])
        self.assertTrue(values["bridge_enabled"])
        values = self.rpc(self.admin, "res.config.settings", "get_values",
                          self.ids_args("res.config.settings", "get_values"))
        self.assertTrue(values["styd_bridge_enabled"])
        wizard = self.env["styd.odoo.bridge.setup.wizard"].with_user(self.admin).create({})
        action = self.rpc(self.admin, "styd.odoo.bridge.setup.wizard", "action_save_settings", [wizard.ids])
        self.assertEqual(action["res_model"], "styd.odoo.bridge.setup.wizard")
