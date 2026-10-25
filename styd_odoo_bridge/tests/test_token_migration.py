import glob
import hashlib
import importlib.util
import json
import logging
import os

from odoo.modules.module import get_module_path
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase

LEGACY_TOKEN = "styd-legacy-plaintext-token-0123456789abcdef"
LEGACY_HASH = hashlib.sha256(LEGACY_TOKEN.encode("utf-8")).hexdigest()


def _load_migration_script():
    """Import this release's migrations/<version>/post-migrate.py."""
    pattern = os.path.join(get_module_path("styd_odoo_bridge"), "migrations", "*", "post-migrate.py")
    paths = sorted(glob.glob(pattern))
    assert paths, "post-migrate.py not found"
    spec = importlib.util.spec_from_file_location("styd_bridge_post_migrate", paths[-1])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _TokenParams:
    def _service(self):
        return self.env["styd.odoo.bridge.service"]

    def _set(self, key, value):
        self._service()._icp_set(key, value)

    def _get(self, key):
        return self._service()._icp_get(key, "") or ""

    def _seed_legacy(self, token=LEGACY_TOKEN, token_hash=False):
        self._set("styd_odoo_bridge.token", token)
        self._set("styd_odoo_bridge.token_hash", token_hash)


@tagged("post_install", "-at_install")
class TestTokenMigration(_TokenParams, TransactionCase):

    def test_01_plaintext_is_hashed_in_place(self):
        self._seed_legacy()
        self.assertTrue(self._service()._migrate_legacy_token_to_hash())
        self.assertEqual(self._get("styd_odoo_bridge.token_hash"), LEGACY_HASH)
        self.assertEqual(self._get("styd_odoo_bridge.token"), "")
        self.assertTrue(self._service()._token_is_configured())
        self.assertFalse(self._service()._has_legacy_plaintext_token())

    def test_02_idempotent(self):
        self._seed_legacy()
        self._service()._migrate_legacy_token_to_hash()
        self.assertFalse(self._service()._migrate_legacy_token_to_hash())
        self.assertEqual(self._get("styd_odoo_bridge.token_hash"), LEGACY_HASH)
        self.assertEqual(self._get("styd_odoo_bridge.token"), "")

    def test_03_existing_hash_wins(self):
        # The controller prefers the hash, so it is the live credential: keep
        # it and only clear the stale plaintext.
        live_hash = hashlib.sha256(b"another-live-token").hexdigest()
        self._seed_legacy(token_hash=live_hash)
        self.assertTrue(self._service()._migrate_legacy_token_to_hash())
        self.assertEqual(self._get("styd_odoo_bridge.token_hash"), live_hash)
        self.assertEqual(self._get("styd_odoo_bridge.token"), "")

    def test_04_nothing_configured(self):
        self._seed_legacy(token=False)
        self.assertFalse(self._service()._migrate_legacy_token_to_hash())
        self.assertEqual(self._get("styd_odoo_bridge.token_hash"), "")
        self.assertFalse(self._service()._token_is_configured())

    def test_05_migration_script(self):
        self._seed_legacy()
        script = _load_migration_script()
        script.migrate(self.env.cr, None)  # fresh install: no-op
        self.assertEqual(self._get("styd_odoo_bridge.token"), LEGACY_TOKEN)
        script.migrate(self.env.cr, "0.9.0")  # upgrade from an older version
        self.assertEqual(self._get("styd_odoo_bridge.token_hash"), LEGACY_HASH)
        self.assertEqual(self._get("styd_odoo_bridge.token"), "")

    def test_06_migration_never_logs_the_token(self):
        self._seed_legacy()
        script = _load_migration_script()
        messages = []
        handler = logging.Handler(logging.INFO)
        handler.emit = lambda record: messages.append(record.getMessage())
        logger = logging.getLogger(script.__name__)
        logger.addHandler(handler)
        try:
            script.migrate(self.env.cr, "0.9.0")
        finally:
            logger.removeHandler(handler)
        self.assertEqual(len(messages), 1, messages)
        for line in messages:
            self.assertNotIn(LEGACY_TOKEN, line)
            self.assertNotIn(LEGACY_HASH, line)


@tagged("post_install", "-at_install")
class TestTokenMigrationHttp(_TokenParams, HttpCase):
    """End to end: an install that still stores the plaintext token keeps
    accepting the same raw token after the migration hashed it."""

    HEALTH_URL = "/styd_bridge/v1/health"

    def _health(self, token=None):
        headers = {"Authorization": "Bearer %s" % token} if token else {}
        return self.url_open(self.HEALTH_URL, headers=headers)

    def test_01_live_connection_survives_migration(self):
        self._set("styd_odoo_bridge.enabled", "True")
        self._seed_legacy()

        before = self._health(LEGACY_TOKEN)
        self.assertEqual(before.status_code, 200)

        _load_migration_script().migrate(self.env.cr, "0.9.0")
        self.assertEqual(self._get("styd_odoo_bridge.token"), "")
        self.assertEqual(self._get("styd_odoo_bridge.token_hash"), LEGACY_HASH)

        after = self._health(LEGACY_TOKEN)
        self.assertEqual(after.status_code, 200)
        self.assertTrue(json.loads(after.text)["ok"])

        self.assertEqual(self._health("wrong-token").status_code, 401)
        self.assertEqual(self._health().status_code, 401)
        # The stored hash itself is not a valid bearer token.
        self.assertEqual(self._health(LEGACY_HASH).status_code, 401)
