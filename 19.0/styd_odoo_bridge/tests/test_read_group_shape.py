import inspect
import json
import re

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.styd_odoo_bridge.controllers.bridge_api import _json_default

# The same file runs on 19.0 and 20.0. On 19.0 (public read_group still takes
# fields= / lazy=) the Odoo 20 adapter is also compared row by row with Odoo's
# own read_group, which is what the bridge returned so far.
CASES = [
    {"group_by": [], "aggregates": []},
    {"group_by": ["type"], "aggregates": []},
    {"group_by": ["type"], "aggregates": ["color:sum"], "order": "color desc"},
    {"group_by": ["country_id"], "aggregates": ["color:max"], "order": "country_id asc"},
    {"group_by": ["is_company", "type"], "aggregates": ["color:avg"]},
    {"group_by": ["create_date"], "aggregates": []},
    {"group_by": ["create_date", "type"], "aggregates": ["color:sum"], "tz": "Asia/Bangkok"},
]

MONTH_LABEL = re.compile(r"^[A-Z][a-z]+ \d{4}$")


def _as_json(value):
    return json.loads(json.dumps(value, default=_json_default))


@tagged("post_install", "-at_install")
class TestReadGroupShape(TransactionCase):

    def setUp(self):
        super().setUp()
        self.orm = self.env["styd.odoo.bridge.orm"]
        country = self.env.ref("base.be")
        self.partners = self.env["res.partner"].create([
            {"name": "STYD Shape A", "is_company": True, "type": "contact", "color": 3, "country_id": country.id},
            {"name": "STYD Shape B", "type": "invoice", "color": 5},
            {"name": "STYD Shape C", "type": "invoice", "color": 1, "country_id": country.id},
        ])
        self.domain = [["id", "in", self.partners.ids]]

    def _bridge(self, case):
        return _as_json(self.orm.orm_read_group(
            "res.partner",
            domain=self.domain,
            group_by=case["group_by"],
            aggregates=case["aggregates"],
            order=case.get("order"),
            tz=case.get("tz"),
        ))

    def _legacy_read_group_available(self):
        params = inspect.signature(type(self.env["res.partner"]).read_group).parameters
        return "fields" in params and "lazy" in params

    def test_01_shape(self):
        for case in CASES:
            result = self._bridge(case)
            self.assertEqual(
                set(result), {"groups", "group_by", "aggregates", "returned_count", "limit"}
                | ({"tz"} if case.get("tz") else set()),
            )
            self.assertEqual(result["group_by"], case["group_by"])
            agg_names = [spec.split(":")[0] for spec in case["aggregates"]]
            self.assertEqual(sum(g["count"] for g in result["groups"]), 3)
            for group in result["groups"]:
                expected_keys = set(case["group_by"]) | set(agg_names) | {"count"}
                if case.get("tz"):
                    expected_keys.add("ranges")
                self.assertEqual(set(group), expected_keys)
                self.assertIsInstance(group["count"], int)
                for name in agg_names:
                    self.assertIsInstance(group[name], (int, float))
                if "country_id" in group and group["country_id"]:
                    country_id, country_name = group["country_id"]
                    self.assertIsInstance(country_id, int)
                    self.assertIsInstance(country_name, str)
                if "create_date" in group:
                    self.assertRegex(group["create_date"], MONTH_LABEL)
                if "type" in group:
                    self.assertIn(group["type"], ("contact", "invoice"))
                if "is_company" in group:
                    self.assertIsInstance(group["is_company"], bool)

    def test_02_adapter_matches_odoo_read_group(self):
        if not self._legacy_read_group_available():
            self.skipTest("Odoo 20+: no legacy read_group to compare with")
        model = self.env["res.partner"].sudo()
        for case in CASES:
            scoped = model.with_context(tz=case["tz"]) if case.get("tz") else model
            domain = [tuple(leaf) for leaf in self.domain]
            specs = case["aggregates"]
            legacy = scoped.read_group(
                domain=domain, fields=specs, groupby=case["group_by"],
                lazy=False, orderby=case.get("order"),
            )
            adapted = self.orm._orm_read_group_rows(
                scoped, domain, case["group_by"], specs, order=case.get("order"),
            )
            keys = set(case["group_by"]) | {s.split(":")[0] for s in specs} | {"__count", "__range"}
            self.assertEqual(
                _as_json([{k: row.get(k) for k in keys if k in row} for row in adapted]),
                _as_json([{k: row.get(k) for k in keys if k in row} for row in legacy]),
                "adapter differs from read_group for %s" % case,
            )
