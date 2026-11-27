"""Pairing (code, pair session, proof of possession), secret storage, unpair
both ways, rotation, settings."""

import threading

from odoo import SUPERUSER_ID, Command, api, release
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.styd_odoo_bridge.models import bridge_channel as channel
from odoo.addons.styd_odoo_bridge.models import bridge_channel_pair as pair
from odoo.addons.styd_odoo_bridge.models import bridge_channel_protocol as proto

from .channel_common import GROUPS, ChannelCase


@tagged("post_install", "-at_install")
class TestChannelPairing(ChannelCase):
    def setUp(self):
        super().setUp()
        self.Wizard = self.env["styd.odoo.bridge.channel.wizard"].with_user(self.admin)
        self.Pairing = self.env["styd.odoo.bridge.pairing"].sudo()
        self.Pairing.search([]).unlink()

    def _show_code(self):
        wizard = self.Wizard.create({})
        action = wizard.action_show_code()
        code = action["context"]["styd_pair_code"]
        row = self.Pairing.search([("state", "=", "pending")])
        self.assertEqual(len(row), 1)
        return code, row

    def _run_session(self, row, code, life_s=20):
        """Run the pair session in a thread, as Odoo does; return (thread, outcome box)."""
        self.sync()
        store = channel.PairingStore(self.dbname, self.registry)
        hub = channel.HubClient(self.hub.url, True)
        info = {"module_version": "0.11.0", "odoo_series": "17.0", "db_uuid": "test-db",
                "db_name": self.dbname, "company_name": self.admin.company_id.name}
        box = {}
        code_hash = proto.pair_code_hash(proto.normalize_pair_code(code))

        def target():
            box["outcome"] = pair.run_pair_session(store, hub, row.id, code_hash, self.admin.id, info,
                                                   life_s=life_s)

        t = threading.Thread(target=target, daemon=True)
        t.start()
        self.addCleanup(t.join, 10)
        return t, box

    # -- storage ------------------------------------------------------------------------
    def test_01_secret_model_has_no_acl(self):
        Access = self.env["ir.access" if "ir.access" in self.env else "ir.model.access"].sudo()  # 20: ir.access
        for model in ("styd.odoo.bridge.pairing", "styd.odoo.bridge.channel.seen"):
            self.assertFalse(Access.search([("model_id.model", "=", model)]), model)
            with self.assertRaises(AccessError):
                self.env[model].with_user(self.admin).search([])
        row = self.make_pairing()
        with self.assertRaises(AccessError):
            self.env["styd.odoo.bridge.pairing"].with_user(self.admin).browse(row.id).read(["secret"])
        icp_values = self.env["ir.config_parameter"].sudo().search([]).mapped("value")
        self.assertNotIn(row.secret, icp_values)

    def test_02_member_group_exists(self):
        group = self.env.ref("styd_odoo_bridge.group_styd_member")
        self.assertEqual(group._name, "res.groups")

    # -- the code and the wizard --------------------------------------------------------
    def test_10_show_code(self):
        code, row = self._show_code()
        self.assertRegex(code, r"^[%s]{4}-[%s]{4}$" % (proto.PAIR_CODE_ALPHABET, proto.PAIR_CODE_ALPHABET))
        self.assertEqual(row.owner_uid, self.admin.id)
        self.assertFalse(row.secret)
        self.assertTrue(row.pair_expires_at)
        # the code is not stored anywhere
        for value in row.read()[0].values():
            self.assertNotIn(code.replace("-", ""), str(value))
        # a second code replaces the first pending one
        self._show_code()

    def test_11_show_code_rules(self):
        user = self.env["res.users"].create({
            "name": "STYD plain", "login": "styd_plain_test",
            GROUPS: [Command.set([self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self.env["styd.odoo.bridge.channel.wizard"].with_user(user).create({}).action_show_code()
        portal = self.env["res.users"].create({
            "name": "STYD portal owner", "login": "styd_portal_owner",
            GROUPS: [Command.set([self.env.ref("base.group_portal").id])],
        })
        with self.assertRaises(UserError):
            self.Wizard.create({"owner_user_id": portal.id}).action_show_code()
        with self.assertRaises(UserError):
            self.Wizard.create({"owner_user_id": 1}).action_show_code()
        self.icp.set_param("styd_odoo_bridge.enabled", "False")
        with self.assertRaises(UserError):
            self.Wizard.create({}).action_show_code()

    def test_12_form_opens_with_state(self):
        self.make_pairing(label="Acme <b>Corp</b>")
        names = ("pair_code", "has_pair_code", "pairings_html", "bridge_enabled", "owner_user_id")
        if int(release.version_info[0]) >= 17:
            values = self.Wizard.with_context(styd_pair_code="K7QX-M2PR").onchange({}, [], {f: {} for f in names})["value"]
        else:
            values = self.Wizard.with_context(styd_pair_code="K7QX-M2PR").onchange({}, [], {f: "1" for f in names})["value"]
        self.assertEqual(values["pair_code"], "K7QX-M2PR")
        self.assertTrue(values["has_pair_code"])
        self.assertTrue(values["bridge_enabled"])
        self.assertIn("Acme &lt;b&gt;Corp&lt;/b&gt;", values["pairings_html"], "labels are escaped")
        self.assertNotIn("<b>Corp", values["pairings_html"])

    # -- the pair session ---------------------------------------------------------------
    def test_20_pair_end_to_end(self):
        code, row = self._show_code()
        t, box = self._run_session(row, code)
        self.assertTrue(self.hub.wait_for(lambda: self.hub.pair_opens), "pair session opened")
        opened = self.hub.pair_opens[0]
        self.assertEqual(opened["owner_uid"], self.admin.id)
        self.assertEqual(opened["code_hash"], proto.pair_code_hash(proto.normalize_pair_code(code)))
        self.assertNotIn(code.replace("-", ""), str(opened), "only the hash travels")
        self.assertIsNone(self.hub.claim("K7QX-M2PR"), "a wrong code matches nothing")
        pairing_id, secret = self.hub.claim(code, label="Acme")
        t.join(15)
        self.assertEqual(box.get("outcome"), "paired")
        self.reload()
        # Acked, then held until an Odoo admin approves it.
        self.assertEqual(row.state, "waiting_approval")
        self.assertEqual(row.pairing_id, pairing_id)
        self.assertEqual(row.secret, secret)
        self.assertEqual(row.workspace_label, "Acme")
        self.assertTrue(row.ack_confirmed)
        self.assertFalse(row.pair_attempt)
        self.assertEqual(self.hub.pairings[pairing_id]["state"], "active", "the hub stored it after the ack")
        self.assertIn(row, self.Pairing.search(self.Pairing._streamable_domain()))
        self.assertNotIn(row, self.Pairing.search(self.Pairing._approved_domain()))
        self.Wizard.create({"approval_row_id": row.id}).action_approve()
        self.assertEqual(row.state, "active")
        self.assertIn(row, self.Pairing.search(self.Pairing._approved_domain()))

    def test_25_first_pair_call_names_the_database_and_company(self):
        """STYD's confirm card shows the database and the service user's company."""
        captured = []
        self.patch(pair, "start_pair_thread", lambda *args: captured.append(args))
        code, row = self._show_code()
        self.env.cr.postcommit.run()  # what the commit of the click would run
        self.assertEqual(len(captured), 1)
        info = captured[0][5]
        self.sync()
        store = channel.PairingStore(self.dbname, self.registry)
        outcome = pair.run_pair_session(store, channel.HubClient(self.hub.url, True), row.id,
                                        captured[0][2], self.admin.id, info, life_s=1)
        self.assertEqual(outcome, "expired")
        opened = self.hub.pair_opens[0]
        self.assertEqual(opened["db_name"], self.env.cr.dbname)
        self.assertEqual(opened["company_name"], self.admin.company_id.name)
        self.assertTrue(opened["company_name"])

    def test_21_refused_ack_deletes_the_pairing(self):
        code, row = self._show_code()
        self.hub.force("/bridge/v1/pair", 401, {"t": "error", "code": "bad_signature"},
                       match=lambda b: (b or {}).get("t") == "paired_ack")
        t, box = self._run_session(row, code)
        self.assertTrue(self.hub.wait_for(lambda: self.hub.pair_opens))
        self.hub.claim(code)
        t.join(15)
        self.assertEqual(box.get("outcome"), "failed")
        self.reload()
        self.assertFalse(row.exists())

    def test_22_expired(self):
        code, row = self._show_code()
        self.hub.force("/bridge/v1/pair", 410, {"t": "error", "code": "pair_expired"},
                       match=lambda b: "pair_session" in (b or {}))
        t, box = self._run_session(row, code)
        t.join(15)
        self.assertEqual(box.get("outcome"), "expired")
        self.reload()
        self.assertFalse(row.exists())

    def test_23_cancelled_by_the_admin(self):
        code, row = self._show_code()
        t, box = self._run_session(row, code)
        self.assertTrue(self.hub.wait_for(lambda: self.hub.pair_opens))
        # Cancel from the wizard while the session is held: rows are only touched
        # between holds, through the channel's own cursor lock.
        with self.registry.cursor() as cr:
            api.Environment(cr, SUPERUSER_ID, {})["styd.odoo.bridge.pairing"].browse(row.id).unlink()
        t.join(15)
        self.assertEqual(box.get("outcome"), "cancelled")
        self.assertFalse(any(ps["acked"] for ps in self.hub.pair_sessions.values()))

    def test_24_module_too_old(self):
        code, row = self._show_code()
        self.hub.min_module_version = "99.0.0"
        t, box = self._run_session(row, code)
        t.join(15)
        self.assertEqual(box.get("outcome"), "failed")
        self.reload()
        self.assertEqual(row.status_code, "module_too_old")
        self.assertEqual(row.state, "pending")

    # -- unpair, both ways --------------------------------------------------------------
    def test_30_unpair_from_odoo(self):
        row = self.make_pairing()
        pid = row.pairing_id
        secret = row.secret
        wizard = self.Wizard.create({"pairing_choice": str(row.id)})
        wizard.action_unpair()
        events = [b for p, b in self.hub.events if p == pid]
        self.assertEqual(events, [{"t": "event", "kind": "unpair", "reason": "admin"}])
        self.assertEqual(self.hub.pairings[pid]["state"], "revoked")
        self.assertFalse(self.hub.refused, "the unpair event was signed correctly")
        self.reload()
        self.assertEqual(row.state, "revoked")
        self.assertFalse(row.secret)
        self.assertNotIn(secret, str(row.read()))
        self.Wizard.create({"pairing_choice": str(row.id)}).action_forget()
        self.assertFalse(row.exists())

    def test_31_unpaired_from_styd(self):
        row = self.make_pairing()
        pid = row.pairing_id
        stream = self.make_stream(row)
        stream.poll_once()
        self.hub.send(pid, t="unpaired", op="control.unpaired", member_uid=0, args={"reason": "styd"})
        stream.poll_once()
        self.assertTrue(stream.stop_event.is_set())
        self.reload()
        self.assertEqual(row.state, "revoked")
        self.assertEqual(row.revoked_reason, "styd")
        self.assertFalse(row.secret)

    def test_32_forged_unpaired_is_dropped(self):
        row = self.make_pairing()
        pid = row.pairing_id
        stream = self.make_stream(row)
        stream.poll_once()
        _other, other_secret = self.hub.add_pairing()
        self.hub.send(pid, t="unpaired", op="control.unpaired", member_uid=0, secret=other_secret)
        stream.poll_once()
        self.assertFalse(stream.stop_event.is_set())
        self.reload()
        self.assertEqual(row.state, "active")

    def test_33_not_paired_is_not_an_unpair(self):
        row = self.make_pairing()
        pid = row.pairing_id
        self.hub.pairings[pid]["state"] = "revoked"  # hub store hiccup
        stream = self.make_stream(row)
        stream.poll_once()
        self.reload()
        self.assertEqual(row.state, "active")
        self.assertEqual(row.status_code, "not_paired")

    # -- rotation -------------------------------------------------------------------------
    def _wait_rotation(self, pairing_id):
        return self.hub.wait_for(lambda: any(b.get("kind") == "rotate_ack" for p, b in self.hub.events
                                             if p == pairing_id))

    def test_40_rotation(self):
        row = self.make_pairing()
        pid = row.pairing_id
        old = row.secret
        stream = self.make_stream(row)
        stream.poll_once()
        _rid, fresh = self.hub.rotate(pid)
        stream.poll_once()
        self.assertTrue(self._wait_rotation(pid))
        self.assertTrue(self.hub.wait_for(lambda: stream.current_secret() == fresh))
        self.assertEqual(self.hub.pairings[pid]["secret"], fresh, "the proof was right")
        # the hub signs with the new secret, and the old one still passes within the grace
        new_id = self.hub.send(pid, op="health", member_uid=self.admin.id)
        old_id = self.hub.send(pid, op="health", member_uid=self.admin.id, secret=old)
        self.assertEqual(set(stream.accepted_secrets()), {fresh, old})
        stream.poll_once()  # signed with the new secret now
        self.assertTrue(self.hub.wait_for(lambda: new_id in self.hub.results and old_id in self.hub.results))
        self.assertTrue(self.hub.results[new_id]["ok"], self.hub.results[new_id])
        self.assertTrue(self.hub.results[old_id]["ok"], self.hub.results[old_id])
        self.join_stream(stream)
        stream.runner.executor.shutdown(wait=True)
        self.reload()
        self.assertEqual(row.secret, fresh)
        self.assertEqual(row.previous_secret, old)
        self.assertTrue(row.previous_secret_until)
        self.assertFalse(row.pending_secret)

    def test_41_rotation_refused_keeps_the_old_secret(self):
        row = self.make_pairing()
        pid = row.pairing_id
        old = row.secret
        stream = self.make_stream(row)
        stream.poll_once()
        self.hub.force("/bridge/v1/event", 401, {"t": "error", "code": "bad_signature"},
                       match=lambda b: (b or {}).get("kind") == "rotate_ack")
        self.hub.rotate(pid)
        stream.poll_once()
        self.assertTrue(self._wait_rotation(pid))
        self.assertTrue(self.hub.wait_for(lambda: stream.pairing.get("pending_secret") is None, timeout=10))
        self.assertEqual(stream.current_secret(), old)
        self.join_stream(stream)
        self.reload()
        self.assertEqual(row.secret, old)
        self.assertFalse(row.pending_secret)

    def test_43_lost_ack_answer_promotes_on_first_new_signature(self):
        """The ack's answer was lost: the hub switched, the module did not know.
        The first hub message signed only with the new secret switches the module."""
        row = self.make_pairing()
        pid = row.pairing_id
        old = row.secret
        stream = self.make_stream(row)
        stream.poll_once()
        _rid, fresh = self.hub.rotate(pid)
        # what handle_rotate leaves after a post that got no answer
        with stream._plock:
            stream.pairing["pending_secret"] = fresh
        rec = self.hub.pairings[pid]
        rec["old"], rec["old_until"], rec["secret"], rec["pending"] = old, self.hub.now_ms() + 120_000, fresh, None
        self.hub.sessions[pid]["queue"].clear()
        msg_id = self.hub.send(pid, op="health", member_uid=self.admin.id)
        stream.poll_once()
        self.assertEqual(stream.current_secret(), fresh)
        self.assertTrue(self.hub.wait_for(lambda: msg_id in self.hub.results))
        self.assertTrue(self.hub.results[msg_id]["ok"])
        stream.runner.executor.shutdown(wait=True)
        self.reload()
        self.assertEqual((row.secret, row.previous_secret), (fresh, old))

    def test_42_rotate_request_from_odoo(self):
        row = self.make_pairing()
        pid = row.pairing_id
        self.Wizard.create({"pairing_choice": str(row.id)}).action_rotate()
        self.assertIn({"t": "event", "kind": "rotate_request"},
                      [b for p, b in self.hub.events if p == pid])

    # -- several pairings, settings ----------------------------------------------------------
    def test_50_several_pairings(self):
        first = self.make_pairing(label="Workspace A")
        first_pid = first.pairing_id
        second = self.make_pairing(label="Workspace B")
        second_pid = second.pairing_id
        runner = self.make_runner()
        self.sync()
        self.assertTrue(runner.tick())
        self.assertEqual(set(runner.streams), {first_pid, second_pid})
        self.assertTrue(self.hub.wait_for(
            lambda: {p for p, _h in self.hub.hellos} == {first_pid, second_pid}))
        for stream in list(runner.streams.values()):
            self.join_stream(stream)

    def test_51_ca_bundle_setting(self):
        Settings = self.env["res.config.settings"]
        with self.assertRaises(UserError):
            Settings.create({"styd_bridge_channel_ca_bundle": "/nonexistent/ca.pem"}).execute()
        Settings.create({"styd_bridge_channel_ca_bundle": "", "styd_bridge_channel_restrict_group": True}).execute()
        self.assertEqual(self.icp.get_param("styd_odoo_bridge.channel_restrict_to_group"), "True")
        self.assertFalse(self.icp.get_param(channel.ICP_CA_BUNDLE))
