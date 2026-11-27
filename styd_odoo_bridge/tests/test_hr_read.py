"""HR in the allowlist, exactly STYD's API-key HR read:
the same models, the same field lists, the same fields left out. Read over the
outbound channel only, as the asking member's own Odoo user (no sudo, read-only
cursor); the sudo HTTP routes refuse it."""

import uuid

from odoo import Command
from odoo.tests import tagged

from odoo.addons.styd_odoo_bridge.models import bridge_channel_executor as ex
from odoo.addons.styd_odoo_bridge.models.bridge_orm import (
    ORM_HR_FIELDS, ORM_HR_MODELS, ORM_MEMBER_RIGHTS_CTX, StydOrmError, model_has_access,
)

from .channel_common import GROUPS, ChannelCase

# STYD's lists, copied by hand from STYD's HR read: a change on
# either side must be deliberate.
STYD_HR_FIELDS = {
    "hr.employee.public": {"id", "name", "active", "department_id", "job_id", "job_title", "parent_id",
                           "company_id", "work_email", "work_phone", "user_id", "tz", "leave_manager_id",
                           "attendance_manager_id", "expense_manager_id", "resource_calendar_id"},
    "hr.department": {"id", "name", "complete_name", "parent_id", "manager_id", "company_id", "active"},
    "hr.leave.report.calendar": {"id", "employee_id", "department_id", "company_id", "state", "duration",
                                 "start_datetime", "stop_datetime", "request_date_from", "request_date_to"},
    "hr.leave": {"id", "employee_id", "department_id", "employee_company_id", "user_id", "request_date_from",
                 "request_date_to", "date_from", "date_to", "number_of_days", "number_of_hours",
                 "number_of_hours_display", "state", "holiday_status_id", "work_entry_type_id"},
    "hr.leave.type": {"id", "name", "time_type", "requires_allocation", "unpaid", "company_id", "active"},
    "hr.work.entry.type": {"id", "name", "count_as", "requires_allocation", "unpaid", "time_off_selectable",
                           "active"},
    "hr.leave.allocation": {"id", "employee_id", "employee_company_id", "number_of_days", "max_leaves",
                            "leaves_taken", "date_from", "date_to", "state", "holiday_status_id",
                            "work_entry_type_id", "type_request_unit"},
    "hr.attendance": {"id", "employee_id", "check_in", "check_out", "worked_hours"},
    "resource.calendar.leaves": {"id", "date_from", "date_to", "calendar_id", "company_id", "resource_id"},
}
PUBLIC_HOLIDAYS = [["resource_id", "=", False]]
class MemberOrm:
    """The ORM as the channel calls it for a member: the entry points with
    ``member_rights=True`` and the pairing's owner."""

    ENTRY_POINTS = ("_orm_list_models", "_orm_model_fields", "_orm_search_read", "_orm_read_group")

    def __init__(self, orm, owner_uid):
        self._orm = orm
        self._owner_uid = owner_uid

    def __getattr__(self, name):
        if name in self.ENTRY_POINTS:
            method = getattr(self._orm, name)
            return lambda *a, **kw: method(*a, member_rights=True, owner_uid=self._owner_uid, **kw)
        return getattr(self._orm._orm_mode(True, self._owner_uid), name)


NEVER = ("hr.employee", "hr.contract", "hr.job", "hr.payslip", "hr.expense", "hr.applicant", "hr.version",
         "resource.calendar", "res.partner.bank")


@tagged("post_install", "-at_install")
class TestHrLists(ChannelCase):
    def test_00_same_lists_as_styd(self):
        self.assertEqual(set(ORM_HR_FIELDS), set(STYD_HR_FIELDS))
        for model, fields in STYD_HR_FIELDS.items():
            self.assertEqual(set(ORM_HR_FIELDS[model]), fields, model)
        orm = self.env["styd.odoo.bridge.orm"]
        for model in NEVER:
            self.assertNotIn(model, orm.MODEL_ALLOWLIST)
            self.assertNotIn(model, ORM_HR_MODELS)
            with self.assertRaises(StydOrmError) as ctx:
                orm.with_context(**{ORM_MEMBER_RIGHTS_CTX: True})._orm_check_model(model)
            self.assertEqual(ctx.exception.code, "model_not_allowed", model)


@tagged("post_install", "-at_install")
class TestHrRead(ChannelCase):
    def setUp(self):
        super().setUp()
        for needed in ("hr.leave", "hr.attendance", "hr.employee.public"):
            if needed not in self.env:
                self.skipTest("hr_holidays and hr_attendance are not installed")
        Users = self.env["res.users"].with_context(no_reset_password=True)
        group_user = self.env.ref("base.group_user")
        # Odoo 20: a new employee also gets the default user group, which brings the
        # employee's own time off and attendance (the test sets the groups explicitly).
        default_group = self.env.ref("base.default_user_group", raise_if_not_found=False)
        self.plain = Users.create({
            "name": "STYD HR plain", "login": "styd_hr_plain",
            GROUPS: [Command.set([group_user.id] + (default_group.ids if default_group else []))],
        })
        officer_groups = [group_user, self.env.ref("hr.group_hr_user"),
                          self.env.ref("hr_holidays.group_hr_holidays_user")]
        attendance_officer = self.env.ref("hr_attendance.group_hr_attendance_officer", raise_if_not_found=False)
        if attendance_officer:
            officer_groups.append(attendance_officer)
        self.officer = Users.create({
            "name": "STYD HR officer", "login": "styd_hr_officer",
            GROUPS: [Command.set([g.id for g in officer_groups])],
        })
        Employee = self.env["hr.employee"]
        self.emp_plain = Employee.create({"name": "STYD Plain Employee", "user_id": self.plain.id,
                                          "mobile_phone": "+32 470 00 00 01"})
        self.emp_officer = Employee.create({"name": "STYD Officer Employee", "user_id": self.officer.id})
        self.emp_other = Employee.create({"name": "STYD Other Employee", "mobile_phone": "+32 470 99 99 99",
                                          "private_email": "other.private@example.com"})
        if "hr.leave.type" in self.env:
            LeaveType = self.env["hr.leave.type"]
            no_allocation = False if LeaveType._fields["requires_allocation"].type == "boolean" else "no"  # 19: Boolean
            self.leave_type = LeaveType.create({
                "name": "STYD paid leave", "requires_allocation": no_allocation, "time_type": "leave",
                "company_id": False,
            })
            self.type_field = "holiday_status_id"
        else:  # Odoo 20: time off types are work entry types
            self.leave_type = self.env["hr.work.entry.type"].create({
                "name": "STYD paid leave", "code": "STYDPL", "requires_allocation": False,
                "time_off_selectable": True, "count_as": "absence",
            })
            self.type_field = "work_entry_type_id"
        Leave = self.env["hr.leave"].with_context(mail_create_nolog=True, mail_notrack=True)
        self.leave_plain = Leave.create({
            "name": "plain leave", "employee_id": self.emp_plain.id, self.type_field: self.leave_type.id,
            "request_date_from": "2026-03-02", "request_date_to": "2026-03-03",
        })
        self.leave_other = Leave.create({
            "name": "other leave (private reason)", "employee_id": self.emp_other.id,
            self.type_field: self.leave_type.id,
            "request_date_from": "2026-03-09", "request_date_to": "2026-03-10",
        })
        Attendance = self.env["hr.attendance"]
        self.att_plain = Attendance.create({"employee_id": self.emp_plain.id, "check_in": "2026-03-04 08:00:00",
                                            "check_out": "2026-03-04 16:00:00"})
        self.att_other = Attendance.create({"employee_id": self.emp_other.id, "check_in": "2026-03-04 09:00:00",
                                            "check_out": "2026-03-04 17:00:00"})
        # An approved pairing of this database (the executor reads its row).
        self.pairing = {"pairing_id": self.make_pairing().pairing_id, "owner_uid": self.admin.id}

    # -- helpers ------------------------------------------------------------------------
    def run_op(self, op, args, member):
        self.sync()
        fields = {"v": 1, "id": str(uuid.uuid4()), "ts": 0, "op": op, "member_uid": member.id,
                  "pairing_id": self.pairing["pairing_id"], "args_json": "{}"}
        out = ex.execute_request(self.dbname, self.pairing, fields, args, registry=self.registry)
        self.reload()
        self.assertTrue(out["ok"], out)
        return out

    def member_orm(self, user):
        ctx = ex.member_context(user)
        orm = self.env["styd.odoo.bridge.orm"].with_user(user).with_context(**ctx)
        return MemberOrm(orm, self.admin.id)

    def assertRefused(self, codes, fn, *args, **kwargs):
        with self.assertRaises(StydOrmError) as ctx:
            fn(*args, **kwargs)
        self.assertIn(ctx.exception.code, codes, (args, kwargs))
        return ctx.exception

    def odoo_ids(self, user, model, domain):
        """What Odoo itself lets this user read (access rights and record rules)."""
        Model = self.env[model].with_user(user).with_context(allowed_company_ids=user.company_ids.ids)
        if not model_has_access(Model, "read"):
            return None
        return set(Model.search(domain).ids)

    # -- the sudo routes ------------------------------------------------------------------
    def test_01_sudo_routes_refuse_hr(self):
        orm = self.env["styd.odoo.bridge.orm"].sudo()
        for model in ORM_HR_MODELS:
            self.assertRefused({"model_not_allowed"}, orm._orm_search_read, model, fields=["id"])
            self.assertRefused({"model_not_allowed"}, orm._orm_read_group, model, group_by=["id"])
            self.assertRefused({"model_not_allowed"}, orm._orm_model_fields, model)
        self.assertFalse([m for m in orm._orm_list_models() if m["model"].startswith("hr.")])
        # hr.employee itself: never, not even as the member
        out = self.run_op("orm.search_read", {"model": "hr.employee", "fields": ["name"]}, self.officer)
        self.assertEqual((out["status"], out["body"]["error"]), (400, "model_not_allowed"))

    # -- an HR officer sees what Odoo lets them see -------------------------------------------
    def test_10_officer_sees_what_odoo_lets_them_see(self):
        ours = [self.emp_plain.id, self.emp_other.id, self.emp_officer.id]
        for model, fields in (
            ("hr.leave", ["employee_id", "state", "number_of_days", self.type_field]),
            ("hr.attendance", ["employee_id", "check_in", "check_out", "worked_hours"]),
        ):
            domain = [["employee_id", "in", ours]]
            out = self.run_op("orm.search_read", {"model": model, "fields": fields, "domain": domain}, self.officer)
            expected = self.odoo_ids(self.officer, model, domain)
            if expected is None:
                self.assertEqual(out["status"], 403, model)
                continue
            self.assertEqual(out["status"], 200, out["body"])
            self.assertEqual(out["body"]["access_mode"], "member_rights")
            self.assertEqual({r["id"] for r in out["body"]["records"]}, expected, model)
        leaves = self.run_op("orm.search_read", {"model": "hr.leave", "fields": ["employee_id"],
                                                 "domain": [["employee_id", "in", ours]]}, self.officer)
        self.assertIn(self.leave_other.id, {r["id"] for r in leaves["body"]["records"]},
                      "a Time Off officer reads everyone's time off, as in Odoo")
        group = self.run_op("orm.read_group", {"model": "hr.leave", "group_by": ["employee_id"],
                                               "aggregates": ["number_of_days:sum"],
                                               "domain": [["employee_id", "in", ours]]}, self.officer)
        self.assertEqual(group["status"], 200, group["body"])
        self.assertEqual({g["employee_id"][0] for g in group["body"]["groups"]},
                         {self.emp_plain.id, self.emp_other.id})

    # -- a plain employee does not see others' private data -----------------------------------
    def test_11_plain_employee_sees_only_their_own(self):
        ours = [self.emp_plain.id, self.emp_other.id, self.emp_officer.id]
        for model, fields, own in (
            ("hr.leave", ["employee_id", "state", "number_of_days"], self.leave_plain.id),
            ("hr.attendance", ["employee_id", "check_in", "worked_hours"], self.att_plain.id),
        ):
            domain = [["employee_id", "in", ours]]
            out = self.run_op("orm.search_read", {"model": model, "fields": fields, "domain": domain}, self.plain)
            expected = self.odoo_ids(self.plain, model, domain)
            if expected is None:
                self.assertEqual(out["status"], 403, model)
                continue
            got = {r["id"] for r in out["body"]["records"]}
            self.assertEqual(got, expected, model)
            self.assertEqual(got, {own}, "%s: only the employee's own rows" % model)
        out = self.run_op("orm.read_group", {"model": "hr.leave", "group_by": ["employee_id"],
                                             "aggregates": ["number_of_days:sum"],
                                             "domain": [["employee_id", "in", ours]]}, self.plain)
        self.assertIn("groups", out["body"], out)
        self.assertEqual({g["employee_id"][0] for g in out["body"]["groups"]}, {self.emp_plain.id},
                         "a total never folds in someone else's time off")
        # The directory is public in Odoo (names, jobs); private columns never come out.
        out = self.run_op("orm.search_read", {"model": "hr.employee.public", "fields": ["name", "work_email"],
                                              "domain": [["id", "in", ours]]}, self.plain)
        self.assertEqual(out["status"], 200)
        self.assertEqual({r["id"] for r in out["body"]["records"]}, set(ours))
        self.assertTrue(all(set(r) == {"id", "name", "work_email"} for r in out["body"]["records"]))
        for field in ("mobile_phone", "private_email", "birthday", "km_home_work"):
            out = self.run_op("orm.search_read", {"model": "hr.employee.public", "fields": ["name", field]},
                              self.plain)
            self.assertEqual((out["status"], out["body"]["error"]), (400, "field_not_allowed"), field)
            out = self.run_op("orm.search_read", {"model": "hr.employee.public", "fields": ["name"],
                                                  "domain": [[field, "!=", False]]}, self.plain)
            self.assertEqual((out["status"], out["body"]["error"]), (400, "field_not_allowed"), field)
        # The officer is walled the same way: the wall takes no role.
        out = self.run_op("orm.search_read", {"model": "hr.employee.public", "fields": ["mobile_phone"]},
                          self.officer)
        self.assertEqual((out["status"], out["body"]["error"]), (400, "field_not_allowed"))
        self.assertNotIn("+32 470", str(out))

    # -- every left-out field is refused --------------------------------------------------------
    def test_20_every_left_out_field_is_refused(self):
        orm = self.member_orm(self.officer)
        checked = 0
        for model in sorted(ORM_HR_MODELS):
            if model not in self.env:
                continue
            allowed = set(ORM_HR_FIELDS[model])
            meta = self.env[model].fields_get()
            left_out = sorted(set(meta) - allowed)
            self.assertTrue(left_out, model)
            for fname in left_out:
                self.assertRefused({"field_not_allowed"}, orm._orm_search_read, model, fields=["id", fname])
                self.assertRefused({"field_not_allowed", "operator_not_allowed", "domain_invalid"},
                                   orm._orm_search_read, model, fields=["id"], domain=[[fname, "!=", False]])
                self.assertRefused({"field_not_allowed", "order_invalid"},
                                   orm._orm_search_read, model, fields=["id"], order=fname)
                self.assertRefused({"field_not_allowed"}, orm._orm_read_group, model, group_by=[fname])
                self.assertRefused({"field_not_allowed"}, orm._orm_read_group, model,
                                   group_by=["id"], aggregates=["%s:sum" % fname])
                checked += 1
            # A read that names no field would return every field: refused.
            self.assertRefused({"field_not_allowed"}, orm._orm_search_read, model)
            self.assertRefused({"field_not_allowed"}, orm._orm_read_group, model)
            # orm.fields describes the wall's fields only.
            described = {f["name"] for f in orm._orm_model_fields(model)}
            self.assertTrue(described <= allowed, (model, described - allowed))
        self.assertGreater(checked, 100)

    def test_21_listed_fields_are_readable(self):
        """The wall's own lists work end to end (the fields this Odoo has)."""
        orm = self.member_orm(self.officer)
        for model in sorted(ORM_HR_MODELS):
            if model not in self.env:
                continue
            meta = self.env[model].fields_get()
            fields = [f for f in ORM_HR_FIELDS[model] if f in meta and f != "id"]
            try:
                domain = PUBLIC_HOLIDAYS if model == "resource.calendar.leaves" else None
                out = orm._orm_search_read(model, fields=fields, domain=domain, limit=5)
            except Exception as exc:  # an AccessError is Odoo's own answer, not the wall's
                self.assertNotIsInstance(exc, StydOrmError, (model, getattr(exc, "code", exc)))
                continue
            self.assertIsInstance(out["records"], list, model)

    def test_22_hr_company_scope(self):
        """STYD's company scope applies on top of Odoo's rules (employee_company_id for time off)."""
        company2 = self.env["res.company"].create({"name": "STYD HR second"})
        self.officer.write({"company_ids": [Command.link(company2.id)]})
        emp2 = self.env["hr.employee"].create({"name": "STYD second-company employee", "company_id": company2.id})
        leave2 = self.env["hr.leave"].with_context(mail_create_nolog=True).create({
            "name": "c2 leave", "employee_id": emp2.id, self.type_field: self.leave_type.id,
            "request_date_from": "2026-03-16", "request_date_to": "2026-03-16",
        })
        args = {"model": "hr.leave", "fields": ["employee_id"],
                "domain": [["employee_id", "in", [emp2.id, self.emp_other.id]]]}
        first = self.officer.company_id.id
        ids = {r["id"] for r in self.run_op("orm.search_read", dict(args, company_ids=[first]),
                                            self.officer)["body"]["records"]}
        self.assertEqual(ids, {self.leave_other.id})
        ids = {r["id"] for r in self.run_op("orm.search_read", dict(args, company_ids=[company2.id]),
                                            self.officer)["body"]["records"]}
        self.assertEqual(ids, {leave2.id})
        att2 = self.env["hr.attendance"].create({"employee_id": emp2.id, "check_in": "2026-03-05 08:00:00",
                                                 "check_out": "2026-03-05 12:00:00"})
        self.officer.write({GROUPS: [Command.link(self.env.ref("hr_attendance.group_hr_attendance_manager").id)]})
        att = self.run_op("orm.search_read", {"model": "hr.attendance", "fields": ["employee_id"],
                                              "company_ids": [company2.id],
                                              "domain": [["employee_id", "in", [emp2.id, self.emp_other.id]]]},
                          self.officer)
        self.assertEqual({r["id"] for r in att["body"]["records"]}, {att2.id},
                         "attendance is scoped through the employee's company")


    def test_23_public_holidays_and_employee_managers(self):
        """Public holidays (resource.calendar.leaves with no resource), with STYD's
        company scope and the asker's own rights; never a person's leave row. The
        directory's manager and schedule fields, where the version has them."""
        company2 = self.env["res.company"].create({"name": "STYD HR holidays second"})
        self.officer.write({"company_ids": [Command.link(company2.id)]})
        first = self.officer.company_id
        Holidays = self.env["resource.calendar.leaves"]
        calendar1 = first.resource_calendar_id or self.env["resource.calendar"].create(
            {"name": "STYD calendar 1", "company_id": first.id})
        calendar2 = self.env["resource.calendar"].create({"name": "STYD calendar 2", "company_id": company2.id})
        h1 = Holidays.create({"name": "STYD holiday 1", "calendar_id": calendar1.id,
                              "date_from": "2026-05-01 00:00:00", "date_to": "2026-05-01 23:59:59"})
        h2 = Holidays.create({"name": "STYD holiday 2", "calendar_id": calendar2.id,
                              "date_from": "2026-05-08 00:00:00", "date_to": "2026-05-08 23:59:59"})
        self.assertEqual((h1.company_id, h2.company_id), (first, company2))
        personal = Holidays.create({"name": "STYD personal leave row", "calendar_id": calendar1.id,
                                    "resource_id": self.emp_other.resource_id.id,
                                    "date_from": "2026-05-11 00:00:00", "date_to": "2026-05-11 23:59:59"})
        ours = [h1.id, h2.id, personal.id]
        fields = ["date_from", "date_to", "calendar_id", "company_id"]
        for user in (self.plain, self.officer):
            domain = [["id", "in", ours], ["resource_id", "=", False]]
            out = self.run_op("orm.search_read", {"model": "resource.calendar.leaves", "fields": fields,
                                                  "domain": domain}, user)
            self.assertEqual(out["status"], 200, out["body"])
            self.assertEqual(out["body"]["access_mode"], "member_rights")
            got = {r["id"] for r in out["body"]["records"]}
            expected = self.odoo_ids(user, "resource.calendar.leaves",
                                     [("id", "in", ours), ("resource_id", "=", False),
                                      ("company_id", "in", user.company_ids.ids)])
            self.assertEqual(got, expected, user.login)
            self.assertIn(h1.id, got, user.login)
            self.assertNotIn(personal.id, got, user.login)
            self.assertTrue(all(set(r) == {"id"} | set(fields) for r in out["body"]["records"]))
            # Not public-holidays-only: refused, however it is written.
            for bad in ([["id", "in", ours]], [["resource_id", "!=", False]],
                        ["|", ["resource_id", "=", False], ["id", "in", ours]],
                        ["!", ["resource_id", "!=", False]]):
                out = self.run_op("orm.search_read", {"model": "resource.calendar.leaves", "fields": fields,
                                                      "domain": bad}, user)
                self.assertEqual(out["status"], 400, bad)
                self.assertIn(out["body"]["error"], ("field_not_allowed", "domain_invalid"), bad)
            out = self.run_op("orm.read_group", {"model": "resource.calendar.leaves", "group_by": ["company_id"],
                                                 "domain": [["id", "in", ours]]}, user)
            self.assertEqual((out["status"], out["body"]["error"]), (400, "field_not_allowed"))
            out = self.run_op("orm.search_read", {"model": "resource.calendar.leaves", "fields": ["name"],
                                                  "domain": PUBLIC_HOLIDAYS}, user)
            self.assertEqual((out["status"], out["body"]["error"]), (400, "field_not_allowed"))
        # STYD's company scope on top of Odoo's rules: no company, or one of the read's.
        args = {"model": "resource.calendar.leaves", "fields": ["company_id"],
                "domain": [["id", "in", ours], ["resource_id", "=", False]]}
        ids = {r["id"] for r in self.run_op("orm.search_read", dict(args, company_ids=[first.id]),
                                            self.officer)["body"]["records"]}
        self.assertEqual(ids, {h1.id})
        ids = {r["id"] for r in self.run_op("orm.search_read", dict(args, company_ids=[company2.id]),
                                            self.officer)["body"]["records"]}
        self.assertEqual(ids, {h2.id})
        # The sudo routes refuse it; resource.calendar itself stays closed.
        self.assertRefused({"model_not_allowed"}, self.env["styd.odoo.bridge.orm"].sudo()._orm_search_read,
                           "resource.calendar.leaves", fields=["date_from"], domain=PUBLIC_HOLIDAYS)
        out = self.run_op("orm.search_read", {"model": "resource.calendar", "fields": ["name"]}, self.officer)
        self.assertEqual((out["status"], out["body"]["error"]), (400, "model_not_allowed"))
        # The directory's manager and schedule fields: read and filtered as the member.
        self.emp_plain.write({"parent_id": self.emp_officer.id})
        # Where the version has them, and as far as Odoo's own field groups let this user read them.
        public = self.env["hr.employee.public"]._fields
        present = [f for f in ("leave_manager_id", "attendance_manager_id", "expense_manager_id",
                               "resource_calendar_id") if f in public]
        self.assertIn("resource_calendar_id", present)
        visible = self.env["hr.employee.public"].with_user(self.plain).fields_get()
        for field in [f for f in present if f not in visible]:
            out = self.run_op("orm.search_read", {"model": "hr.employee.public", "fields": ["name", field]},
                              self.plain)
            self.assertEqual((out["status"], out["body"]["error"]), (400, "field_not_allowed"), field)
        present = [f for f in present if f in visible]
        out = self.run_op("orm.search_read", {"model": "hr.employee.public", "fields": ["name"] + present,
                                              "domain": [["id", "=", self.emp_plain.id]]}, self.plain)
        self.assertEqual(out["status"], 200, out["body"])
        row = out["body"]["records"][0]
        self.assertEqual(set(row), {"id", "name"} | set(present))
        self.assertEqual(row["resource_calendar_id"] and row["resource_calendar_id"][0],
                         self.emp_plain.resource_calendar_id.id or False)
        for field in present:
            value = self.emp_plain[field].id
            if not value:
                continue
            out = self.run_op("orm.search_read", {"model": "hr.employee.public", "fields": ["name"],
                                                  "domain": [[field, "=", value],
                                                             ["id", "=", self.emp_plain.id]]}, self.plain)
            self.assertEqual({r["id"] for r in out["body"]["records"]}, {self.emp_plain.id}, field)

@tagged("post_install", "-at_install")
class TestPayOnAnalyticLines(ChannelCase):
    def test_amount_only_on_journal_items(self):
        if "account.analytic.line" not in self.env:
            self.skipTest("account is not installed")
        orm = self.env["styd.odoo.bridge.orm"].sudo()
        model = "account.analytic.line"
        journal_item = orm._orm_journal_item_field(model)  # move_id on Odoo 15
        journal_items = [[journal_item, "!=", False]]

        def refused(code, **kw):
            with self.assertRaises(StydOrmError) as ctx:
                (orm._orm_read_group if "group_by" in kw or "aggregates" in kw else orm._orm_search_read)(model, **kw)
            self.assertEqual(ctx.exception.code, code, kw)

        # Not journal-items-only: a timesheet read, which follows the HR rules and is
        # never served by the sudo routes (the amount with it).
        refused("model_not_allowed", fields=["amount"])
        refused("model_not_allowed", fields=["name"], domain=[["amount", "<", 0]])
        refused("model_not_allowed", fields=["name"], order="amount desc")
        refused("model_not_allowed", group_by=["account_id"], aggregates=["amount:sum"])
        refused("model_not_allowed", fields=["amount"], domain=["|", [journal_item, "!=", False], ["id", ">", 0]])
        refused("model_not_allowed", fields=["amount"], domain=["!", [journal_item, "=", False]])
        refused("model_not_allowed", fields=["amount"], domain=[[journal_item, "=", False]])
        refused("model_not_allowed", fields=["unit_amount", "name", "date"])
        # The ledger reader's reads stay open.
        self.assertIn("records", orm._orm_search_read(model, fields=["amount", "date"], domain=journal_items))
        self.assertIn("groups", orm._orm_read_group(model, group_by=["account_id"], aggregates=["amount:sum"],
                                                    domain=journal_items + [["date", ">=", "2026-01-01"]]))
