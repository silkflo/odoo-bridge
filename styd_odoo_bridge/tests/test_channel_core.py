"""M1: the channel core (leader lock, keeper, hello, polls, backoff, clock offset)."""

import time

from odoo.tests import tagged

from odoo.addons.styd_odoo_bridge.models import bridge_channel as channel
from odoo.addons.styd_odoo_bridge.models import bridge_channel_protocol as proto

from .channel_common import ChannelCase


@tagged("post_install", "-at_install")
class TestChannelCore(ChannelCase):
    # -- leader election and keeper ------------------------------------------------
    def test_01_advisory_lock_one_leader(self):
        first = channel.ChannelRunner(self.dbname, registry=self.registry)
        second = channel.ChannelRunner(self.dbname, registry=self.registry)
        self.assertTrue(first.take_lock())
        self.addCleanup(first.release_lock)
        self.assertTrue(first.lock_alive())
        self.assertFalse(second.take_lock(), "a second runner must stay on standby")
        first.release_lock()
        self.assertFalse(first.lock_alive())
        self.assertTrue(second.take_lock(), "the lock is free once the leader's connection closes")
        second.release_lock()

    def test_02_keeper_cron_record(self):
        cron = self.env.ref(channel.KEEPER_CRON_XMLID)
        self.assertTrue(cron.active)
        self.assertEqual((cron.interval_number, cron.interval_type), (1, "minutes"))
        self.assertEqual(cron.code.strip(), "model._cron_keeper()")

    def test_03_keeper_idle_without_pairing_or_when_disabled(self):
        Keeper = self.env["styd.odoo.bridge.channel"]
        self.env["styd.odoo.bridge.pairing"].sudo().search([]).unlink()
        self.assertEqual(Keeper._cron_keeper(), "idle")
        self.make_pairing()
        self.icp.set_param("styd_odoo_bridge.enabled", "False")
        self.assertEqual(Keeper._cron_keeper(), "idle")
        self.assertTrue(self.env["styd.odoo.bridge.pairing"].sudo().search_count([("state", "=", "active")]))

    def test_04_boot_trigger(self):
        cron = self.env.ref(channel.KEEPER_CRON_XMLID)
        Trigger = self.env["ir.cron.trigger"].sudo()
        Keeper = self.env["styd.odoo.bridge.channel"]
        self.env["styd.odoo.bridge.pairing"].sudo().search([]).unlink()
        before = Trigger.search_count([("cron_id", "=", cron.id)])
        Keeper._register_hook()
        self.assertEqual(Trigger.search_count([("cron_id", "=", cron.id)]), before, "no pairing: no trigger")
        self.make_pairing()
        Keeper._register_hook()
        self.assertEqual(Trigger.search_count([("cron_id", "=", cron.id)]), before + 1)

    def test_05_tick_stops_when_disabled_or_unpaired(self):
        runner = self.make_runner()
        self.sync()
        self.assertFalse(runner.tick(), "no pairing: the runner stops")
        row = self.make_pairing()
        self.icp.set_param("styd_odoo_bridge.enabled", "False")
        self.sync()
        self.assertFalse(runner.tick(), "Bridge switched off: the runner stops")
        self.icp.set_param("styd_odoo_bridge.enabled", "True")
        self.sync()
        self.assertTrue(runner.tick())
        self.assertIn(row.pairing_id, runner.streams)
        stream = runner.streams[row.pairing_id]
        self.assertTrue(self.hub.wait_for(lambda: self.hub.hellos), "the stream says hello")
        # unpaired in another process: the next tick stops the stream
        self.join_stream(stream)
        row.sudo()._revoke("admin")
        self.sync()
        self.assertFalse(runner.tick())

    def test_06_streamable_waits_for_ack_or_grace(self):
        row = self.make_pairing()
        Pairing = self.env["styd.odoo.bridge.pairing"].sudo()
        self.assertIn(row, Pairing.search(Pairing._streamable_domain()))
        row.write({"ack_confirmed": False, "paired_at": self.env.cr.now()})
        self.assertNotIn(row, Pairing.search(Pairing._streamable_domain()))

    # -- hello and polls -------------------------------------------------------------
    def test_10_hello_then_plain_polls(self):
        row = self.make_pairing()
        stream = self.make_stream(row)
        stream.poll_once()
        self.assertTrue(stream.ready.is_set())
        self.assertEqual(len(self.hub.hellos), 1)
        pairing_id, hello = self.hub.hellos[0]
        self.assertEqual(pairing_id, row.pairing_id)
        self.assertEqual(hello["t"], "hello")
        self.assertEqual(hello["protocol"], [1])
        self.assertEqual(hello["ops"], list(proto.OPS))
        self.assertRegex(hello["module_version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(hello["odoo_series"], "17.0")
        self.assertTrue(hello["db_uuid"])
        self.assertTrue(0 < len(hello["instance"]) <= 64)
        self.assertEqual(stream.version["t"], "version")
        stream.poll_once()  # plain poll, held then empty
        self.assertEqual(len(self.hub.hellos), 1)
        self.assertFalse(self.hub.refused)
        self.reload()
        self.assertEqual(row.status_code, "ok")
        self.assertTrue(row.last_seen_at)

    def test_11_two_polls_outstanding_one_hello(self):
        row = self.make_pairing()
        stream = self.make_stream(row)
        self.hub.hold_s = 1.0
        stream.start()
        self.assertTrue(self.hub.wait_for(lambda: self.hub.max_held.get(row.pairing_id, 0) >= 2, timeout=10))
        self.join_stream(stream)
        self.assertEqual(len(self.hub.hellos), 1, "only one poller says hello")

    def test_12_hello_required_after_hub_restart(self):
        row = self.make_pairing()
        stream = self.make_stream(row)
        stream.poll_once()
        self.hub.drop_sessions()
        stream.poll_once()  # 409 hello_required
        self.assertFalse(stream.ready.is_set())
        self.assertEqual(stream.pause_until, 0.0, "409: resend at once")
        stream.poll_once()
        self.assertTrue(stream.ready.is_set())
        self.assertEqual(len(self.hub.hellos), 2)

    def test_13_not_paired_keeps_the_pairing(self):
        row = self.make_pairing()
        stream = self.make_stream(row)
        self.hub.force("/bridge/v1/poll", 401, {"t": "error", "code": "not_paired"})
        stream.poll_once()
        self.assertFalse(stream.ready.is_set())
        self.assertAlmostEqual(stream.pause_until - time.monotonic(), channel.NOT_PAIRED_RETRY_S, delta=5)
        self.reload()
        self.assertEqual(row.state, "active")
        self.assertTrue(row.secret)
        self.assertEqual(row.status_code, "not_paired")

    def test_14_module_too_old_waits_an_hour(self):
        row = self.make_pairing()
        stream = self.make_stream(row)
        self.hub.min_module_version = "99.0.0"
        stream.poll_once()
        self.assertAlmostEqual(stream.pause_until - time.monotonic(), channel.TOO_OLD_RETRY_S, delta=5)
        self.reload()
        self.assertEqual(row.status_code, "module_too_old")

    def test_15_rate_limited_waits_retry_after(self):
        row = self.make_pairing()
        stream = self.make_stream(row)
        self.hub.force("/bridge/v1/poll", 429, {"t": "error", "code": "rate_limited", "retry_after_s": 7})
        stream.poll_once()
        self.assertAlmostEqual(stream.pause_until - time.monotonic(), 7, delta=1)

    def test_16_backoff_with_jitter_resets_after_a_good_poll(self):
        row = self.make_pairing()
        stream = self.make_stream(row)
        self.hub.force("/bridge/v1/poll", 503, {"t": "error", "code": "hub_draining", "retry_after_s": 2}, times=3)
        waits = []
        for _i in range(3):
            stream.pause_until = 0.0
            stream.poll_once()
            waits.append(stream.pause_until - time.monotonic())
        self.assertEqual(stream.failures, 3)
        for wait, base in zip(waits, (1, 2, 4)):
            self.assertTrue(base / 2.0 - 0.2 <= wait <= base + 0.2, (wait, base))
        stream.pause_until = 0.0
        stream.poll_once()
        self.assertEqual(stream.failures, 0)

    def test_17_clock_offset(self):
        """A server clock 10 minutes off: the first try is stale, the answer's
        server_time fixes it, and the hub's own timestamps are checked with it."""
        row = self.make_pairing()
        stream = self.make_stream(row)
        self.hub.clock_skew_ms = 600_000
        stream.poll_once()
        self.assertEqual([c for _p, c in self.hub.refused], ["stale_request"])
        self.assertTrue(stream.ready.is_set(), "the retry with the learned offset passed")
        self.assertAlmostEqual(stream.signer.offset_ms, 600_000, delta=5_000)
        ping_id = self.hub.send(row.pairing_id, t="ping", op="control.ping", member_uid=0)
        stream.poll_once()
        self.assertTrue(self.hub.wait_for(
            lambda: any(b.get("kind") == "pong" and b.get("id") == ping_id for _p, b in self.hub.events)))

    def test_18_unknown_messages_ignored(self):
        row = self.make_pairing()
        stream = self.make_stream(row)
        stream.poll_once()
        self.hub.queue_raw(row.pairing_id, {"t": "future_kind", "x": 1})
        self.hub.queue_raw(row.pairing_id, {"t": "request", "id": "nope"})
        stream.poll_once()
        self.assertFalse(self.hub.results)

    def test_19_forged_request_answered_bad_signature(self):
        row = self.make_pairing()
        stream = self.make_stream(row)
        stream.poll_once()
        _pid, other_secret = self.hub.add_pairing()
        msg_id = self.hub.send(row.pairing_id, op="health", member_uid=self.admin.id, secret=other_secret)
        stream.poll_once()
        self.assertTrue(self.hub.wait_for(lambda: msg_id in self.hub.results))
        self.assertEqual(self.hub.results[msg_id]["error"]["code"], "bad_signature")

    # -- end to end with the runner thread ---------------------------------------------------
    def test_30_runner_end_to_end(self):
        row = self.make_pairing()
        self.sync()
        runner = channel.ChannelRunner(self.dbname, registry=self.registry, refresh_s=0.2)
        self._runners.append(runner)
        runner.start()
        self.assertTrue(self.hub.wait_for(lambda: self.hub.hellos, timeout=15), "runner said hello")
        self.assertEqual(runner.state, "leader")
        msg_id = self.hub.send(row.pairing_id, op="health", member_uid=self.admin.id)
        self.assertTrue(self.hub.wait_for(lambda: msg_id in self.hub.results, timeout=15))
        result = self.hub.results[msg_id]
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], 200)
        self.assertTrue(result["body"]["ok"])
        self.assertIn("supported_features", result["body"])
        self.assertIsInstance(result["exec_ms"], float)
        # a second process would stand by
        other = channel.ChannelRunner(self.dbname, registry=self.registry)
        self.assertFalse(other.take_lock())
        runner.stop()
        runner.join(15)
        self.assertFalse(runner.is_alive())
        self.assertEqual(runner.state, "stopped")
