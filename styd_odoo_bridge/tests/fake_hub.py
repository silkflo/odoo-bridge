"""A fake STYD hub for the module's tests (B2 protocol, the hub's side).

A real HTTP server on 127.0.0.1 (random port) speaking /bridge/v1/pair, /poll,
/result and /event: pair sessions and proof of possession, upstream signature,
timestamp and nonce checks, hello and held polls, results, pong, rotation and
unpair. Knobs force answers (``force``), skew the hub's clock, and short holds
keep the tests fast. Test code only.
"""

import base64
import json
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from odoo.addons.styd_odoo_bridge.models import bridge_channel_protocol as proto


def _rand_id(prefix):
    return prefix + base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")


def new_secret():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):  # keep the test output clean
        pass

    def do_POST(self):
        hub = self.server.hub
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        status, body = hub.handle(self.path, self.headers, raw)
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeHub:
    def __init__(self, hold_s=0.3, min_module_version="0.0.0"):
        self.hold_s = hold_s
        self.min_module_version = min_module_version
        self.clock_skew_ms = 0
        self.cond = threading.Condition()
        self.pairings = {}        # pairing_id -> {"secret", "state", "old", "old_until", "pending", "rotation_id"}
        self.sessions = {}        # pairing_id -> {"queue": [], "hello": {}, "held": 0}
        self.pair_sessions = {}   # ps -> {...}
        self.results = {}         # request id -> result
        self.events = []          # (pairing_id, body)
        self.hellos = []          # (pairing_id, hello)
        self.pair_opens = []      # first pair bodies
        self.refused = []         # (path, code)
        self.max_held = {}        # pairing_id -> max polls held at once
        self.forced = []          # [path, status, body, times]
        self.nonces = set()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.daemon_threads = True
        self.server.hub = self
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        self._thread = None

    # -- lifecycle -----------------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="fake-hub")
        self._thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def now_ms(self):
        return int(time.time() * 1000) + self.clock_skew_ms

    def _reply(self, status, body):
        body = dict(body)
        body["server_time"] = self.now_ms()
        return status, body

    def _error(self, status, code, **extra):
        body = {"t": "error", "code": code}
        body.update(extra)
        return self._reply(status, body)

    def wait_for(self, predicate, timeout=10.0):
        deadline = time.monotonic() + timeout
        with self.cond:
            while not predicate():
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self.cond.wait(min(left, 0.1))
            return True

    # -- knobs ------------------------------------------------------------------------
    def force(self, path, status, body, times=1, match=None):
        """Answer the next ``times`` requests to ``path`` (optionally only when
        ``match(body)`` is true) with ``status`` and ``body``."""
        with self.cond:
            self.forced.append([path, status, body, times, match])

    def add_pairing(self, pairing_id=None, secret=None):
        pairing_id = pairing_id or _rand_id("bp_")
        secret = secret or new_secret()
        with self.cond:
            self.pairings[pairing_id] = {"secret": secret, "state": "active", "old": None, "old_until": 0,
                                         "pending": None, "rotation_id": None}
        return pairing_id, secret

    def drop_sessions(self):
        """Like a hub restart: sessions are gone, pairings stay."""
        with self.cond:
            self.sessions.clear()
            self.cond.notify_all()

    def send(self, pairing_id, t="request", op="health", member_uid=2, args=None, args_json=None,
             secret=None, msg_id=None, ts=None, extra=None):
        """Sign and queue an envelope for the pairing's next poll. Returns its id."""
        with self.cond:
            rec = self.pairings[pairing_id]
            fields = {
                "v": 1,
                "id": msg_id or str(uuid.uuid4()),
                "ts": ts if ts is not None else self.now_ms(),
                "op": op,
                "member_uid": member_uid,
                "pairing_id": pairing_id,
                "args_json": args_json if args_json is not None else json.dumps(args or {}),
            }
            msg = dict(fields, t=t, sig=proto.sign_request(secret or rec["secret"], fields))
            if extra:
                msg.update(extra)
            self.sessions.setdefault(pairing_id, {"queue": [], "hello": None, "held": 0})["queue"].append(msg)
            self.cond.notify_all()
            return fields["id"]

    def queue_raw(self, pairing_id, msg):
        with self.cond:
            self.sessions.setdefault(pairing_id, {"queue": [], "hello": None, "held": 0})["queue"].append(msg)
            self.cond.notify_all()

    def rotate(self, pairing_id):
        """Send a rotate (signed with the current secret). Returns (rotation_id, new_secret)."""
        rotation_id = _rand_id("rt_")
        fresh = new_secret()
        with self.cond:
            rec = self.pairings[pairing_id]
            rec["pending"], rec["rotation_id"] = fresh, rotation_id
        self.send(pairing_id, t="rotate", op="control.rotate", member_uid=0,
                  args={"rotation_id": rotation_id, "new_secret": fresh})
        return rotation_id, fresh

    def claim(self, code, label="Acme", answer_ack=True):
        """STYD side: a user typed ``code``. Returns (pairing_id, secret) or None."""
        norm = proto.normalize_pair_code(code)
        if not norm:
            return None
        code_hash = proto.pair_code_hash(norm)
        with self.cond:
            for ps_id, ps in self.pair_sessions.items():
                if ps["code_hash"] == code_hash and not ps["claimed"]:
                    pairing_id, secret = _rand_id("bp_"), new_secret()
                    ps["claimed"] = True
                    ps["claim"] = {"pairing_id": pairing_id, "secret": secret}
                    ps["paired"] = {"t": "paired", "pair_session": ps_id, "pairing_id": pairing_id,
                                    "secret": secret, "workspace_label": label}
                    self.cond.notify_all()
                    return pairing_id, secret
        return None

    # -- request handling ---------------------------------------------------------------
    def _take_forced(self, path, body):
        with self.cond:
            for item in self.forced:
                if item[0] == path and item[3] > 0 and (item[4] is None or item[4](body)):
                    item[3] -= 1
                    return item[1], item[2]
        return None

    def handle(self, path, headers, raw):
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            body = None
        if path == "/bridge/v1/pair":
            forced = self._take_forced(path, body)
            if forced:
                return self._reply(*forced)
            return self._pair(body)
        if path not in proto.UP_PATHS:
            return 404, {"t": "error", "code": "not_found"}
        # signature headers (section 4.2)
        pairing_id = headers.get(proto.UP_HEADERS["pairing"])
        ts_text = headers.get(proto.UP_HEADERS["ts"]) or ""
        nonce = headers.get(proto.UP_HEADERS["nonce"]) or ""
        sig = headers.get(proto.UP_HEADERS["sig"])
        if not pairing_id or not ts_text.isdigit() or not proto.NONCE_RE.match(nonce) or not sig:
            return self._error(400, "bad_message")
        ts = int(ts_text)
        now = self.now_ms()
        with self.cond:
            rec = self.pairings.get(pairing_id)
            if not rec or rec["state"] != "active":
                self.refused.append((path, "not_paired"))
                return self._error(401, "not_paired")
            candidates = [rec["secret"], rec["pending"]]
            if rec["old"] and rec["old_until"] > now:
                candidates.append(rec["old"])
            if not any(c and proto.verify_upstream_sig(c, path, pairing_id, ts, nonce, raw, sig) for c in candidates):
                self.refused.append((path, "bad_signature"))
                return self._error(401, "bad_signature")
            if abs(now - ts) > proto.TS_WINDOW_MS:
                self.refused.append((path, "stale_request"))
                return self._error(401, "stale_request")
            key = (pairing_id, nonce)
            if key in self.nonces:
                self.refused.append((path, "replayed_request"))
                return self._error(401, "replayed_request")
            self.nonces.add(key)
            if path == "/bridge/v1/event":
                self.events.append((pairing_id, body or {}))
                self.cond.notify_all()
        forced = self._take_forced(path, body)
        if forced:
            return self._reply(*forced)
        if path == "/bridge/v1/poll":
            return self._poll(pairing_id, body)
        if path == "/bridge/v1/result":
            with self.cond:
                for r in (body or {}).get("results") or []:
                    self.results[r.get("id")] = r
                self.cond.notify_all()
            return self._reply(200, {"t": "ack", "accepted": len((body or {}).get("results") or []), "ignored": 0})
        return self._event(pairing_id, body or {})

    def _poll(self, pairing_id, body):
        body = body or {}
        with self.cond:
            if body.get("hello") is not None:
                hello = body["hello"]
                if proto.compare_versions(hello.get("module_version"), self.min_module_version) in (None, -1):
                    return self._error(426, "module_too_old")
                old = self.sessions.get(pairing_id)
                queue = old["queue"] if old else []
                self.sessions[pairing_id] = {"queue": queue, "hello": hello, "held": 0}
                self.hellos.append((pairing_id, hello))
                self.cond.notify_all()
                return self._reply(200, {"t": "batch", "messages": [{
                    "t": "version", "protocol": 1, "min_module_version": self.min_module_version,
                    "server_time": self.now_ms(), "poll_hold_s": 25, "pollers": 2, "heartbeat_s": 30,
                    "max_in_flight": 32,
                }]})
            session = self.sessions.get(pairing_id)
            if not session or session.get("hello") is None:
                return self._error(409, "hello_required")
            session["held"] += 1
            self.max_held[pairing_id] = max(self.max_held.get(pairing_id, 0), session["held"])
            self.cond.notify_all()
            try:
                deadline = time.monotonic() + self.hold_s
                while not session["queue"] and time.monotonic() < deadline \
                        and self.sessions.get(pairing_id) is session:
                    self.cond.wait(0.05)
                messages = session["queue"][:32]
                del session["queue"][:32]
            finally:
                session["held"] -= 1
            return self._reply(200, {"t": "batch", "messages": messages})

    def _event(self, pairing_id, body):
        with self.cond:
            rec = self.pairings[pairing_id]
            kind = body.get("kind")
            if kind == "unpair":
                rec["state"] = "revoked"
                self.sessions.pop(pairing_id, None)
                return self._reply(200, {"t": "ack"})
            if kind == "rotate_ack":
                if body.get("rotation_id") != rec["rotation_id"] or not rec["pending"]:
                    return self._error(400, "bad_message")
                expected = proto.rotate_proof(rec["pending"], pairing_id, rec["rotation_id"])
                if not proto.sig_equal(body.get("proof"), expected):
                    rec["pending"] = rec["rotation_id"] = None
                    return self._error(401, "bad_signature")
                rec["old"], rec["old_until"] = rec["secret"], self.now_ms() + proto.ROTATION_GRACE_MS
                rec["secret"], rec["pending"], rec["rotation_id"] = rec["pending"], None, None
                return self._reply(200, {"t": "ack"})
            if kind in ("pong", "rotate_request"):
                return self._reply(200, {"t": "ack"})
            return self._reply(200, {"t": "ack", "ignored": True})

    def _pair(self, body):
        if not isinstance(body, dict):
            return self._error(400, "bad_message")
        with self.cond:
            if body.get("t") == "pair" and "pair_session" not in body:
                if not isinstance(body.get("code_hash"), str) or not proto.HEX64_RE.match(body["code_hash"]):
                    return self._error(400, "bad_message", message="code_hash")
                if proto.compare_versions(body.get("module_version"), self.min_module_version) in (None, -1):
                    return self._error(426, "module_too_old")
                ps_id = _rand_id("ps_")
                self.pair_sessions[ps_id] = {"code_hash": body["code_hash"], "owner_uid": body.get("owner_uid"),
                                             "claimed": False, "claim": None, "paired": None, "acked": False,
                                             "expired": False}
                self.pair_opens.append(body)
                self.cond.notify_all()
                return self._reply(200, {"t": "pair_wait", "pair_session": ps_id, "expires_in_s": 900})
            ps = self.pair_sessions.get(body.get("pair_session"))
            if not ps or ps["expired"]:
                return self._error(410, "pair_expired")
            if body.get("t") == "pair":
                deadline = time.monotonic() + self.hold_s
                while not ps["paired"] and not ps["expired"] and time.monotonic() < deadline:
                    self.cond.wait(0.05)
                if ps["expired"]:
                    return self._error(410, "pair_expired")
                if ps["paired"]:
                    return self._reply(200, ps["paired"])
                return self._reply(200, {"t": "pair_wait", "pair_session": body["pair_session"], "expires_in_s": 600})
            if body.get("t") == "paired_ack":
                claim = ps["claim"]
                if not claim or body.get("pairing_id") != claim["pairing_id"]:
                    return self._error(400, "bad_message")
                if not proto.sig_equal(body.get("ack"), proto.paired_ack(claim["secret"], claim["pairing_id"])):
                    return self._error(401, "bad_signature")
                ps["acked"] = True
                ps["expired"] = True
                self.pairings[claim["pairing_id"]] = {"secret": claim["secret"], "state": "active", "old": None,
                                                      "old_until": 0, "pending": None, "rotation_id": None}
                self.cond.notify_all()
                return self._reply(200, {"t": "pair_done", "pairing_id": claim["pairing_id"]})
        return self._error(400, "bad_message")
