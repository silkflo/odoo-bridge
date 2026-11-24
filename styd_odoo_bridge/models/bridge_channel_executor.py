"""Bridge channel executor (B2 step M2): runs one verified request inside Odoo.

Each request:
  * runs in its own cursor, ``SET TRANSACTION READ ONLY`` and a local
    ``statement_timeout`` just under STYD's call timeout (section 11);
  * as the asking member's own Odoo user (``api.Environment(cr, uid, ctx)``, no
    sudo), with that user's companies, lang and tz, through the add-on's
    existing validators (``bridge_orm.py``);
  * answers what the matching ``/styd_bridge/v1/*`` route answers for the same
    input (status and JSON body), with ``access_mode`` "member_rights";
  * leaves one row in ``styd.odoo.bridge.access.log`` (never data).

Owner-only ops (directory, snapshot, search, capabilities) keep today's service
code (sudo inside, as the routes) and run only for the pairing's owner uid.
"""

import contextlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from odoo import SUPERUSER_ID, api
from odoo.exceptions import AccessError
from odoo.modules.registry import Registry

from . import bridge_channel_protocol as proto
from .bridge_orm import ORM_HR_MODELS, ORM_MEMBER_ACCESS_MODE, ORM_MEMBER_RIGHTS_CTX, StydOrmError, _json_default

_logger = logging.getLogger(__name__)

MEMBER_GROUP_XMLID = "styd_odoo_bridge.group_styd_member"
ICP_ENABLED = "styd_odoo_bridge.enabled"
ICP_RESTRICT_GROUP = "styd_odoo_bridge.channel_restrict_to_group"
AUDIT_DETAIL_MAX_LEN = 500
USERS_SEARCH_MAX_LEN = 128

ACCESS_DENIED_DETAIL = "The member's Odoo access rights do not allow this read."


def _truthy(raw):
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


def dumps(payload):
    """The routes' serialisation (same default for dates, bytes, Decimal)."""
    return json.dumps(payload, default=_json_default)


# ---------------------------------------------------------------------------
# limits (section 10): 4 threads, a queue of 16, 10 calls/s with bursts of 20
# ---------------------------------------------------------------------------
class TokenBucket:
    def __init__(self, rate=10.0, burst=20, clock=time.monotonic):
        self.rate = float(rate)
        self.burst = float(burst)
        self.tokens = float(burst)
        self.clock = clock
        self.last = clock()
        self._lock = threading.Lock()

    def take(self):
        with self._lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


class ChannelExecutor:
    """A bounded pool. ``try_submit`` returns False (the caller answers ``busy``)
    when the queue is full or the token bucket is empty."""

    def __init__(self, dbname, workers=4, queue_size=16, rate=10.0, burst=20):
        self.dbname = dbname
        self.capacity = workers + queue_size
        self.bucket = TokenBucket(rate, burst)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="styd-channel-exec")
        self._lock = threading.Lock()
        self._inflight = 0

    @property
    def inflight(self):
        return self._inflight

    def try_submit(self, fn, *args):
        with self._lock:
            if self._inflight >= self.capacity:
                return False
            if not self.bucket.take():
                return False
            self._inflight += 1
        try:
            self._pool.submit(self._run, fn, args)
        except RuntimeError:  # pool shut down
            with self._lock:
                self._inflight -= 1
            return False
        return True

    def _run(self, fn, args):
        threading.current_thread().dbname = self.dbname
        try:
            fn(*args)
        except Exception:
            _logger.exception("STYD channel: executor job failed")
        finally:
            with self._lock:
                self._inflight -= 1

    def shutdown(self, wait=False):
        self._pool.shutdown(wait=wait)


# ---------------------------------------------------------------------------
# the read-only cursor
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def readonly_cursor(registry, statement_ms):
    """A fresh cursor whose transaction PostgreSQL keeps read-only, with a local
    statement timeout. Always rolled back, never committed."""
    cr = registry.cursor()
    try:
        cr.execute("SET TRANSACTION READ ONLY")
        cr.execute("SELECT set_config('statement_timeout', %s, true)", (str(int(statement_ms)),))
        yield cr
    finally:
        try:
            cr.rollback()
        finally:
            cr.close()


# ---------------------------------------------------------------------------
# who may be asked as (section 7)
# ---------------------------------------------------------------------------
def check_member(su_env, member_uid, op, owner_uid):
    """Return the res.users record the op may run as, or raise ChannelError."""
    if not isinstance(member_uid, int) or isinstance(member_uid, bool) or member_uid < 1:
        raise proto.ChannelError("member_missing", "No usable member_uid.")
    if member_uid == SUPERUSER_ID:
        raise proto.ChannelError("member_not_allowed", "This Odoo user may not be asked as.")
    user = su_env["res.users"].with_context(active_test=False).browse(member_uid).exists()
    if not user or not user.active or user.share:
        raise proto.ChannelError("member_not_allowed", "This Odoo user may not be asked as.")
    icp = su_env["ir.config_parameter"]
    if _truthy(icp.get_param(ICP_RESTRICT_GROUP, "False")):
        group = su_env.ref(MEMBER_GROUP_XMLID, raise_if_not_found=False)
        if not group or group not in user.groups_id:
            raise proto.ChannelError("member_not_allowed", "This Odoo user is not in the Speak To Your Database group.")
    if op in proto.OWNER_ONLY_OPS and member_uid != owner_uid:
        raise proto.ChannelError("member_not_allowed", "Only the connector owner may run this read.")
    return user


def member_context(user, owner_uid):
    companies = [user.company_id.id] + [c for c in user.company_ids.ids if c != user.company_id.id]
    return {
        "allowed_company_ids": companies,
        "lang": user.lang or "en_US",
        "tz": user.tz or "UTC",
        ORM_MEMBER_RIGHTS_CTX: True,
        "styd_bridge_connector_owner_uid": owner_uid,
    }


# ---------------------------------------------------------------------------
# the ops: (status, body, row_count, detail) as the routes answer
# ---------------------------------------------------------------------------
def _err(status, code, detail=None):
    body = {"ok": False, "error": code}
    if detail:
        body["detail"] = detail
    return status, body


def _run_owner_op(su_env, op, args, owner_uid):
    service = su_env["styd.odoo.bridge.service"].with_context(styd_bridge_connector_owner_uid=owner_uid).sudo()
    if op == "health":
        try:
            return 200, service._build_health_payload(), None, None
        except Exception as exc:
            return _err(500, "health_build_failed", str(exc)) + (None, None)
    if op == "security.snapshot":
        try:
            return 200, service._build_security_snapshot_payload(), None, None
        except Exception as exc:
            return _err(500, "snapshot_build_failed", str(exc)) + (None, None)
    if op == "users.directory":
        try:
            payload = service._build_user_directory_snapshot_payload()
            return 200, payload, len(payload.get("users") or []), None
        except Exception as exc:
            return _err(500, "user_directory_build_failed", str(exc)) + (None, None)
    if op == "users.search":
        q = args.get("q")
        q = q[:USERS_SEARCH_MAX_LEN] if isinstance(q, str) else None
        try:
            payload = service._build_user_search_payload(q)
            return 200, payload, payload.get("count"), None
        except Exception as exc:
            return _err(500, "user_search_failed", str(exc)) + (None, None)
    if op == "capabilities":
        try:
            return 200, service._build_capability_snapshot_payload(), None, None
        except Exception as exc:
            return _err(500, "capability_snapshot_build_failed", str(exc)) + (None, None)
    raise proto.ChannelError("op_not_allowed")


def _run_member_op(env, op, args):
    orm = env["styd.odoo.bridge.orm"]
    model = args.get("model")
    detail = "model=%s" % str(model)[:64]
    try:
        if op == "orm.models":
            models_list = orm._orm_list_models()
            return 200, {"ok": True, "access_mode": ORM_MEMBER_ACCESS_MODE, "models": models_list}, len(models_list), None
        if op == "orm.fields":
            fields_list = orm._orm_model_fields(model)
            body = {"ok": True, "access_mode": ORM_MEMBER_ACCESS_MODE, "model": model, "fields": fields_list}
            return 200, body, len(fields_list), detail
        if op == "orm.search_read":
            result = orm._orm_search_read(
                model=model,
                domain=args.get("domain"),
                fields=args.get("fields"),
                limit=args.get("limit"),
                offset=args.get("offset"),
                order=args.get("order"),
                tz=args.get("tz"),
                tz_mode=args.get("tz_mode"),
                lang=args.get("lang"),
                company_ids=args.get("company_ids"),
            )
        else:
            result = orm._orm_read_group(
                model=model,
                domain=args.get("domain"),
                group_by=args.get("group_by"),
                aggregates=args.get("aggregates"),
                limit=args.get("limit"),
                order=args.get("order"),
                tz=args.get("tz"),
                tz_mode=args.get("tz_mode"),
                lang=args.get("lang"),
                company_ids=args.get("company_ids"),
            )
        body = {"ok": True, "access_mode": ORM_MEMBER_ACCESS_MODE, "model": model}
        body.update(result)
        return 200, body, result.get("returned_count"), detail
    except StydOrmError as exc:
        return _err(400, exc.code, exc.message) + (None, detail)
    except AccessError:
        return _err(403, "access_denied", ACCESS_DENIED_DETAIL) + (None, detail)
    except Exception as exc:
        _logger.warning("STYD channel: %s failed (model=%s, error_type=%s)", op, str(model)[:64], type(exc).__name__)
        message = {
            "orm.models": "Failed to list models.",
            "orm.fields": "Failed to read fields.",
        }.get(op, "Query failed.")
        return _err(500, "orm_error", message) + (None, detail)


DISCUSS_HR_SHARED_DETAIL = "HR is answered only in a direct message with the assistant."
DISCUSS_ACTIVE_STATES = ("pending", "sent")


def discuss_read_guard(su_env, pairing_id, user, args):
    """Reads STYD makes for a Discuss question carry ``discuss_question_id``
    (docs/DISCUSS_CONTRACT.md). They must be for an open question of this
    member on this pairing; in a conversation others can read, HR is refused.
    Returns a route-like refusal tuple, None to go on, or raises ChannelError."""
    qid = args.get("discuss_question_id")
    if qid is None:
        return None
    question = None
    if isinstance(qid, str) and proto.QUESTION_ID_RE.match(qid):
        question = su_env["styd.discuss.question"].sudo().search([("question_id", "=", qid)], limit=1)
    if not question or question.pairing_ref != pairing_id or question.user_id.id != user.id \
            or question.state not in DISCUSS_ACTIVE_STATES:
        raise proto.ChannelError("discuss_question_unknown",
                                 "This read is not for an open Discuss question of this member.")
    if question.shared and args.get("model") in ORM_HR_MODELS:
        return _err(400, "model_not_allowed", DISCUSS_HR_SHARED_DETAIL) + (None, "model=%s" % str(args.get("model"))[:64])
    return None


# ---------------------------------------------------------------------------
# one request, end to end
# ---------------------------------------------------------------------------
def execute_request(dbname, pairing, fields, args, timeout_ms=None, registry=None):
    """Run a verified request envelope and return its result message (section 6.3).

    ``pairing``: the pairing snapshot (``pairing_id``, ``owner_uid``).
    ``fields``: the envelope's signed fields. ``args``: the parsed args_json.
    """
    t0 = time.perf_counter()
    op = fields.get("op")
    member_uid = fields.get("member_uid")
    out = {"t": "result", "id": fields.get("id")}
    audit = {"outcome": "denied", "reason_code": None, "http_status": 0, "row_count": None, "detail": None}
    try:
        if op not in proto.OPS:
            raise proto.ChannelError("op_not_allowed", "This op is not served by the channel.")
        registry = registry or Registry(dbname)
        stmt_ms = proto.statement_timeout_ms(timeout_ms)
        with readonly_cursor(registry, stmt_ms) as cr:
            su_env = api.Environment(cr, SUPERUSER_ID, {})
            if not _truthy(su_env["ir.config_parameter"].get_param(ICP_ENABLED, "False")):
                raise proto.ChannelError("bridge_disabled", "The Bridge is switched off in Odoo.")
            user = check_member(su_env, member_uid, op, pairing.get("owner_uid"))
            if op == "health" or op in proto.OWNER_ONLY_OPS:
                status, body, rows, detail = _run_owner_op(su_env, op, args, pairing.get("owner_uid"))
            else:
                guarded = discuss_read_guard(su_env, pairing.get("pairing_id"), user, args)
                if guarded:
                    status, body, rows, detail = guarded
                else:
                    env = api.Environment(cr, user.id, member_context(user, pairing.get("owner_uid")))
                    status, body, rows, detail = _run_member_op(env, op, args)
        out.update(ok=True, status=status, body=body)
        audit.update(
            outcome="granted" if status == 200 else ("error" if status >= 500 else "denied"),
            reason_code="ok" if status == 200 else (body.get("error") if isinstance(body, dict) else "error"),
            http_status=status,
            row_count=rows,
            detail=detail,
        )
    except proto.ChannelError as exc:
        out.update(ok=False, error={"code": exc.code, "message": exc.message})
        audit.update(reason_code=exc.code)
    except Exception as exc:
        _logger.warning("STYD channel: request failed before the op ran (op=%s, error_type=%s)", op, type(exc).__name__)
        out.update(ok=False, error={"code": "module_error", "message": "The module could not run this request."})
        audit.update(outcome="error", reason_code="module_error")
    out["exec_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    write_audit(
        registry or Registry(dbname),
        op=op if isinstance(op, str) else "?",
        member_uid=member_uid if isinstance(member_uid, int) else 0,
        pairing_id=pairing.get("pairing_id"),
        duration_ms=out["exec_ms"],
        **audit,
    )
    return out


def refusal(request_id, code, message=None):
    """An ok:false result for a request the module did not run."""
    return {"t": "result", "id": request_id, "ok": False, "error": {"code": code, "message": message or code}, "exec_ms": 0.0}


def write_audit(registry, op, member_uid, pairing_id, duration_ms, outcome, reason_code, http_status,
                row_count=None, detail=None):
    """One audit row per op, on its own cursor (committed). Never raises."""
    try:
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["styd.odoo.bridge.access.log"].sudo().create({
                "endpoint": "channel:%s" % str(op)[:64],
                "method": "CHANNEL",
                "outcome": outcome,
                "reason_code": reason_code,
                "http_status": http_status or 0,
                "member_uid": member_uid or 0,
                "pairing_ref": pairing_id,
                "duration_ms": duration_ms,
                "row_count": row_count or 0,
                "detail": str(detail)[:AUDIT_DETAIL_MAX_LEN] if detail else None,
            })
    except Exception:
        _logger.exception("STYD channel: audit log write FAILED (op=%s, outcome=%s, reason=%s)", op, outcome, reason_code)
