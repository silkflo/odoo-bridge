"""Bridge channel pairing (B2 step M3): code, pair session, proof of possession,
unpair and rotate from Odoo, and the admin wizard.

The pairing code is made with ``secrets.choice``, shown once to an Odoo admin
(``base.group_system``), valid 15 minutes, kept in memory only. Only
``sha256("styd-bridge-pair-v1\\n" + code)`` travels to the hub. The hub hands the
secret down the held pair session; the module stores it, then proves it holds
it (``paired_ack``). On anything but ``pair_done`` the stored pairing is deleted.
"""

import datetime
import logging
import secrets
import threading
import time

import requests
from markupsafe import Markup

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError

from . import bridge_channel as channel
from . import bridge_channel_executor as executor_mod
from . import bridge_channel_protocol as proto

_logger = logging.getLogger(__name__)

PAIR_LABEL_MAX = 128
NOT_PAIRED_ALERT = datetime.timedelta(hours=24)


# ---------------------------------------------------------------------------
# the pair session (runs in a background thread)
# ---------------------------------------------------------------------------
def run_pair_session(store, hub, row_id, code_hash, owner_uid, info, life_s=proto.PAIR_CODE_LIFE_S,
                     stop_event=None):
    """Hold ``/bridge/v1/pair`` until the code is typed on STYD, the 15 minutes
    pass, or the admin cancels (the pending row is deleted). Returns one of
    "paired", "expired", "cancelled", "failed"."""
    stop_event = stop_event or threading.Event()
    deadline = time.monotonic() + life_s
    first = {
        "t": "pair",
        "protocol": list(proto.PROTOCOL_VERSIONS),
        "module_version": info["module_version"],
        "odoo_series": info["odoo_series"],
        "db_uuid": info["db_uuid"],
        "owner_uid": owner_uid,
        "code_hash": code_hash,
        # Shown by STYD in its confirm card before the user clicks Connect.
        "db_name": info.get("db_name") or "",
        "company_name": info.get("company_name") or "",
    }
    session = None
    failures = 0
    while time.monotonic() < deadline and not stop_event.is_set():
        row = store.get(row_id)
        if not row or row["state"] != "pending":
            return "cancelled"
        try:
            if session is None:
                status, data = hub.post(channel.PATH_PAIR, executor_mod.dumps(first).encode("utf-8"),
                                        timeout=channel.POST_TIMEOUT)
            else:
                status, data = hub.post(channel.PATH_PAIR,
                                        executor_mod.dumps({"t": "pair", "pair_session": session}).encode("utf-8"),
                                        timeout=channel.POLL_TIMEOUT)
        except requests.RequestException as exc:
            failures += 1
            _logger.info("STYD channel: pair poll failed (%s)", type(exc).__name__)
            stop_event.wait(proto.backoff_delay(failures))
            continue
        failures = 0
        data = data or {}
        kind = data.get("t")
        if status == 200 and kind == "pair_wait":
            ps = data.get("pair_session")
            if isinstance(ps, str) and proto.PAIR_SESSION_RE.match(ps):
                session = ps
                continue  # re-poll at once
        elif status == 200 and kind == "paired" and session and data.get("pair_session") == session:
            return _finish_pairing(store, hub, row_id, session, data)
        elif status == 410:
            store.delete(row_id)
            return "expired"
        elif status == 429:
            retry = data.get("retry_after_s")
            retry = retry if isinstance(retry, (int, float)) and retry > 0 else channel.DEFAULT_RETRY_AFTER_S
            store.write(row_id, {"status_code": data.get("code") or "pair_limit"})
            stop_event.wait(min(float(retry), max(0.0, deadline - time.monotonic())))
            continue
        code = data.get("code") or ("http_%s" % status)
        _logger.warning("STYD channel: pairing refused by the hub (status=%s, code=%s)", status, code)
        store.write(row_id, {"status_code": code, "pair_expires_at": fields.Datetime.now()})
        return "failed"
    store.delete(row_id)
    return "expired"


def _finish_pairing(store, hub, row_id, session, data):
    pairing_id = data.get("pairing_id")
    secret = data.get("secret")
    label = data.get("workspace_label")
    if not isinstance(pairing_id, str) or not proto.PAIRING_ID_RE.match(pairing_id) \
            or proto.secret_key(secret) is None:
        _logger.warning("STYD channel: malformed paired message; pairing dropped")
        store.delete(row_id)
        return "failed"
    label = label[:PAIR_LABEL_MAX] if isinstance(label, str) else ""
    # Store the pairing BEFORE sending the ack (section 5.3).
    stored = store.write(row_id, {
        "pairing_id": pairing_id,
        "secret": secret,
        "workspace_label": label,
        "state": "active",
        "paired_at": fields.Datetime.now(),
        "ack_confirmed": False,
        "pair_attempt": False,
        "pair_expires_at": False,
        "status_code": "pairing",
        "status_since": fields.Datetime.now(),
    })
    if not stored:
        return "cancelled"  # the admin cancelled: no ack, the hub stores nothing
    ack = {"t": "paired_ack", "pair_session": session, "pairing_id": pairing_id,
           "ack": proto.paired_ack(secret, pairing_id)}
    try:
        status, answer = hub.post(channel.PATH_PAIR, executor_mod.dumps(ack).encode("utf-8"),
                                  timeout=channel.POST_TIMEOUT)
    except requests.RequestException as exc:
        _logger.warning("STYD channel: paired_ack failed (%s)", type(exc).__name__)
        status, answer = None, None
    answer = answer or {}
    if status == 200 and answer.get("t") == "pair_done" and answer.get("pairing_id") == pairing_id:
        store.write(row_id, {"ack_confirmed": True, "status_code": "paired", "status_since": fields.Datetime.now()})
        _logger.info("STYD channel: paired (pairing %s)", pairing_id)
        return "paired"
    # On anything but pair_done, delete the stored pairing.
    store.delete(row_id)
    _logger.warning("STYD channel: pairing not confirmed by the hub (status=%s)", status)
    return "failed"


def _pair_thread(dbname, row_id, code_hash, owner_uid, hub, info):
    threading.current_thread().dbname = dbname
    store = channel.PairingStore(dbname)
    try:
        outcome = run_pair_session(store, hub, row_id, code_hash, owner_uid, info)
        if outcome == "paired":
            from odoo.modules.registry import Registry
            with Registry(dbname).cursor() as cr:
                api.Environment(cr, SUPERUSER_ID, {})["styd.odoo.bridge.channel"]._trigger_keeper()
    except Exception:
        _logger.exception("STYD channel: pair session crashed")


def start_pair_thread(dbname, row_id, code_hash, owner_uid, hub, info):
    t = threading.Thread(target=_pair_thread, args=(dbname, row_id, code_hash, owner_uid, hub, info),
                         daemon=True, name="styd-channel-pair")
    t.start()
    return t


# ---------------------------------------------------------------------------
# signed events from Odoo (unpair, rotate_request)
# ---------------------------------------------------------------------------
def send_event(hub, snapshot, payload):
    signer = channel.SignedClient(hub, snapshot["pairing_id"], lambda: snapshot["secret"],
                                  snapshot.get("clock_offset_ms"))
    try:
        return signer.post(channel.PATH_EVENT, payload, timeout=channel.POST_TIMEOUT)
    except requests.RequestException as exc:
        _logger.info("STYD channel: event post failed (%s)", type(exc).__name__)
        return None, None


def check_owner(user):
    """The owner must pass the member rule (section 7): active, internal, not uid 1."""
    if not user or user.id == SUPERUSER_ID or not user.active or user.share:
        raise UserError(_("The connector owner must be an active internal Odoo user."))


def hub_from_settings(env):
    settings = channel.read_settings(env)
    try:
        return channel.HubClient(settings["hub_url"], channel.resolve_verify(settings["ca_bundle"])), settings
    except ValueError as exc:
        raise UserError(_("Channel settings: %s", exc))


# ---------------------------------------------------------------------------
# the admin wizard
# ---------------------------------------------------------------------------
class StydOdooBridgeChannelWizard(models.TransientModel):
    _name = "styd.odoo.bridge.channel.wizard"
    _description = "Speak To Your Database: connect without opening a port"

    owner_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Connector owner",
        domain="[('share', '=', False)]",
        help="STYD reads as this Odoo user for its members who are not linked to an Odoo "
             "user, and only this user may read the user directory and the schema.",
    )
    pairing_choice = fields.Selection(selection="_selection_pairings", string="Pairing")
    pairings_html = fields.Html(compute="_compute_pairings_html", sanitize=False)
    bridge_enabled = fields.Boolean(compute="_compute_pairings_html")
    pair_code = fields.Char(compute="_compute_pair_code", string="Pairing code")
    has_pair_code = fields.Boolean(compute="_compute_pair_code")

    # -- helpers ----------------------------------------------------------------
    def _check_admin(self):
        if not self.env.user._is_system():
            raise AccessError(_("Only an Odoo administrator can pair this database with STYD."))

    def _pairings(self):
        return self.env["styd.odoo.bridge.pairing"].sudo()

    @api.model
    def _selection_pairings(self):
        if not self.env.user._is_system():
            return []
        out = []
        for p in self._pairings().search([("state", "in", ("active", "revoked"))]):
            label = p.workspace_label or p.pairing_id or "?"
            out.append((str(p.id), "%s (%s)" % (label, dict(p._fields["state"].selection).get(p.state))))
        return out

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        owner_id = self.env["styd.odoo.bridge.service"]._get_connector_owner_user_id()
        owner = self.env["res.users"].browse(owner_id).exists() if owner_id else self.env["res.users"]
        res["owner_user_id"] = (owner or self.env.user).id
        code = self.env.context.get("styd_pair_code") or ""
        # Odoo 15-18 fill a new form from default_get() only (computed fields
        # without dependencies are not recomputed), so give the display values here.
        display = {
            "pair_code": code or False,
            "has_pair_code": bool(code),
            "pairings_html": self._render_pairings() if self.env.user._is_system() else False,
            "bridge_enabled": executor_mod._truthy(
                self.env["ir.config_parameter"].sudo().get_param(executor_mod.ICP_ENABLED, "False")),
        }
        for fname, value in display.items():
            if fname in fields_list:
                res[fname] = value
        return res

    @api.depends_context("styd_pair_code")
    def _compute_pair_code(self):
        code = self.env.context.get("styd_pair_code") or ""
        for record in self:
            record.pair_code = code or False
            record.has_pair_code = bool(code)

    @api.depends_context("uid")
    def _compute_pairings_html(self):
        enabled = executor_mod._truthy(
            self.env["ir.config_parameter"].sudo().get_param(executor_mod.ICP_ENABLED, "False"))
        html = self._render_pairings() if self.env.user._is_system() else Markup("")
        for record in self:
            record.pairings_html = html
            record.bridge_enabled = enabled

    def _status_text(self, p):
        now = fields.Datetime.now()
        if p.state == "pending":
            if p.status_code and p.status_code not in ("pairing",):
                return _("Pairing failed (%s). Show a new code.", p.status_code)
            if p.pair_expires_at and p.pair_expires_at < now:
                return _("The code expired. Show a new code.")
            return _("Waiting for the code to be typed in STYD (until %s UTC).",
                     fields.Datetime.to_string(p.pair_expires_at) if p.pair_expires_at else "?")
        if p.state == "revoked":
            return _("Unpaired. Pair again to reconnect.")
        code = p.status_code or ""
        if code == "not_paired":
            if p.status_since and now - p.status_since > NOT_PAIRED_ALERT:
                return _("STYD does not know this pairing. Unpair it and pair again.")
            return _("STYD did not recognise this pairing; retrying every 10 minutes.")
        if code in ("module_too_old", "protocol_unsupported"):
            return _("Update the Bridge from the Odoo Apps store.")
        if code in ("ok", "paired"):
            return _("Connected.")
        return _("Connecting (%s).", code or "starting")

    def _render_pairings(self):
        rows = []
        for p in self._pairings().search([], order="id desc"):
            rows.append(Markup("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>") % (
                p.workspace_label or (p.pairing_id or "-"),
                dict(p._fields["state"].selection).get(p.state),
                fields.Datetime.to_string(p.last_seen_at) + " UTC" if p.last_seen_at else "-",
                self._status_text(p),
            ))
        if not rows:
            return Markup("<p class='text-muted'>%s</p>") % _("No pairing yet.")
        head = Markup("<thead><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr></thead>") % (
            _("STYD workspace"), _("State"), _("Last contact"), _("Status"))
        return Markup("<table class='table table-sm'>") + head + Markup("<tbody>") + Markup("").join(rows) \
            + Markup("</tbody></table>")

    def _reopen(self, code=None):
        action = {
            "type": "ir.actions.act_window",
            "name": _("Connect without opening a port"),
            "res_model": self._name,
            "view_mode": "form",
            "view_id": self.env.ref("styd_odoo_bridge.view_styd_bridge_channel_wizard_form").id,
            "target": "current",
        }
        if code:
            action["context"] = {"styd_pair_code": code}
        return action

    def _selected(self, states):
        self.ensure_one()
        if not self.pairing_choice:
            raise UserError(_("Choose a pairing first."))
        rec = self._pairings().browse(int(self.pairing_choice)).exists()
        if not rec or rec.state not in states:
            raise UserError(_("This pairing cannot do that in its current state."))
        return rec

    # -- buttons ----------------------------------------------------------------
    def action_refresh(self):
        self._check_admin()
        return self._reopen()

    def action_show_code(self):
        """Make a code, open a pair session in the background, show the code once."""
        self.ensure_one()
        self._check_admin()
        if not executor_mod._truthy(
                self.env["ir.config_parameter"].sudo().get_param(executor_mod.ICP_ENABLED, "False")):
            raise UserError(_("Enable the Bridge first (Connection Setup or Settings)."))
        owner = self.owner_user_id or self.env.user
        check_owner(owner)
        hub, settings = hub_from_settings(self.env)
        Pairing = self._pairings()
        # One pending code at a time: an older pair session sees its row gone and stops.
        Pairing.search([("state", "=", "pending")]).unlink()
        code = proto.new_pair_code()
        row = Pairing.create({
            "state": "pending",
            "owner_uid": owner.id,
            "pair_attempt": secrets.token_hex(8),
            "pair_expires_at": fields.Datetime.now() + datetime.timedelta(seconds=proto.PAIR_CODE_LIFE_S),
            "status_code": "pairing",
            "status_since": fields.Datetime.now(),
        })
        info = {
            "module_version": channel.module_version(),
            "odoo_series": channel.odoo_series(),
            "db_uuid": settings["db_uuid"],
            "db_name": self.env.cr.dbname,
            "company_name": owner.company_id.name or "",
        }
        dbname, row_id, code_hash = self.env.cr.dbname, row.id, proto.pair_code_hash(code)
        # Start only once the row is committed (the thread reads it).
        self.env.cr.postcommit.add(lambda: start_pair_thread(dbname, row_id, code_hash, owner.id, hub, info))
        return self._reopen(code=proto.format_pair_code(code))

    def action_cancel_code(self):
        self._check_admin()
        self._pairings().search([("state", "=", "pending")]).unlink()
        return self._reopen()

    def action_unpair(self):
        """Send the signed unpair event, then delete the secret and stop the stream."""
        self._check_admin()
        rec = self._selected(("active",))
        try:
            hub, _settings = hub_from_settings(self.env)
            status, _data = send_event(hub, rec._snapshot(), {"t": "event", "kind": "unpair", "reason": "admin"})
            if status != 200:
                _logger.warning("STYD channel: unpair event answered %s; revoked locally anyway", status)
        except UserError:
            _logger.warning("STYD channel: unpair event not sent (bad settings); revoked locally anyway")
        rec._revoke("admin")
        return self._reopen()

    def action_rotate(self):
        """Ask STYD for a new secret; it arrives signed down the stream."""
        self._check_admin()
        rec = self._selected(("active",))
        hub, _settings = hub_from_settings(self.env)
        status, data = send_event(hub, rec._snapshot(), {"t": "event", "kind": "rotate_request"})
        if status != 200:
            raise UserError(_("STYD did not accept the request (%s). Try again later.",
                              (data or {}).get("code") or status or _("no answer")))
        return self._reopen()

    def action_forget(self):
        self._check_admin()
        self._selected(("revoked",)).unlink()
        return self._reopen()
