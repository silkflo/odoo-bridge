"""Bridge channel protocol, version 1: the wire formats, in one place.

Pure Python: no Odoo import, no I/O, no logging, no clock (callers pass
``now_ms``). The hub (STYD, TypeScript) implements the same functions; both
sides test against the same vectors (tests/data/b2_protocol_vectors.json).

    request signature   hex HMAC-SHA256(key, v|id|ts|op|member_uid|pairing_id|sha256hex(args_json))
    upstream signature  hex HMAC-SHA256(key, styd-bridge-up-v1|path|pairing_id|ts|nonce|sha256hex(body))
    pair code hash      sha256hex("styd-bridge-pair-v1\\n" + CODE)
    paired ack          hex HMAC-SHA256(key, "styd-bridge-paired-v1\\n" + pairing_id)
    rotate proof        hex HMAC-SHA256(new key, "styd-bridge-rotated-v1\\n" + pairing_id + "\\n" + rotation_id)

The secret is 32 random bytes sent once as base64url without padding; the
HMAC key is the 32 decoded bytes, never the text.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import threading
import urllib.parse
from collections import OrderedDict

PROTOCOL_VERSIONS = (1,)
ENVELOPE_V = 1

# The closed op list (spec section 7). Ops are additive: a name never changes meaning.
OPS = (
    "health",
    "security.snapshot",
    "users.directory",
    "users.search",
    "capabilities",
    "orm.models",
    "orm.fields",
    "orm.search_read",
    "orm.read_group",
)
# Ops that describe every user or the whole schema: run only for the pairing's owner uid.
OWNER_ONLY_OPS = frozenset({"security.snapshot", "users.directory", "users.search", "capabilities"})

# Control messages: their "t" and the op they must carry (section 4.1).
CONTROL_OP_FOR_T = {
    "ping": "control.ping",
    "rotate": "control.rotate",
    "unpaired": "control.unpaired",
}

# Discuss assistant (docs/DISCUSS_CONTRACT.md in this repository): messages from
# the hub that deliver an answer. Same envelope and signature as a request; the
# op is fixed by the "t" and member_uid is the asking Odoo user (>= 1).
DISCUSS_OP_FOR_T = {
    "discuss_answer": "discuss.answer",
}
# Additive capabilities announced in hello.features (the hub ignores unknown ones).
FEATURES = ("discuss.v1",)

TS_WINDOW_MS = 120_000
REPLAY_TTL_MS = 300_000
REPLAY_MAX = 10_000
ROTATION_GRACE_MS = 120_000

PAIR_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PAIR_CODE_LENGTH = 8
PAIR_CODE_LIFE_S = 900

# The public address sent in the first pair message and in every hello (``public_url``).
PUBLIC_URL_MAX = 2048

UP_PATHS = ("/bridge/v1/poll", "/bridge/v1/result", "/bridge/v1/event")
UP_HEADERS = {
    "pairing": "X-Styd-Bridge-Pairing",
    "ts": "X-Styd-Bridge-Ts",
    "nonce": "X-Styd-Bridge-Nonce",
    "sig": "X-Styd-Bridge-Sig",
}

PAIRING_ID_RE = re.compile(r"^bp_[A-Za-z0-9_-]{22}$")
PAIR_SESSION_RE = re.compile(r"^ps_[A-Za-z0-9_-]{22}$")
ROTATION_ID_RE = re.compile(r"^rt_[A-Za-z0-9_-]{22}$")
QUESTION_ID_RE = re.compile(r"^dq_[A-Za-z0-9_-]{22}$")
REQUEST_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
VERSION_RE = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")
ERROR_CODE_RE = re.compile(r"^[a-z_]{1,64}$")


class ChannelError(Exception):
    """A protocol-level refusal, carrying one of the spec's error codes (section 9)."""

    def __init__(self, code, message=None):
        super().__init__(code)
        self.code = code
        self.message = message or code


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------
def sha256hex(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _hmac_hex(key, text):
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()


def secret_key(secret):
    """The HMAC key of a secret: its 32 decoded bytes, or None when the text is not
    a 43-character base64url secret."""
    if not isinstance(secret, str) or not SECRET_RE.match(secret):
        return None
    try:
        key = base64.urlsafe_b64decode(secret + "=")
    except (binascii.Error, ValueError):
        return None
    return key if len(key) == 32 else None


def sig_equal(given, expected):
    """Constant-time equality of two lowercase hex signatures (False on any shape mismatch)."""
    if not isinstance(given, str) or not HEX64_RE.match(given) or not HEX64_RE.match(expected):
        return False
    return hmac.compare_digest(given.encode("ascii"), expected.encode("ascii"))


def new_nonce():
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")


def new_question_id():
    return "dq_" + base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")


def new_instance_id():
    return base64.urlsafe_b64encode(secrets.token_bytes(12)).decode("ascii").rstrip("=")


def _num(value):
    """Decimal text of an integer, no sign, padding or exponent."""
    return str(int(value))


# ---------------------------------------------------------------------------
# section 4.1: the request envelope (hub -> module)
# ---------------------------------------------------------------------------
ENVELOPE_FIELDS = ("v", "id", "ts", "op", "member_uid", "pairing_id", "args_json")


def request_sig_base(fields):
    return "|".join((
        _num(fields["v"]),
        fields["id"],
        _num(fields["ts"]),
        fields["op"],
        _num(fields["member_uid"]),
        fields["pairing_id"],
        sha256hex(fields["args_json"].encode("utf-8")),
    ))


def sign_request(secret, fields):
    key = secret_key(secret)
    if key is None:
        raise ValueError("bad secret")
    return _hmac_hex(key, request_sig_base(fields))


def verify_request_sig(secret, fields, sig):
    key = secret_key(secret)
    return key is not None and sig_equal(sig, _hmac_hex(key, request_sig_base(fields)))


# ---------------------------------------------------------------------------
# section 4.2: the upstream signature (module -> hub)
# ---------------------------------------------------------------------------
def upstream_sig_base(path, pairing_id, ts, nonce, body):
    if isinstance(body, str):
        body = body.encode("utf-8")
    return "|".join(("styd-bridge-up-v1", path, pairing_id, _num(ts), nonce, sha256hex(body)))


def sign_upstream(secret, path, pairing_id, ts, nonce, body):
    key = secret_key(secret)
    if key is None:
        raise ValueError("bad secret")
    return _hmac_hex(key, upstream_sig_base(path, pairing_id, ts, nonce, body))


def verify_upstream_sig(secret, path, pairing_id, ts, nonce, body, sig):
    """Used by the tests' fake hub."""
    key = secret_key(secret)
    return key is not None and sig_equal(sig, _hmac_hex(key, upstream_sig_base(path, pairing_id, ts, nonce, body)))


def upstream_headers(secret, path, pairing_id, ts, body, nonce=None):
    nonce = nonce or new_nonce()
    return {
        UP_HEADERS["pairing"]: pairing_id,
        UP_HEADERS["ts"]: _num(ts),
        UP_HEADERS["nonce"]: nonce,
        UP_HEADERS["sig"]: sign_upstream(secret, path, pairing_id, ts, nonce, body),
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# section 5: pairing
# ---------------------------------------------------------------------------
def new_pair_code():
    """8 characters of the alphabet, drawn with `secrets`."""
    return "".join(secrets.choice(PAIR_CODE_ALPHABET) for _ in range(PAIR_CODE_LENGTH))


def format_pair_code(code):
    return "%s-%s" % (code[:4], code[4:])


def normalize_pair_code(code):
    """Upper case, no spaces or dashes; None when it is not 8 characters of the alphabet."""
    if not isinstance(code, str) or len(code) > 32:
        return None
    norm = re.sub(r"[\s-]+", "", code.upper())
    if len(norm) != PAIR_CODE_LENGTH or any(ch not in PAIR_CODE_ALPHABET for ch in norm):
        return None
    return norm


def pair_code_hash(normalized_code):
    return sha256hex("styd-bridge-pair-v1\n" + normalized_code)


def paired_ack(secret, pairing_id):
    key = secret_key(secret)
    if key is None:
        raise ValueError("bad secret")
    return _hmac_hex(key, "styd-bridge-paired-v1\n" + pairing_id)


def rotate_proof(new_secret, pairing_id, rotation_id):
    key = secret_key(new_secret)
    if key is None:
        raise ValueError("bad secret")
    return _hmac_hex(key, "styd-bridge-rotated-v1\n%s\n%s" % (pairing_id, rotation_id))


def clean_public_url(value):
    """The address Odoo users open (``web.base.url``) as the module sends it: an
    absolute http(s) URL with no credentials, query or fragment, and no trailing
    slash. None when the value is not such an address."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or len(url) > PUBLIC_URL_MAX or any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host:
        return None
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        return None
    return "%s://%s%s" % (parts.scheme.lower(), parts.netloc, parts.path.rstrip("/"))


# ---------------------------------------------------------------------------
# section 8: versions
# ---------------------------------------------------------------------------
def compare_versions(a, b):
    """-1, 0 or 1 for "x.y.z" strings; None when either is not of that shape."""
    if not isinstance(a, str) or not isinstance(b, str) or not VERSION_RE.match(a) or not VERSION_RE.match(b):
        return None
    pa = [int(x) for x in a.split(".")]
    pb = [int(x) for x in b.split(".")]
    if pa == pb:
        return 0
    return -1 if pa < pb else 1


def module_version_from_manifest(version):
    """"17.0.0.11.0" -> "0.11.0" (the add-on's x.y.z without the Odoo series)."""
    parts = str(version or "").split(".")
    if len(parts) >= 5:
        return ".".join(parts[2:5])
    if len(parts) == 3:
        return ".".join(parts)
    return "0.0.0"


# ---------------------------------------------------------------------------
# section 4.3: checking an envelope from the hub
# ---------------------------------------------------------------------------
def _is_int(value, minimum=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


class ReplayCache:
    """Ids already accepted, for REPLAY_TTL_MS, at most REPLAY_MAX (oldest dropped first).

    ``persist`` (optional) is called with the id after the in-memory check passes; it
    returns False when the id was already stored by another process (the table that
    closes the gap after a leader change)."""

    def __init__(self, ttl_ms=REPLAY_TTL_MS, max_entries=REPLAY_MAX, persist=None):
        self.ttl_ms = ttl_ms
        self.max_entries = max_entries
        self.persist = persist
        self._seen = OrderedDict()
        self._lock = threading.Lock()

    def _expire(self, now_ms):
        while self._seen:
            key, at = next(iter(self._seen.items()))
            if now_ms - at <= self.ttl_ms and len(self._seen) <= self.max_entries:
                break
            self._seen.popitem(last=False)

    def __contains__(self, key):
        with self._lock:
            return key in self._seen

    def check_and_add(self, key, now_ms):
        """True when ``key`` is new (and records it); False when it is a replay."""
        with self._lock:
            self._expire(now_ms)
            if key in self._seen:
                return False
            self._seen[key] = now_ms
            self._expire(now_ms)
        if self.persist is not None and not self.persist(key, now_ms):
            return False
        return True


def parse_envelope_shape(msg):
    """Step 1 of section 4.3. Returns the signed fields, or raises ChannelError
    ("bad_message"). Also enforces that ``t`` and ``op`` agree."""
    if not isinstance(msg, dict):
        raise ChannelError("bad_message", "not an object")
    t = msg.get("t")
    fields = {k: msg.get(k) for k in ENVELOPE_FIELDS}
    if not _is_int(fields["v"], 1) or fields["v"] != ENVELOPE_V:
        raise ChannelError("bad_message", "v")
    if not isinstance(fields["id"], str) or not REQUEST_ID_RE.match(fields["id"]):
        raise ChannelError("bad_message", "id")
    if not _is_int(fields["ts"], 0):
        raise ChannelError("bad_message", "ts")
    if not isinstance(fields["op"], str) or not 0 < len(fields["op"]) <= 64:
        raise ChannelError("bad_message", "op")
    if not _is_int(fields["member_uid"], 0):
        raise ChannelError("bad_message", "member_uid")
    if not isinstance(fields["pairing_id"], str) or not PAIRING_ID_RE.match(fields["pairing_id"]):
        raise ChannelError("bad_message", "pairing_id")
    if not isinstance(fields["args_json"], str):
        raise ChannelError("bad_message", "args_json")
    if not isinstance(msg.get("sig"), str):
        raise ChannelError("bad_message", "sig")
    op = fields["op"]
    if t == "request":
        if op.startswith("control.") or op in DISCUSS_OP_FOR_T.values():
            raise ChannelError("bad_message", "t and op disagree")
    elif t in DISCUSS_OP_FOR_T:
        if op != DISCUSS_OP_FOR_T[t] or fields["member_uid"] < 1:
            raise ChannelError("bad_message", "t and op disagree")
    elif t in CONTROL_OP_FOR_T:
        if op != CONTROL_OP_FOR_T[t] or fields["member_uid"] != 0:
            raise ChannelError("bad_message", "t and op disagree")
    else:
        raise ChannelError("bad_message", "t")
    return fields


def check_envelope(msg, pairing_id, secrets_list, now_ms, replay):
    """Run the five checks of section 4.3 in order and return ``(fields, args)``.

    ``secrets_list``: every secret accepted right now (current, pending rotation,
    previous within its grace). ``replay``: a ReplayCache. The id is recorded only
    after every check passed, so a forged message cannot fill the cache.
    Raises ChannelError with the first failing code.
    """
    fields = parse_envelope_shape(msg)
    if fields["pairing_id"] != pairing_id:
        raise ChannelError("wrong_pairing")
    sig = msg.get("sig")
    if not any(s and verify_request_sig(s, fields, sig) for s in secrets_list):
        raise ChannelError("bad_signature")
    if abs(now_ms - fields["ts"]) > TS_WINDOW_MS:
        raise ChannelError("stale_request")
    if not replay.check_and_add(fields["id"], now_ms):
        raise ChannelError("replayed_request")
    # The string was hashed as received (above); only now is it parsed.
    try:
        args = json.loads(fields["args_json"])
    except ValueError:
        raise ChannelError("bad_message", "args_json is not JSON")
    if not isinstance(args, dict):
        raise ChannelError("bad_message", "args_json is not an object")
    return fields, args


# ---------------------------------------------------------------------------
# section 11: backoff and statement timeout
# ---------------------------------------------------------------------------
BACKOFF_MAX_S = 60
DEFAULT_CALL_TIMEOUT_MS = 20_000
MAX_CALL_TIMEOUT_MS = 90_000
MIN_CALL_TIMEOUT_MS = 1_000


def backoff_base(failures):
    """1, 2, 4, ... 60 s for the 1st, 2nd, 3rd... consecutive failure."""
    if failures <= 0:
        return 0
    return min(BACKOFF_MAX_S, 2 ** (failures - 1))


def backoff_delay(failures, rand=None):
    """Full jitter: a random wait between half and all of the base."""
    base = backoff_base(failures)
    if not base:
        return 0.0
    r = rand if rand is not None else secrets.SystemRandom().random()
    return base / 2.0 + (base / 2.0) * r


def statement_timeout_ms(timeout_ms):
    """min(timeout_ms, 60 000) - 1 000, at least 1 000 (timeout_ms advisory, clamped to 1..90 s)."""
    if not _is_int(timeout_ms, 0):
        timeout_ms = DEFAULT_CALL_TIMEOUT_MS
    timeout_ms = max(MIN_CALL_TIMEOUT_MS, min(MAX_CALL_TIMEOUT_MS, timeout_ms))
    return max(1_000, min(timeout_ms, 60_000) - 1_000)
