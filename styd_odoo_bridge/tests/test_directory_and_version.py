"""The user directory read in pages, the user search over every user, the
module's own version in /health and the security snapshot, and the public
address sent in the first pair message and in the hello."""

import ast
import os
import uuid

from odoo import Command
from odoo.modules.module import get_module_path
from odoo.tests import tagged

from odoo.addons.styd_odoo_bridge.models import bridge_channel as channel
from odoo.addons.styd_odoo_bridge.models import bridge_channel_executor as ex
from odoo.addons.styd_odoo_bridge.models import bridge_channel_pair as pair
from odoo.addons.styd_odoo_bridge.models import bridge_channel_protocol as proto
from odoo.addons.styd_odoo_bridge.models import bridge_service as service_mod

from .channel_common import GROUPS, ChannelCase

MODULE = "styd_odoo_bridge"


def manifest_module_version():
    """``x.y.z`` read from the manifest file itself (not through Odoo's helpers)."""
    with open(os.path.join(get_module_path(MODULE), "__manifest__.py"), encoding="utf-8") as fh:
        version = ast.literal_eval(fh.read())["version"]
    return ".".join(version.split(".")[2:5])


class ModuleInfoCase(ChannelCase):
    def setUp(self):
        super().setUp()
        self.Service = self.env["styd.odoo.bridge.service"].sudo()
        self.Users = self.env["res.users"].with_context(no_reset_password=True)
        self.pairing = {"pairing_id": self.make_pairing().pairing_id, "owner_uid": self.admin.id}

    def make_users(self, count, prefix):
        group = self.env.ref("base.group_user")
        return self.Users.create([{
            "name": "%s %02d" % (prefix, i), "login": "%s_%02d" % (prefix, i),
            "email": "%s_%02d@example.com" % (prefix, i),
            GROUPS: [Command.set([group.id])],
        } for i in range(count)])

    def run_op(self, op, args=None, member=None):
        self.sync()
        fields = {
            "v": 1, "id": str(uuid.uuid4()), "ts": 0, "op": op, "member_uid": (member or self.admin).id,
            "pairing_id": self.pairing["pairing_id"], "args_json": "{}",
        }
        out = ex.execute_request(self.dbname, self.pairing, fields, args or {}, registry=self.registry)
        self.reload()
        return out

    def all_pages(self, limit):
        ids, cursor, pages = [], None, 0
        while True:
            body = self.Service._build_user_directory_snapshot_payload(cursor=cursor, limit=limit)
            self.assertLessEqual(len(body["users"]), limit)
            ids += [u["odoo_user_id"] for u in body["users"]]
            pages += 1
            cursor = body["next_cursor"]
            if cursor is None:
                return ids, pages
            self.assertIsInstance(cursor, str)
            self.assertLess(pages, 1000)


@tagged("post_install", "-at_install")
class TestDirectoryPages(ModuleInfoCase):
    def test_p01_every_active_user_once_across_pages(self):
        made = self.make_users(7, "styd_page_user")
        archived = made[-1]
        archived.active = False
        expected = self.env["res.users"].sudo().search([("active", "=", True)], order="id").ids
        ids, pages = self.all_pages(limit=3)
        self.assertEqual(ids, expected, "every active user once, in id order")
        self.assertNotIn(archived.id, ids)
        self.assertEqual(pages, -(-len(expected) // 3))

    def test_p02_first_page_without_cursor_and_last_page(self):
        self.make_users(3, "styd_page_first")
        total = self.env["res.users"].sudo().search_count([("active", "=", True)])
        body = self.Service._build_user_directory_snapshot_payload()
        self.assertIn("next_cursor", body)
        self.assertEqual(len(body["users"]), min(total, self.Service.USER_DIRECTORY_LIMIT))
        if total <= self.Service.USER_DIRECTORY_LIMIT:
            self.assertIsNone(body["next_cursor"])
            exact = self.Service._build_user_directory_snapshot_payload(limit=total)
            self.assertIsNone(exact["next_cursor"], "a page that ends on the last user is the last page")
            one_short = self.Service._build_user_directory_snapshot_payload(limit=total - 1)
            self.assertIsNotNone(one_short["next_cursor"])

    def test_p03_beyond_the_page_size(self):
        """More users than one page: the later ones are reached through the cursor."""
        self.patch(type(self.Service), "USER_DIRECTORY_LIMIT", 2)
        made = self.make_users(5, "styd_page_cap")
        first = self.Service._build_user_directory_snapshot_payload(limit=50)
        self.assertEqual(len(first["users"]), 2, "the page size stays the maximum")
        ids, _pages = self.all_pages(limit=2)
        self.assertTrue(set(made.ids) <= set(ids))

    def test_p04_bad_cursor_or_limit(self):
        for cursor in ("abc", "-1", "1.5", "1" * 19, 12, ["1"]):
            with self.assertRaises(service_mod.DirectoryPageError) as ctx:
                self.Service._build_user_directory_snapshot_payload(cursor=cursor)
            self.assertEqual(ctx.exception.code, "invalid_cursor", cursor)
        for limit in ("0", "x", 0, -3, True, 2.5):
            with self.assertRaises(service_mod.DirectoryPageError) as ctx:
                self.Service._build_user_directory_snapshot_payload(limit=limit)
            self.assertEqual(ctx.exception.code, "invalid_limit", limit)
        body = self.Service._build_user_directory_snapshot_payload(cursor="", limit="2")
        self.assertLessEqual(len(body["users"]), 2)

    def test_p05_over_the_channel(self):
        self.make_users(4, "styd_page_chan")
        expected = self.env["res.users"].sudo().search([("active", "=", True)], order="id").ids
        ids, cursor = [], None
        for _round in range(100):
            args = {"limit": 2}
            if cursor:
                args["cursor"] = cursor
            out = self.run_op("users.directory", args=args)
            self.assertTrue(out["ok"], out)
            ids += [u["odoo_user_id"] for u in out["body"]["users"]]
            cursor = out["body"]["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(ids, expected)
        out = self.run_op("users.directory", args={"cursor": "not-a-cursor"})
        self.assertEqual(out["status"], 400)
        self.assertEqual(out["body"]["error"], "invalid_cursor")
        self.assertEqual(self.run_op("users.directory", args={"limit": 0})["body"]["error"], "invalid_limit")

    def test_p06_search_reaches_users_beyond_one_page(self):
        self.patch(type(self.Service), "USER_DIRECTORY_LIMIT", 2)
        made = self.make_users(5, "styd_search_far")
        target = made[-1]
        body = self.Service._build_user_search_payload(target.login)
        self.assertEqual([u["odoo_user_id"] for u in body["users"]], [target.id])
        self.assertEqual(body["count"], 1)
        self.assertFalse(body["truncated"])
        by_email = self.Service._build_user_search_payload(target.email.upper())
        self.assertEqual([u["odoo_user_id"] for u in by_email["users"]], [target.id], "any case, email too")
        wide = self.Service._build_user_search_payload("styd_search_far")
        self.assertEqual(wide["count"], 2)
        self.assertTrue(wide["truncated"])

    def test_p07_search_wildcards_are_literal(self):
        self.make_users(2, "styd_wild")
        self.assertEqual(self.Service._build_user_search_payload("styd%wild")["count"], 0)
        self.assertEqual(self.Service._build_user_search_payload("styd_wild_01")["count"], 1)
        self.assertEqual(self.Service._build_user_search_payload("WILD 0")["count"], 2, "names match too")
        self.assertEqual(self.Service._build_user_search_payload("styd?wild")["count"], 0)

    def test_p08_paging_is_advertised(self):
        self.assertIn("odoo_user_directory_paging_v1", self.Service._build_health_payload()["supported_features"])


@tagged("post_install", "-at_install")
class TestModuleVersion(ModuleInfoCase):
    def test_v01_health_and_snapshot_carry_the_module_version(self):
        version = manifest_module_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        health = self.Service._build_health_payload()
        self.assertEqual(health["module_version"], version)
        self.assertEqual(health["bridge_version"], self.Service.BRIDGE_VERSION, "the protocol version is kept")
        self.assertEqual(self.Service.BRIDGE_VERSION, "0.3.0")
        snapshot = self.Service._build_security_snapshot_payload(owner_uid=self.admin.id)
        self.assertEqual(snapshot["module_version"], version)
        self.assertEqual(snapshot["bridge_version"], "0.3.0")

    def test_v02_same_value_in_the_hello_the_pair_message_and_the_channel_health(self):
        version = manifest_module_version()
        self.assertEqual(channel.module_version(), version, "never 0.0.0 on any Odoo version")
        self.assertEqual(self.make_runner().info["module_version"], version)
        out = self.run_op("health")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["body"]["module_version"], version)
        self.assertEqual(out["body"]["bridge_version"], "0.3.0")


@tagged("post_install", "-at_install")
class TestPublicUrl(ModuleInfoCase):
    def test_u01_clean_public_url(self):
        ok = {
            "https://odoo.example.com": "https://odoo.example.com",
            "https://odoo.example.com/": "https://odoo.example.com",
            " HTTPS://Odoo.Example.com:8443/erp/ ": "https://Odoo.Example.com:8443/erp",
            "http://192.168.1.20:8069": "http://192.168.1.20:8069",
            "http://localhost:8069": "http://localhost:8069",
        }
        for raw, want in ok.items():
            self.assertEqual(proto.clean_public_url(raw), want, raw)
        for bad in (None, False, "", "   ", "odoo.example.com", "ftp://odoo.example.com",
                    "https://user:pw@odoo.example.com", "https://odoo.example.com/?a=1",
                    "https://odoo.example.com/#x", "https://odoo.example.com:99999",
                    "https://odoo example.com", "javascript:alert(1)", "https://",
                    "https://odoo.example.com/" + "a" * 2100, 42):
            self.assertIsNone(proto.clean_public_url(bad), bad)

    def test_u02_first_pair_message_carries_the_public_url(self):
        self.icp.set_param("web.base.url", "https://erp.example.com/")
        captured = []
        self.patch(pair, "start_pair_thread", lambda *args: captured.append(args))
        wizard = self.env["styd.odoo.bridge.channel.wizard"].with_user(self.admin).create({})
        wizard.action_show_code()
        row = self.env["styd.odoo.bridge.pairing"].sudo().search([("state", "=", "pending")])
        self.env.cr.postcommit.run()
        info = captured[0][5]
        self.assertEqual(info["public_url"], "https://erp.example.com")
        self.sync()
        store = channel.PairingStore(self.dbname, self.registry)
        outcome = pair.run_pair_session(store, channel.HubClient(self.hub.url, True), row.id,
                                        captured[0][2], self.admin.id, info, life_s=1)
        self.assertEqual(outcome, "expired")
        self.assertEqual(self.hub.pair_opens[0]["public_url"], "https://erp.example.com")

    def test_u03_no_usable_address_is_null(self):
        self.icp.set_param("web.base.url", "not an address")
        self.assertIsNone(channel.read_settings(self.env)["public_url"])
        self.assertIsNone(channel.read_settings(self.env, fresh=True)["public_url"])

    def test_u04_hello_carries_the_public_url(self):
        self.icp.set_param("web.base.url", "http://odoo.internal.example:8069/")
        runner = self.make_runner()
        self.sync()
        self.assertTrue(runner.tick())
        self.assertTrue(self.hub.wait_for(lambda: self.hub.hellos), "the stream says hello")
        pairing_id, hello = self.hub.hellos[0]
        self.assertEqual(pairing_id, self.pairing["pairing_id"])
        self.assertEqual(hello["public_url"], "http://odoo.internal.example:8069")
        self.assertEqual(hello["module_version"], manifest_module_version())
