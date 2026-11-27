"""What STYD's hub expects of the module for 0.11.0, beyond the earlier tests:
one hello ``instance`` for the life of the Odoo process, a hello refused with
``409 pairing_moved``, names in the pair message within the hub's limit, the conversation kinds of ``discuss.ask``, and
no ``discuss.delivered`` without a question id."""

import time

from odoo.tests import tagged

from odoo.addons.styd_odoo_bridge.models import bridge_channel as channel
from odoo.addons.styd_odoo_bridge.models import bridge_channel_pair as pair
from odoo.addons.styd_odoo_bridge.models import bridge_discuss as discuss

from .channel_common import ChannelCase
from .test_discuss import DiscussCase


@tagged("post_install", "-at_install")
class TestHubContract(ChannelCase):
    def test_c01_one_instance_per_process(self):
        first = self.make_stream(self.make_pairing())
        second = self.make_stream(self.make_pairing(label="Other"), runner=self.make_runner())
        self.assertEqual(first.instance, channel.PROCESS_INSTANCE)
        self.assertEqual(second.instance, channel.PROCESS_INSTANCE)
        first.poll_once()
        _pid, hello = self.hub.hellos[0]
        self.assertEqual(hello["instance"], channel.PROCESS_INSTANCE)
        # A stream started again in the same process says the same instance.
        again = self.make_stream(self.make_pairing(label="Again"))
        self.assertEqual(again.instance, first.instance)

    def test_c02_pairing_moved_stops_polling_for_retry_after(self):
        for retry, expected in ((300, 300), (900, 900), (10, channel.PAIRING_MOVED_RETRY_S), (None, 300)):
            row = self.make_pairing(label="Moved %s" % retry)
            stream = self.make_stream(row)
            body = {"t": "error", "code": "pairing_moved", "message": "another database"}
            if retry is not None:
                body["retry_after_s"] = retry
            self.hub.force("/bridge/v1/poll", 409, body)
            stream.poll_once()
            self.assertFalse(stream.ready.is_set(), retry)
            self.assertAlmostEqual(stream.pause_until - time.monotonic(), expected, delta=5, msg=retry)
            self.assertEqual(stream.status, "pairing_moved")
            self.reload()
            self.assertEqual(row.status_code, "pairing_moved")
            self.assertEqual(row.state, "active", "never unpaired by itself")
            self.assertTrue(row.secret)
        wizard = self.env["styd.odoo.bridge.channel.wizard"].with_user(self.admin).create({})
        self.assertIn("copied or moved", wizard._status_text(row))

    def test_c04_pair_message_names_within_128(self):
        self.admin.company_id.name = "Acme " + "x" * 300
        captured = []
        self.patch(pair, "start_pair_thread", lambda *args: captured.append(args))
        wizard = self.env["styd.odoo.bridge.channel.wizard"].with_user(self.admin).create({})
        wizard.action_show_code()
        self.env.cr.postcommit.run()
        info = captured[0][5]
        self.assertEqual(len(info["company_name"]), pair.PAIR_LABEL_MAX)
        self.assertTrue(info["company_name"].startswith("Acme x"))
        self.assertLessEqual(len(info["db_name"]), pair.PAIR_LABEL_MAX)


@tagged("post_install", "-at_install")
class TestDiscussContract(DiscussCase):
    def test_c10_conversation_kinds_on_the_wire(self):
        self.assertEqual(discuss.wire_kind("chat"), "chat")
        self.assertEqual(discuss.wire_kind("channel"), "channel")
        self.assertEqual(discuss.wire_kind("group"), "group")
        for other in ("livechat", "whatsapp", None, ""):
            self.assertEqual(discuss.wire_kind(other), "channel", other)
        chat = self.dm(self.asker)
        q = self.Question.create({"question_id": "dq_" + "c" * 22, "user_id": self.asker.id,
                                  "channel_id": chat.id, "state": "pending", "text": "hi",
                                  "pairing_ref": self.row.pairing_id, "conversation_kind": "livechat",
                                  "shared": True})
        conversation = q._ask_payload()["conversation"]
        self.assertEqual(conversation["kind"], "channel")
        self.assertEqual(conversation["asked_in"], "chat")
        self.assertTrue(conversation["shared"])

    def test_c11_no_delivered_event_without_a_question_id(self):
        stream = self.make_stream(self.row)
        stream.start()
        self.addCleanup(self.join_stream, stream)
        self.assertTrue(self.hub.wait_for(lambda: self.hub.hellos))
        self.hub.send_answer(self.row.pairing_id, self.asker.id,
                             {"question_id": "not-a-question", "status": "answered", "text": "x"})
        self.hub.send(self.row.pairing_id, op="health", member_uid=self.admin.id)
        self.assertTrue(self.hub.wait_for(lambda: len(self.hub.results) >= 1, timeout=10))
        self.join_stream(stream)
        self.assertFalse(self.hub.discuss_delivered)
        self.assertFalse(self.Inbox.search([]))
