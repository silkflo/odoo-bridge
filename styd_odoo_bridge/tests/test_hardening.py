"""Hardening of 0.11.0: the pairing is bound to its database and approved by an
Odoo administrator; timesheet lines follow the HR rules; channel answers only
reach internal users; bot answers carry no link; only the module posts as the
bot; fixed error messages; member rights and the owner as explicit arguments;
one free bot line per user per minute; the Discuss pairing list for admins only.
See docs/B2_HARDENING.md."""

import inspect
import json
import os
import threading
import uuid

from markupsafe import Markup

from odoo import Command, release
from odoo.exceptions import AccessError, UserError
from odoo.modules.module import get_module_path
from odoo.tests import tagged

from odoo.addons.styd_odoo_bridge.models import bridge_channel as channel
from odoo.addons.styd_odoo_bridge.models import bridge_channel_executor as ex
from odoo.addons.styd_odoo_bridge.models import bridge_channel_pair as pair
from odoo.addons.styd_odoo_bridge.models import bridge_channel_protocol as proto
from odoo.addons.styd_odoo_bridge.models import bridge_discuss as discuss
from odoo.addons.styd_odoo_bridge.models import bridge_discuss_text as text_mod
from odoo.addons.styd_odoo_bridge.models import bridge_orm as orm_mod
from odoo.addons.styd_odoo_bridge.models.bridge_orm import ORM_HR_COMPANY_SCOPE, ORM_HR_FIELDS, StydOrmError

from .channel_common import GROUPS, ChannelCase
from .test_discuss import CHANNEL, DiscussCase

MAJOR = int(release.version_info[0])
MODULE = "styd_odoo_bridge"
TIMESHEET = "account.analytic.line"


def _db_values(env):
    env.cr.execute(
        "SELECT key, value FROM ir_config_parameter WHERE key IN ('database.uuid', 'database.create_date')")
    raw = dict(env.cr.fetchall())
    return raw.get("database.uuid") or "", raw.get("database.create_date") or ""


def _users(env):
    return env["res.users"].with_context(no_reset_password=True)


class HardeningCase(ChannelCase):
    def setUp(self):
        super().setUp()
        self.Pairing = self.env["styd.odoo.bridge.pairing"].sudo()
        self.Wizard = self.env["styd.odoo.bridge.channel.wizard"].with_user(self.admin)
        self.plain = _users(self.env).create({
            "name": "STYD hardening plain", "login": "styd_hardening_plain",
            GROUPS: [Command.set([self.env.ref("base.group_user").id])],
        })

    def bound_pairing(self, state="active", **values):
        """A pairing of THIS database (what the pair flow records), in ``state``."""
        row = self.make_pairing()
        db_uuid, db_create = _db_values(self.env)
        row.write(dict({"state": state, "db_uuid": db_uuid, "db_create_date": db_create}, **values))
        return row

    def run_request(self, row, op="health", args=None, member=None):
        self.sync()
        fields = {"v": 1, "id": str(uuid.uuid4()), "ts": 0, "op": op, "member_uid": (member or self.admin).id,
                  "pairing_id": row.pairing_id, "args_json": "{}"}
        out = ex.execute_request(self.dbname, {"pairing_id": row.pairing_id, "owner_uid": self.admin.id},
                                 fields, args or {}, registry=self.registry)
        self.reload()
        return out

    def show_code(self):
        action = self.Wizard.create({}).action_show_code()
        code = action["context"]["styd_pair_code"]
        return code, self.Pairing.search([("state", "=", "pending")])

    def run_session(self, row, code, life_s=20):
        self.sync()
        store = channel.PairingStore(self.dbname, self.registry)
        hub = channel.HubClient(self.hub.url, True)
        info = {"module_version": "0.11.0", "odoo_series": "%s.0" % MAJOR, "db_uuid": "test-db",
                "db_name": self.dbname, "company_name": self.admin.company_id.name}
        box = {}
        code_hash = proto.pair_code_hash(proto.normalize_pair_code(code))

        def target():
            box["outcome"] = pair.run_pair_session(store, hub, row.id, code_hash, self.admin.id, info, life_s=life_s)

        t = threading.Thread(target=target, daemon=True)
        t.start()
        self.addCleanup(t.join, 10)
        return t, box

    def claim(self, code, **paired_extra):
        """STYD side: the code is typed; the ``paired`` message carries ``paired_extra``."""
        with self.hub.cond:
            claimed = self.hub.claim(code, label=paired_extra.pop("workspace_label", "Acme"))
            for ps in self.hub.pair_sessions.values():
                if ps.get("paired") and ps["paired"].get("pairing_id") == (claimed or (None,))[0]:
                    ps["paired"].update(paired_extra)
        return claimed


# ---------------------------------------------------------------------------
# the pairing is bound to its database
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestPairingBoundToDatabase(HardeningCase):
    def test_h01_code_records_this_database(self):
        _code, row = self.show_code()
        self.assertEqual((row.db_uuid, row.db_create_date), _db_values(self.env))
        self.assertTrue(row.db_uuid and row.db_create_date)

    def test_h02_copy_never_streams(self):
        row = self.bound_pairing()
        pid = row.pairing_id  # read before the channel's threads start (Odoo 20)
        runner = self.make_runner()
        self.sync()
        self.assertTrue(runner.tick())
        self.assertIn(pid, runner.streams)
        for stream in list(runner.streams.values()):
            self.join_stream(stream)
        runner.streams = {}
        # What Odoo does to a duplicated database: a new uuid.
        self.icp.set_param("database.uuid", str(uuid.uuid4()))
        self.sync()
        self.assertFalse(runner.tick(), "nothing to stream in the copy")
        self.assertFalse(runner.streams)
        self.reload()
        self.assertEqual(row.status_code, "database_copied")
        self.assertFalse(self.Pairing.search(self.Pairing._streamable_domain()))
        html = str(self.Wizard.create({}).pairings_html)
        self.assertIn("copy", html)

    def test_h03_other_creation_date_never_streams(self):
        row = self.bound_pairing()
        row.write({"db_create_date": "2001-01-01 00:00:00"})
        self.assertNotIn(row, self.Pairing.search(self.Pairing._streamable_domain()))
        out = self.run_request(row)
        self.assertFalse(out["ok"])

    def test_h04_neutralize_revokes_every_pairing(self):
        if MAJOR < 16:
            self.skipTest("neutralization exists since Odoo 16 (the database check covers 15)")
        path = os.path.join(get_module_path(MODULE), "data", "neutralize.sql")
        self.assertTrue(os.path.isfile(path))
        active = self.bound_pairing()
        waiting = self.bound_pairing(state="waiting_approval")
        self.sync()
        with open(path, encoding="utf-8") as fh:
            self.env.cr.execute(fh.read())
        self.reload()
        for row in (active, waiting):
            self.assertEqual(row.state, "revoked")
            self.assertFalse(row.secret or row.pending_secret or row.previous_secret)


# ---------------------------------------------------------------------------
# pairing approval
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestPairingApproval(HardeningCase):
    def test_m01_paired_waits_for_an_admin(self):
        self.Pairing.search([]).unlink()
        code, row = self.show_code()
        t, box = self.run_session(row, code)
        self.assertTrue(self.hub.wait_for(lambda: self.hub.pair_opens))
        long_name = "Acme Production " + "x" * 100
        self.claim(code, workspace_name=long_name, workspace_id="ws_42", claimant_email_domain="Acme.example")
        t.join(15)
        self.assertEqual(box.get("outcome"), "paired")
        self.reload()
        self.assertEqual(row.state, "waiting_approval")
        self.assertEqual(row.workspace_label, long_name[:80])
        self.assertEqual(row.workspace_ref, "ws_42")
        self.assertEqual(row.claimant_email_domain, "acme.example")
        self.assertTrue(self.hub.pairings[row.pairing_id], "the ack went out as before")
        self.assertNotIn(row, self.Pairing.search(self.Pairing._approved_domain()))
        # Every Settings administrator is told, in their chat with the assistant.
        bot = self.env.ref(discuss.BOT_XMLID)
        msgs = self.env["mail.message"].sudo().search([("author_id", "=", bot.id), ("model", "=", CHANNEL)])
        self.assertTrue(any("ws_42" in str(m.body) and "acme.example" in str(m.body) for m in msgs))
        chat = self.env["styd.discuss.question"].sudo()._bot_chat(self.admin)
        self.assertIn(self.admin.partner_id, discuss.member_partners(chat))

    def test_m02_requests_refused_until_approved(self):
        row = self.bound_pairing(state="waiting_approval")
        out = self.run_request(row)
        self.assertEqual((out["ok"], out["error"]["code"]), (False, "pairing_not_approved"))
        out = self.run_request(row, op="orm.search_read", args={"model": "res.partner", "fields": ["name"]})
        self.assertEqual(out["error"]["code"], "pairing_not_approved")
        self.assertIn(row, self.Pairing.search(self.Pairing._streamable_domain()), "it streams to answer so")
        wizard = self.Wizard.create({})
        self.assertEqual(wizard.approval_row_id, row.id)
        wizard.action_approve()
        self.reload()
        self.assertEqual(row.state, "active")
        self.assertTrue(row.approved_at)
        self.assertTrue(self.run_request(row)["ok"])

    def test_m03_no_discuss_until_approved(self):
        self.icp.set_param(discuss.ICP_DISCUSS_ENABLED, "True")
        self.Pairing.search([]).unlink()
        row = self.bound_pairing(state="waiting_approval")
        Question = self.env["styd.discuss.question"].sudo()
        self.assertFalse(Question._resolve_pairing(Question._settings()))
        row.state = "active"
        self.assertEqual(Question._resolve_pairing(Question._settings()), row)

    def test_m04_refuse_unpairs(self):
        row = self.bound_pairing(state="waiting_approval")
        pid = row.pairing_id
        self.Wizard.create({"approval_row_id": row.id}).action_refuse()
        self.reload()
        self.assertEqual(row.state, "revoked")
        self.assertFalse(row.secret)
        self.assertIn({"t": "event", "kind": "unpair", "reason": "admin"}, [b for p, b in self.hub.events if p == pid])

    def test_m05_only_admins_approve(self):
        row = self.bound_pairing(state="waiting_approval")
        wizard = self.Wizard.create({})
        with self.assertRaises(AccessError):
            wizard.with_user(self.plain).action_approve()
        with self.assertRaises(AccessError):
            wizard.with_user(self.plain).action_refuse()
        self.assertEqual(row.state, "waiting_approval")
        # Approve acts on the pairing the form showed, never on a newer one.
        newer = self.bound_pairing(state="waiting_approval")
        wizard.action_approve()
        self.reload()
        self.assertEqual((row.state, newer.state), ("active", "waiting_approval"))
        with self.assertRaises(UserError):
            self.Wizard.create({"approval_row_id": row.id}).action_approve()

    def test_m06_wizard_shows_the_waiting_pairing(self):
        self.bound_pairing(state="waiting_approval", workspace_label="Acme <b>Prod</b>", workspace_ref="ws_7",
                           claimant_email_domain="acme.example")
        values = self.Wizard.default_get(["approval_row_id", "approval_html", "has_approval", "pairings_html"])
        self.assertTrue(values["has_approval"])
        html = str(values["approval_html"])
        self.assertIn("Acme &lt;b&gt;Prod&lt;/b&gt;", html)
        self.assertIn("ws_7", html)
        self.assertIn("acme.example", html)
        arch = self.env.ref("styd_odoo_bridge.view_styd_bridge_channel_wizard_form").arch
        self.assertIn("action_approve", arch)
        self.assertIn("action_refuse", arch)
        self.assertIn("Never share this code", arch)


# ---------------------------------------------------------------------------
# timesheet lines follow the HR rules
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestHrListParity(HardeningCase):
    def test_t01_same_hr_list_as_styd(self):
        """The module's HR list against STYD's, loaded from the fixture file."""
        path = os.path.join(get_module_path(MODULE), "tests", "data", "styd_hr_read_policy.json")
        with open(path, encoding="utf-8") as fh:
            styd = json.load(fh)
        ours = {model: set(fields) for model, fields in ORM_HR_FIELDS.items()}
        ours[TIMESHEET] = set(getattr(orm_mod, "ORM_TIMESHEET_FIELDS", ()))
        self.assertEqual(set(ours), set(styd["fields"]))
        for model, fields in styd["fields"].items():
            self.assertEqual(ours[model], set(fields), model)
        scopes = dict(ORM_HR_COMPANY_SCOPE)
        scopes[TIMESHEET] = getattr(orm_mod, "ORM_TIMESHEET_COMPANY_SCOPE", None)
        for model, scope in styd["company_scope"].items():
            ours_scope = scopes.get(model, "missing")
            if scope["kind"] == "configuration":
                self.assertIsNone(ours_scope, model)
            elif scope["kind"] == "company":
                self.assertEqual(ours_scope, (scope["field"], scope["allowEmpty"]), model)
            elif scope["field"] is None:
                self.assertEqual(ours_scope, "employees", model)
            else:
                self.assertEqual(ours_scope, ("employees", scope["field"]), model)


@tagged("post_install", "-at_install")
class TestTimesheetsAreHr(HardeningCase):
    def setUp(self):
        super().setUp()
        if TIMESHEET not in self.env:
            self.skipTest("account is not installed")
        self.orm = self.env["styd.odoo.bridge.orm"]
        self.journal = self.orm._orm_journal_item_field(TIMESHEET)

    def test_t02_http_routes_refuse_timesheet_reads(self):
        sudo_orm = self.orm.sudo()
        for kw in ({"fields": ["unit_amount", "name"]}, {"fields": ["name"], "domain": [["unit_amount", ">", 0]]},
                   {"fields": ["name"], "domain": ["|", [self.journal, "!=", False], ["id", ">", 0]]}):
            with self.assertRaises(StydOrmError) as ctx:
                sudo_orm._orm_search_read(TIMESHEET, **kw)
            self.assertEqual(ctx.exception.code, "model_not_allowed", kw)
        with self.assertRaises(StydOrmError) as ctx:
            sudo_orm._orm_read_group(TIMESHEET, group_by=["employee_id" if "employee_id" in self.env[TIMESHEET]._fields
                                                          else "date"], aggregates=["unit_amount:sum"])
        self.assertEqual(ctx.exception.code, "model_not_allowed")
        # Journal-item lines (the ledger reader) stay open.
        self.assertIn("records", sudo_orm._orm_search_read(TIMESHEET, fields=["amount", "date"],
                                                           domain=[[self.journal, "!=", False]]))

    def _timesheet_setup(self):
        if "employee_id" not in self.env[TIMESHEET]._fields or "hr.employee.public" not in self.env:
            self.skipTest("hr_timesheet is not installed")
        account = {"name": "STYD hardening cost centre"}
        if "account.analytic.plan" in self.env:
            account["plan_id"] = self.env["account.analytic.plan"].create({"name": "STYD hardening plan"}).id
        self.account = self.env["account.analytic.account"].create(account)
        self.other_company = self.env["res.company"].create({"name": "STYD hardening other company"})
        Employee = self.env["hr.employee"].sudo()
        self.emp_here = Employee.create({"name": "STYD here", "company_id": self.admin.company_id.id})
        self.emp_away = Employee.create({"name": "STYD away", "company_id": self.other_company.id})
        Line = self.env[TIMESHEET].sudo()
        for name, emp in (("STYD ts here", self.emp_here), ("STYD ts away", self.emp_away)):
            Line.create({"name": name, "unit_amount": 3, "amount": -90, "account_id": self.account.id,
                         "employee_id": emp.id, "company_id": self.admin.company_id.id})

    def test_t03_channel_limits_fields_and_scope(self):
        self._timesheet_setup()
        row = self.bound_pairing()
        args = {"model": TIMESHEET, "fields": ["name", "unit_amount", "employee_id"],
                "domain": [["name", "like", "STYD ts "]]}
        out = self.run_request(row, op="orm.search_read", args=args)
        self.assertEqual(out["status"], 200, out)
        names = {r["name"] for r in out["body"]["records"]}
        self.assertEqual(names, {"STYD ts here"}, "only employees of the read's companies")
        for fields_ in (["name", "account_id"], ["name", "amount"], None):
            out = self.run_request(row, op="orm.search_read", args=dict(args, fields=fields_))
            self.assertEqual((out["status"], out["body"]["error"]), (400, "field_not_allowed"), fields_)
        out = self.run_request(row, op="orm.read_group", args={"model": TIMESHEET, "group_by": ["account_id"],
                                                               "aggregates": ["unit_amount:sum"]})
        self.assertEqual(out["body"]["error"], "field_not_allowed")
        out = self.run_request(row, op="orm.read_group", args={"model": TIMESHEET, "group_by": ["employee_id"],
                                                               "aggregates": ["unit_amount:sum"]})
        self.assertEqual(out["status"], 200, out)

    def test_t04_refused_in_shared_conversations(self):
        self.icp.set_param(discuss.ICP_DISCUSS_ENABLED, "True")
        row = self.bound_pairing()
        room = self.env[CHANNEL].sudo().create({"name": "STYD hardening room", "channel_type": "channel"})
        q = self.env["styd.discuss.question"].sudo().create({
            "question_id": proto.new_question_id(), "user_id": self.admin.id, "channel_id": room.id,
            "state": "sent", "shared": True, "pairing_ref": row.pairing_id})
        args = {"model": TIMESHEET, "fields": ["name"], "discuss_question_id": q.question_id}
        out = self.run_request(row, op="orm.search_read", args=args)
        self.assertEqual((out["status"], out["body"]["error"]), (400, "model_not_allowed"))
        journal = dict(args, fields=["amount"], domain=[[self.journal, "!=", False]])
        self.assertEqual(self.run_request(row, op="orm.search_read", args=journal)["status"], 200)


# ---------------------------------------------------------------------------
# settings: the admin guard holds when another group has ACL rights
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestSettingsGuard(HardeningCase):
    def test_s01_acl_rights_do_not_open_the_settings(self):
        group = self.env["res.groups"].create({"name": "STYD hardening settings editors"})
        Access = self.env["ir.access" if "ir.access" in self.env else "ir.model.access"].sudo()
        model = self.env["ir.model"]._get("res.config.settings")
        if Access._name == "ir.access":  # Odoo 20
            Access.create({"name": "styd hardening settings", "model_id": model.id, "group_id": group.id,
                           "operation": "crud"})
        else:
            Access.create({"name": "styd hardening settings", "model_id": model.id, "group_id": group.id,
                           "perm_read": True, "perm_write": True, "perm_create": True, "perm_unlink": True})
        self.plain.write({GROUPS: [Command.link(group.id)]})
        Settings = self.env["res.config.settings"].with_user(self.plain)
        with self.assertRaises(AccessError):
            Settings.browse().get_values()
        with self.assertRaises(AccessError):
            Settings.browse().set_values()
        self.assertEqual(self.icp.get_param("styd_odoo_bridge.enabled"), "True")


# ---------------------------------------------------------------------------
# Discuss: channel answers, links, posting as the bot, free lines
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestDiscussHardening(DiscussCase):
    def join(self, room, partners):
        if hasattr(room, "add_members"):
            kwargs = {"post_joined_message": False} if "post_joined_message" in                 inspect.signature(room.add_members).parameters else {}  # not on 15
            room.add_members(partner_ids=partners.ids, **kwargs)
        else:  # Odoo 20
            room._add_members(partners=partners, post_joined_message=False)

    def room_with(self, *partners):
        Channel = self.env[CHANNEL].sudo()
        values = {"name": "STYD hardening room", "channel_type": "channel"}
        # Open to anyone invited, as an admin can set it: "private" on Odoo 15 (its
        # "public" field), no group restriction since 16.
        if "public" in Channel._fields:
            values["public"] = "private"
        elif "group_public_id" in Channel._fields:
            values["group_public_id"] = False
        room = Channel.create(values)
        self.join(room, self.asker.partner_id.browse([p.id for p in partners] + [self.asker.partner_id.id]))
        return room

    def test_d01_answer_in_channel_rechecks_members_when_posting(self):
        self.icp.set_param(discuss.ICP_ANSWER_IN_CHANNEL, "True")
        room = self.room_with(self.outsider.partner_id)
        self.ask(self.asker, room, "Marge par client ?", mention=True)
        q = self.Question.search([])
        self.assertEqual(q.channel_id, room)
        self.run_job()
        # A portal user joins while STYD answers.
        portal = _users(self.env).create({"name": "STYD hardening portal", "login": "styd_hardening_portal",
                                          GROUPS: [Command.set([self.env.ref("base.group_portal").id])]})
        self.join(room, portal.partner_id)
        self.assertEqual(self.deliver(q), "ok")
        self.run_job()
        self.assertFalse(any("12 400" in b for b in self.bot_bodies(room)), "never in a room with a portal user")
        chat = self.Question._bot_chat(self.asker)
        self.assertIn("12 400", self.bot_bodies(chat)[-1])
        self.assertIn(text_mod.say("answered_in_dm", "fr_FR"), " ".join(self.bot_texts(room)))
        help_text = self.env["res.config.settings"]._fields["styd_discuss_answer_in_channel"].help
        self.assertIn("visible to everyone in the channel", help_text)

    def test_d02_contact_without_user_counts_as_external(self):
        self.icp.set_param(discuss.ICP_ANSWER_IN_CHANNEL, "True")
        contact = self.env["res.partner"].create({"name": "STYD hardening customer"})
        room = self.room_with(self.outsider.partner_id)
        self.assertFalse(self.Question._has_external_members(room))
        self.join(room, contact)
        self.assertTrue(self.Question._has_external_members(room))

    def test_d03_answers_carry_no_link(self):
        answer = text_mod.validate_answer({
            "question_id": proto.new_question_id(), "status": "answered", "lang": "en_US",
            "text": "Log in at https://evil.example/login or www.evil.example now.",
            "tables": [{"columns": ["Site"], "rows": [["http://shop.example/cart"]]}],
        })
        html = str(text_mod.render_answer(answer, "en_US"))
        for bad in ("https://", "http://", "www.evil.example", "evil.example/login", "<a"):
            self.assertNotIn(bad, html)
        self.assertIn("evil[.]example/login", html)
        self.assertIn("shop[.]example/cart", html)

    def test_d04_only_the_module_posts_as_the_bot(self):
        chat = self.dm(self.asker)
        for ctx in ({}, {discuss.BOT_POST_CTX if hasattr(discuss, "BOT_POST_CTX") else "x": True}):
            with self.assertRaises(AccessError):
                chat.with_user(self.asker).with_context(**ctx).message_post(
                    body=Markup("<p>fake answer</p>"), author_id=self.bot.id, message_type="comment",
                    subtype_xmlid="mail.mt_comment")
        self.Question._post_bot(chat, text_mod.bot_line("looking", "en_US"))
        self.assertTrue(self.bot_bodies(chat))

    def test_d05_one_free_line_per_minute(self):
        self.icp.set_param(discuss.ICP_DISCUSS_ENABLED, False)
        chat = self.dm(self.asker)
        for _i in range(3):
            self.ask(self.asker, chat, "Ventes ?")
        self.assertEqual(len(self.bot_bodies(chat)), 1)
        self.assertEqual(self.Question.search_count([("user_id", "=", self.asker.id), ("state", "=", "blocked")]), 1)

    def test_d06_pairing_selection_for_admins_only(self):
        Settings = self.env["res.config.settings"]
        self.assertFalse(Settings.with_user(self.asker)._styd_discuss_pairing_selection())
        self.assertIn(self.row.pairing_id,
                      [k for k, _v in Settings.with_user(self.admin)._styd_discuss_pairing_selection()])


# ---------------------------------------------------------------------------
# owner ops, explicit arguments, the owner warning
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestOwnerAndContext(HardeningCase):
    def test_o01_owner_op_failure_is_a_fixed_message(self):
        row = self.bound_pairing()
        Service = type(self.env["styd.odoo.bridge.service"])

        def broken(*_a, **_kw):
            raise ValueError("internal detail /srv/odoo/secret-path")

        self.patch(Service, "_build_health_payload", broken)
        out = self.run_request(row)
        self.assertEqual(out["status"], 500)
        self.assertNotIn("internal detail", json.dumps(out))
        self.assertTrue(out["body"]["detail"])

    def test_o02_context_keys_set_nothing(self):
        other = self.plain
        self.icp.set_param("styd_odoo_bridge.connector_owner_user_id", str(self.admin.id))
        service = self.env["styd.odoo.bridge.service"].sudo().with_context(styd_bridge_connector_owner_uid=other.id)
        self.assertEqual(service._get_connector_owner_user_id(), self.admin.id)
        self.assertEqual(service._get_connector_owner_user_id(owner_uid=other.id), other.id)
        orm = self.env["styd.odoo.bridge.orm"].sudo().with_context(styd_bridge_member_rights=True)
        names = {m["model"] for m in orm._orm_list_models()}
        self.assertFalse({n for n in names if n.startswith("hr.")}, "the context does not open member mode")
        if "hr.employee.public" in self.env:
            with self.assertRaises(StydOrmError) as ctx:
                orm._orm_search_read("hr.employee.public", fields=["name"])
            self.assertEqual(ctx.exception.code, "model_not_allowed")

    def test_o03_routes_strip_the_internal_keys(self):
        from odoo.addons.styd_odoo_bridge.controllers import bridge_api
        ctl = bridge_api.StydBridgeApi()
        fake = type("Req", (), {})()
        fake.env = self.env(context=dict(self.env.context, styd_bridge_member_rights=True,
                                         styd_bridge_connector_owner_uid=self.plain.id))
        self.patch(bridge_api, "request", fake)
        for model in (ctl._get_orm(), ctl._get_service()):
            self.assertNotIn("styd_bridge_member_rights", model.env.context)
            self.assertNotIn("styd_bridge_connector_owner_uid", model.env.context)
            self.assertTrue(model.env.su)

    def test_o04_wizard_warns_when_the_owner_is_an_admin(self):
        wizard = self.Wizard.create({"owner_user_id": self.admin.id})
        self.assertTrue(wizard.owner_is_admin)
        wizard.owner_user_id = self.plain
        self.assertFalse(wizard.owner_is_admin)
        arch = self.env.ref("styd_odoo_bridge.view_styd_bridge_channel_wizard_form").arch
        self.assertIn("dedicated Odoo user", arch)
        # Administrators stay allowed as members (owner decision).
        row = self.bound_pairing()
        self.assertTrue(self.run_request(row, member=self.admin)["ok"])
