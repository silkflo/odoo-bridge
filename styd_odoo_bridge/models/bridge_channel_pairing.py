"""Storage of the outbound channel: pairings (with their secret) and seen request ids.

Neither model has an ``ir.model.access`` row, on purpose: no group can read them
through the ORM, the web client or XML-RPC. Only module code reads them, with
``sudo()``. Admins see a pairing's label, state and last contact through the
channel wizard, which copies those fields (never the secret) into its own form.
"""

import datetime
import logging
import time

from odoo import api, fields, models

from . import bridge_channel_protocol as proto

_logger = logging.getLogger(__name__)


class StydOdooBridgePairing(models.Model):
    _name = "styd.odoo.bridge.pairing"
    _description = "Speak To Your Database outbound channel pairing"
    _order = "id desc"
    _rec_name = "workspace_label"

    pairing_id = fields.Char(index=True, copy=False, readonly=True)
    state = fields.Selection(
        selection=[
            ("pending", "Waiting for the code"),
            ("active", "Paired"),
            ("revoked", "Unpaired"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    workspace_label = fields.Char(readonly=True)
    owner_uid = fields.Integer(
        string="Connector owner uid",
        help="Odoo user id STYD sends for members not linked to an Odoo user, and the "
             "only uid the owner-only reads (directory, snapshot, capabilities) run for.",
    )

    # Secrets: never shown, never logged, never in ir.config_parameter.
    secret = fields.Char(copy=False, prefetch=False)
    pending_secret = fields.Char(copy=False, prefetch=False)
    pending_rotation_id = fields.Char(copy=False)
    previous_secret = fields.Char(copy=False, prefetch=False)
    previous_secret_until = fields.Datetime(copy=False)

    # Pair session (state "pending"): the code itself lives only in memory.
    pair_attempt = fields.Char(index=True, copy=False)
    pair_expires_at = fields.Datetime(copy=False)
    ack_confirmed = fields.Boolean(
        copy=False,
        help="The hub confirmed the proof of possession (pair_done).",
    )

    paired_at = fields.Datetime(copy=False)
    revoked_at = fields.Datetime(copy=False)
    revoked_reason = fields.Char(copy=False)
    last_seen_at = fields.Datetime(string="Last contact with STYD", copy=False)
    status_code = fields.Char(copy=False, help="Last channel condition, e.g. ok, not_paired, module_too_old.")
    status_since = fields.Datetime(copy=False)
    clock_offset_ms = fields.Integer(copy=False, help="STYD's clock minus this server's clock, last measured.")

    _pairing_id_unique = models.Constraint("unique(pairing_id)", "A pairing id is stored once.")

    # ------------------------------------------------------------------
    # Helpers used by the channel (always on a sudo recordset)
    # ------------------------------------------------------------------
    def _accepted_secrets(self, now=None):
        """Secrets an envelope from the hub may be signed with right now."""
        self.ensure_one()
        now = now or fields.Datetime.now()
        out = [self.secret, self.pending_secret]
        if self.previous_secret and self.previous_secret_until and self.previous_secret_until > now:
            out.append(self.previous_secret)
        return [s for s in out if s]

    def _snapshot(self):
        """Plain values the channel threads keep (no ORM record crosses threads)."""
        self.ensure_one()
        return {
            "id": self.id,
            "state": self.state,
            "pair_attempt": self.pair_attempt,
            "pairing_id": self.pairing_id,
            "owner_uid": self.owner_uid,
            "workspace_label": self.workspace_label,
            "secret": self.secret,
            "pending_secret": self.pending_secret,
            "pending_rotation_id": self.pending_rotation_id,
            "previous_secret": self.previous_secret,
            "previous_secret_until": self.previous_secret_until,
            "clock_offset_ms": self.clock_offset_ms or 0,
        }

    @api.model
    def _streamable_domain(self):
        """Active pairings the leader streams: the hub confirmed the ack, or the ack
        went out long enough ago that a crash between storing and pair_done must
        not leave the pairing unused (section 5.3)."""
        grace = fields.Datetime.now() - datetime.timedelta(seconds=60)
        return [
            ("state", "=", "active"),
            ("pairing_id", "!=", False),
            ("secret", "!=", False),
            "|", ("ack_confirmed", "=", True), ("paired_at", "<", grace),
        ]

    def _revoke(self, reason):
        """Unpaired (either side): drop every secret, keep the row to show "pair again"."""
        self.write({
            "state": "revoked",
            "secret": False,
            "pending_secret": False,
            "pending_rotation_id": False,
            "previous_secret": False,
            "previous_secret_until": False,
            "revoked_at": fields.Datetime.now(),
            "revoked_reason": reason,
            "status_code": "revoked",
            "status_since": fields.Datetime.now(),
        })

    @api.autovacuum
    def _gc_expired_pair_sessions(self):
        """Pending rows whose 15 minutes passed (the thread normally removes them)."""
        stale = self.sudo().search([
            ("state", "=", "pending"),
            ("pair_expires_at", "<", fields.Datetime.now() - datetime.timedelta(minutes=5)),
        ])
        stale.unlink()


class StydOdooBridgeChannelSeen(models.Model):
    """Request ids the module already accepted, for 300 s (section 4.3).

    Closes the replay gap after a leader change: a new leader checks this table
    as well as its in-memory cache. Rows are removed by the leader every minute
    and by the daily autovacuum as a backstop.
    """

    _name = "styd.odoo.bridge.channel.seen"
    _description = "Speak To Your Database channel: seen request ids"
    _log_access = False

    request_id = fields.Char(required=True, index=True)
    seen_ms = fields.Float(required=True, digits=(16, 0))

    _request_id_unique = models.Constraint("unique(request_id)", "A request id is stored once.")

    @api.model
    def _record_raw(self, cr, request_id, now_ms):
        """Insert on ``cr`` (a fresh cursor of the caller). True when the id is new."""
        cr.execute(
            "INSERT INTO styd_odoo_bridge_channel_seen (request_id, seen_ms) VALUES (%s, %s) "
            "ON CONFLICT (request_id) DO NOTHING RETURNING id",
            (request_id, now_ms),
        )
        return bool(cr.fetchone())

    @api.model
    def _gc_raw(self, cr, now_ms):
        cr.execute(
            "DELETE FROM styd_odoo_bridge_channel_seen WHERE seen_ms < %s",
            (now_ms - proto.REPLAY_TTL_MS,),
        )

    @api.autovacuum
    def _gc_seen(self):
        self._gc_raw(self.env.cr, int(time.time() * 1000))
