"""Discuss assistant (M-D), module side. Contract: docs/DISCUSS_CONTRACT.md.

  * A direct message to the bot partner "Speak To Your Database", or a mention
    of it in a channel, saves a pending question (``styd.discuss.question``) and
    triggers the Discuss job at once (``ir.cron`` trigger). The user's request
    never waits on STYD: nothing leaves Odoo in it.
  * The job sends the question OUT, as a signed ``discuss.ask`` event on the
    existing outbound channel (``/bridge/v1/event``), never through an inbound
    call. STYD then reads, as the asking member, over the channel (read-only
    cursor, no sudo), and sends its answer down a poll as a signed
    ``discuss_answer``. The poll thread only stores it (``styd.discuss.inbox``)
    and triggers the job; the job posts it as the bot.
  * A mention in a channel or a group is answered in the asker's direct chat
    with the bot (the reads ran with the asker's own rights), and one line in
    the channel says so, as a reply to the question. The admin setting "Answer
    mentions in the channel" (off by default) answers in the channel instead.
  * Off by default. An admin chooses who may ask; anyone else gets a free
    "ask your admin" line, with no call to STYD. Per-user and per-database rate
    limits apply before anything is sent.
  * Question and answer texts are data: the question travels as a JSON string,
    the answer is escaped and rendered here, secrets are hidden, and the only
    write the assistant ever makes is its own message in the conversation the
    question came from.

Neither model has an ``ir.model.access`` row: only module code reads them (sudo).
"""

import datetime
import inspect
import json
import logging
import threading
import time

import requests

from odoo import SUPERUSER_ID, api, fields, models
from odoo.modules import module as odoo_module

from . import bridge_channel as channel_mod
from . import bridge_channel_executor as executor_mod
from . import bridge_channel_protocol as proto
from . import bridge_discuss_text as text_mod

_logger = logging.getLogger(__name__)

BOT_XMLID = "styd_odoo_bridge.partner_styd_bot"
CRON_XMLID = "styd_odoo_bridge.ir_cron_styd_discuss"

ICP_DISCUSS_ENABLED = "styd_odoo_bridge.discuss_enabled"
ICP_DISCUSS_AUDIENCE = "styd_odoo_bridge.discuss_audience"
ICP_DISCUSS_GROUP = "styd_odoo_bridge.discuss_group_id"
ICP_DISCUSS_USERS = "styd_odoo_bridge.discuss_user_ids"
ICP_DISCUSS_PAIRING = "styd_odoo_bridge.discuss_pairing_id"
ICP_RATE_USER_HOUR = "styd_odoo_bridge.discuss_rate_user_hour"
ICP_RATE_DB_HOUR = "styd_odoo_bridge.discuss_rate_db_hour"
ICP_ANSWER_IN_CHANNEL = "styd_odoo_bridge.discuss_answer_in_channel"

AUDIENCES = ("all", "group", "users")
DEFAULT_RATE_USER_HOUR = 30
DEFAULT_RATE_DB_HOUR = 300
BURST_USER_PER_MINUTE = 3

ANSWER_TIMEOUT_S = 180
SEND_ATTEMPTS = 3
RETRY_DELAYS_S = (5, 20, 60)
BATCH = 20
OPEN_CHATS_MAX = 500
KEEP_DAYS = 30

# States whose questions count against the rate limits (they went, or will go, to STYD).
COUNTED_STATES = ("pending", "sent", "done", "refused", "failed", "timeout")
OPEN_STATES = ("pending", "sent")


def _int(raw, default=0):
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _ids(raw):
    out = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            out.append(int(part))
    return out


def _auto_commit():
    """Commit each question, except under tests (the thread flag before Odoo 19,
    ``current_test`` on every version)."""
    if getattr(threading.current_thread(), "testing", False):
        return False
    return not getattr(odoo_module, "current_test", None)



def open_chat(Channel, partner_ids):
    """The direct chat of ``Channel.env.user`` with ``partner_ids``, opened if needed:
    ``_get_or_create_chat`` since Odoo 19, ``channel_get`` before."""
    if hasattr(Channel, "_get_or_create_chat"):
        if "pin" in inspect.signature(Channel._get_or_create_chat).parameters:  # 19 (20: no pin)
            return Channel._get_or_create_chat(partner_ids, pin=True)
        return Channel._get_or_create_chat(partner_ids)
    return channel_record(Channel, Channel.channel_get(partner_ids, pin=True))


def members_field(Channel):
    """The channel's member lines: ``channel_member_ids`` since Odoo 16,
    ``channel_last_seen_partner_ids`` on 15."""
    return "channel_member_ids" if "channel_member_ids" in Channel._fields else "channel_last_seen_partner_ids"


def member_partners(channel):
    return channel.sudo()[members_field(channel)].partner_id


def channel_record(Channel, result):
    """``channel_get`` returns the channel's info (a dict) before Odoo 17, the record after."""
    if isinstance(result, dict):
        return Channel.browse(result["id"])
    return result

class StydDiscussQuestion(models.Model):
    _name = "styd.discuss.question"
    _description = "Speak To Your Database: a question asked in Discuss"
    _order = "id"

    question_id = fields.Char(required=True, index=True, copy=False, readonly=True)
    state = fields.Selection(
        selection=[
            ("pending", "Waiting to be sent"),
            ("sent", "Sent, waiting for the answer"),
            ("done", "Answered"),
            ("refused", "Refused by STYD"),
            ("failed", "Could not be sent"),
            ("timeout", "No answer in time"),
            ("blocked", "Not sent (not allowed or rate limited)"),
        ],
        default="pending", required=True, index=True,
    )
    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    channel_id = fields.Many2one("discuss.channel", required=True, ondelete="cascade",
                                 help="Where the bot answers: the conversation, or the asker's chat with the bot.")
    message_id = fields.Many2one("mail.message", ondelete="set null")
    origin_channel_id = fields.Many2one(
        "discuss.channel", ondelete="set null",
        help="A mention in a channel or group answered in the asker's chat: where it was asked.")
    origin_notified = fields.Boolean(help="The line 'answered you in a direct message' was posted.")
    pairing_ref = fields.Char(help="pairing_id of the outbound channel used.")
    text = fields.Text(help="The question, kept only until it is sent.")
    truncated = fields.Boolean()
    lang = fields.Char()
    tz = fields.Char()
    shared = fields.Boolean(help="Others than the asker can read the conversation.")
    conversation_kind = fields.Char()
    attempts = fields.Integer()
    next_try_at = fields.Datetime()
    sent_at = fields.Datetime()
    finished_at = fields.Datetime()
    outcome_code = fields.Char()

    _sql_constraints = [
        ("question_id_unique", "unique(question_id)", "A question id is stored once."),
    ]

    # ------------------------------------------------------------------
    # settings and rules
    # ------------------------------------------------------------------
    @api.model
    def _settings(self):
        icp = self.env["ir.config_parameter"].sudo()
        audience = executor_mod.icp_get(icp, ICP_DISCUSS_AUDIENCE, "all") or "all"
        return {
            "enabled": executor_mod._truthy(executor_mod.icp_get(icp, ICP_DISCUSS_ENABLED, "False")),
            "bridge_enabled": executor_mod._truthy(executor_mod.icp_get(icp, executor_mod.ICP_ENABLED, "False")),
            "restrict_group": executor_mod._truthy(executor_mod.icp_get(icp, executor_mod.ICP_RESTRICT_GROUP, "False")),
            "audience": audience if audience in AUDIENCES else "all",
            "group_id": _int(executor_mod.icp_get(icp, ICP_DISCUSS_GROUP)),
            "user_ids": _ids(executor_mod.icp_get(icp, ICP_DISCUSS_USERS)),
            "pairing_ref": (executor_mod.icp_get(icp, ICP_DISCUSS_PAIRING) or "").strip(),
            "rate_user_hour": _int(executor_mod.icp_get(icp, ICP_RATE_USER_HOUR), DEFAULT_RATE_USER_HOUR),
            "rate_db_hour": _int(executor_mod.icp_get(icp, ICP_RATE_DB_HOUR), DEFAULT_RATE_DB_HOUR),
            "answer_in_channel": executor_mod._truthy(executor_mod.icp_get(icp, ICP_ANSWER_IN_CHANNEL, "False")),
        }

    @api.model
    def _bot(self):
        return self.env.ref(BOT_XMLID, raise_if_not_found=False)

    @api.model
    def _may_ask(self, user, settings):
        """The admin's audience, on top of the channel's own rule (section 7 of
        the protocol): active, internal, not __system__, and in the STYD group
        when that restriction is on."""
        user = user.sudo()
        if not user.exists() or not user.active or user.share or user.id == SUPERUSER_ID:
            return False
        if settings["restrict_group"]:
            group = self.env.ref(executor_mod.MEMBER_GROUP_XMLID, raise_if_not_found=False)
            if not group or group not in executor_mod.user_groups(user):
                return False
        if settings["audience"] == "group":
            return bool(settings["group_id"]) and settings["group_id"] in executor_mod.user_groups(user).ids
        if settings["audience"] == "users":
            return user.id in settings["user_ids"]
        return True

    @api.model
    def _resolve_pairing(self, settings):
        """The pairing the assistant asks through: the chosen one, or the only one."""
        if not settings["bridge_enabled"]:
            return None
        Pairing = self.env["styd.odoo.bridge.pairing"].sudo()
        pairings = Pairing.search(Pairing._streamable_domain())
        if settings["pairing_ref"]:
            pairings = pairings.filtered(lambda p: p.pairing_id == settings["pairing_ref"])
        return pairings if len(pairings) == 1 else None

    @api.model
    def _rate_limit_key(self, user, settings):
        """None, or the bot line to say: per user (burst and hourly) and per database."""
        now = fields.Datetime.now()
        hour = now - datetime.timedelta(hours=1)
        minute = now - datetime.timedelta(minutes=1)
        mine = [("user_id", "=", user.id), ("state", "in", COUNTED_STATES)]
        if self.search_count(mine + [("create_date", ">=", minute)]) >= BURST_USER_PER_MINUTE:
            return "rate_user"
        if self.search_count(mine + [("create_date", ">=", hour)]) >= settings["rate_user_hour"]:
            return "rate_user"
        if self.search_count([("state", "in", COUNTED_STATES), ("create_date", ">=", hour)]) >= settings["rate_db_hour"]:
            return "rate_db"
        return None

    # ------------------------------------------------------------------
    # a message for the bot (in the user's own request: nothing leaves Odoo)
    # ------------------------------------------------------------------
    @api.model
    def _receive(self, channel, message, user):
        bot = self._bot()
        lang = user.lang or "en_US"
        settings = self._settings()
        # The asker's own chat with the bot; anything else (a channel, a group, a
        # chat with a colleague) is read by others too.
        own_chat = channel.channel_type == "chat" and bot in member_partners(channel)

        def reply(key):
            # Free lines say nothing private: posted where the user asked (as a reply
            # to the question when others read that conversation).
            self._post_bot(channel, text_mod.bot_line(key, lang), parent=None if own_chat else message)

        if not settings["enabled"]:
            reply("disabled")
            return None
        base = {
            "question_id": proto.new_question_id(),
            "user_id": user.id,
            "channel_id": channel.id,
            "message_id": message.id,
            "lang": lang,
            "tz": user.tz or "UTC",
        }
        if not self._may_ask(user, settings):
            self.create(dict(base, state="blocked", outcome_code="not_allowed", finished_at=fields.Datetime.now()))
            reply("not_allowed")
            return None
        text, truncated = text_mod.extract_question(message.body, bot.id, bot.name)
        if not text:
            reply("empty")
            return None
        pairing = self._resolve_pairing(settings)
        if not pairing:
            reply("not_connected")
            return None
        limited = self._rate_limit_key(user, settings)
        if limited:
            self.create(dict(base, state="blocked", outcome_code=limited, finished_at=fields.Datetime.now()))
            reply(limited)
            return None
        answer_channel, origin = channel, False
        if not own_chat and not settings["answer_in_channel"]:
            # Owner decision: a mention is answered in the asker's own chat with the bot.
            answer_channel, origin = self._user_chat(user), channel
        others = member_partners(answer_channel) - bot - user.partner_id
        question = self.create(dict(
            base,
            state="pending",
            channel_id=answer_channel.id,
            origin_channel_id=origin and origin.id,
            pairing_ref=pairing.pairing_id,
            text=text,
            truncated=truncated,
            shared=answer_channel.channel_type != "chat" or bool(others),
            conversation_kind=answer_channel.channel_type,
        ))
        self._trigger()
        return question

    @api.model
    def _trigger(self, at=None):
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger(at=at)

    @api.model
    def _post_bot(self, channel, body, parent=None):
        """Post ``body`` (Markup built by bridge_discuss_text) as the bot, in
        ``channel`` only (as a reply to ``parent`` when given). No partner is
        notified beyond the conversation."""
        bot = self._bot()
        values = {"parent_id": parent.id} if parent else {}
        return channel.sudo().message_post(
            body=body, author_id=bot.id, message_type="comment", subtype_xmlid="mail.mt_comment", **values)

    def _say(self, key):
        self.ensure_one()
        self._post_bot(self.channel_id, text_mod.bot_line(key, self.lang))

    def _finish(self, state, code, say_key=None):
        self.ensure_one()
        self.write({"state": state, "outcome_code": code, "finished_at": fields.Datetime.now(),
                    "text": False, "next_try_at": False})
        if say_key:
            self._say(say_key)
        self._notify_origin()

    def _notify_origin(self):
        """Once the asker has their reply in the direct chat, one line where they asked."""
        self.ensure_one()
        if not self.origin_channel_id or self.origin_notified:
            return
        self.origin_notified = True
        message = self.message_id
        parent = message if message and message.model == "discuss.channel" \
            and message.res_id == self.origin_channel_id.id else None
        self._post_bot(self.origin_channel_id, text_mod.bot_line("answered_in_dm", self.lang), parent=parent)

    # ------------------------------------------------------------------
    # the job
    # ------------------------------------------------------------------
    @api.model
    def _cron_process(self):
        """Send what is pending, post what arrived, close what timed out. Each
        question is committed on its own (except under tests)."""
        commit = _auto_commit()
        self._process_sends(commit)
        self._process_answers(commit)
        self._process_timeouts(commit)

    @api.model
    def _process_sends(self, commit=False):
        now = fields.Datetime.now()
        rows = self.search([("state", "=", "pending"), "|", ("next_try_at", "=", False), ("next_try_at", "<=", now)],
                           limit=BATCH)
        settings = channel_mod.read_settings(self.env)
        for row in rows:
            try:
                row._send(settings)
            except Exception:
                _logger.exception("STYD discuss: sending a question failed")
                row._retry(None)
            if commit:
                self.env.cr.commit()

    def _ask_payload(self):
        self.ensure_one()
        return {
            "t": "event",
            "kind": "discuss.ask",
            "question_id": self.question_id,
            "member_uid": self.user_id.id,
            "conversation": {
                "key": "discuss.channel:%d" % self.channel_id.id,
                "kind": self.conversation_kind or "chat",
                "shared": bool(self.shared),
                "asked_in": (self.origin_channel_id or self.channel_id).channel_type,
            },
            "lang": self.lang or "en_US",
            "tz": self.tz or "UTC",
            "text": self.text or "",
            "truncated": bool(self.truncated),
            "asked_at": int(self.create_date.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000),
            "attempt": self.attempts + 1,
        }

    def _send(self, settings):
        self.ensure_one()
        Pairing = self.env["styd.odoo.bridge.pairing"].sudo()
        pairing = Pairing.search([("pairing_id", "=", self.pairing_ref)] + Pairing._streamable_domain(), limit=1)
        if not settings["enabled"] or not pairing:
            self._finish("failed", "not_connected", "not_connected")
            return
        try:
            hub = channel_mod.HubClient(settings["hub_url"], channel_mod.resolve_verify(settings["ca_bundle"]))
        except ValueError:
            self._finish("failed", "bad_settings", "not_connected")
            return
        secret = pairing.secret
        signer = channel_mod.SignedClient(hub, pairing.pairing_id, lambda: secret, pairing.clock_offset_ms)
        try:
            status, data = signer.post(channel_mod.PATH_EVENT, self._ask_payload(), timeout=channel_mod.POST_TIMEOUT)
        except requests.RequestException as exc:
            _logger.info("STYD discuss: the hub could not be reached (%s)", type(exc).__name__)
            status, data = None, None
        self._handle_ack(status, data or {})

    def _handle_ack(self, status, data):
        self.ensure_one()
        code = data.get("code") if isinstance(data.get("code"), str) else None
        if status == 200 and data.get("t") == "ack":
            if data.get("ignored"):
                # The hub does not know discuss.ask yet (older STYD).
                self._finish("failed", "hub_unsupported", "discuss_off")
            elif data.get("accepted") is True:
                self.write({"state": "sent", "sent_at": fields.Datetime.now(), "attempts": self.attempts + 1,
                            "next_try_at": False, "text": False})
                self._say("looking")
                self._trigger(fields.Datetime.now() + datetime.timedelta(seconds=ANSWER_TIMEOUT_S + 5))
            elif code == "busy":
                self._retry(data.get("retry_after_s"))
            else:
                self._finish("refused", code or "refused",
                             text_mod.REFUSAL_MESSAGE_KEYS.get(code or "", "unreachable"))
            return
        if status == 401 and code == "not_paired":
            self._finish("failed", "not_paired", "not_connected")
            return
        if status in (400, 413):
            self._finish("failed", code or "bad_message", "error")
            return
        self._retry(data.get("retry_after_s"))

    def _retry(self, retry_after_s=None):
        self.ensure_one()
        attempts = self.attempts + 1
        if attempts >= SEND_ATTEMPTS:
            self.write({"attempts": attempts})
            self._finish("failed", "unreachable", "unreachable")
            return
        delay = RETRY_DELAYS_S[min(attempts - 1, len(RETRY_DELAYS_S) - 1)]
        if isinstance(retry_after_s, (int, float)) and not isinstance(retry_after_s, bool) and retry_after_s > 0:
            delay = max(delay, min(float(retry_after_s), 600.0))
        at = fields.Datetime.now() + datetime.timedelta(seconds=delay)
        self.write({"attempts": attempts, "next_try_at": at})
        self._trigger(at)

    @api.model
    def _known_secrets(self):
        out = []
        for p in self.env["styd.odoo.bridge.pairing"].sudo().search([]):
            out += [s for s in (p.secret, p.pending_secret, p.previous_secret) if s]
        return out

    @api.model
    def _process_answers(self, commit=False):
        Inbox = self.env["styd.discuss.inbox"].sudo()
        secrets = None
        for item in Inbox.search([], order="id", limit=BATCH):
            question = self.search([("question_id", "=", item.question_ref)], limit=1)
            if question and question.state == "pending":
                continue  # its ack is not processed yet: next run
            if question and question.state == "sent" and question.user_id.id == item.member_uid:
                try:
                    answer = json.loads(item.payload or "{}")
                    if secrets is None:
                        secrets = self._known_secrets()
                    body = text_mod.render_answer(answer, question.lang, secrets)
                    question._post_bot(question.channel_id, body)
                    question._finish("done", answer.get("status") or "answered")
                except Exception:
                    _logger.exception("STYD discuss: could not post an answer")
                    question._finish("failed", "post_failed", "error")
            item.unlink()
            if commit:
                self.env.cr.commit()

    @api.model
    def _process_timeouts(self, commit=False):
        limit = fields.Datetime.now() - datetime.timedelta(seconds=ANSWER_TIMEOUT_S)
        for row in self.search([("state", "=", "sent"), ("sent_at", "<", limit)], limit=BATCH):
            row._finish("timeout", "timeout", "timeout")
            if commit:
                self.env.cr.commit()

    # ------------------------------------------------------------------
    # chats with the bot (no change to Discuss screens: the server opens them)
    # ------------------------------------------------------------------
    @api.model
    def _user_chat(self, user):
        """The user's direct chat with the bot, opened if needed. The welcome line
        is posted once per user ever, and only while the assistant is on."""
        bot = self._bot()
        Channel = self.env["discuss.channel"].sudo()
        chat = Channel.search([
            ("channel_type", "=", "chat"),
            (members_field(Channel) + ".partner_id", "=", user.partner_id.id),
            (members_field(Channel) + ".partner_id", "=", bot.id),
        ], limit=1)
        if not chat:
            chat = open_chat(Channel.with_user(user).sudo(), [bot.id])
        Welcome = self.env["styd.discuss.welcome"].sudo()
        if self._settings()["enabled"] and not Welcome.search_count([("user_id", "=", user.id)]):
            Welcome.create({"user_id": user.id})
            self._post_bot(chat, text_mod.bot_line("welcome", user.lang))
        return chat

    @api.model
    def _open_chats(self, limit=OPEN_CHATS_MAX):
        """Open the chat with the bot, with its welcome line, for each user who
        may ask and was never welcomed (a user welcomed once is never welcomed
        again, even after leaving that chat). Returns how many were opened."""
        settings = self._settings()
        if not settings["enabled"] or not self._bot():
            return 0
        welcomed = self.env["styd.discuss.welcome"].sudo().search([]).user_id
        users = self.env["res.users"].sudo().search([("share", "=", False), ("id", "!=", SUPERUSER_ID)]) - welcomed
        opened = 0
        for user in users:
            if opened >= limit:
                _logger.info("STYD discuss: %s chats opened, the others open on the next save", opened)
                break
            if self._may_ask(user, settings):
                self._user_chat(user)
                opened += 1
        return opened

    @api.autovacuum
    def _gc_old_questions(self):
        limit = fields.Datetime.now() - datetime.timedelta(days=KEEP_DAYS)
        self.sudo().search([("create_date", "<", limit), ("state", "not in", OPEN_STATES)]).unlink()


class StydDiscussWelcome(models.Model):
    """Users the bot already welcomed: the welcome line is posted once per user ever."""

    _name = "styd.discuss.welcome"
    _description = "Speak To Your Database: users welcomed by the Discuss assistant"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")

    _sql_constraints = [
        ("user_unique", "unique(user_id)", "A user is welcomed once."),
    ]


class StydDiscussInbox(models.Model):
    """Answers that arrived down the channel, waiting for the Discuss job.
    Written by the poll thread on its own cursor (insert only), so it never
    competes with the job for a question row."""

    _name = "styd.discuss.inbox"
    _description = "Speak To Your Database: Discuss answers waiting to be posted"
    _order = "id"

    question_ref = fields.Char(required=True, index=True)
    member_uid = fields.Integer(required=True)
    payload = fields.Text(help="The validated answer (JSON); removed once posted.")

    @api.model
    def _deliver(self, pairing_id, member_uid, args):
        """Check a verified ``discuss_answer`` against its question and store it.
        Returns "ok", or why it was not stored (contract section 4)."""
        code = "ok"
        try:
            answer = text_mod.validate_answer(args)
        except text_mod.AnswerError:
            qid = args.get("question_id") if isinstance(args, dict) else None
            if not isinstance(qid, str) or not proto.QUESTION_ID_RE.match(qid):
                return "bad_answer"
            # Tell the asker something went wrong instead of leaving them waiting.
            answer = {"question_id": qid, "status": "error", "lang": None,
                      "error": {"code": "bad_answer", "message": None}}
            code = "bad_answer"
        Question = self.env["styd.discuss.question"].sudo()
        question = Question.search([("question_id", "=", answer["question_id"])], limit=1)
        if not question or question.pairing_ref != pairing_id:
            return "unknown_question"
        if question.user_id.id != member_uid:
            return "wrong_member"
        if question.state not in OPEN_STATES:
            return "late"
        if self.search_count([("question_ref", "=", question.question_id)]):
            return "duplicate"
        self.create({"question_ref": question.question_id, "member_uid": member_uid,
                     "payload": json.dumps(answer)})
        Question._trigger()
        return code

    @api.autovacuum
    def _gc_old_inbox(self):
        limit = fields.Datetime.now() - datetime.timedelta(days=1)
        self.sudo().search([("create_date", "<", limit)]).unlink()


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _get_allowed_message_partner_ids(self, partner_ids):
        """Odoo 19+ (only called there): mentioned partners who cannot read the
        channel are dropped. The bot has no user, so its mention, which is how a
        question is asked in a channel, would be dropped too: keep the bot only."""
        allowed = super()._get_allowed_message_partner_ids(partner_ids)
        bot = self.env["styd.discuss.question"].sudo()._bot()
        if bot and bot.id in (partner_ids or []) and bot.id not in allowed:
            allowed = list(allowed) + [bot.id]
        return allowed

    def _message_post_after_hook(self, message, *args, **kwargs):
        # Odoo 15 to 19 pass the message's values; 20 passes the message only.
        res = super()._message_post_after_hook(message, *args, **kwargs)
        msg_vals = args[0] if args else kwargs.get("msg_vals")
        if msg_vals is None:
            msg_vals = {"message_type": message.message_type, "author_id": message.author_id.id,
                        "partner_ids": message.partner_ids.ids}
        try:
            with self.env.cr.savepoint():
                self._styd_discuss_take(message, msg_vals)
        except Exception:
            # The user's own message is never lost because of the assistant.
            _logger.exception("STYD discuss: could not take a question")
        return res

    def _styd_discuss_take(self, message, msg_vals):
        """A comment by an internal user, in a direct chat with the bot or
        mentioning it, becomes a question. Anything else is ignored: the bot's
        own posts, other bots, notifications, emails, chatter on records."""
        if len(self) != 1 or msg_vals.get("message_type") != "comment":
            return
        Question = self.env["styd.discuss.question"].sudo()
        bot = Question._bot()
        author_id = msg_vals.get("author_id")
        if not bot or not author_id or author_id == bot.id:
            return
        user = self.env.user
        if not user or user._is_public() or user.id == SUPERUSER_ID or user.partner_id.id != author_id:
            return
        direct = self.channel_type == "chat" and bot in member_partners(self)
        mentioned = bot.id in set(msg_vals.get("partner_ids") or ())
        if direct or mentioned:
            Question._receive(self, message, user)
