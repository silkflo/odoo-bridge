import hashlib

from odoo import release
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

FORM_FIELDS = (
    "bridge_enabled",
    "connector_owner_user_id",
    "token_configured",
    "legacy_plaintext_token_present",
    "base_url",
    "generated_token",
    "has_generated_token",
)


@tagged("post_install", "-at_install")
class TestConnectionSetupForm(TransactionCase):
    """The Connection Setup form as the web client opens it.

    The first onchange of a new record is what fills the form. On Odoo 15-18
    it takes every field from default_get(), so these tests guard against the
    form showing an empty token / wrong state (regression found on 15-18).
    """

    def setUp(self):
        super().setUp()
        self.service = self.env["styd.odoo.bridge.service"]
        self.admin = self.env.ref("base.user_admin")
        self.Wizard = self.env["styd.odoo.bridge.setup.wizard"].with_user(self.admin)

    def _open_form(self, context=None):
        wizard = self.Wizard.with_context(**(context or {}))
        if int(release.version_info[0]) >= 17:
            result = wizard.onchange({}, [], {fname: {} for fname in FORM_FIELDS})
        else:
            result = wizard.onchange({}, [], {fname: "1" for fname in FORM_FIELDS})
        return result["value"]

    def _set(self, key, value):
        self.service._icp_set(key, value)

    def test_01_fresh_form_shows_no_token(self):
        self._set("styd_odoo_bridge.token", False)
        self._set("styd_odoo_bridge.token_hash", False)
        values = self._open_form()
        self.assertFalse(values["token_configured"])
        self.assertFalse(values["generated_token"])
        self.assertFalse(values["has_generated_token"])
        self.assertFalse(values["legacy_plaintext_token_present"])

    def test_02_generated_token_is_shown_once_and_stored_hashed(self):
        self._set("styd_odoo_bridge.token", False)
        self._set("styd_odoo_bridge.token_hash", False)
        wizard = self.Wizard.create({"bridge_enabled": True, "connector_owner_user_id": self.admin.id})
        action = wizard.action_generate_token()
        token = action["context"]["generated_token"]
        self.assertTrue(token)

        values = self._open_form(action["context"])
        self.assertEqual(values["generated_token"], token)
        self.assertTrue(values["has_generated_token"])
        self.assertTrue(values["token_configured"])

        self.assertEqual(
            self.service._get_bridge_token_hash(),
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(self.service._get_bridge_token(), "")
        self.assertFalse(type(wizard)._fields["generated_token"].store)

        # Reopening the page without the action context never shows it again.
        self.assertFalse(self._open_form()["generated_token"])
        self.assertTrue(self._open_form()["token_configured"])

    def test_03_form_shows_settings_and_base_url(self):
        self._set("styd_odoo_bridge.enabled", "True")
        self._set("styd_odoo_bridge.connector_owner_user_id", str(self.admin.id))
        self._set("web.base.url", "https://odoo.example.com")
        values = self._open_form()
        self.assertTrue(values["bridge_enabled"])
        owner = values["connector_owner_user_id"]
        owner_id = owner["id"] if isinstance(owner, dict) else (owner[0] if isinstance(owner, (list, tuple)) else owner)
        self.assertEqual(owner_id, self.admin.id)
        self.assertEqual(values["base_url"], "https://odoo.example.com")

    def test_04_legacy_plaintext_token_is_flagged(self):
        self._set("styd_odoo_bridge.token_hash", False)
        self._set("styd_odoo_bridge.token", "legacy-plaintext-value")
        values = self._open_form()
        self.assertTrue(values["legacy_plaintext_token_present"])
        self.assertTrue(values["token_configured"])
