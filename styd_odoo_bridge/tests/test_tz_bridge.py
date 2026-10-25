from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.styd_odoo_bridge.models.bridge_orm import StydOrmError

# UTC+7 all year (no DST), so expected values are stable.
BANGKOK = "Asia/Bangkok"


def _invalidate(env):
    if hasattr(env, "invalidate_all"):
        env.invalidate_all()
    else:  # Odoo 15
        env["res.partner"].invalidate_cache()


@tagged("post_install", "-at_install")
class TestStydBridgeTimezone(TransactionCase):
    """Opt-in time zone support (tz_aware_v1).

    A partner created on 1 Oct 2026 at 05:00 in Bangkok is stored as
    2026-09-30 22:00:00 UTC: it belongs to October locally, to September in UTC.
    """

    def setUp(self):
        super().setUp()
        self.orm = self.env["styd.odoo.bridge.orm"]
        self.service = self.env["styd.odoo.bridge.service"]
        self.meta = self.env["res.partner"].fields_get()
        self.partner = self.env["res.partner"].create({"name": "STYD TZ Probe"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            ("2026-09-30 22:00:00", self.partner.id),
        )
        _invalidate(self.env)

    def _localize(self, leaf):
        return self.orm._orm_localize_domain(self.meta, [leaf], BANGKOK)

    # 1. Without tz / tz_mode nothing changes (legacy behaviour).
    def test_01_no_tz_is_legacy(self):
        domain = [("create_date", ">=", "2026-10-01")]
        self.assertIs(self.orm._orm_localize_domain(self.meta, domain, None), domain)
        self.assertIsNone(self.orm._orm_resolve_tz(None, None))
        result = self.orm.orm_search_read(
            "res.partner", domain=[["id", "=", self.partner.id]], fields=["name", "create_date"],
        )
        self.assertNotIn("tz", result)
        self.assertNotIn("datetime_format", result)
        grouped = self.orm.orm_read_group(
            "res.partner", domain=[["id", "=", self.partner.id]], group_by=["create_date"], aggregates=[],
        )
        self.assertNotIn("tz", grouped)
        self.assertNotIn("ranges", grouped["groups"][0])

    # 2. Date-only values on datetime fields mean the whole local day.
    def test_02_date_only_bounds(self):
        start, end = "2026-09-30 17:00:00", "2026-10-01 17:00:00"
        self.assertEqual(self._localize(("create_date", ">=", "2026-10-01")), [("create_date", ">=", start)])
        self.assertEqual(self._localize(("create_date", "<", "2026-10-01")), [("create_date", "<", start)])
        self.assertEqual(self._localize(("create_date", ">", "2026-10-01")), [("create_date", ">=", end)])
        self.assertEqual(self._localize(("create_date", "<=", "2026-10-01")), [("create_date", "<", end)])
        self.assertEqual(
            self._localize(("create_date", "=", "2026-10-01")),
            ["&", ("create_date", ">=", start), ("create_date", "<", end)],
        )
        self.assertEqual(
            self._localize(("create_date", "!=", "2026-10-01")),
            ["|", "|", ("create_date", "=", False), ("create_date", "<", start), ("create_date", ">=", end)],
        )

    # 3. Datetime values: naive = local wall time, explicit offsets are honoured.
    def test_03_datetime_values(self):
        self.assertEqual(
            self._localize(("create_date", ">=", "2026-10-01 05:00:00")),
            [("create_date", ">=", "2026-09-30 22:00:00")],
        )
        self.assertEqual(
            self._localize(("create_date", ">=", "2026-10-01T05:00:00Z")),
            [("create_date", ">=", "2026-10-01 05:00:00")],
        )
        self.assertEqual(
            self._localize(("create_date", ">=", "2026-10-01T05:00:00+02:00")),
            [("create_date", ">=", "2026-10-01 03:00:00")],
        )

    # 4. Only datetime fields with date-like values are rewritten.
    def test_04_other_leaves_untouched(self):
        for leaf in (
            ("name", "=", "2026-10-01"),           # char field
            ("create_date", "in", ["2026-10-01"]),
            ("create_date", "=", False),
        ):
            self.assertEqual(self._localize(leaf), [leaf])
        # date fields carry no time zone (synthetic meta: res.partner has no
        # date field on every Odoo series)
        date_leaf = ("some_day", ">=", "2026-10-01")
        self.assertEqual(
            self.orm._orm_localize_domain({"some_day": {"type": "date"}}, [date_leaf], BANGKOK),
            [date_leaf],
        )
        domain = ["|", ("name", "=", "x"), ("create_date", "=", "2026-10-01")]
        self.assertEqual(
            self.orm._orm_localize_domain(self.meta, domain, BANGKOK),
            ["|", ("name", "=", "x"), "&",
             ("create_date", ">=", "2026-09-30 17:00:00"), ("create_date", "<", "2026-10-01 17:00:00")],
        )
        with self.assertRaises(StydOrmError) as cm:
            self._localize(("create_date", ">=", "2026-13-01"))
        self.assertEqual(cm.exception.code, "domain_invalid")

    # 5. search-read: "this month" in Bangkok includes the order, values are local.
    def test_05_search_read_with_tz(self):
        base = [["id", "=", self.partner.id]]
        october = self.orm.orm_search_read(
            "res.partner", domain=base + [["create_date", ">=", "2026-10-01"]],
            fields=["name", "create_date"], tz=BANGKOK,
        )
        self.assertEqual(october["count"], 1)
        self.assertEqual(october["records"][0]["create_date"], "2026-10-01T05:00:00+07:00")
        self.assertEqual(october["tz"], BANGKOK)
        self.assertEqual(october["datetime_format"], "iso8601_offset")
        september = self.orm.orm_search_read(
            "res.partner", domain=base + [["create_date", "<", "2026-10-01"]],
            fields=["name"], tz=BANGKOK,
        )
        self.assertEqual(september["count"], 0)

    # 6. read-group: monthly buckets follow the time zone and expose their bounds.
    def test_06_read_group_buckets(self):
        base = [["id", "=", self.partner.id]]
        local = self.orm.orm_read_group(
            "res.partner", domain=base, group_by=["create_date"], aggregates=[], tz=BANGKOK,
        )
        group = local["groups"][0]
        self.assertEqual(group["create_date"], "October 2026")
        self.assertEqual(group["count"], 1)
        self.assertEqual(group["ranges"]["create_date"], {
            "from": "2026-10-01T00:00:00+07:00",
            "to": "2026-11-01T00:00:00+07:00",
        })
        utc = self.orm.orm_read_group(
            "res.partner", domain=base, group_by=["create_date"], aggregates=[], tz="UTC",
        )
        self.assertEqual(utc["groups"][0]["create_date"], "September 2026")

    # 7. tz / tz_mode validation and resolution.
    def test_07_resolve_tz(self):
        for bad_tz, bad_mode in (("Mars/Olympus", None), (12, None), (None, "user"), (None, "COMPANY")):
            with self.assertRaises(StydOrmError) as cm:
                self.orm._orm_resolve_tz(bad_tz, bad_mode)
            self.assertEqual(cm.exception.code, "tz_invalid")
        self.assertEqual(self.orm._orm_resolve_tz(BANGKOK, "company"), BANGKOK)
        owner = self.env["res.users"].create({
            "name": "STYD TZ Owner", "login": "styd_tz_owner", "tz": "Europe/Paris",
        })
        self.service._icp_set("styd_odoo_bridge.connector_owner_user_id", str(owner.id))
        self.assertEqual(self.orm._orm_resolve_tz(None, "company"), "Europe/Paris")

    # 8. Bridge time zone fallbacks: owner, owner's company, main company, UTC.
    def test_08_bridge_tz_fallbacks(self):
        owner = self.env["res.users"].create({
            "name": "STYD TZ Owner 2", "login": "styd_tz_owner_2", "tz": False,
        })
        self.service._icp_set("styd_odoo_bridge.connector_owner_user_id", str(owner.id))
        companies = self.env["res.company"].search([])
        companies.mapped("partner_id").write({"tz": False})
        owner.partner_id.tz = False
        self.assertEqual(self.service._get_bridge_tz(), "UTC")
        main = self.env["res.company"].search([], order="id", limit=1)
        main.partner_id.tz = "America/New_York"
        self.assertEqual(self.service._get_bridge_tz(), "America/New_York")
        owner.company_id.partner_id.tz = "Asia/Tokyo"
        self.assertEqual(self.service._get_bridge_tz(), "Asia/Tokyo")
        owner.tz = BANGKOK
        self.assertEqual(self.service._get_bridge_tz(), BANGKOK)

    # 9. The time zone is advertised (additive keys only).
    def test_09_timezone_advertised(self):
        health = self.service.build_health_payload()
        self.assertIn("tz_aware_v1", health["supported_features"])
        self.assertTrue(health["timezone"])
        capabilities = self.service.build_capability_snapshot_payload()
        self.assertEqual(capabilities["instance"]["timezone"], health["timezone"])
        self.assertEqual(capabilities["configuration_hints"]["timezone"], health["timezone"])
