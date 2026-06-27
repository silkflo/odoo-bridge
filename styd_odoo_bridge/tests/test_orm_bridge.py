from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.styd_odoo_bridge.models.bridge_orm import StydOrmError


@tagged("post_install", "-at_install")
class TestStydOrmBridge(TransactionCase):
    """Unit tests for the read-only ORM bridge validators (Phase 5B).

    These exercise the service-layer logic directly (no HTTP), so they run in
    the module's test DB which only has `base`. res.partner is therefore the
    only allowlisted model present; sale.order / account.move queries are
    covered by the manual curl checks against the sandbox.
    """

    def setUp(self):
        super().setUp()
        self.orm = self.env["styd.odoo.bridge.orm"]

    # 1. /models returns only allowlisted models
    def test_01_list_models_allowlist_only(self):
        models = self.orm.orm_list_models()
        names = {m["model"] for m in models}
        self.assertTrue(names.issubset(self.orm.MODEL_ALLOWLIST))
        self.assertNotIn("res.users", names)
        self.assertNotIn("ir.config_parameter", names)
        self.assertIn("res.partner", names)
        for m in models:
            self.assertTrue(m["allowed"])
            self.assertIn("label", m)
            self.assertIn("transient", m)

    # 2. /models/<model>/fields returns safe field metadata
    def test_02_model_fields_metadata(self):
        fields = self.orm.orm_model_fields("res.partner")
        by_name = {f["name"]: f for f in fields}
        self.assertIn("name", by_name)
        self.assertIn("email", by_name)
        for key in ("name", "string", "type", "store", "searchable", "groupable"):
            self.assertIn(key, by_name["name"])

    # 3. forbidden field names are stripped
    def test_03_forbidden_fields_stripped(self):
        self.assertTrue(self.orm._orm_is_forbidden_field("password"))
        self.assertTrue(self.orm._orm_is_forbidden_field("oauth_access_token"))
        self.assertTrue(self.orm._orm_is_forbidden_field("api_key"))
        self.assertFalse(self.orm._orm_is_forbidden_field("name"))
        # "auth" refinement: credential-style auth blocked, benign words allowed
        self.assertTrue(self.orm._orm_is_forbidden_field("auth"))
        self.assertTrue(self.orm._orm_is_forbidden_field("auth_token"))
        self.assertFalse(self.orm._orm_is_forbidden_field("author_id"))
        self.assertFalse(self.orm._orm_is_forbidden_field("authorized_transaction_ids"))
        self.assertFalse(self.orm._orm_is_forbidden_field("authority_id"))
        for f in self.orm.orm_model_fields("res.partner"):
            low = f["name"].lower()
            for bad in self.orm.FORBIDDEN_FIELD_SUBSTRINGS:
                self.assertNotIn(bad, low)

    # 4. blocked model returns model_not_allowed
    def test_04_blocked_model(self):
        with self.assertRaises(StydOrmError) as cm:
            self.orm.orm_model_fields("res.users")
        self.assertEqual(cm.exception.code, "model_not_allowed")
        with self.assertRaises(StydOrmError) as cm2:
            self.orm.orm_search_read("ir.config_parameter", fields=["key"])
        self.assertEqual(cm2.exception.code, "model_not_allowed")

    # 5. search-read works for res.partner with safe fields
    def test_05_search_read_partner_safe(self):
        self.env["res.partner"].create({"name": "STYD Test Partner"})
        result = self.orm.orm_search_read(
            "res.partner",
            domain=[["name", "=", "STYD Test Partner"]],
            fields=["name", "email"],
            limit=10,
        )
        self.assertIn("records", result)
        self.assertGreaterEqual(result["returned_count"], 1)
        self.assertEqual(result["limit"], 10)
        self.assertTrue(set(result["records"][0].keys()).issubset({"id", "name", "email"}))

    # 6. search-read rejects unsupported domain/operator
    def test_06_search_read_rejects_bad_domain(self):
        with self.assertRaises(StydOrmError) as cm:
            self.orm.orm_search_read("res.partner", domain=[["name", "child_of", 1]], fields=["name"])
        self.assertEqual(cm.exception.code, "operator_not_allowed")
        with self.assertRaises(StydOrmError) as cm2:
            self.orm.orm_search_read("res.partner", domain=[["password", "=", "x"]], fields=["name"])
        self.assertEqual(cm2.exception.code, "field_not_allowed")
        with self.assertRaises(StydOrmError) as cm3:
            self.orm.orm_search_read("res.partner", domain="not-a-list", fields=["name"])
        self.assertEqual(cm3.exception.code, "domain_invalid")

    # 7. search-read caps/rejects too-large limit
    def test_07_search_read_limit_exceeded(self):
        with self.assertRaises(StydOrmError) as cm:
            self.orm.orm_search_read("res.partner", fields=["name"], limit=999)
        self.assertEqual(cm.exception.code, "limit_exceeded")

    # 8. read-group works
    def test_08_read_group_partner(self):
        self.env["res.partner"].create({"name": "STYD G1", "company_type": "company"})
        result = self.orm.orm_read_group(
            "res.partner",
            domain=[],
            group_by=["company_type"],
            aggregates=[],
        )
        self.assertIn("groups", result)
        self.assertEqual(result["group_by"], ["company_type"])
        for g in result["groups"]:
            self.assertIn("count", g)
            self.assertIn("company_type", g)

    # 9. read-group rejects unsafe aggregate/group fields
    def test_09_read_group_rejects_unsafe(self):
        with self.assertRaises(StydOrmError) as cm:
            self.orm.orm_read_group("res.partner", group_by=["company_type"], aggregates=["name:sum"])
        self.assertEqual(cm.exception.code, "field_not_allowed")
        with self.assertRaises(StydOrmError) as cm2:
            self.orm.orm_read_group("res.partner", group_by=["password"], aggregates=[])
        self.assertEqual(cm2.exception.code, "field_not_allowed")
        with self.assertRaises(StydOrmError) as cm3:
            self.orm.orm_read_group("res.partner", group_by=["company_type", "country_id", "email"], aggregates=[])
        self.assertEqual(cm3.exception.code, "field_not_allowed")

    # order validation
    def test_10_order_validation(self):
        with self.assertRaises(StydOrmError) as cm:
            self.orm.orm_search_read("res.partner", fields=["name"], order="password desc")
        self.assertEqual(cm.exception.code, "order_invalid")
        ok = self.orm.orm_search_read("res.partner", fields=["name"], order="name desc", limit=5)
        self.assertIn("records", ok)

    # default fields never include forbidden ones
    def test_11_default_fields_safe(self):
        result = self.orm.orm_search_read("res.partner", fields=None, limit=1)
        if result["records"]:
            for key in result["records"][0].keys():
                low = key.lower()
                for bad in self.orm.FORBIDDEN_FIELD_SUBSTRINGS:
                    self.assertNotIn(bad, low)

    # malformed / unbalanced domain -> domain_invalid (not orm_error / 500)
    def test_12_unbalanced_domain_rejected(self):
        # '&' is binary but only one operand follows
        with self.assertRaises(StydOrmError) as cm:
            self.orm.orm_search_read("res.partner", domain=["&", ["name", "=", "x"]], fields=["name"])
        self.assertEqual(cm.exception.code, "domain_invalid")
        # trailing operator
        with self.assertRaises(StydOrmError) as cm2:
            self.orm.orm_search_read("res.partner", domain=[["name", "=", "x"], "|"], fields=["name"])
        self.assertEqual(cm2.exception.code, "domain_invalid")
        # lone unary operator
        with self.assertRaises(StydOrmError) as cm3:
            self.orm.orm_search_read("res.partner", domain=["!"], fields=["name"])
        self.assertEqual(cm3.exception.code, "domain_invalid")
        # a valid implicit-AND multi-leaf domain still passes
        ok = self.orm.orm_search_read(
            "res.partner",
            domain=[["name", "!=", False], ["name", "!=", "zzz-nope"]],
            fields=["name"], limit=5,
        )
        self.assertIn("records", ok)

    # 13. Phase 5H-D — an empty group_by is a VALID global aggregation (the fix).
    def test_13_read_group_empty_group_by_global(self):
        self.env["res.partner"].create({"name": "STYD Global Agg"})
        result = self.orm.orm_read_group("res.partner", domain=[], group_by=[], aggregates=[])
        self.assertIn("groups", result)
        self.assertEqual(result["group_by"], [])
        self.assertEqual(result["returned_count"], 1)
        self.assertIn("count", result["groups"][0])
        self.assertGreaterEqual(result["groups"][0]["count"], 1)
        # group_by omitted (None) behaves the same — one global group.
        result_none = self.orm.orm_read_group("res.partner", domain=[], group_by=None, aggregates=[])
        self.assertEqual(result_none["group_by"], [])
        self.assertEqual(result_none["returned_count"], 1)

    # 14. an empty group_by STILL enforces aggregate / model / domain guards.
    def test_14_empty_group_by_keeps_guards(self):
        # unsafe aggregate field (char, not numeric) still rejected
        with self.assertRaises(StydOrmError) as cm:
            self.orm.orm_read_group("res.partner", group_by=[], aggregates=["name:sum"])
        self.assertEqual(cm.exception.code, "field_not_allowed")
        # non-allowlisted model still rejected (model check runs first)
        with self.assertRaises(StydOrmError) as cm2:
            self.orm.orm_read_group("res.users", group_by=[], aggregates=[])
        self.assertEqual(cm2.exception.code, "model_not_allowed")
        # domain validation still enforced with an empty group_by
        with self.assertRaises(StydOrmError) as cm3:
            self.orm.orm_read_group("res.partner", domain=[["password", "=", "x"]], group_by=[], aggregates=[])
        self.assertEqual(cm3.exception.code, "field_not_allowed")

    # 15. the aggregate validator accepts STORED numeric/monetary fields and
    #     rejects everything else. sale.order.amount_total and
    #     account.move.amount_residual are stored monetary on the sandbox (and so
    #     is account.move.amount_total_signed) → all accepted; this proves the
    #     validator logic with a synthetic fields_get meta so it runs in the
    #     base-only test DB. End-to-end is covered by the STYD live eval.
    def test_15_aggregate_field_allowlist_logic(self):
        meta = {
            "amount_total": {"store": True, "type": "monetary"},
            "amount_residual": {"store": True, "type": "monetary"},
            "amount_total_signed": {"store": True, "type": "monetary"},
            "qty": {"store": True, "type": "integer"},
            "rate": {"store": True, "type": "float"},
            "name": {"store": True, "type": "char"},
            "html_note": {"store": True, "type": "html"},
            "partner_id": {"store": True, "type": "many2one"},
            "computed_total": {"store": False, "type": "monetary"},
            "secret_amount": {"store": True, "type": "monetary"},
        }
        # stored numeric/monetary accepted (incl. amount_total + amount_residual +
        # amount_total_signed)
        specs, names = self.orm._orm_validate_aggregates(
            meta, ["amount_total:sum", "amount_residual:sum", "amount_total_signed:sum", "qty:sum", "rate:avg"]
        )
        self.assertEqual(set(names), {"amount_total", "amount_residual", "amount_total_signed", "qty", "rate"})
        self.assertIn("amount_residual:sum", specs)
        self.assertIn("amount_total:sum", specs)

        # char / html / relational rejected (not numeric)
        for bad in ("name:sum", "html_note:sum", "partner_id:sum"):
            with self.assertRaises(StydOrmError) as cm:
                self.orm._orm_validate_aggregates(meta, [bad])
            self.assertEqual(cm.exception.code, "field_not_allowed")
        # non-stored computed numeric rejected (read_group cannot aggregate it)
        with self.assertRaises(StydOrmError) as cmn:
            self.orm._orm_validate_aggregates(meta, ["computed_total:sum"])
        self.assertEqual(cmn.exception.code, "field_not_allowed")
        # credential-looking field rejected even though it is stored monetary
        with self.assertRaises(StydOrmError) as cmc:
            self.orm._orm_validate_aggregates(meta, ["secret_amount:sum"])
        self.assertEqual(cmc.exception.code, "field_not_allowed")
        # bad syntax (no ':func') rejected
        with self.assertRaises(StydOrmError) as cms:
            self.orm._orm_validate_aggregates(meta, ["amount_total"])
        self.assertEqual(cms.exception.code, "field_not_allowed")
        # unsupported aggregate function rejected
        with self.assertRaises(StydOrmError) as cmf:
            self.orm._orm_validate_aggregates(meta, ["amount_total:median"])
        self.assertEqual(cmf.exception.code, "field_not_allowed")
        # unknown field (not in meta) rejected
        with self.assertRaises(StydOrmError) as cmu:
            self.orm._orm_validate_aggregates(meta, ["does_not_exist:sum"])
        self.assertEqual(cmu.exception.code, "field_not_allowed")
