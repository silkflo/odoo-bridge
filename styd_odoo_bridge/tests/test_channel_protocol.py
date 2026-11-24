import json
import os
import uuid

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.styd_odoo_bridge.models import bridge_channel as channel
from odoo.addons.styd_odoo_bridge.models import bridge_channel_protocol as proto

VECTORS_PATH = os.path.join(os.path.dirname(__file__), "data", "b2_protocol_vectors.json")
SECRET_A = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
SECRET_B = "__79_Pv6-fj39vX08_Lx8O_u7ezr6uno5-bl5OPi4eA"
PAIRING_A = "bp_AAAAAAAAAAAAAAAAAAAAAA"


def _envelope(t="request", op="health", member_uid=7, secret=SECRET_A, ts=1795435200000, args_json="{}",
              pairing_id=PAIRING_A, msg_id=None):
    fields = {"v": 1, "id": msg_id or str(uuid.uuid4()), "ts": ts, "op": op, "member_uid": member_uid,
              "pairing_id": pairing_id, "args_json": args_json}
    return dict(fields, t=t, sig=proto.sign_request(secret, fields))


@tagged("post_install", "-at_install")
class TestChannelProtocolVectors(TransactionCase):
    """B2_PROTOCOL_VECTORS.json (the hub tests against the same file)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(VECTORS_PATH, encoding="utf-8") as fh:
            cls.vectors = json.load(fh)

    def test_01_secret_keys(self):
        for name, s in self.vectors["secrets"].items():
            self.assertEqual(proto.secret_key(s["secret"]).hex(), s["key_hex"], name)
        self.assertIsNone(proto.secret_key("short"))
        self.assertIsNone(proto.secret_key(SECRET_A + "="))

    def test_02_request_envelopes_verify(self):
        self.assertEqual(len(self.vectors["request_envelopes"]), 5)
        for e in self.vectors["request_envelopes"]:
            self.assertEqual(proto.request_sig_base(e["fields"]), e["sig_base"], e["name"])
            self.assertEqual(proto.sign_request(e["secret"], e["fields"]), e["sig"], e["name"])
            self.assertTrue(proto.verify_request_sig(e["secret"], e["fields"], e["sig"]), e["name"])

    def test_03_request_envelopes_invalid_fail(self):
        self.assertEqual(len(self.vectors["request_envelopes_invalid"]), 6)
        for e in self.vectors["request_envelopes_invalid"]:
            self.assertFalse(proto.verify_request_sig(e["secret"], e["fields"], e["sig"]), e["name"])

    def test_04_upstream_signatures(self):
        for u in self.vectors["upstream"]:
            base = proto.upstream_sig_base(u["path"], u["pairing_id"], u["ts"], u["nonce"], u["body"])
            self.assertEqual(base, u["sig_base"], u["name"])
            sig = proto.sign_upstream(u["secret"], u["path"], u["pairing_id"], u["ts"], u["nonce"],
                                      u["body"].encode("utf-8"))
            self.assertEqual(sig, u["sig"], u["name"])
            headers = proto.upstream_headers(u["secret"], u["path"], u["pairing_id"], u["ts"],
                                             u["body"].encode("utf-8"), nonce=u["nonce"])
            self.assertEqual(headers["X-Styd-Bridge-Sig"], u["sig"], u["name"])

    def test_05_pair_codes(self):
        for c in self.vectors["pair_codes"]:
            norm = proto.normalize_pair_code(c["input"])
            self.assertEqual(norm, c["normalized"], c["input"])
            self.assertEqual(proto.pair_code_hash(norm) if norm else None, c["code_hash"], c["input"])

    def test_06_paired_ack_and_rotate_proof(self):
        for a in self.vectors["paired_ack"]:
            self.assertEqual(proto.paired_ack(a["secret"], a["pairing_id"]), a["ack"])
        for r in self.vectors["rotate_proof"]:
            self.assertEqual(proto.rotate_proof(r["new_secret"], r["pairing_id"], r["rotation_id"]), r["proof"])

    def test_07_version_compare(self):
        for v in self.vectors["version_compare"]:
            self.assertEqual(proto.compare_versions(v["a"], v["b"]), v["expected"], (v["a"], v["b"]))
        self.assertEqual(proto.module_version_from_manifest("17.0.0.11.0"), "0.11.0")
        self.assertEqual(proto.module_version_from_manifest("17.0.0.10.1"), "0.10.1")


@tagged("post_install", "-at_install")
class TestChannelProtocolRules(TransactionCase):
    def test_10_new_pair_code(self):
        seen = set()
        for _i in range(50):
            code = proto.new_pair_code()
            self.assertEqual(len(code), 8)
            self.assertTrue(all(ch in proto.PAIR_CODE_ALPHABET for ch in code))
            self.assertEqual(proto.normalize_pair_code(proto.format_pair_code(code)), code)
            seen.add(code)
        self.assertGreater(len(seen), 45)
        for bad in "0O1IL":
            self.assertNotIn(bad, proto.PAIR_CODE_ALPHABET)

    def test_11_statement_timeout(self):
        self.assertEqual(proto.statement_timeout_ms(None), 19_000)
        self.assertEqual(proto.statement_timeout_ms(20_000), 19_000)
        self.assertEqual(proto.statement_timeout_ms(90_000), 59_000)
        self.assertEqual(proto.statement_timeout_ms(500_000), 59_000)
        self.assertEqual(proto.statement_timeout_ms(1_500), 1_000)
        self.assertEqual(proto.statement_timeout_ms(10), 1_000)
        self.assertEqual(proto.statement_timeout_ms("20000"), 19_000)
        self.assertEqual(proto.statement_timeout_ms(True), 19_000)

    def test_12_backoff(self):
        self.assertEqual([proto.backoff_base(n) for n in range(0, 9)], [0, 1, 2, 4, 8, 16, 32, 60, 60])
        for n in range(1, 10):
            base = proto.backoff_base(n)
            self.assertEqual(proto.backoff_delay(n, rand=0.0), base / 2.0)
            self.assertEqual(proto.backoff_delay(n, rand=1.0), float(base))
            d = proto.backoff_delay(n)
            self.assertTrue(base / 2.0 <= d <= base)

    def test_13_replay_cache(self):
        cache = proto.ReplayCache(ttl_ms=1000, max_entries=3)
        self.assertTrue(cache.check_and_add("a", 0))
        self.assertFalse(cache.check_and_add("a", 500))
        self.assertTrue(cache.check_and_add("a", 1601))  # expired after the ttl
        for key in "bcde":
            self.assertTrue(cache.check_and_add(key, 1700))
        self.assertNotIn("a", cache)  # oldest dropped first when full
        persisted = []
        cache = proto.ReplayCache(persist=lambda k, now: (persisted.append(k), k != "dup")[1])
        self.assertTrue(cache.check_and_add("x", 0))
        self.assertFalse(cache.check_and_add("dup", 0))  # another process stored it
        self.assertEqual(persisted, ["x", "dup"])

    def _check(self, msg, now=1795435200000, secrets=(SECRET_A,), replay=None, pairing_id=PAIRING_A):
        return proto.check_envelope(msg, pairing_id, list(secrets), now, replay or proto.ReplayCache())

    def _code(self, *args, **kwargs):
        with self.assertRaises(proto.ChannelError) as ctx:
            self._check(*args, **kwargs)
        return ctx.exception.code

    def test_14_check_order(self):
        good = _envelope()
        fields, args = self._check(good)
        self.assertEqual(fields["op"], "health")
        self.assertEqual(args, {})
        # 1. shape
        self.assertEqual(self._code(dict(good, id="not-a-uuid")), "bad_message")
        self.assertEqual(self._code(dict(good, member_uid="7")), "bad_message")
        self.assertEqual(self._code(dict(good, ts=True)), "bad_message")
        self.assertEqual(self._code({k: v for k, v in good.items() if k != "sig"}), "bad_message")
        # 2. pairing before signature: a message for another pairing, badly signed too
        other = _envelope(pairing_id="bp_BBBBBBBBBBBBBBBBBBBBBB", secret=SECRET_B)
        self.assertEqual(self._code(dict(other, sig="0" * 64)), "wrong_pairing")
        # 3. signature before timestamp
        stale_forged = dict(_envelope(ts=1), sig="0" * 64)
        self.assertEqual(self._code(stale_forged), "bad_signature")
        self.assertEqual(self._code(_envelope(secret=SECRET_B)), "bad_signature")
        # 4. timestamp window, +-120 s
        self.assertEqual(self._code(_envelope(ts=1795435200000 - 120_001)), "stale_request")
        self.assertEqual(self._code(_envelope(ts=1795435200000 + 120_001)), "stale_request")
        self._check(_envelope(ts=1795435200000 - 120_000))
        # 5. replay, recorded only after every check passed
        replay = proto.ReplayCache()
        msg_id = str(uuid.uuid4())
        forged = dict(_envelope(msg_id=msg_id), sig="f" * 64)
        self.assertEqual(self._code(forged, replay=replay), "bad_signature")
        self._check(_envelope(msg_id=msg_id), replay=replay)  # the forged copy did not fill the cache
        self.assertEqual(self._code(_envelope(msg_id=msg_id), replay=replay), "replayed_request")

    def test_15_t_and_op_agree(self):
        self.assertEqual(self._code(_envelope(t="request", op="control.ping", member_uid=0)), "bad_message")
        self.assertEqual(self._code(_envelope(t="ping", op="health", member_uid=0)), "bad_message")
        self.assertEqual(self._code(_envelope(t="ping", op="control.ping", member_uid=7)), "bad_message")
        self.assertEqual(self._code(_envelope(t="unpaired", op="control.rotate", member_uid=0)), "bad_message")
        self.assertEqual(self._code(_envelope(t="future", op="health")), "bad_message")
        for t, op in proto.CONTROL_OP_FOR_T.items():
            self._check(_envelope(t=t, op=op, member_uid=0))
        # an op outside the list passes the envelope checks; the executor refuses it
        fields, _args = self._check(_envelope(op="orm.write"))
        self.assertNotIn(fields["op"], proto.OPS)

    def test_16_args_hashed_as_received(self):
        spaced = '{ "model": "sale.order" }'
        fields, args = self._check(_envelope(op="orm.fields", args_json=spaced))
        self.assertEqual(args, {"model": "sale.order"})
        self.assertEqual(self._code(_envelope(args_json="[1, 2]")), "bad_message")

    def test_17_any_accepted_secret(self):
        """During a rotation and its grace both secrets verify."""
        self._check(_envelope(secret=SECRET_B), secrets=(SECRET_A, SECRET_B))
        self.assertEqual(self._code(_envelope(secret=SECRET_B), secrets=(SECRET_A, None)), "bad_signature")

    def test_18_hub_url_and_tls(self):
        self.assertEqual(channel.check_hub_url("https://hub.example.com/"), "https://hub.example.com")
        self.assertEqual(channel.check_hub_url("http://127.0.0.1:8080"), "http://127.0.0.1:8080")
        for bad in ("http://hub.example.com", "ftp://x", "https://hub.example.com/bridge",
                    "https://user:pw@hub.example.com", "https://hub.example.com?x=1", ""):
            with self.assertRaises(ValueError, msg=bad):
                channel.check_hub_url(bad)
        self.assertIs(channel.resolve_verify(""), True)
        self.assertIs(channel.resolve_verify(None), True)
        self.assertEqual(channel.resolve_verify(VECTORS_PATH), VECTORS_PATH)
        with self.assertRaises(ValueError):
            channel.resolve_verify("/nonexistent/ca.pem")
        with self.assertRaises(ValueError):
            channel.HubClient("https://hub.example.com", verify=False)
        client = channel.HubClient("https://hub.example.com", verify=True)
        self.assertIs(client._session().verify, True)
        client = channel.HubClient("https://hub.example.com", verify=VECTORS_PATH)
        self.assertEqual(client._session().verify, VECTORS_PATH)
