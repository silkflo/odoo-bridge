"""M-R2 to M-R5: the read policy STYD uses on an API key (odooReadPolicy.ts),
on the Bridge: the wider model allowlist, the named many2many exceptions, a
validated ``lang`` and an ordered ``company_ids`` (company first)."""

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.styd_odoo_bridge.models.bridge_channel_executor import icp_set
from odoo.addons.styd_odoo_bridge.models.bridge_orm import StydOrmError

from .channel_common import GROUPS

# The models STYD reads on an API key (HR has its own list).
R2_MODELS = (
    "pos.order", "pos.order.line", "pos.session", "pos.config", "pos.payment", "pos.payment.method",
    "report.pos.order", "restaurant.table", "account.bank.statement", "account.bank.statement.line",
    "account.partial.reconcile",
    "stock.valuation.layer", "account.analytic.line", "account.analytic.account", "account.analytic.plan",
    "project.task.type", "project.project.stage", "project.milestone", "project.update",
    "mrp.workcenter", "mrp.workcenter.productivity", "mrp.workcenter.productivity.loss",
    "mrp.routing.workcenter", "mrp.unbuild", "res.currency.rate",
)
STILL_REFUSED = (
    "hr.employee", "hr.contract", "hr.leave", "hr.attendance", "res.users", "ir.config_parameter",
    "payment.transaction", "res.groups", "ir.attachment", "stock.production.lot",
)

M2M = {"type": "many2many", "store": True}


def _meta(**fields):
    base = {"name": {"type": "char", "store": True}, "id": {"type": "integer", "store": True}}
    base.update(fields)
    return base


@tagged("post_install", "-at_install")
class TestReadPolicy(TransactionCase):
    def setUp(self):
        super().setUp()
        self.orm = self.env["styd.odoo.bridge.orm"].sudo()

    def assertCode(self, code, fn, *args, **kwargs):
        with self.assertRaises(StydOrmError) as ctx:
            fn(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code)

    # -- M-R2 ----------------------------------------------------------------------
    def test_r2_allowlist_widened(self):
        for model in R2_MODELS:
            self.assertIn(model, self.orm.MODEL_ALLOWLIST, model)
            if model not in self.env:
                self.assertCode("model_not_installed", self.orm._orm_check_model, model)
        for model in STILL_REFUSED:
            self.assertNotIn(model, self.orm.MODEL_ALLOWLIST, model)
            self.assertCode("model_not_allowed", self.orm._orm_check_model, model)
        self.assertFalse([m for m in self.orm.MODEL_ALLOWLIST if m.startswith("hr.")])

    def test_r2_lots_of_this_version(self):
        """Lots: stock.lot (Odoo 16 and later). Odoo 15's stock.production.lot is not read."""
        self.assertIn("stock.lot", self.orm.MODEL_ALLOWLIST)
        self.assertNotIn("stock.production.lot", self.orm.MODEL_ALLOWLIST)
        if "stock.production.lot" in self.env:
            self.assertCode("model_not_allowed", self.orm._orm_check_model, "stock.production.lot")

    def test_r2_restaurant_tables(self):
        """restaurant.table (POS restaurant) is readable where pos_restaurant is installed."""
        self.assertIn("restaurant.table", self.orm.MODEL_ALLOWLIST)
        if "restaurant.table" not in self.env:
            self.assertCode("model_not_installed", self.orm._orm_check_model, "restaurant.table")
            return
        self.orm._orm_check_model("restaurant.table")
        out = self.orm._orm_search_read(model="restaurant.table", fields=["seats"], limit=5)
        self.assertEqual(out["returned_count"], len(out["records"]))
        self.assertIn("restaurant.table", [m["model"] for m in self.orm._orm_list_models()])

    def test_r2_currency_rates_read(self):
        """res.currency.rate is in base: a real read through the validators."""
        currency = self.env.ref("base.EUR")
        self.env["res.currency.rate"].create({"currency_id": currency.id, "rate": 1.25, "name": "2026-01-02"})
        out = self.orm._orm_search_read(model="res.currency.rate", fields=["name", "rate", "currency_id"],
                                        domain=[["currency_id", "=", currency.id], ["name", "=", "2026-01-02"]])
        self.assertEqual(out["returned_count"], 1)
        self.assertEqual(out["records"][0]["rate"], 1.25)
        self.assertIn("res.currency.rate", [m["model"] for m in self.orm._orm_list_models()])

    # -- M-R3 ----------------------------------------------------------------------
    def test_r3_group_only_many2many(self):
        task = _meta(user_ids=dict(M2M, relation="res.users"), tag_ids=dict(M2M, relation="project.tags"))
        aml = _meta(tax_ids=dict(M2M, relation="account.tax"))
        move = _meta(scrap_reason_tag_ids=dict(M2M, relation="stock.scrap.reason.tag"))
        gb = self.orm._orm_validate_group_by
        self.assertEqual(gb(task, ["user_ids"], model="project.task"), ["user_ids"])
        self.assertEqual(gb(aml, ["tax_ids", "name"], model="account.move.line"), ["tax_ids", "name"])
        self.assertEqual(gb(move, ["scrap_reason_tag_ids"], model="stock.move"), ["scrap_reason_tag_ids"])
        # the same name on another model, another relation, not stored, another many2many, no model
        self.assertCode("field_not_allowed", gb, task, ["user_ids"], model="project.project")
        self.assertCode("field_not_allowed", gb, _meta(user_ids=dict(M2M, relation="res.partner")), ["user_ids"],
                        model="project.task")
        self.assertCode("field_not_allowed", gb, _meta(tax_ids=dict(M2M, relation="account.tax", store=False)),
                        ["tax_ids"], model="account.move.line")
        self.assertCode("field_not_allowed", gb, task, ["tag_ids"], model="project.task")
        self.assertCode("field_not_allowed", gb, task, ["user_ids"])
        self.assertCode("field_not_allowed", gb, move, ["scrap_reason_tag_ids"], model="stock.scrap")
        # group-only: never returned, filtered or ordered
        self.assertCode("field_not_allowed", self.orm._orm_validate_fields, aml, ["tax_ids"], model="account.move.line")
        self.assertCode("field_not_allowed", self.orm._orm_validate_domain, aml, [["tax_ids", "in", [1]]],
                        model="account.move.line")
        self.assertCode("field_not_allowed", self.orm._orm_validate_domain, move,
                        [["scrap_reason_tag_ids", "in", [1]]], model="stock.move")
        self.assertCode("order_invalid", self.orm._orm_validate_order, task, "user_ids")
        self.assertCode("field_not_allowed", self.orm._orm_validate_fields, task, ["user_ids"], model="project.task")

    def test_r3_assignee_filter(self):
        task = _meta(user_ids=dict(M2M, relation="res.users"))
        dom = self.orm._orm_validate_domain
        self.assertEqual(dom(task, [["user_ids", "in", [2, 7]]], model="project.task"), [("user_ids", "in", [2, 7])])
        self.assertEqual(dom(task, [["user_ids", "=", 2]], model="project.task"), [("user_ids", "=", 2)])
        for operator, value in (("in", []), ("in", [0]), ("in", [True]), ("in", ["2"]), ("=", 0), ("=", False),
                                ("=", "2"), ("not in", [2]), ("!=", 2), ("ilike", "x")):
            self.assertCode("field_not_allowed", dom, task, [["user_ids", operator, value]], model="project.task")
        self.assertCode("field_not_allowed", dom, task, [["user_ids", "in", [2]]], model="project.project")
        self.assertCode("field_not_allowed", dom, task, [["user_ids", "in", [2]]])

    def test_r3_variant_ids_returned_when_named(self):
        bom_line = _meta(bom_product_template_attribute_value_ids=dict(
            M2M, relation="product.template.attribute.value"))
        product = _meta(product_template_attribute_value_ids=dict(M2M, relation="product.template.attribute.value"))
        fields = self.orm._orm_validate_fields
        self.assertEqual(fields(bom_line, ["name", "bom_product_template_attribute_value_ids"], model="mrp.bom.line"),
                         ["name", "bom_product_template_attribute_value_ids"])
        self.assertEqual(fields(product, ["product_template_attribute_value_ids"], model="product.product"),
                         ["product_template_attribute_value_ids"])
        self.assertNotIn("bom_product_template_attribute_value_ids", fields(bom_line, None, model="mrp.bom.line"),
                         "never in a read that names no fields")
        self.assertCode("field_not_allowed", fields, bom_line, ["bom_product_template_attribute_value_ids"],
                        model="product.product")
        self.assertCode("field_not_allowed", fields, product, ["product_template_attribute_value_ids"])
        self.assertCode("field_not_allowed", self.orm._orm_validate_domain, product,
                        [["product_template_attribute_value_ids", "in", [1]]], model="product.product")
        self.assertCode("field_not_allowed", self.orm._orm_validate_group_by, product,
                        ["product_template_attribute_value_ids"], model="product.product")

    # -- M-R4 ----------------------------------------------------------------------
    def test_r4_lang_validated(self):
        for bad in ("xx_XX", "de_DE", 12, ["en_US"], "en_US; DROP"):
            self.assertCode("lang_invalid", self.orm._orm_search_read, model="res.partner", lang=bad)
            self.assertCode("lang_invalid", self.orm._orm_read_group, model="res.partner", group_by=["is_company"],
                            lang=bad)
        self.assertTrue(self.orm._orm_search_read(model="res.partner", limit=1, lang="en_US")["records"] is not None)
        self.assertIn("groups", self.orm._orm_read_group(model="res.partner", group_by=["is_company"], lang="en_US"))

    def test_r4_lang_reaches_the_read(self):
        """Names come back in the asked language: a country's name (translated) on a partner."""
        self.env["res.lang"]._activate_lang("fr_FR")
        country = self.env["res.country"].create({"name": "Styd Land", "code": "ZZ"})
        country.with_context(lang="fr_FR").write({"name": "Pays Styd"})
        partner = self.env["res.partner"].create({"name": "STYD R4 partner", "country_id": country.id})
        args = dict(model="res.partner", fields=["country_id"], domain=[["id", "=", partner.id]])
        self.assertEqual(self.orm._orm_search_read(lang="fr_FR", **args)["records"][0]["country_id"][1], "Pays Styd")
        self.assertEqual(self.orm._orm_search_read(lang="en_US", **args)["records"][0]["country_id"][1], "Styd Land")
        groups = self.orm._orm_read_group(model="res.partner", group_by=["country_id"], lang="fr_FR",
                                          domain=[["id", "=", partner.id]])["groups"]
        self.assertEqual(groups[0]["country_id"][1], "Pays Styd")

    # -- M-R5 ----------------------------------------------------------------------
    def _companies(self):
        admin = self.env.ref("base.user_admin")
        icp_set(self.env["ir.config_parameter"].sudo(), "styd_odoo_bridge.connector_owner_user_id", str(admin.id))
        c1 = self.env.ref("base.main_company")
        c2 = self.env["res.company"].create({"name": "STYD R5 second"})
        c3 = self.env["res.company"].create({"name": "STYD R5 not the owner's"})
        admin.write({"company_ids": [Command.link(c2.id)]})
        Partner = self.env["res.partner"]
        Partner.create([{"name": "R5 one", "company_id": c1.id}, {"name": "R5 two", "company_id": c2.id},
                        {"name": "R5 three", "company_id": c3.id}])
        return c1, c2, c3

    def test_r5_company_first(self):
        c1, c2, _c3 = self._companies()
        companies = self.orm._orm_resolve_companies([c2.id, c1.id])
        self.assertEqual(companies.ids, [c2.id, c1.id], "the order is kept")
        scoped = self.orm._orm_scoped(self.env["res.partner"].sudo(), companies)
        self.assertEqual(scoped.env.context["allowed_company_ids"], [c2.id, c1.id])
        self.assertEqual(scoped.env.company, c2, "the first company is the read's company")
        r5 = ["R5 one", "R5 two", "R5 three"]  # (a new company's own partner has no company)
        args = dict(model="res.partner", domain=[["name", "in", r5]], fields=["name"])
        names = {r["name"] for r in self.orm._orm_search_read(company_ids=[c2.id], **args)["records"]}
        self.assertEqual(names, {"R5 two"})
        names = {r["name"] for r in self.orm._orm_search_read(company_ids=[c2.id, c1.id], **args)["records"]}
        self.assertEqual(names, {"R5 one", "R5 two"})
        names = {r["name"] for r in self.orm._orm_search_read(**args)["records"]}
        self.assertEqual(names, {"R5 one", "R5 two"}, "without company_ids: the owner's companies, as before")
        groups = self.orm._orm_read_group(model="res.partner", domain=[["name", "in", r5]],
                                          group_by=["company_id"], company_ids=[c2.id])["groups"]
        self.assertEqual([g["company_id"][0] for g in groups], [c2.id])

    def test_r5_company_ids_validated(self):
        c1, c2, c3 = self._companies()
        for bad in ([c3.id], [c2.id, c3.id], [], [c1.id, c1.id], ["1"], [True], [0], c1.id, "1", [-1],
                    list(range(1, 60))):
            self.assertCode("company_invalid", self.orm._orm_search_read, model="res.partner", company_ids=bad)
            self.assertCode("company_invalid", self.orm._orm_read_group, model="res.partner",
                            group_by=["is_company"], company_ids=bad)


@tagged("post_install", "-at_install")
class TestReadPolicyApps(TransactionCase):
    """Real reads when the apps are installed (the run with project and account)."""

    def setUp(self):
        super().setUp()
        self.orm = self.env["styd.odoo.bridge.orm"].sudo()

    def test_project_assignee_group_and_filter(self):
        if "project.task" not in self.env:
            self.skipTest("project is not installed")
        admin = self.env.ref("base.user_admin")
        other = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "STYD assignee", "login": "styd_assignee",
            GROUPS: [Command.set([self.env.ref("base.group_user").id])],
        })
        project = self.env["project.project"].create({"name": "STYD R3 project"})
        Task = self.env["project.task"]
        Task.create([
            {"name": "t1", "project_id": project.id, "user_ids": [Command.set([admin.id])]},
            {"name": "t2", "project_id": project.id, "user_ids": [Command.set([admin.id, other.id])]},
            {"name": "t3", "project_id": project.id, "user_ids": [Command.set([other.id])]},
        ])
        domain = [["project_id", "=", project.id]]
        out = self.orm._orm_read_group(model="project.task", domain=domain, group_by=["user_ids"])
        counts = {g["user_ids"][0]: g["count"] for g in out["groups"] if g["user_ids"]}
        self.assertEqual(counts, {admin.id: 2, other.id: 2})
        mine = self.orm._orm_search_read(model="project.task", fields=["name"],
                                         domain=domain + [["user_ids", "in", [other.id]]])
        self.assertEqual({r["name"] for r in mine["records"]}, {"t2", "t3"})
        for model in ("project.task.type", "project.milestone", "project.update", "project.project.stage"):
            if model in self.env:
                self.assertIsInstance(self.orm._orm_search_read(model=model, limit=1)["records"], list, model)

    def test_ledger_tax_group_and_new_models(self):
        if "account.move.line" not in self.env:
            self.skipTest("account is not installed")
        out = self.orm._orm_read_group(model="account.move.line", group_by=["tax_ids"],
                                       aggregates=["balance:sum"])
        self.assertIsInstance(out["groups"], list)
        for model in ("account.partial.reconcile", "account.bank.statement", "account.bank.statement.line",
                      "account.analytic.line", "account.analytic.account", "account.analytic.plan"):
            if model in self.env:
                # Analytic lines: journal-item lines only (timesheet lines follow the HR rules).
                domain = [[self.orm._orm_journal_item_field(model), "!=", False]] \
                    if model == "account.analytic.line" else None
                self.assertIsInstance(self.orm._orm_search_read(model=model, limit=1, domain=domain)["records"],
                                      list, model)
