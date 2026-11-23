"""Shared set-up for the outbound channel tests: a fake hub, test-mode cursors
(so the channel's own cursors see this test's data), and helpers to drive a
stream synchronously or with its threads."""

import threading

from odoo.tests.common import TransactionCase

from odoo.addons.styd_odoo_bridge.models import bridge_channel as channel
from odoo.addons.styd_odoo_bridge.models import bridge_channel_executor as executor_mod

from .fake_hub import FakeHub


class ChannelCase(TransactionCase):
    def setUp(self):
        super().setUp()
        if not self.registry.in_test_mode():
            self.registry.enter_test_mode(self.cr)
            self.addCleanup(self.registry.leave_test_mode)
        # Odoo's test guard on `requests` cannot read a (connect, read) timeout
        # tuple; production keeps the tuples of section 11.
        self.patch(channel, "POLL_TIMEOUT", 40)
        self.patch(channel, "POST_TIMEOUT", 30)
        self.hub = FakeHub().start()
        self.addCleanup(self.hub.stop)
        self.icp = self.env["ir.config_parameter"].sudo()
        self.icp.set_param("styd_odoo_bridge.enabled", "True")
        self.icp.set_param(channel.ICP_HUB_URL, self.hub.url)
        self.icp.set_param(channel.ICP_CA_BUNDLE, False)
        self.admin = self.env.ref("base.user_admin")
        self.dbname = self.env.cr.dbname
        self._runners = []
        self.addCleanup(self._stop_all)

    # -- data ---------------------------------------------------------------------
    def make_pairing(self, owner=None, label="Acme"):
        pairing_id, secret = self.hub.add_pairing()
        row = self.env["styd.odoo.bridge.pairing"].sudo().create({
            "pairing_id": pairing_id,
            "secret": secret,
            "state": "active",
            "ack_confirmed": True,
            "owner_uid": (owner or self.admin).id,
            "workspace_label": label,
        })
        return row

    def sync(self):
        """Hand this test's pending writes to the channel's cursors."""
        self.env.flush_all()

    def reload(self):
        self.env.invalidate_all()

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
