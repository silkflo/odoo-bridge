"""S4 open points 6 and 8: the leader sees settings changes within its tick, and
the channel's token bucket holds one engine question (and the next ones)."""

import time

from odoo.tests import tagged

from odoo.addons.styd_odoo_bridge.models import bridge_channel as channel
from odoo.addons.styd_odoo_bridge.models import bridge_channel_executor as ex

from .channel_common import ChannelCase
from .fake_hub import FakeHub


@tagged("post_install", "-at_install")
class TestChannelSettings(ChannelCase):
    # -- helpers ----------------------------------------------------------------------------
    def set_raw(self, key, value):
        """Change a parameter the way another process does: in the table, without
        clearing THIS process's ``get_param`` cache (the leader's situation)."""
        self.sync()
        self.env.cr.execute("DELETE FROM ir_config_parameter WHERE key = %s", (key,))
        if value is not None:
            self.env.cr.execute(
                "INSERT INTO ir_config_parameter (key, value, create_uid, write_uid, create_date, write_date)"
                " VALUES (%s, %s, 1, 1, now() at time zone 'UTC', now() at time zone 'UTC')", (key, value))

    def warm_cache(self):
        for key in channel.FRESH_PARAMS:
            self.icp.get_param(key)

    def no_stream_threads(self):
        """A tick starts one stream per pairing; here the streams start no thread,
        so this test's own cursor is never used by two threads at once."""
        self.patch(channel.PairingStream, "start", lambda stream: None)

    # -- open point 8: the bucket -------------------------------------------------------------
    def test_01_defaults_40_per_second_burst_60(self):
        pool = ex.ChannelExecutor(self.dbname)
        self.addCleanup(pool.shutdown, True)
        self.assertEqual((pool.bucket.rate, pool.bucket.burst), (40.0, 60.0))
        self.assertEqual(pool.capacity, ex.DEFAULT_WORKERS + ex.DEFAULT_QUEUE)
        self.assertEqual(ex.DEFAULT_WORKERS, 4)
        settings = channel.read_settings(self.env, fresh=True)
        self.assertEqual((settings["rate"], settings["burst"]), (40.0, 60))

    def test_02_parse_limit(self):
        for raw, expected in [(None, 7), ("", 7), ("abc", 7), ("0", 7), ("-3", 7), ("nan", 7),
                              ("1", 1.0), (" 25 ", 25.0), ("12.5", 12.5), ("100000", 1000)]:
            self.assertEqual(ex.parse_limit(raw, 7), expected, raw)

    def test_03_bucket_reconfigured_in_place(self):
        now = [100.0]
        bucket = ex.TokenBucket(rate=10, burst=20, clock=lambda: now[0])
        for _ in range(15):
            self.assertTrue(bucket.take())
        bucket.configure(40, 60)  # the 5 tokens left stay, no free refill to 60
        for _ in range(5):
            self.assertTrue(bucket.take())
        self.assertFalse(bucket.take())
        now[0] += 0.5  # 20 tokens back at 40 per second
        for _ in range(20):
            self.assertTrue(bucket.take())
        self.assertFalse(bucket.take())
        bucket.configure(5, 2)  # a smaller burst caps what is left
        now[0] += 10
        self.assertTrue(bucket.take())
        self.assertTrue(bucket.take())
        self.assertFalse(bucket.take())

    def test_04_one_engine_question_and_the_next_are_not_busy(self):
        """22 to 25 reads per question (S4 bench). The old 10/s burst 20 refused
        the reads above 20 at once, and every question after the first waited."""
        now = [0.0]
        old = ex.TokenBucket(rate=10, burst=20, clock=lambda: now[0])
        new = ex.TokenBucket(clock=lambda: now[0])
        refused = {"old": 0, "new": 0}
        for _question in range(4):  # four questions, 0.5 s apart, 25 reads each
            for _ in range(25):
                refused["old"] += not old.take()
                refused["new"] += not new.take()
            now[0] += 0.5
        self.assertEqual(refused["new"], 0)
        self.assertGreater(refused["old"], 40)

    def test_05_tick_applies_the_limit_parameters(self):
        self.no_stream_threads()
        self.make_pairing()
        runner = self.make_runner()
        self.warm_cache()
        self.set_raw(ex.ICP_RATE, "15")
        self.set_raw(ex.ICP_BURST, "33")
        self.assertTrue(runner.tick())
        self.assertEqual((runner.executor.bucket.rate, runner.executor.bucket.burst), (15.0, 33.0))
        self.set_raw(ex.ICP_RATE, "not a number")
        self.set_raw(ex.ICP_BURST, None)
        self.assertTrue(runner.tick())
        self.assertEqual((runner.executor.bucket.rate, runner.executor.bucket.burst), (40.0, 60.0))

    def test_06_a_question_of_25_reads_in_one_batch(self):
        """End to end: one hub batch of 25 reads, no ``busy``."""
        row = self.make_pairing()
        stream = self.make_stream(row)
        stream.poll_once()  # hello
        self.assertTrue(stream.ready.is_set())
        ids = []
        with self.hub.cond:  # all 25 queued before the poll is answered: one batch
            for i in range(25):
                if i % 3 == 2:
                    op, args = "orm.search_read", {"model": "res.partner", "domain": [], "fields": ["name"],
                                                   "limit": 5}
                else:
                    op, args = "orm.fields", {"model": "res.partner" if i % 2 else "res.users"}
                ids.append(self.hub.send(row.pairing_id, op=op, member_uid=self.admin.id, args=args))
        stream.poll_once()
        self.assertTrue(self.hub.wait_for(lambda: all(i in self.hub.results for i in ids), timeout=60))
        codes = [self.hub.results[i].get("error", {}).get("code") for i in ids if not self.hub.results[i]["ok"]]
        self.assertEqual(codes, [])
        self.join_stream(stream)

    # -- open point 6: settings reach the running leader within its tick ----------------------------
    def test_10_load_reads_the_table_not_the_process_cache(self):
        self.make_pairing()
        self.warm_cache()
        self.set_raw(channel.ICP_HUB_URL, "https://hub.example.com")
        self.set_raw(channel.ICP_CA_BUNDLE, "/etc/ssl/certs/ca.pem")
        # this process's cache still has the old values (what the leader used for up to 75 s)
        self.assertEqual(self.icp.get_param(channel.ICP_HUB_URL), self.hub.url)
        self.assertFalse(self.icp.get_param(channel.ICP_CA_BUNDLE))
        settings = channel.PairingStore(self.dbname, self.registry).load()["settings"]
        self.assertEqual(settings["hub_url"], "https://hub.example.com")
        self.assertEqual(settings["ca_bundle"], "/etc/ssl/certs/ca.pem")
        self.set_raw(channel.ICP_HUB_URL, None)
        settings = channel.PairingStore(self.dbname, self.registry).load()["settings"]
        self.assertEqual(settings["hub_url"], channel.DEFAULT_HUB_URL)

    def test_11_switched_off_reaches_the_leader_at_the_next_tick(self):
        self.no_stream_threads()
        self.make_pairing()
        runner = self.make_runner()
        self.sync()
        self.assertTrue(runner.tick())
        self.warm_cache()
        self.set_raw("styd_odoo_bridge.enabled", "False")
        self.assertEqual(self.icp.get_param("styd_odoo_bridge.enabled"), "True", "cache is stale")
        self.assertFalse(runner.tick(), "the leader stops at its next tick")

    def test_12_bad_ca_bundle_reaches_the_leader_at_the_next_tick(self):
        self.no_stream_threads()
        self.make_pairing()
        runner = self.make_runner()
        self.sync()
        self.assertTrue(runner.tick())
        self.warm_cache()
        self.set_raw(channel.ICP_CA_BUNDLE, "/nonexistent/styd-ca.pem")
        with self.assertLogs(channel._logger.name, level="WARNING") as logs:
            self.assertFalse(runner.tick())
        self.assertIn("bad channel settings", "\n".join(logs.output))

    def test_13_running_leader_moves_to_the_new_hub_within_its_tick(self):
        """The runner thread, as in production: the hub URL is changed in the table
        only (another process saved it); the leader says hello to the new hub
        within a tick, and answers there."""
        hub2 = FakeHub().start()
        self.addCleanup(hub2.stop)
        row = self.make_pairing()
        hub2.add_pairing(row.pairing_id, row.secret)
        self.sync()
        self.warm_cache()  # before the thread starts: from here on, SQL only through the locked test cursor
        runner = channel.ChannelRunner(self.dbname, registry=self.registry, refresh_s=0.3)
        self._runners.append(runner)
        runner.start()
        self.assertTrue(self.hub.wait_for(lambda: self.hub.hellos, timeout=15), "hello to the first hub")
        t0 = time.monotonic()
        with self.registry.cursor() as cr:  # the test cursor, as the leader's own cursors see it
            cr.execute("UPDATE ir_config_parameter SET value = %s WHERE key = %s", (hub2.url, channel.ICP_HUB_URL))
        self.assertTrue(hub2.wait_for(lambda: hub2.hellos, timeout=10), "hello to the new hub")
        self.assertLess(time.monotonic() - t0, 5.0, "within a tick or two, not the next keeper run")
        msg_id = hub2.send(row.pairing_id, op="health", member_uid=self.admin.id)
        self.assertTrue(hub2.wait_for(lambda: msg_id in hub2.results, timeout=15))
        self.assertTrue(hub2.results[msg_id]["ok"])
        runner.stop()
        runner.join(15)
        self.assertFalse(runner.is_alive())
        self.assertEqual(self.icp.get_param(channel.ICP_HUB_URL), self.hub.url,
                         "this process's cache never saw the change: the leader read the table")

    def test_14_the_executor_limits_follow_a_running_leader(self):
        self.make_pairing()
        self.sync()
        runner = channel.ChannelRunner(self.dbname, registry=self.registry, refresh_s=0.2)
        self._runners.append(runner)
        runner.start()
        self.assertTrue(self.hub.wait_for(lambda: self.hub.hellos, timeout=15))
        self.assertTrue(self.hub.wait_for(
            lambda: runner.executor is not None and runner.executor.bucket.rate == 40.0, timeout=5))
        with self.registry.cursor() as cr:
            cr.execute("INSERT INTO ir_config_parameter (key, value) VALUES (%s, '80'), (%s, '120')",
                       (ex.ICP_RATE, ex.ICP_BURST))
        self.assertTrue(self.hub.wait_for(
            lambda: (runner.executor.bucket.rate, runner.executor.bucket.burst) == (80.0, 120.0), timeout=5))
        runner.stop()
        runner.join(15)
