from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.styd_odoo_bridge.models.bridge_orm import StydOrmError


@tagged("post_install", "-at_install")
class TestStydOrmBridge(TransactionCase):
    """Unit tests for the read-only ORM bridge validators.

    These exercise the service-layer logic directly (no HTTP), so they run in
    the module's test DB which only has `base`. The allowlisted models that are
    actually installed there are the base ones (res.partner, res.users,
    res.company); the optional-app models (sale.order, account.move,
    mrp.production, ...) are allowlisted but NOT installed, which lets us assert
    graceful degradation here and leaves full end-to-end coverage to the live
    STYD evals / manual curl checks against a fully-featured sandbox.
    """

    def setUp(self):
        super().setUp()
        self.orm = self.env["styd.odoo.bridge.orm"]

    # 1. /models returns only allowlisted models that are actually installed
    def test_01_list_models_allowlist_only(self):
        models = self.orm.orm_list_models()
        names = {m["model"] for m in models}
        # Never lists anything outside the allowlist...
        self.assertTrue(names.issubset(self.orm.MODEL_ALLOWLIST))
        # ...and never lists an explicitly-excluded sensitive model.
        self.assertNotIn("ir.config_parameter", names)
        self.assertNotIn("res.groups", names)
        self.assertNotIn("ir.model.access", names)
        # base-only models that ARE allowlisted and installed appear.
        self.assertIn("res.partner", names)
        self.assertIn("res.users", names)
        self.assertIn("res.company", names)
        # Optional-app models that are NOT installed in the base-only test DB are
        # silently skipped (graceful), so they must not appear in the listing.
        self.assertNotIn("sale.order", names)
        self.assertNotIn("mrp.production", names)
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

    # 4. blocked (non-allowlisted, sensitive) models return model_not_allowed.
    #    These models DO exist in a base-only DB, so this proves the allowlist --
    #    not mere absence -- is what blocks them.
    def test_04_blocked_model(self):
        for blocked in ("ir.config_parameter", "res.groups", "ir.model.access"):
            with self.assertRaises(StydOrmError) as cm:
                self.orm.orm_model_fields(blocked)
            self.assertEqual(cm.exception.code, "model_not_allowed")
        with self.assertRaises(StydOrmError) as cm2:
            self.orm.orm_search_read("ir.config_parameter", fields=["key"])
        self.assertEqual(cm2.exception.code, "model_not_allowed")
        with self.assertRaises(StydOrmError) as cm3:
            self.orm.orm_read_group("res.groups", group_by=[], aggregates=[])
        self.assertEqual(cm3.exception.code, "model_not_allowed")

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
            self.orm.orm_read_group("ir.config_parameter", group_by=[], aggregates=[])
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

    # 16. (req #1 + #5) allowlisted models that ARE installed can be requested,
    #     and credential fields are never exposed -- incl. the newly-allowed
    #     res.users / res.company alongside the long-supported res.partner.
    def test_16_allowed_base_models_requestable(self):
        safe_fields = {
            "res.partner": ["name"],
            "res.users": ["login", "name"],
            "res.company": ["name"],
        }
        for model_name, fnames in safe_fields.items():
            meta = self.orm.orm_model_fields(model_name)
            self.assertTrue(meta, "expected field metadata for %s" % model_name)
            for f in meta:
                low = f["name"].lower()
                for bad in self.orm.FORBIDDEN_FIELD_SUBSTRINGS:
                    self.assertNotIn(bad, low)
            result = self.orm.orm_search_read(model_name, fields=fnames, limit=1)
            self.assertIn("records", result)
        # res.users: useful identity fields are exposed, secrets are stripped.
        user_fields = {f["name"] for f in self.orm.orm_model_fields("res.users")}
        self.assertIn("login", user_fields)
        self.assertNotIn("password", user_fields)

    # 17. (req #3) a model that is allowlisted but whose Odoo app is NOT installed
    #     fails gracefully with `model_not_installed` (never a crash / 500), and
    #     is silently skipped from the /models listing.
    def test_17_optional_app_models_fail_gracefully(self):
        candidates = [
            "sale.order", "account.move", "mrp.production", "maintenance.request",
            "purchase.order", "crm.lead", "project.task", "stock.warehouse",
        ]
        # Robust on any DB: assert only on those genuinely absent here.
        missing = [m for m in candidates
                   if m in self.orm.MODEL_ALLOWLIST and m not in self.env]
        self.assertTrue(missing, "expected allowlisted-but-uninstalled models in a base-only DB")
        listed = {m["model"] for m in self.orm.orm_list_models()}
        for model_name in missing:
            with self.assertRaises(StydOrmError) as cm:
                self.orm.orm_model_fields(model_name)
            self.assertEqual(cm.exception.code, "model_not_installed")
            with self.assertRaises(StydOrmError) as cm2:
                self.orm.orm_search_read(model_name, fields=["name"], limit=5)
            self.assertEqual(cm2.exception.code, "model_not_installed")
            with self.assertRaises(StydOrmError) as cm3:
                self.orm.orm_read_group(model_name, group_by=[], aggregates=[])
            self.assertEqual(cm3.exception.code, "model_not_installed")
            self.assertNotIn(model_name, listed)

    # 18. (req #2) the allowlist is exactly the reviewed business set, and none of
    #     the dangerous / private / config / security models are ever included.
    #     Pinned on purpose: changing the bridge's data surface must be deliberate.
    def test_18_allowlist_contents_and_exclusions(self):
        expected = {
            "res.partner", "res.company", "res.users",
            "sale.order", "sale.order.line",
            "account.move", "account.move.line", "account.payment",
            "account.journal", "account.account", "account.tax",
            "product.template", "product.product", "product.category", "uom.uom",
            "stock.quant", "stock.location", "stock.move", "stock.move.line",
            "stock.picking", "stock.picking.type", "stock.warehouse",
            "purchase.order", "purchase.order.line",
            "crm.lead", "crm.stage", "crm.team",
            "project.project", "project.task",
            "mrp.production", "mrp.workorder", "mrp.bom", "mrp.bom.line",
            "maintenance.equipment", "maintenance.request", "maintenance.team",
        }
        self.assertEqual(set(self.orm.MODEL_ALLOWLIST), expected)
        forbidden = {
            "ir.config_parameter", "ir.attachment", "mail.message", "mail.thread",
            "res.groups", "ir.model.access", "ir.rule", "ir.module.module",
            "hr.employee", "auth_totp.device", "res.users.apikeys",
        }
        self.assertEqual(set(self.orm.MODEL_ALLOWLIST) & forbidden, set())

    # 19. (req #4) the ORM transport is read-only: it exposes ONLY read primitives,
    #     advertises the documented access mode, and running those primitives never
    #     mutates the database.
    def test_19_bridge_is_read_only(self):
        public = {n for n in dir(self.orm) if n.startswith("orm_")}
        self.assertEqual(
            public,
            {"orm_list_models", "orm_model_fields", "orm_search_read", "orm_read_group"},
        )
        for writer in ("orm_create", "orm_write", "orm_unlink", "orm_copy",
                       "orm_call", "orm_call_kw", "orm_action"):
            self.assertFalse(hasattr(self.orm, writer), writer)
        self.assertEqual(self.orm.ACCESS_MODE, "sudo_company_scoped")
        # Behavioural: the read path leaves the row count unchanged.
        self.env["res.partner"].create({"name": "STYD RO Probe"})
        before = self.env["res.partner"].search_count([])
        self.orm.orm_search_read("res.partner", fields=["name"], limit=50)
        self.orm.orm_read_group("res.partner", group_by=["company_type"], aggregates=[])
        self.orm.orm_model_fields("res.partner")
        self.orm.orm_list_models()
        self.assertEqual(self.env["res.partner"].search_count([]), before)

    # 20. (req #4) the HTTP surface exposes no state-changing verbs -- every bridge
    #     route is GET or POST (POST only carries a read query body).
    def test_20_controller_exposes_no_write_verbs(self):
        from odoo.addons.styd_odoo_bridge.controllers.bridge_api import StydBridgeApi
        routed = 0
        for attr_name in dir(StydBridgeApi):
            routing = getattr(getattr(StydBridgeApi, attr_name), "routing", None)
            if not routing:
                continue
            routed += 1
            methods = set(routing.get("methods") or [])
            for verb in ("PUT", "PATCH", "DELETE"):
                self.assertNotIn(verb, methods)
            self.assertTrue(methods.issubset({"GET", "POST"}), methods)
        # Guard against the routing metadata shape changing under us.
        self.assertGreaterEqual(routed, 8)

    # 21. (req #6) the manifest version was bumped to 19.0.0.7.0.
    def test_21_manifest_version_bumped(self):
        from odoo.modules.module import get_manifest
        manifest = get_manifest("styd_odoo_bridge")
        self.assertEqual(manifest.get("version"), "19.0.0.7.0")
