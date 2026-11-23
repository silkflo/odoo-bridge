"""M2: the executor (member rule, no sudo, read-only cursor, route bodies, limits, audit)."""

import threading
import uuid

import psycopg2

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.styd_odoo_bridge.models import bridge_channel_executor as ex
from odoo.addons.styd_odoo_bridge.models import bridge_channel_protocol as proto

from .channel_common import ChannelCase


@tagged("post_install", "-at_install")
class TestChannelExecutor(ChannelCase):
    def setUp(self):
        super().setUp()
        Users = self.env["res.users"].with_context(no_reset_password=True)
        group_user = self.env.ref("base.group_user")
        self.member = Users.create({
            "name": "STYD member", "login": "styd_member_test", "email": "member@example.com",
            "groups_id": [Command.set([group_user.id])],
        })
        self.portal = Users.create({
            "name": "STYD portal", "login": "styd_portal_test",
            "groups_id": [Command.set([self.env.ref("base.group_portal").id])],
        })
        self.inactive = Users.create({
            "name": "STYD inactive", "login": "styd_inactive_test",
            "groups_id": [Command.set([group_user.id])],
        })
        self.inactive.active = False
        self.pairing = {"pairing_id": "bp_" + "E" * 22, "owner_uid": self.admin.id}

    def run_op(self, op, args=None, member=None, member_uid=None, timeout_ms=None):
        self.sync()
        fields = {
            "v": 1, "id": str(uuid.uuid4()), "ts": 0, "op": op,
            "member_uid": member_uid if member_uid is not None else (member or self.member).id,
            "pairing_id": self.pairing["pairing_id"], "args_json": "{}",
        }
        out = ex.execute_request(self.dbname, self.pairing, fields, args or {}, timeout_ms=timeout_ms,
                                 registry=self.registry)
        self.reload()
        self.assertEqual(out["id"], fields["id"])
        self.assertEqual(out["t"], "result")
        return out

    def assertRefused(self, out, code):
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["error"]["code"], code)

    # -- who may be asked as -------------------------------------------------------
    def test_01_member_rule(self):
        self.assertTrue(self.run_op("health")["ok"])
        self.assertTrue(self.run_op("orm.models", member=self.admin)["ok"], "admins may be asked as by default")
        self.assertRefused(self.run_op("health", member_uid=0), "member_missing")
        self.assertRefused(self.run_op("health", member_uid=1), "member_not_allowed")
        self.assertRefused(self.run_op("health", member=self.portal), "member_not_allowed")
        self.assertRefused(self.run_op("health", member=self.inactive), "member_not_allowed")
        self.assertRefused(self.run_op("health", member_uid=987654321), "member_not_allowed")

    def test_02_optional_group_restriction(self):
        self.icp.set_param(ex.ICP_RESTRICT_GROUP, "True")
        self.assertRefused(self.run_op("orm.models"), "member_not_allowed")
        self.member.groups_id = [Command.link(self.env.ref("styd_odoo_bridge.group_styd_member").id)]
        self.assertTrue(self.run_op("orm.models")["ok"])
        self.icp.set_param(ex.ICP_RESTRICT_GROUP, "False")
        self.assertTrue(self.run_op("orm.models", member=self.admin)["ok"])

    def test_03_owner_only_ops(self):
        for op in proto.OWNER_ONLY_OPS:
            self.assertRefused(self.run_op(op, args={"q": "x"}), "member_not_allowed")
        out = self.run_op("users.directory", member=self.admin)
        self.assertEqual(out["status"], 200)
        logins = {u["login"] for u in out["body"]["users"]}
        self.assertIn("styd_member_test", logins)
        out = self.run_op("users.search", args={"q": "styd_member"}, member=self.admin)
        self.assertEqual(out["body"]["count"], 1)
        self.assertEqual(out["body"]["query"], "styd_member")
        out = self.run_op("security.snapshot", member=self.admin)
        self.assertEqual(out["body"]["connector_owner"]["odoo_user_id"], self.admin.id,
                         "the pairing's owner is the connector owner")
        self.assertEqual(self.run_op("capabilities", member=self.admin)["status"], 200)

    def test_04_disabled_and_unknown_op(self):
        self.assertRefused(self.run_op("orm.write", args={"model": "res.partner"}), "op_not_allowed")
        self.icp.set_param("styd_odoo_bridge.enabled", "False")
        self.assertRefused(self.run_op("health"), "bridge_disabled")

    # -- route-identical bodies, member rights -------------------------------------------
    def test_10_bodies_match_the_routes(self):
        orm = self.env["styd.odoo.bridge.orm"].sudo()
        out = self.run_op("orm.models", member=self.admin)
        self.assertEqual(out["body"]["access_mode"], "member_rights")
        self.assertEqual([m["model"] for m in out["body"]["models"]], [m["model"] for m in orm.orm_list_models()])
        out = self.run_op("orm.fields", args={"model": "res.partner"})
        self.assertEqual(set(out["body"]), {"ok", "access_mode", "model", "fields"})
        self.assertEqual(out["body"]["model"], "res.partner")
        self.assertTrue(any(f["name"] == "name" for f in out["body"]["fields"]))
        self.env["res.partner"].create({"name": "STYD channel partner"})
        args = {"model": "res.partner", "domain": [["name", "=", "STYD channel partner"]], "fields": ["name"]}
        out = self.run_op("orm.search_read", args=args)
        self.assertEqual(out["status"], 200)
        route_like = {"ok": True, "access_mode": "member_rights", "model": "res.partner"}
        route_like.update(orm.orm_search_read(model="res.partner", domain=args["domain"], fields=["name"]))
        self.assertEqual(out["body"], route_like)
        out = self.run_op("orm.read_group", args={"model": "res.partner", "group_by": ["is_company"],
                                                  "domain": [["name", "=", "STYD channel partner"]]})
        self.assertEqual(out["status"], 200)
        self.assertEqual(out["body"]["access_mode"], "member_rights")
        self.assertEqual(out["body"]["group_by"], ["is_company"])
        self.assertEqual(sum(g["count"] for g in out["body"]["groups"]), 1)

    def test_11_route_refusals_are_ok_results(self):
        out = self.run_op("orm.search_read", args={"model": "ir.config_parameter"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], 400)
        self.assertEqual(out["body"]["error"], "model_not_allowed")
        self.assertEqual(set(out["body"]), {"ok", "error", "detail"})
        out = self.run_op("orm.fields", args={"model": ["res.partner"]})
        self.assertEqual((out["status"], out["body"]["error"]), (400, "model_not_allowed"))
        out = self.run_op("orm.search_read", args={"model": "res.partner", "fields": ["signup_token"]})
        self.assertEqual((out["status"], out["body"]["error"]), (400, "field_not_allowed"))
        out = self.run_op("orm.search_read", args={"model": "res.partner", "limit": 999})
        self.assertEqual((out["status"], out["body"]["error"]), (400, "limit_exceeded"))

    def test_12_access_denied_is_403(self):
        Partner = type(self.env["res.partner"])
        member_id = self.member.id
        original = Partner.check_access_rights

        def deny(model, operation, raise_exception=True):
            if model.env.uid == member_id:
                if raise_exception:
                    raise AccessError("no")
                return False
            return original(model, operation, raise_exception=raise_exception)

        self.patch(Partner, "check_access_rights", deny)
        out = self.run_op("orm.search_read", args={"model": "res.partner"})
        self.assertEqual(out["status"], 403)
        self.assertEqual(out["body"], {"ok": False, "error": "access_denied", "detail": ex.ACCESS_DENIED_DETAIL})
        out = self.run_op("orm.models")
        partner = [m for m in out["body"]["models"] if m["model"] == "res.partner"][0]
        self.assertFalse(partner["allowed"], "models lists what this member may read")

    def test_13_record_rules_apply_no_sudo(self):
        """The member's own record rules filter the read; the route (sudo) sees all."""
        group = self.env["res.groups"].create({"name": "STYD rule test"})
        self.member.groups_id = [Command.link(group.id)]
        self.env["ir.rule"].create({
            "name": "STYD test: only visible partners",
            "model_id": self.env.ref("base.model_res_partner").id,
            "groups": [Command.set([group.id])],
            "domain_force": "[('name', '=', 'STYD rule visible')]",
        })
        Partner = self.env["res.partner"]
        Partner.create([{"name": "STYD rule visible"}, {"name": "STYD rule hidden"}])
        args = {"model": "res.partner", "domain": [["name", "ilike", "STYD rule "]], "fields": ["name"]}
        member_names = {r["name"] for r in self.run_op("orm.search_read", args=args)["body"]["records"]}
        admin_names = {r["name"] for r in self.run_op("orm.search_read", args=args, member=self.admin)["body"]["records"]}
        route_names = {r["name"] for r in self.env["styd.odoo.bridge.orm"].sudo().orm_search_read(
            model="res.partner", domain=args["domain"], fields=["name"])["records"]}
        self.assertEqual(member_names, {"STYD rule visible"})
        self.assertEqual(admin_names, {"STYD rule visible", "STYD rule hidden"})
        self.assertEqual(route_names, admin_names)

    def test_14_member_context(self):
        company2 = self.env["res.company"].create({"name": "STYD second company"})
        self.member.write({"company_ids": [Command.link(company2.id)], "tz": "Europe/Paris", "lang": "en_US"})
        ctx = ex.member_context(self.member, self.admin.id)
        self.assertEqual(ctx["allowed_company_ids"][0], self.member.company_id.id)
        self.assertEqual(set(ctx["allowed_company_ids"]), set(self.member.company_ids.ids))
        self.assertEqual(ctx["tz"], "Europe/Paris")
        self.assertTrue(ctx["styd_bridge_member_rights"])

    # -- the read-only cursor ---------------------------------------------------------
    def test_20_readonly_cursor(self):
        self.sync()
        with ex.readonly_cursor(self.registry, 1500) as cr:
            cr.execute("SHOW transaction_read_only")
            self.assertEqual(cr.fetchone()[0], "on")
            cr.execute("SHOW statement_timeout")
            self.assertEqual(cr.fetchone()[0], "1500ms")
            with self.assertRaises(psycopg2.Error) as ctx:
                cr.execute("UPDATE res_partner SET name = name WHERE id = -1", log_exceptions=False)
            self.assertEqual(ctx.exception.pgcode, "25006")  # read_only_sql_transaction
        # the test's own transaction is writable again
        self.env.cr.execute("SHOW transaction_read_only")
        self.assertEqual(self.env.cr.fetchone()[0], "off")
        self.env["res.partner"].create({"name": "still writable"})
        self.env.flush_all()

    def test_21_statement_timeout_cancels(self):
        self.sync()
        with ex.readonly_cursor(self.registry, 1000) as cr:
            with self.assertRaises(psycopg2.Error) as ctx:
                cr.execute("SELECT pg_sleep(3)", log_exceptions=False)
            self.assertEqual(ctx.exception.pgcode, "57014")  # query_canceled

    # -- limits -------------------------------------------------------------------------------
    def test_30_token_bucket(self):
        now = [100.0]
        bucket = ex.TokenBucket(rate=10, burst=2, clock=lambda: now[0])
        self.assertTrue(bucket.take())
        self.assertTrue(bucket.take())
        self.assertFalse(bucket.take())
        now[0] += 0.15  # 1.5 tokens back at 10 per second
        self.assertTrue(bucket.take())
        self.assertFalse(bucket.take())

    def test_31_queue_full_is_busy(self):
        pool = ex.ChannelExecutor(self.dbname, workers=1, queue_size=1, rate=100, burst=100)
        self.addCleanup(pool.shutdown, True)
        gate = threading.Event()
        self.assertTrue(pool.try_submit(gate.wait, 5))
        self.assertTrue(pool.try_submit(gate.wait, 5))
        self.assertFalse(pool.try_submit(gate.wait, 5), "queue full: busy")
        gate.set()
        pool.shutdown(True)
        self.assertEqual(pool.inflight, 0)

    def test_32_default_limits(self):
        pool = ex.ChannelExecutor(self.dbname)
        self.addCleanup(pool.shutdown, True)
        self.assertEqual(pool.capacity, 4 + 16)
        self.assertEqual((pool.bucket.rate, pool.bucket.burst), (10.0, 20.0))

    # -- audit ---------------------------------------------------------------------------------
    def test_40_audit_rows(self):
        Log = self.env["styd.odoo.bridge.access.log"].sudo()
        before = Log.search_count([])
        self.run_op("orm.search_read", args={"model": "res.partner", "domain": [["name", "=", "secret value"]]})
        self.run_op("health", member_uid=1)
        rows = Log.search([], order="id desc", limit=Log.search_count([]) - before)
        self.assertEqual(len(rows), 2)
        refused, granted = rows[0], rows[1]
        self.assertEqual(granted.endpoint, "channel:orm.search_read")
        self.assertEqual((granted.method, granted.outcome, granted.reason_code), ("CHANNEL", "granted", "ok"))
        self.assertEqual(granted.member_uid, self.member.id)
        self.assertEqual(granted.pairing_ref, self.pairing["pairing_id"])
        self.assertEqual(granted.detail, "model=res.partner")
        self.assertNotIn("secret value", str(granted.read()))
        self.assertEqual((refused.endpoint, refused.outcome, refused.reason_code),
                         ("channel:health", "denied", "member_not_allowed"))

    def test_41_seen_table(self):
        Seen = self.env["styd.odoo.bridge.channel.seen"]
        cr = self.env.cr
        self.assertTrue(Seen._record_raw(cr, "id-1", 1_000_000))
        self.assertFalse(Seen._record_raw(cr, "id-1", 1_000_500), "a second leader sees the replay")
        self.assertTrue(Seen._record_raw(cr, "id-2", 1_200_000))
        Seen._gc_raw(cr, 1_000_000 + proto.REPLAY_TTL_MS + 1)
        cr.execute("SELECT request_id FROM styd_odoo_bridge_channel_seen WHERE request_id IN ('id-1', 'id-2')")
        self.assertEqual([r[0] for r in cr.fetchall()], ["id-2"])
