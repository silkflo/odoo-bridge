"""Bridge outbound channel (B2 step M1): Odoo opens a connection OUT to STYD.

Shape (docs: STYD repo, docs/internal/bridge/B2_PROTOCOL.md):
  * a one-minute ``ir.cron`` watchdog (and a trigger at boot) calls
    ``ensure_runner(dbname)`` in whatever process runs crons;
  * ``ensure_runner`` starts at most one ``ChannelRunner`` daemon thread per
    process and database; that thread takes a PostgreSQL session advisory lock
    on its OWN connection (outside Odoo's pool, which cron workers close), so
    exactly one process per database talks to the hub;
  * the leader runs one ``PairingStream`` per active pairing: a hello, then two
    long-polls outstanding over HTTPS with ``requests``, with backoff and jitter,
    and the hub's clock offset;
  * every message from the hub is verified (signature, pairing, timestamp,
    replay) before anything runs; requests go to the executor
    (``bridge_channel_executor``), whose results are posted at once.

TLS is always verified (or against the custom CA bundle setting). There is no
switch to skip verification. ``HTTPS_PROXY`` is honoured by ``requests``.
"""

import datetime
import logging
import os
import threading
import time
import urllib.parse

import psycopg2
import requests

import odoo
from odoo import SUPERUSER_ID, api, models
from odoo import fields as odoo_fields
from odoo.modules.registry import Registry

from . import bridge_channel_executor as executor_mod
from . import bridge_channel_protocol as proto

_logger = logging.getLogger(__name__)

MODULE_NAME = "styd_odoo_bridge"
KEEPER_CRON_XMLID = "styd_odoo_bridge.ir_cron_styd_bridge_channel_keeper"

ICP_HUB_URL = "styd_odoo_bridge.channel_hub_url"
ICP_CA_BUNDLE = "styd_odoo_bridge.channel_ca_bundle"
DEFAULT_HUB_URL = "https://speaktoyourdatabase.com"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

PATH_PAIR = "/bridge/v1/pair"
PATH_POLL = "/bridge/v1/poll"
PATH_RESULT = "/bridge/v1/result"
PATH_EVENT = "/bridge/v1/event"

# pg_try_advisory_lock(bigint): one channel leader per database ("STYDB2").
LOCK_KEY = 0x535459444232

POLLERS = 2
POLL_TIMEOUT = (10, 40)    # hold 25 s + 15
POST_TIMEOUT = (10, 30)
REFRESH_S = 10             # leader: re-read pairings, settings (fresh), lock health
SEEN_GC_S = 60
STATUS_WRITE_S = 60        # last_seen_at written at most once a minute
NOT_PAIRED_RETRY_S = 600
TOO_OLD_RETRY_S = 3600
DEFAULT_RETRY_AFTER_S = 60

_RUNNERS = {}
_RUNNERS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------
def check_hub_url(url):
    """Normalised hub base URL, or ValueError. HTTPS only; plain http is accepted
    for a loopback host (development and the module's own tests)."""
    url = (url or "").strip()
    parts = urllib.parse.urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("The hub URL must be a plain https:// address.")
    if parts.path not in ("", "/"):
        raise ValueError("The hub URL must not contain a path.")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError("The hub URL has no host.")
    if parts.scheme == "https":
        pass
    elif parts.scheme == "http" and host in LOOPBACK_HOSTS:
        pass
    else:
        raise ValueError("The hub URL must start with https://.")
    return "%s://%s" % (parts.scheme, parts.netloc)


def resolve_verify(ca_bundle):
    """``True`` (system CAs) or the path of the custom CA bundle. Never False."""
    ca_bundle = (ca_bundle or "").strip()
    if not ca_bundle:
        return True
    if not os.path.isfile(ca_bundle) or not os.access(ca_bundle, os.R_OK):
        raise ValueError("The CA bundle file does not exist or cannot be read.")
    return ca_bundle


# The parameters the running leader must see within its tick (S4 open point 6).
# ``get_param`` is cached per process and the leader's process clears that cache
# only when it runs a cron job, so a corrected hub URL or CA bundle took up to
# 75 s. ``PairingStore.load`` reads these straight from the table instead.
FRESH_PARAMS = (
    executor_mod.ICP_ENABLED,
    ICP_HUB_URL,
    ICP_CA_BUNDLE,
    executor_mod.ICP_RATE,
    executor_mod.ICP_BURST,
)


def read_params_fresh(cr, keys=FRESH_PARAMS):
    """``{key: value}`` from ``ir_config_parameter`` itself, never the ORM cache."""
    cr.execute("SELECT key, value FROM ir_config_parameter WHERE key IN %s", (tuple(keys),))
    return dict(cr.fetchall())


def read_settings(env, fresh=False):
    """The channel settings. ``fresh``: the channel parameters come from the table
    (the leader's tick), not from the per-process ``get_param`` cache."""
    icp = env["ir.config_parameter"].sudo()
    if fresh:
        raw = read_params_fresh(env.cr)
        get = raw.get
    else:
        def get(key):
            return icp.get_param(key)
    return {
        "enabled": executor_mod._truthy(get(executor_mod.ICP_ENABLED) or "False"),
        "hub_url": get(ICP_HUB_URL) or DEFAULT_HUB_URL,
        "ca_bundle": get(ICP_CA_BUNDLE) or "",
        "rate": executor_mod.parse_limit(get(executor_mod.ICP_RATE), executor_mod.DEFAULT_RATE),
        "burst": executor_mod.parse_limit(get(executor_mod.ICP_BURST), executor_mod.DEFAULT_BURST),
        "db_uuid": icp.get_param("database.uuid", "") or "",
    }


def module_version():
    try:
        from odoo.modules.module import get_manifest
        manifest = get_manifest(MODULE_NAME) or {}
    except Exception:  # pragma: no cover - older helpers
        manifest = {}
    return proto.module_version_from_manifest(manifest.get("version"))


def odoo_series():
    return "%s.0" % odoo.release.version_info[0]


# ---------------------------------------------------------------------------
# HTTP to the hub
# ---------------------------------------------------------------------------
class HubClient:
    """POSTs to the hub; one ``requests.Session`` per thread (keep-alive)."""

    def __init__(self, base_url, verify=True):
        self.base_url = check_hub_url(base_url)
        if verify is False:  # defence in depth: there is no such setting
            raise ValueError("TLS verification cannot be switched off.")
        self.verify = verify
        self._local = threading.local()

    def _session(self):
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.verify = self.verify
            self._local.session = s
        return s

    def post(self, path, body, headers=None, timeout=POST_TIMEOUT):
        """Send ``body`` (bytes, sent as is) and return ``(status, json or None)``.
        Network errors raise ``requests.RequestException``."""
        hdrs = {"Content-Type": "application/json"}
        hdrs.update(headers or {})
        r = self._session().post(
            self.base_url + path,
            data=body,
            headers=hdrs,
            timeout=timeout,
            verify=self.verify,
            allow_redirects=False,
        )
        try:
            data = r.json()
        except ValueError:
            data = None
        return r.status_code, data if isinstance(data, dict) else None


class SignedClient:
    """Upstream signing (section 4.2) for one pairing, with the hub's clock offset."""

    def __init__(self, hub, pairing_id, secret_getter, offset_ms=0):
        self.hub = hub
        self.pairing_id = pairing_id
        self.secret_getter = secret_getter
        self.offset_ms = int(offset_ms or 0)

    def now_ms(self):
        return int(time.time() * 1000) + self.offset_ms

    def learn(self, data):
        st = data.get("server_time") if isinstance(data, dict) else None
        if isinstance(st, int) and not isinstance(st, bool) and st > 0:
            self.offset_ms = st - int(time.time() * 1000)

    def post(self, path, payload, timeout=POST_TIMEOUT, retry_stale=True):
        # Build the bytes once, sign them, send the same bytes (data=, never json=).
        body = executor_mod.dumps(payload).encode("utf-8")
        secret = self.secret_getter()
        headers = proto.upstream_headers(secret, path, self.pairing_id, self.now_ms(), body)
        status, data = self.hub.post(path, body, headers, timeout)
        self.learn(data)
        if retry_stale and status == 401 and (data or {}).get("code") == "stale_request":
            return self.post(path, payload, timeout, retry_stale=False)
        return status, data


# ---------------------------------------------------------------------------
# DB access for the threads (each call opens and closes its own cursor)
# ---------------------------------------------------------------------------
class PairingStore:
    def __init__(self, dbname, registry=None):
        self.dbname = dbname
        self._registry = registry

    @property
    def registry(self):
        return self._registry or Registry(self.dbname)

    def _env(self, cr):
        return api.Environment(cr, SUPERUSER_ID, {})

    def load(self):
        """Settings and the streamable pairings; None when the module is gone."""
        registry = self.registry
        if "styd.odoo.bridge.pairing" not in registry:
            return None
        with registry.cursor() as cr:
            cr.execute("SELECT state FROM ir_module_module WHERE name = %s", (MODULE_NAME,))
            row = cr.fetchone()
            if not row or row[0] not in ("installed", "to upgrade"):
                return None
            env = self._env(cr)
            settings = read_settings(env, fresh=True)
            Pairing = env["styd.odoo.bridge.pairing"].sudo()
            pairings = [p._snapshot() for p in Pairing.search(Pairing._streamable_domain())]
            return {"settings": settings, "pairings": pairings}

    def get(self, row_id):
        with self.registry.cursor() as cr:
            rec = self._env(cr)["styd.odoo.bridge.pairing"].sudo().browse(row_id).exists()
            return rec._snapshot() if rec else None

    def write(self, row_id, values):
        with self.registry.cursor() as cr:
            rec = self._env(cr)["styd.odoo.bridge.pairing"].sudo().browse(row_id).exists()
            if rec:
                rec.write(values)
            return bool(rec)

    def accepted_secrets(self, row_id):
        with self.registry.cursor() as cr:
            rec = self._env(cr)["styd.odoo.bridge.pairing"].sudo().browse(row_id).exists()
            return rec._accepted_secrets() if rec else []

    def revoke(self, row_id, reason):
        with self.registry.cursor() as cr:
            rec = self._env(cr)["styd.odoo.bridge.pairing"].sudo().browse(row_id).exists()
            if rec:
                rec._revoke(reason)

    def delete(self, row_id):
        with self.registry.cursor() as cr:
            self._env(cr)["styd.odoo.bridge.pairing"].sudo().browse(row_id).exists().unlink()

    def persist_seen(self, request_id, now_ms):
        try:
            with self.registry.cursor() as cr:
                return self._env(cr)["styd.odoo.bridge.channel.seen"]._record_raw(cr, request_id, now_ms)
        except Exception:
            # The table is a second line of defence; the in-memory cache already passed.
            _logger.warning("STYD channel: could not store a seen request id")
            return True

    def gc_seen(self, now_ms):
        with self.registry.cursor() as cr:
            self._env(cr)["styd.odoo.bridge.channel.seen"]._gc_raw(cr, now_ms)


# ---------------------------------------------------------------------------
# one pairing's stream
# ---------------------------------------------------------------------------
class PairingStream:
    def __init__(self, runner, snapshot):
        self.runner = runner
        self.dbname = runner.dbname
        self.pairing = dict(snapshot)
        self.row_id = snapshot["id"]
        self.pairing_id = snapshot["pairing_id"]
        self._plock = threading.Lock()
        self.signer = SignedClient(runner.hub, self.pairing_id, self.current_secret, snapshot.get("clock_offset_ms"))
        self.replay = proto.ReplayCache(persist=runner.store.persist_seen)
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self._hello_lock = threading.Lock()
        self._gen = 0
        self._state_lock = threading.Lock()
        self.failures = 0
        self.pause_until = 0.0
        self.version = None
        self.status = "starting"
        self._status_written = None
        self._last_seen_write = 0.0
        self.instance = proto.new_instance_id()
        self.threads = []
        self.stats = {"polls": 0, "requests": 0, "results": 0, "pongs": 0}

    # -- secrets ---------------------------------------------------------------
    def current_secret(self):
        with self._plock:
            return self.pairing.get("secret")

    def accepted_secrets(self):
        now = odoo_fields.Datetime.now()
        with self._plock:
            out = [self.pairing.get("secret"), self.pairing.get("pending_secret")]
            until = self.pairing.get("previous_secret_until")
            if self.pairing.get("previous_secret") and until and until > now:
                out.append(self.pairing.get("previous_secret"))
        return [s for s in out if s]

    def refresh(self, snapshot):
        """The leader re-read the row. Secrets are left alone: only this stream
        changes them (rotation), and a snapshot read just before a rotation must
        not undo it. An unpair elsewhere makes the row unwanted: the leader stops us."""
        with self._plock:
            for key in ("owner_uid", "workspace_label"):
                self.pairing[key] = snapshot.get(key)

    # -- lifecycle --------------------------------------------------------------
    def start(self):
        for idx in range(POLLERS):
            t = threading.Thread(
                target=self._poll_loop, args=(idx,), daemon=True,
                name="styd-channel-poll-%s-%d" % (self.pairing_id[-6:], idx),
            )
            t.start()
            self.threads.append(t)

    def stop(self):
        self.stop_event.set()
        self.ready.set()  # wake pollers waiting for a hello

    def alive(self):
        return any(t.is_alive() for t in self.threads)

    # -- the poll loop ------------------------------------------------------------
    def _wait(self, seconds):
        return self.stop_event.wait(max(0.0, seconds))

    def _poll_loop(self, idx):
        threading.current_thread().dbname = self.dbname
        while not self.stop_event.is_set():
            delay = self.pause_until - time.monotonic()
            if delay > 0:
                self._wait(min(delay, REFRESH_S))
                continue
            try:
                self.poll_once()
            except requests.RequestException as exc:
                _logger.info("STYD channel: poll failed (%s)", type(exc).__name__)
                self._fail("network")
            except Exception:
                _logger.exception("STYD channel: poll loop error")
                self._fail("module_error")

    def poll_once(self):
        if not self.ready.is_set():
            if not self._hello_lock.acquire(blocking=False):
                self.ready.wait(1.0)
                return
            try:
                if self.ready.is_set() or self.stop_event.is_set():
                    return
                gen = self._gen
                status, data = self.signer.post(PATH_POLL, {"t": "poll", "hello": self.hello()}, timeout=POLL_TIMEOUT)
                if self._handle_answer(status, data, gen, with_hello=True) and not self.stop_event.is_set():
                    with self._state_lock:
                        self._gen += 1
                    self.ready.set()
            finally:
                self._hello_lock.release()
            return
        gen = self._gen
        status, data = self.signer.post(PATH_POLL, {"t": "poll"}, timeout=POLL_TIMEOUT)
        self._handle_answer(status, data, gen)

    def hello(self):
        info = self.runner.info
        return {
            "t": "hello",
            "protocol": list(proto.PROTOCOL_VERSIONS),
            "module_version": info["module_version"],
            "odoo_series": info["odoo_series"],
            "db_uuid": info["db_uuid"],
            "ops": list(proto.OPS),
            "features": list(proto.FEATURES),
            "instance": self.instance,
        }

    def _session_lost(self, gen):
        """The hub has no session for us (409, 401, 426): the next poll says hello.
        Only for the session this poll belonged to, so a late 409 from an old
        session does not replace a fresh one."""
        with self._state_lock:
            if gen == self._gen:
                self.ready.clear()

    def _fail(self, code):
        self.failures += 1
        self.pause_until = time.monotonic() + proto.backoff_delay(self.failures)
        self._set_status(code)

    def _handle_answer(self, status, data, gen, with_hello=False):
        """Handle a poll answer; True when it was a good batch."""
        data = data or {}
        code = data.get("code")
        self.stats["polls"] += 1
        if status == 200 and data.get("t") == "batch":
            self.failures = 0
            self._set_status("ok", seen=True)
            if not self.stop_event.is_set():
                for msg in data.get("messages") or []:
                    self.dispatch(msg)
            return True
        if status == 409 and not with_hello:  # hello_required: resend at once with a hello
            self._session_lost(gen)
            return False
        if status == 401 and code == "not_paired":
            # Not an unpair (it can be a store hiccup): keep the pairing, retry in 10 min.
            self._session_lost(gen)
            self.pause_until = time.monotonic() + NOT_PAIRED_RETRY_S
            self._set_status("not_paired")
            return False
        if status == 426:
            self._session_lost(gen)
            self.pause_until = time.monotonic() + TOO_OLD_RETRY_S
            self._set_status(code if code in ("module_too_old", "protocol_unsupported") else "module_too_old")
            return False
        if status == 429:
            retry = data.get("retry_after_s")
            retry = retry if isinstance(retry, (int, float)) and retry > 0 else DEFAULT_RETRY_AFTER_S
            self.pause_until = time.monotonic() + min(float(retry), 3600.0)
            self._set_status(code or "rate_limited")
            return False
        if status == 401:
            self._session_lost(gen)
        self._fail(code or ("http_%s" % status))
        return False

    def _set_status(self, code, seen=False):
        self.status = code
        now = time.monotonic()
        changed = code != self._status_written
        due = seen and now - self._last_seen_write >= STATUS_WRITE_S
        if not changed and not due:
            return
        values = {"status_code": code, "clock_offset_ms": int(self.signer.offset_ms)}
        if changed:
            values["status_since"] = odoo_fields.Datetime.now()
        if seen:
            values["last_seen_at"] = odoo_fields.Datetime.now()
            self._last_seen_write = now
        try:
            self.runner.store.write(self.row_id, values)
            self._status_written = code
        except Exception:
            _logger.warning("STYD channel: could not write the pairing status")

    # -- messages from the hub ----------------------------------------------------
    def dispatch(self, msg):
        t = msg.get("t") if isinstance(msg, dict) else None
        if t == "version":
            self.version = msg
            return
        if t not in ("request",) + tuple(proto.CONTROL_OP_FOR_T) + tuple(proto.DISCUSS_OP_FOR_T):
            return  # unknown t: ignored (forward compatibility)
        try:
            fields, args = proto.check_envelope(
                msg, self.pairing_id, self.accepted_secrets(), self.signer.now_ms(), self.replay)
        except proto.ChannelError as exc:
            msg_id = msg.get("id")
            _logger.warning("STYD channel: refused a %s message (code=%s)", t, exc.code)
            answerable = exc.code in ("wrong_pairing", "bad_signature", "stale_request")
            if t == "request" and answerable and isinstance(msg_id, str) and proto.REQUEST_ID_RE.match(msg_id):
                self._spawn(self.post_results, [executor_mod.refusal(msg_id, exc.code)])
            # A replayed id is only logged: its first copy already has (or will have) its result.
            return
        self._maybe_promote_pending(msg, fields)
        if t == "request":
            self.stats["requests"] += 1
            if fields["op"] not in proto.OPS:
                self._spawn(self.post_results, [executor_mod.refusal(fields["id"], "op_not_allowed")])
                return
            if not self.runner.executor.try_submit(self._run_request, fields, args, msg.get("timeout_ms")):
                self._spawn(self.post_results, [executor_mod.refusal(fields["id"], "busy", "The Odoo module is busy.")])
            return
        if t == "discuss_answer":
            self._spawn(self.handle_discuss_answer, fields, args)
            return
        if t == "ping":
            self._spawn(self.post_event, {"t": "event", "kind": "pong", "id": fields["id"]})
            self.stats["pongs"] += 1
        elif t == "rotate":
            self._spawn(self.handle_rotate, fields, args)
        elif t == "unpaired":
            self.handle_unpaired()

    def _spawn(self, fn, *args):
        def target():
            threading.current_thread().dbname = self.dbname
            try:
                fn(*args)
            except Exception:
                _logger.exception("STYD channel: background step failed")
        threading.Thread(target=target, daemon=True, name="styd-channel-io").start()

    def _run_request(self, fields, args, timeout_ms):
        result = executor_mod.execute_request(
            self.dbname, self.pairing, fields, args, timeout_ms=timeout_ms, registry=self.runner.registry)
        self.post_results([result])

    def post_results(self, results):
        """Post as soon as each op ends; retry a failed post once."""
        payload = {"t": "results", "results": results}
        for attempt in (1, 2):
            try:
                status, _data = self.signer.post(PATH_RESULT, payload, timeout=POST_TIMEOUT)
                if status == 200:
                    self.stats["results"] += len(results)
                    return True
                _logger.info("STYD channel: result post answered %s (attempt %d)", status, attempt)
            except requests.RequestException as exc:
                _logger.info("STYD channel: result post failed (%s, attempt %d)", type(exc).__name__, attempt)
        return False

    def post_event(self, payload):
        try:
            return self.signer.post(PATH_EVENT, payload, timeout=POST_TIMEOUT)
        except requests.RequestException as exc:
            _logger.info("STYD channel: event post failed (%s)", type(exc).__name__)
            return None, None

    # -- rotation (section 6.6) -----------------------------------------------------
    def handle_rotate(self, fields, args):
        rotation_id = args.get("rotation_id")
        new_secret = args.get("new_secret")
        if not isinstance(rotation_id, str) or not proto.ROTATION_ID_RE.match(rotation_id) \
                or proto.secret_key(new_secret) is None:
            _logger.warning("STYD channel: malformed rotate message ignored")
            return
        old_secret = self.current_secret()
        # Store the new secret as pending (accepted for incoming envelopes) before acking.
        self.runner.store.write(self.row_id, {"pending_secret": new_secret, "pending_rotation_id": rotation_id})
        with self._plock:
            self.pairing["pending_secret"] = new_secret
            self.pairing["pending_rotation_id"] = rotation_id
        proof = proto.rotate_proof(new_secret, self.pairing_id, rotation_id)
        status, data = self.post_event({"t": "event", "kind": "rotate_ack", "rotation_id": rotation_id, "proof": proof})
        if status == 200 and (data or {}).get("t") == "ack" and not (data or {}).get("ignored"):
            self._switch_secret(new_secret, old_secret)
            _logger.info("STYD channel: secret rotated (pairing %s)", self.pairing_id)
            return
        if status is None:
            # No answer: the hub may or may not have switched. Keep signing with the
            # old secret, keep accepting the new one; the first hub message signed
            # only with the new one promotes it (see dispatch).
            _logger.warning("STYD channel: rotation ack got no answer; new secret kept pending")
            return
        # The hub refused the ack: keep the old secret.
        self.runner.store.write(self.row_id, {"pending_secret": False, "pending_rotation_id": False})
        with self._plock:
            self.pairing["pending_secret"] = None
            self.pairing["pending_rotation_id"] = None
        _logger.warning("STYD channel: rotation not acknowledged (status=%s)", status)

    def _switch_secret(self, new_secret, old_secret):
        until = odoo_fields.Datetime.now() + _timedelta_ms(proto.ROTATION_GRACE_MS)
        values = {
            "secret": new_secret,
            "previous_secret": old_secret,
            "previous_secret_until": until,
            "pending_secret": False,
            "pending_rotation_id": False,
        }
        self.runner.store.write(self.row_id, values)
        with self._plock:
            self.pairing.update(values)
            self.pairing["pending_secret"] = None
            self.pairing["pending_rotation_id"] = None

    def _maybe_promote_pending(self, msg, fields):
        """The hub signed with the pending secret only: it switched, so do we."""
        with self._plock:
            pending, current = self.pairing.get("pending_secret"), self.pairing.get("secret")
        if not pending or proto.verify_request_sig(current, fields, msg.get("sig")):
            return
        if proto.verify_request_sig(pending, fields, msg.get("sig")):
            self._switch_secret(pending, current)
            _logger.info("STYD channel: the hub uses the new secret; switched (pairing %s)", self.pairing_id)

    # -- Discuss assistant: an answer arrives (docs/DISCUSS_CONTRACT.md) -----------
    def handle_discuss_answer(self, fields, args):
        """Store a verified answer for the Discuss job and wake it; never posts
        in Discuss from this thread. Tells the hub what became of it."""
        code, question_id = discuss_deliver(self.runner.registry, self.pairing_id, fields["member_uid"], args)
        self.post_event({
            "t": "event", "kind": "discuss.delivered", "id": fields["id"],
            "question_id": question_id, "ok": code == "ok", "code": code,
        })

    # -- unpaired from STYD (section 6.7) -----------------------------------------
    def handle_unpaired(self):
        _logger.info("STYD channel: STYD unpaired this database (pairing %s)", self.pairing_id)
        self.runner.store.revoke(self.row_id, "styd")
        self.status = "revoked"
        self.stop()


def _timedelta_ms(ms):
    return datetime.timedelta(milliseconds=ms)


def discuss_deliver(registry, pairing_id, member_uid, args):
    """Hand a verified ``discuss_answer`` to the Discuss inbox, on its own cursor.
    Returns ``(code, question_id)``; code "ok" when stored."""
    question_id = args.get("question_id") if isinstance(args, dict) else None
    question_id = question_id if isinstance(question_id, str) and proto.QUESTION_ID_RE.match(question_id) else None
    try:
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            if "styd.discuss.inbox" not in env:
                return "discuss_unavailable", question_id
            return env["styd.discuss.inbox"].sudo()._deliver(pairing_id, member_uid, args), question_id
    except Exception:
        _logger.exception("STYD discuss: could not store an answer")
        return "module_error", question_id


# ---------------------------------------------------------------------------
# the leader thread
# ---------------------------------------------------------------------------
class ChannelRunner(threading.Thread):
    def __init__(self, dbname, registry=None, refresh_s=REFRESH_S):
        super().__init__(name="styd-channel-%s" % dbname, daemon=True)
        self.dbname = dbname
        self._registry = registry
        self.refresh_s = refresh_s
        self.store = PairingStore(dbname, registry)
        self.state = "starting"
        self.stop_event = threading.Event()
        self.lock_conn = None
        self.streams = {}
        self.all_streams = []  # every stream this runner started (joined by the tests)
        self.hub = None
        self.executor = None
        self.info = {"module_version": module_version(), "odoo_series": odoo_series(), "db_uuid": ""}
        self._hub_key = None
        self._last_gc = 0.0

    @property
    def registry(self):
        return self._registry or Registry(self.dbname)

    # -- leader election ---------------------------------------------------------
    def take_lock(self):
        _db, info = odoo.sql_db.connection_info_for(self.dbname)
        conn = psycopg2.connect(**info)
        conn.autocommit = True
        try:
            with conn.cursor() as cr:
                cr.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
                got = cr.fetchone()[0]
        except Exception:
            conn.close()
            raise
        if not got:
            conn.close()
            return False
        self.lock_conn = conn
        return True

    def lock_alive(self):
        if self.lock_conn is None or self.lock_conn.closed:
            return False
        try:
            with self.lock_conn.cursor() as cr:
                cr.execute("SELECT 1")
            return True
        except Exception:
            return False

    def release_lock(self):
        conn, self.lock_conn = self.lock_conn, None
        if conn is not None:
            try:
                conn.close()  # ends the session: the advisory lock goes with it
            except Exception:
                pass

    # -- main loop -----------------------------------------------------------------
    def run(self):
        threading.current_thread().dbname = self.dbname
        try:
            if not self.take_lock():
                self.state = "standby"
                _logger.info("STYD channel: pid=%s standby (another process holds the channel)", os.getpid())
                return
            self.state = "leader"
            _logger.info("STYD channel: pid=%s is the channel leader", os.getpid())
            self.executor = executor_mod.ChannelExecutor(self.dbname)  # limits set by each tick
            while not self.stop_event.is_set():
                if not self.lock_alive():
                    _logger.warning("STYD channel: lock connection lost, stopping")
                    break
                if not self.tick():
                    break
                self.stop_event.wait(self.refresh_s)
        except Exception:
            _logger.exception("STYD channel: runner crashed")
        finally:
            self.shutdown()

    def tick(self):
        """Reconcile streams with the database. False when the runner must stop."""
        loaded = self.store.load()
        if loaded is None:
            _logger.info("STYD channel: module not installed any more, stopping")
            return False
        settings = loaded["settings"]
        if not settings["enabled"]:
            _logger.info("STYD channel: the Bridge is switched off, stopping")
            return False
        if not loaded["pairings"]:
            return False
        self.info["db_uuid"] = settings["db_uuid"]
        if self.executor is not None:
            self.executor.set_limits(settings["rate"], settings["burst"])
        hub_key = (settings["hub_url"], settings["ca_bundle"])
        if hub_key != self._hub_key:
            try:
                self.hub = HubClient(settings["hub_url"], resolve_verify(settings["ca_bundle"]))
            except ValueError as exc:
                _logger.warning("STYD channel: bad channel settings: %s", exc)
                return False
            self._hub_key = hub_key
            self.stop_streams()
        wanted = {p["pairing_id"]: p for p in loaded["pairings"]}
        for pairing_id, stream in list(self.streams.items()):
            if pairing_id not in wanted or stream.stop_event.is_set():
                stream.stop()
                del self.streams[pairing_id]
            else:
                stream.refresh(wanted[pairing_id])
        for pairing_id, snapshot in wanted.items():
            if pairing_id not in self.streams:
                stream = PairingStream(self, snapshot)
                self.streams[pairing_id] = stream
                self.all_streams.append(stream)
                stream.start()
        now = time.monotonic()
        if now - self._last_gc >= SEEN_GC_S:
            self._last_gc = now
            try:
                self.store.gc_seen(int(time.time() * 1000))
            except Exception:
                _logger.warning("STYD channel: could not clean the seen ids")
        return True

    def stop_streams(self):
        for stream in self.streams.values():
            stream.stop()
        self.streams = {}

    def stop(self):
        self.stop_event.set()

    def shutdown(self):
        self.stop_streams()
        if self.executor is not None:
            self.executor.shutdown(wait=False)
        self.release_lock()
        if self.state == "leader":
            self.state = "stopped"


def ensure_runner(dbname):
    """Start the channel thread for ``dbname`` in THIS process if none is alive."""
    with _RUNNERS_LOCK:
        runner = _RUNNERS.get(dbname)
        if runner and runner.is_alive():
            return runner.state
        runner = ChannelRunner(dbname)
        _RUNNERS[dbname] = runner
        runner.start()
        return "started"


def stop_runner(dbname):
    with _RUNNERS_LOCK:
        runner = _RUNNERS.pop(dbname, None)
    if runner:
        runner.stop()


# ---------------------------------------------------------------------------
# the keeper
# ---------------------------------------------------------------------------
class StydOdooBridgeChannel(models.AbstractModel):
    _name = "styd.odoo.bridge.channel"
    _description = "Speak To Your Database outbound channel keeper"

    @api.model
    def _channel_wanted(self):
        if not executor_mod._truthy(
                self.env["ir.config_parameter"].sudo().get_param(executor_mod.ICP_ENABLED, "False")):
            return False
        Pairing = self.env["styd.odoo.bridge.pairing"].sudo()
        return bool(Pairing.search_count([("state", "=", "active")]))

    @api.model
    def _cron_keeper(self):
        """Every minute: make sure ONE channel thread runs for this database
        (the advisory lock decides which process). Returns at once."""
        if not self._channel_wanted():
            return "idle"
        state = ensure_runner(self.env.cr.dbname)
        _logger.debug("STYD channel keeper: pid=%s state=%s", os.getpid(), state)
        return state

    @api.model
    def _trigger_keeper(self):
        cron = self.env.ref(KEEPER_CRON_XMLID, raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        return bool(cron)

    def _register_hook(self):
        """At boot: ask a cron runner to run the keeper now instead of within a
        minute. Never starts a thread here (the prefork master closes its
        connections after preloading)."""
        res = super()._register_hook()
        try:
            with self.env.cr.savepoint():
                if self._channel_wanted():
                    self._trigger_keeper()
        except Exception:
            _logger.warning("STYD channel: could not trigger the keeper at boot")
        return res
