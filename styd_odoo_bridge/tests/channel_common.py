"""Shared set-up for the outbound channel tests: a fake hub, test-mode cursors
(so the channel's own cursors see this test's data), and helpers to drive a
stream synchronously or with its threads."""

import threading

from odoo import release
from odoo.tests.common import TransactionCase

try:  # Odoo 19+: the test's thread holds the test cursor lock unless released
    from odoo.tests.common import release_test_lock
except ImportError:
    release_test_lock = None

from odoo.addons.styd_odoo_bridge.models import bridge_channel as channel
from odoo.addons.styd_odoo_bridge.models import bridge_channel_executor as executor_mod

from .fake_hub import FakeHub


def flush_env(env):
    """Flush pending ORM writes: ``env.flush_all()`` since Odoo 16."""
    if hasattr(env, "flush_all"):
        env.flush_all()
    else:  # Odoo 15
        env["base"].flush()


class Params:
    """``ir.config_parameter`` with ``get_param`` / ``set_param`` on every version
    (Odoo 20 has ``get_str`` / ``set_str`` only)."""

    def __init__(self, icp):
        self._icp = icp

    def get_param(self, key, default=False):
        return executor_mod.icp_get(self._icp, key, default)

    def set_param(self, key, value):
        return executor_mod.icp_set(self._icp, key, value)

    def __getattr__(self, name):
        return getattr(self._icp, name)


# res.users' groups field when creating or changing a user in a test
# (Odoo 19 renamed groups_id to group_ids).
GROUPS = "group_ids" if int(release.version_info[0]) >= 19 else "groups_id"


class ChannelCase(TransactionCase):
    def setUp(self):
        super().setUp()
        # The channel's own cursors must see this test's data: test mode wraps them
        # around this test's cursor (Odoo 19 moved the switch onto the test case).
        if hasattr(self.registry, "in_test_mode"):
            if not self.registry.in_test_mode():
                self.registry.enter_test_mode(self.cr)
                self.addCleanup(self.registry.leave_test_mode)
        else:
            if not type(self)._registry_patched:
                if hasattr(self, "registry_enter_test_mode"):  # Odoo 19
                    self.registry_enter_test_mode()
                else:  # Odoo 20: a context manager
                    self.enterContext(self.registry_test_mode())
            # Odoo 19 keeps the test cursor lock in the test's thread (HttpCase lets it
            # go around each request). The channel's threads open test cursors while the
            # test waits for them, so the lock is let go for the test, as before 19.
            if release_test_lock is not None:
                released = release_test_lock()
                released.__enter__()
                self.addCleanup(released.__exit__, None, None, None)
        # Odoo's test guard on `requests` cannot read a (connect, read) timeout
        # tuple; production keeps the tuples of section 11.
        self.patch(channel, "POLL_TIMEOUT", 40)
        self.patch(channel, "POST_TIMEOUT", 30)
        self.hub = FakeHub().start()
        self.addCleanup(self.hub.stop)
        self.icp = Params(self.env["ir.config_parameter"].sudo())
        self.icp.set_param("styd_odoo_bridge.enabled", "True")
        self.icp.set_param(channel.ICP_HUB_URL, self.hub.url)
        self.icp.set_param(channel.ICP_CA_BUNDLE, False)
        self.admin = self.env.ref("base.user_admin")
        self.dbname = self.env.cr.dbname
        self._runners = []
        self.addCleanup(self._stop_all)

    # -- data ---------------------------------------------------------------------
    # Odoo 20: a test cursor opened by a channel thread resets this test's cursor
    # while it is open, so a test reads its records (pairing ids) before the
    # threads start, never while they run.
    def make_pairing(self, owner=None, label="Acme", state="active"):
        """An approved pairing of THIS database (as the pair flow leaves it once an
        admin approved it)."""
        pairing_id, secret = self.hub.add_pairing()
        Pairing = self.env["styd.odoo.bridge.pairing"].sudo()
        db = Pairing._current_database()
        row = Pairing.create({
            "pairing_id": pairing_id,
            "secret": secret,
            "state": state,
            "ack_confirmed": True,
            "owner_uid": (owner or self.admin).id,
            "workspace_label": label,
            "db_uuid": db["db_uuid"],
            "db_create_date": db["db_create_date"],
        })
        return row

    def sync(self):
        """Hand this test's pending writes to the channel's cursors. The pre-commit
        hooks run too (Odoo 18 queues bus notifications there when users join
        channels): in test mode the channel's read-only cursor wraps this same
        connection, so they must not run inside it."""
        flush_env(self.env)
        self.env.cr.flush()

    def reload(self):
        if hasattr(self.env, "invalidate_all"):
            self.env.invalidate_all()
        else:  # Odoo 15
            self.env["base"].invalidate_cache()

    # -- channel objects --------------------------------------------------------------
    def make_runner(self, refresh_s=channel.REFRESH_S):
        runner = channel.ChannelRunner(self.dbname, registry=self.registry, refresh_s=refresh_s)
        runner.hub = channel.HubClient(self.hub.url, True)
        runner.executor = executor_mod.ChannelExecutor(self.dbname)
        runner.info["db_uuid"] = self.icp.get_param("database.uuid") or "test-db"
        self._runners.append(runner)
        return runner

    def make_stream(self, row, runner=None):
        self.sync()
        runner = runner or self.make_runner()
        stream = channel.PairingStream(runner, row.sudo()._snapshot())
        runner.streams[row.pairing_id] = stream
        return stream

    def join_stream(self, stream, timeout=5.0):
        stream.stop()
        for t in stream.threads:
            t.join(timeout)
        self.assertFalse(stream.alive(), "stream threads did not stop")

    def _stop_all(self):
        for runner in self._runners:
            runner.stop()
            if runner.is_alive():
                runner.join(10.0)
            for stream in list(runner.streams.values()) + list(runner.all_streams):
                stream.stop()
                for t in stream.threads:
                    t.join(5.0)
            if runner.executor is not None:
                runner.executor.shutdown(wait=True)
            runner.release_lock()
        # io threads spawned for posts are short-lived; give them a moment
        for t in threading.enumerate():
            if t.name == "styd-channel-io":
                t.join(5.0)
