import datetime
import decimal
import itertools

import babel.dates
from dateutil.relativedelta import relativedelta

from odoo import models
from odoo.tools import get_lang

from . import bridge_tz

# Access mode reported on every ORM response (MVP policy: sudo + company scope).
ORM_ACCESS_MODE = "sudo_company_scoped"

# Odoo 20 replaced the public read_group(fields=..., lazy=...) API. When True the
# bridge builds its groups from the private _read_group() through
# _orm_read_group_rows(), which reproduces Odoo 19's read_group() output. On
# 19.0 it stays False (the real read_group() is used) and the adapter is only
# exercised by the shape-parity test.
ORM_USE_PRIVATE_READ_GROUP = True

# Access mode of the outbound channel's answers: the read ran as the asking
# member's own Odoo user, under that user's access rights and record rules.
ORM_MEMBER_ACCESS_MODE = "member_rights"

# Context key the channel executor sets: the ORM primitives below then read as
# env.user (no sudo) and scope companies to env.companies (the member's own).
ORM_MEMBER_RIGHTS_CTX = "styd_bridge_member_rights"

# Datetime values in search-read records, when a tz is applied (tz_aware_v1).
ORM_TZ_DATETIME_FORMAT = "iso8601_offset"

# Read-only model allowlist for the bridge transport layer.
#
# This is a STABLE, BROAD allowlist of common Odoo business models so future
# Speak To Your Database features can cover more business areas WITHOUT
# requiring marketplace users to upgrade this module again. STYD remains the
# product-control layer and decides which of these models/features are actually
# enabled for a given customer; the bridge only guarantees that access is
# read-only, allowlisted, field-filtered and company-scoped.
#
# Membership here does NOT add an install dependency: `depends` stays ["base"].
# A model listed below that is not installed on a given database is simply not
# in `self.env`, so it is skipped by /models and rejected per-request with the
# `model_not_installed` code -- never a global crash.
#
# Deliberately EXCLUDED:
#   res.users, ir.config_parameter, ir.attachment, mail.message, mail.thread,
#   res.groups, ir.model.access, ir.rule, ir.module.module, auth.* and
#   HR/private employee models such as hr.employee.
ORM_MODEL_ALLOWLIST = frozenset({
    # Contacts / companies
    "res.partner",
    "res.company",

    # Sales
    "sale.order",
    "sale.order.line",
    "sale.report",

    # Invoicing / accounting
    "account.move",
    "account.move.line",
    "account.payment",
    "account.journal",
    "account.account",
    "account.tax",
    "account.payment.term",

    # Products
    "product.template",
    "product.product",
    "product.category",
    "uom.uom",

    # Inventory
    "stock.quant",
    "stock.location",
    "stock.move",
    "stock.move.line",
    "stock.picking",
    "stock.picking.type",
    "stock.warehouse",
    "stock.warehouse.orderpoint",
    "stock.lot",

    # Purchase
    "purchase.order",
    "purchase.order.line",

    # CRM
    "crm.lead",
    "crm.stage",
    "crm.team",
    "crm.tag",

    # Projects / tasks
    "project.project",
    "project.task",
    "project.tags",

    # Manufacturing
    "mrp.production",
    "mrp.workorder",
    "mrp.bom",
    "mrp.bom.line",
    "mrp.routing",

    # Maintenance
    "maintenance.equipment",
    "maintenance.request",
    "maintenance.team",

    # M-R2: every model STYD reads on an API key (odooReadPolicy.ts and its
    # area lists), so one add-on upgrade covers them. STYD's switches keep
    # deciding what is used. HR is not here: it has its own walled list
    # (ORM_HR_FIELDS, M-R6), read over the channel only.
    # Point of Sale
    "pos.order",
    "pos.order.line",
    "pos.session",
    "pos.config",
    "pos.payment",
    "pos.payment.method",
    "report.pos.order",
    # Bank statements and reconciliation (ledger reader)
    "account.bank.statement",
    "account.bank.statement.line",
    "account.partial.reconcile",
    # Analytic accounting (cost centres)
    "account.analytic.line",
    "account.analytic.account",
    "account.analytic.plan",
    # Stock valuation, manufacturing extras
    "stock.valuation.layer",
    "mrp.workcenter",
    "mrp.workcenter.productivity",
    "mrp.workcenter.productivity.loss",
    "mrp.routing.workcenter",
    "mrp.unbuild",
    # Project stages, milestones and updates
    "project.task.type",
    "project.project.stage",
    "project.milestone",
    "project.update",
    # Currency rates (thresholds named in another currency)
    "res.currency.rate",
})

# M-R6: HR, exactly what STYD reads on an API key (odooHrAccess.ts
# ODOO_HR_FIELDS), with the same fields left out: a per-model field ALLOWLIST,
# never a denylist. Every field a read touches (returned, filtered, ordered,
# grouped, summed) must be listed; a read must name its fields. mobile_phone,
# every pay, cost or private field stays out for everyone: the wall takes no
# role, so no role opens it.
# These models are read over the outbound channel ONLY, as the asking member's
# own Odoo user (no sudo, read-only cursor): the HTTP routes (sudo) refuse them
# with model_not_allowed. hr.employee itself stays out for good
# (hr.employee.public is the view with no private column).
ORM_HR_FIELDS = {
    "hr.employee.public": (
        "id", "name", "active", "department_id", "job_id", "job_title", "parent_id", "company_id",
        "work_email", "work_phone", "user_id", "tz",
    ),
    "hr.department": ("id", "name", "complete_name", "parent_id", "manager_id", "company_id", "active"),
    # start_datetime / stop_datetime on 15 to 19, request_date_from / request_date_to on 20.
    # Never the type or the description.
    "hr.leave.report.calendar": (
        "id", "employee_id", "department_id", "company_id", "state", "duration", "start_datetime",
        "stop_datetime", "request_date_from", "request_date_to",
    ),
    # holiday_status_id on 15 to 19, work_entry_type_id on 20.
    "hr.leave": (
        "id", "employee_id", "department_id", "employee_company_id", "user_id", "request_date_from",
        "request_date_to", "date_from", "date_to", "number_of_days", "number_of_hours",
        "number_of_hours_display", "state", "holiday_status_id", "work_entry_type_id",
    ),
    "hr.leave.type": ("id", "name", "time_type", "requires_allocation", "unpaid", "company_id", "active"),
    "hr.work.entry.type": (
        "id", "name", "count_as", "requires_allocation", "unpaid", "time_off_selectable", "active",
    ),
    "hr.leave.allocation": (
        "id", "employee_id", "employee_company_id", "number_of_days", "max_leaves", "leaves_taken",
        "date_from", "date_to", "state", "holiday_status_id", "work_entry_type_id", "type_request_unit",
    ),
    "hr.attendance": ("id", "employee_id", "check_in", "check_out", "worked_hours"),
}
ORM_HR_MODELS = frozenset(ORM_HR_FIELDS)

# STYD's company scope per HR model (odooHrAccess.ts ODOO_HR_COMPANY_SCOPE):
# (field, rows with no company allowed). None: configuration with no company.
# "employees": scoped through the employee's company (attendance).
ORM_HR_COMPANY_SCOPE = {
    "hr.employee.public": ("company_id", False),
    "hr.department": ("company_id", True),
    "hr.leave.report.calendar": ("company_id", False),
    # Not company_id: it is not always the employee's.
    "hr.leave": ("employee_company_id", False),
    "hr.leave.allocation": ("employee_company_id", False),
    "hr.leave.type": ("company_id", True),
    "hr.work.entry.type": None,
    "hr.attendance": "employees",
}

# Pay on an analytic line: a timesheet line's `amount` is the employee's cost.
# It is read only on journal-item lines (STYD's ledger reader), so a read that
# touches it must carry ["move_line_id", "!=", False] at the top level of a
# plain AND domain (never under an "|" or "!" that could undo it). On Odoo 15 the
# journal item of an analytic line is ``move_id``: ["move_id", "!=", False] there.
ORM_PAY_ON_LINES = {"account.analytic.line": frozenset({"amount"})}
# A field is forbidden if its lowercased name CONTAINS any of these substrings.
ORM_FORBIDDEN_FIELD_SUBSTRINGS = (
    "password", "passwd", "token", "api_key", "secret", "oauth",
    "reset", "signup", "private_key", "access_token", "refresh_token",
)

# "auth" is treated as a credential hint (see _orm_is_forbidden_field) EXCEPT
# when it appears only inside these benign English word stems -- so genuinely
# useful fields such as author_id / authorized_transaction_ids / authority_id
# are NOT blocked, while auth / auth_token / reauth_* still are.
ORM_AUTH_SAFE_WORD_STEMS = ("author", "authoriz", "authentic", "authority")

# Domain leaf operators allowed for the MVP. Anything else is rejected.
ORM_ALLOWED_DOMAIN_OPERATORS = frozenset({
    "=", "!=", "in", "not in", ">", "<", ">=", "<=", "ilike", "like",
})

# Field types that may be returned / filtered. Excludes binary, one2many,
# many2many to bound payloads and avoid heavy/relational data.
ORM_RETURNABLE_FIELD_TYPES = frozenset({
    "char", "text", "html", "integer", "float", "monetary", "boolean",
    "date", "datetime", "selection", "many2one",
})

ORM_GROUPABLE_FIELD_TYPES = frozenset({
    "many2one", "selection", "boolean", "date", "datetime", "char", "integer",
})

ORM_NUMERIC_FIELD_TYPES = frozenset({"integer", "float", "monetary"})

# M-R3: the named many2many exceptions of STYD's odooReadPolicy.ts, exactly.
# Each is one field on one model, to one relation; the same name on any other
# model stays refused, and so does any other many2many.
# Group-by only (Odoo names each group, so the related model is never read);
# never returned, filtered or ordered: {model: (field, relation)}.
ORM_GROUP_ONLY_M2M = {
    "account.move.line": ("tax_ids", "account.tax"),
    "stock.move": ("scrap_reason_tag_ids", "stock.scrap.reason.tag"),
    "project.task": ("user_ids", "res.users"),
}
# Filter "in" / "=" with positive user ids ("my tasks"): {model: (field, relation)}.
ORM_FILTER_M2M = {
    "project.task": ("user_ids", "res.users"),
}
# Returned when named (never in a read that names no fields, a domain, an
# order or a group-by): {model: field}.
ORM_RETURNED_M2M = {
    "mrp.bom.line": "bom_product_template_attribute_value_ids",
    "product.product": "product_template_attribute_value_ids",
}

# M-R5: at most this many companies in an ordered company_ids.
ORM_MAX_COMPANY_IDS = 50

ORM_ALLOWED_AGG_FUNCS = frozenset({"sum", "avg", "max", "min"})

ORM_DEFAULT_LIMIT = 80
ORM_MAX_LIMIT = 200
ORM_MAX_DOMAIN_CLAUSES = 25
ORM_MAX_DOMAIN_IN_VALUES = 200
ORM_MAX_GROUP_BY = 2
ORM_MAX_AGGREGATES = 5


def model_has_access(model, operation):
    """The model's access rights for ``operation``, as a bool. ``has_access`` since
    Odoo 18 (``check_access_rights`` is deprecated there and gone in 20)."""
    if hasattr(model, "has_access"):
        return bool(model.has_access(operation))
    return bool(model.check_access_rights(operation, raise_exception=False))


def model_check_access(model, operation):
    """Raise ``AccessError`` when the user may not ``operation`` this model (rights;
    on records, rules too). ``check_access`` since Odoo 18."""
    if hasattr(model, "has_access"):
        model.check_access(operation)
    else:
        model.check_access_rights(operation)


def _json_default(value):
    """Best-effort JSON serializer for ORM values (dates, bytes, Decimal).

    Existing Phase 1-3 payloads contain only plain JSON types, so this is never
    invoked for them and their serialized output is byte-for-byte unchanged.
    """
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    if isinstance(value, decimal.Decimal):
        return float(value)
    return str(value)


class StydOrmError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__("%s: %s" % (code, message))


def _short(value):
    return str(value)[:64]


class StydOdooBridgeOrm(models.AbstractModel):
    """Read-only ORM primitives for the Speak To Your Database bridge."""

    _name = "styd.odoo.bridge.orm"
    _description = "Speak To Your Database Bridge ORM (read-only MVP)"

    ACCESS_MODE = ORM_ACCESS_MODE
    MODEL_ALLOWLIST = ORM_MODEL_ALLOWLIST
    FORBIDDEN_FIELD_SUBSTRINGS = ORM_FORBIDDEN_FIELD_SUBSTRINGS
    AUTH_SAFE_WORD_STEMS = ORM_AUTH_SAFE_WORD_STEMS
    ALLOWED_DOMAIN_OPERATORS = ORM_ALLOWED_DOMAIN_OPERATORS
    RETURNABLE_FIELD_TYPES = ORM_RETURNABLE_FIELD_TYPES
    GROUPABLE_FIELD_TYPES = ORM_GROUPABLE_FIELD_TYPES
    NUMERIC_FIELD_TYPES = ORM_NUMERIC_FIELD_TYPES
    ALLOWED_AGG_FUNCS = ORM_ALLOWED_AGG_FUNCS
    DEFAULT_LIMIT = ORM_DEFAULT_LIMIT
    MAX_LIMIT = ORM_MAX_LIMIT
    MAX_DOMAIN_CLAUSES = ORM_MAX_DOMAIN_CLAUSES
    MAX_DOMAIN_IN_VALUES = ORM_MAX_DOMAIN_IN_VALUES
    MAX_GROUP_BY = ORM_MAX_GROUP_BY
    MAX_AGGREGATES = ORM_MAX_AGGREGATES

    def _orm_member_rights(self):
        """True when the outbound channel runs this read as the member (no sudo)."""
        return bool(self.env.context.get(ORM_MEMBER_RIGHTS_CTX))

    def _orm_base(self, model_name):
        """The model to read: sudo for the HTTP routes, the member's own env for the channel."""
        model = self.env[model_name]
        return model if self._orm_member_rights() else model.sudo()

    def _orm_check_model(self, model_name):
        if not isinstance(model_name, str):
            raise StydOrmError("model_not_allowed", "Model is not allowed by this bridge.")
        if model_name in ORM_HR_MODELS:
            # M-R6: HR only as the asking member, over the outbound channel.
            if not self._orm_member_rights():
                raise StydOrmError(
                    "model_not_allowed",
                    "HR is read over the outbound channel only, as the asking member's own Odoo user.")
            if model_name not in self.env:
                raise StydOrmError("model_not_installed", "Model is not installed on this Odoo instance.")
            return
        if not model_name or model_name not in self.MODEL_ALLOWLIST:
            raise StydOrmError("model_not_allowed", "Model is not allowed by this bridge.")
        # Graceful degradation: the model is allowlisted but its Odoo app is not
        # installed on THIS database (e.g. a customer without Manufacturing). We
        # return a distinct, machine-readable code so STYD can show "app not
        # installed" rather than "forbidden", and so a single missing optional
        # app can never crash the bridge globally -- only this one request fails.
        if model_name not in self.env:
            raise StydOrmError("model_not_installed", "Model is not installed on this Odoo instance.")


    def _orm_is_forbidden_field(self, name):
        low = (name or "").lower()
        if any(bad in low for bad in self.FORBIDDEN_FIELD_SUBSTRINGS):
            return True
        if "auth" in low:
            residue = low
            for stem in self.AUTH_SAFE_WORD_STEMS:
                residue = residue.replace(stem, "")
            if "auth" in residue:
                return True
        return False

    def _orm_scope_companies(self):
        if self._orm_member_rights():
            # The channel sets allowed_company_ids to the member's companies.
            return self.env.companies
        service = self.env["styd.odoo.bridge.service"]
        owner_id = None
        try:
            owner_id = service._get_connector_owner_user_id()
        except Exception:
            owner_id = None
        if owner_id:
            owner = self.env["res.users"].sudo().browse(owner_id)
            if owner.exists() and owner.company_ids:
                return owner.company_ids
        return self.env["res.company"].sudo().search([])

    def _orm_company_domain(self, model_name, companies):
        model = self.env[model_name].sudo()
        if model_name in ORM_HR_COMPANY_SCOPE:
            return self._orm_hr_company_domain(model_name, model, companies)
        if "company_id" in model._fields:
            return ["|", ("company_id", "=", False), ("company_id", "in", companies.ids)]
        return []

    # ------------------------------------------------------------------
    # M-R6: the HR wall (odooHrAccess.ts) and pay on analytic lines
    # ------------------------------------------------------------------
    def _orm_hr_company_domain(self, model_name, model, companies):
        """STYD's company scope for an HR model (on top of Odoo's own rules)."""
        scope = ORM_HR_COMPANY_SCOPE[model_name]
        if scope is None:
            return []
        if scope == "employees":
            # The employees of the read's companies, archived ones included (their
            # rows stay theirs), read as the member through hr.employee.public.
            employees = self.env["hr.employee.public"].with_context(active_test=False)._search(
                [("company_id", "in", companies.ids)])
            return [("employee_id", "in", employees)]
        field, allow_empty = scope
        if field not in model._fields:
            field, allow_empty = "company_id", True
            if field not in model._fields:
                return []
        if allow_empty:
            return ["|", (field, "=", False), (field, "in", companies.ids)]
        return [(field, "in", companies.ids)]

    def _orm_hr_require_named(self, model, named):
        if model in ORM_HR_MODELS and not named:
            raise StydOrmError("field_not_allowed", "An HR read must name its fields.")

    def _orm_touched(self, fields=(), domain=(), order=None, group_by=(), agg_names=()):
        """Every field a VALIDATED read touches (returned, filtered, ordered, grouped, summed)."""
        touched = list(fields or ()) + list(group_by or ()) + list(agg_names or ())
        touched += [leaf[0] for leaf in (domain or ()) if not isinstance(leaf, str)]
        for term in (order or "").split(","):
            if term.strip():
                touched.append(term.split()[0])
        return touched

    def _orm_journal_item_field(self, model):
        """The analytic line's journal item: ``move_line_id`` since Odoo 16, ``move_id`` on 15."""
        return "move_line_id" if model in self.env and "move_line_id" in self.env[model]._fields else "move_id"

    def _orm_journal_items_only(self, domain, model):
        """A plain AND domain (no "|" or "!") with [<journal item>, "!=", False]."""
        field = self._orm_journal_item_field(model)
        leaves = domain or []
        plain = not any(isinstance(t, str) and t in ("|", "!") for t in leaves)
        return plain and any(
            not isinstance(t, str) and t[0] == field and t[1] == "!=" and t[2] is False
            for t in leaves)

    def _orm_default_fields_without_pay(self, model, fields, safe_fields, domain):
        """A read naming no field gets every returnable field, minus pay it may
        not read (named, the same field is refused)."""
        pay = ORM_PAY_ON_LINES.get(model)
        if fields or not pay or self._orm_journal_items_only(domain, model):
            return safe_fields
        return [f for f in safe_fields if f not in pay]

    def _orm_check_walls(self, model, domain, touched):
        """The HR field wall, then pay on analytic lines. Called after the
        validators, on their normalised output."""
        allowed = ORM_HR_FIELDS.get(model)
        if allowed is not None:
            for fname in touched:
                if fname not in allowed:
                    raise StydOrmError("field_not_allowed", "Field not allowed for HR: %s." % _short(fname))
        pay = ORM_PAY_ON_LINES.get(model)
        if pay and pay.intersection(touched):
            if not self._orm_journal_items_only(domain, model):
                raise StydOrmError(
                    "field_not_allowed",
                    "Field not allowed: %s (read only on journal-item lines: add [\"%s\", \"!=\", false])."
                    % (_short(sorted(pay.intersection(touched))[0]), self._orm_journal_item_field(model)))

    def _orm_m2m_pair(self, table, model, field, info):
        """True when (model, field) is the named pair of ``table``, as a stored
        many2many to the named relation (odooReadPolicy.ts' isXxxGroup)."""
        pair = table.get(model) if model else None
        return bool(pair) and pair[0] == field and info.get("type") == "many2many" \
            and info.get("relation") == pair[1] and bool(info.get("store"))

    def _orm_is_assignee_filter(self, model, field, info, operator, value):
        if not self._orm_m2m_pair(ORM_FILTER_M2M, model, field, info) or operator not in ("in", "="):
            return False

        def positive_id(v):
            return isinstance(v, int) and not isinstance(v, bool) and v > 0

        if isinstance(value, list):
            return bool(value) and all(positive_id(v) for v in value)
        return positive_id(value)

    def _orm_is_returned_m2m(self, model, field, info):
        return bool(model) and ORM_RETURNED_M2M.get(model) == field and info.get("type") == "many2many"

    def _orm_validate_fields(self, meta, fields, model=None):
        if not fields:
            return [
                fname for fname, info in meta.items()
                if not self._orm_is_forbidden_field(fname)
                and info.get("type") in self.RETURNABLE_FIELD_TYPES
            ]
        if not isinstance(fields, list):
            raise StydOrmError("field_not_allowed", "fields must be a list of field names.")
        safe = []
        for fname in fields:
            if not isinstance(fname, str) or "." in fname:
                raise StydOrmError("field_not_allowed", "Invalid field name.")
            if fname not in meta or self._orm_is_forbidden_field(fname):
                raise StydOrmError("field_not_allowed", "Field not allowed: %s." % _short(fname))
            if meta[fname].get("type") not in self.RETURNABLE_FIELD_TYPES \
                    and not self._orm_is_returned_m2m(model, fname, meta[fname]):
                raise StydOrmError("field_not_allowed", "Field type not returnable: %s." % _short(fname))
            safe.append(fname)
        return safe

    def _orm_is_scalar(self, value):
        return value is None or isinstance(value, (str, int, float, bool))

    def _orm_validate_domain_value(self, operator, value):
        if operator in ("in", "not in"):
            if not isinstance(value, list):
                raise StydOrmError("domain_invalid", "Value for in/not in must be a list.")
            if len(value) > self.MAX_DOMAIN_IN_VALUES:
                raise StydOrmError("domain_invalid", "Too many values in an in/not in clause.")
            for item in value:
                if not self._orm_is_scalar(item):
                    raise StydOrmError("domain_invalid", "Invalid value inside a domain list.")
        elif not self._orm_is_scalar(value):
            raise StydOrmError("domain_invalid", "Invalid domain value.")

    def _orm_validate_domain(self, meta, domain, model=None):
        if not domain:
            return []
        if not isinstance(domain, list):
            raise StydOrmError("domain_invalid", "domain must be a list.")
        normalized = []
        leaves = 0
        for element in domain:
            if isinstance(element, str):
                if element not in ("&", "|", "!"):
                    raise StydOrmError("domain_invalid", "Invalid domain logical operator.")
                normalized.append(element)
                continue
            if not isinstance(element, (list, tuple)) or len(element) != 3:
                raise StydOrmError("domain_invalid", "Each domain clause must be [field, operator, value].")
            field, operator, value = element[0], element[1], element[2]
            leaves += 1
            if leaves > self.MAX_DOMAIN_CLAUSES:
                raise StydOrmError("domain_invalid", "Too many domain clauses.")
            if not isinstance(field, str) or "." in field:
                raise StydOrmError("field_not_allowed", "Invalid or relational domain field.")
            if field not in meta or self._orm_is_forbidden_field(field):
                raise StydOrmError("field_not_allowed", "Domain field not allowed: %s." % _short(field))
            if meta[field].get("type") not in self.RETURNABLE_FIELD_TYPES \
                    and not self._orm_is_assignee_filter(model, field, meta[field], operator, value):
                raise StydOrmError("field_not_allowed", "Domain field type not allowed: %s." % _short(field))
            if operator not in self.ALLOWED_DOMAIN_OPERATORS:
                raise StydOrmError("operator_not_allowed", "Operator not allowed: %s." % _short(operator))
            self._orm_validate_domain_value(operator, value)
            normalized.append((field, operator, value))
        self._orm_check_domain_balanced(normalized)
        return normalized

    def _orm_check_domain_balanced(self, normalized):
        if not normalized:
            return
        arity = {"&": 2, "|": 2, "!": 1}
        expected = 1
        for token in normalized:
            if expected == 0:
                expected = 1
            if isinstance(token, str):
                expected += arity.get(token, 0) - 1
            else:
                expected -= 1
        if expected != 0:
            raise StydOrmError("domain_invalid", "Domain is structurally invalid (unbalanced operators).")

    def _orm_validate_order(self, meta, order):
        if not order:
            return None
        if not isinstance(order, str):
            raise StydOrmError("order_invalid", "order must be a string.")
        terms = []
        for part in order.split(","):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if len(tokens) > 2:
                raise StydOrmError("order_invalid", "Invalid order term.")
            fname = tokens[0]
            direction = tokens[1].lower() if len(tokens) == 2 else "asc"
            if direction not in ("asc", "desc"):
                raise StydOrmError("order_invalid", "Invalid sort direction.")
            if "." in fname or fname not in meta or self._orm_is_forbidden_field(fname):
                raise StydOrmError("order_invalid", "Order field not allowed: %s." % _short(fname))
            if not meta[fname].get("store"):
                raise StydOrmError("order_invalid", "Order field is not stored: %s." % _short(fname))
            if meta[fname].get("type") not in self.RETURNABLE_FIELD_TYPES:
                raise StydOrmError("order_invalid", "Order field type not allowed: %s." % _short(fname))
            terms.append("%s %s" % (fname, direction))
        return ", ".join(terms) or None

    def _orm_resolve_limit(self, limit):
        if limit in (None, ""):
            return self.DEFAULT_LIMIT
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise StydOrmError("limit_exceeded", "limit must be an integer.")
        if limit < 1 or limit > self.MAX_LIMIT:
            raise StydOrmError("limit_exceeded", "limit must be between 1 and %d." % self.MAX_LIMIT)
        return limit

    def _orm_resolve_offset(self, offset):
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            return 0
        return offset

    def _orm_validate_group_by(self, meta, group_by, model=None):
        if not group_by:
            return []
        if not isinstance(group_by, list):
            raise StydOrmError("field_not_allowed", "group_by must be a list.")
        if len(group_by) > self.MAX_GROUP_BY:
            raise StydOrmError("field_not_allowed", "Too many group_by fields (max %d)." % self.MAX_GROUP_BY)
        out = []
        for gb in group_by:
            if not isinstance(gb, str) or "." in gb or ":" in gb:
                raise StydOrmError("field_not_allowed", "Invalid group_by field.")
            if gb not in meta or self._orm_is_forbidden_field(gb):
                raise StydOrmError("field_not_allowed", "group_by field not allowed: %s." % _short(gb))
            groupable = meta[gb].get("store") and meta[gb].get("type") in self.GROUPABLE_FIELD_TYPES
            if not groupable and not self._orm_m2m_pair(ORM_GROUP_ONLY_M2M, model, gb, meta[gb]):
                raise StydOrmError("field_not_allowed", "Field is not groupable: %s." % _short(gb))
            out.append(gb)
        return out

    def _orm_validate_aggregates(self, meta, aggregates):
        if not aggregates:
            return [], []
        if not isinstance(aggregates, list):
            raise StydOrmError("field_not_allowed", "aggregates must be a list.")
        if len(aggregates) > self.MAX_AGGREGATES:
            raise StydOrmError("field_not_allowed", "Too many aggregates (max %d)." % self.MAX_AGGREGATES)
        specs, names = [], []
        for spec in aggregates:
            if not isinstance(spec, str) or ":" not in spec:
                raise StydOrmError("field_not_allowed", "Invalid aggregate; use 'field:func'.")
            fname, func = spec.split(":", 1)
            fname, func = fname.strip(), func.strip().lower()
            if func not in self.ALLOWED_AGG_FUNCS:
                raise StydOrmError("field_not_allowed", "Aggregate function not allowed: %s." % _short(func))
            if "." in fname or fname not in meta or self._orm_is_forbidden_field(fname):
                raise StydOrmError("field_not_allowed", "Aggregate field not allowed: %s." % _short(fname))
            if not (meta[fname].get("store") and meta[fname].get("type") in self.NUMERIC_FIELD_TYPES):
                raise StydOrmError("field_not_allowed", "Aggregate field is not numeric/stored: %s." % _short(fname))
            if fname in names:
                raise StydOrmError("field_not_allowed", "Duplicate aggregate field: %s." % _short(fname))
            specs.append("%s:%s" % (fname, func))
            names.append(fname)
        return specs, names

    def _orm_validate_group_order(self, order, group_by, agg_names):
        if not order:
            return None
        if not isinstance(order, str):
            raise StydOrmError("order_invalid", "order must be a string.")
        allowed = set(group_by) | set(agg_names)
        terms = []
        for part in order.split(","):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if len(tokens) > 2:
                raise StydOrmError("order_invalid", "Invalid order term.")
            fname = tokens[0]
            direction = tokens[1].lower() if len(tokens) == 2 else "asc"
            if direction not in ("asc", "desc"):
                raise StydOrmError("order_invalid", "Invalid sort direction.")
            if fname not in allowed:
                raise StydOrmError("order_invalid", "Order must reference a group_by or aggregate field: %s." % _short(fname))
            terms.append("%s %s" % (fname, direction))
        return ", ".join(terms) or None

    # ------------------------------------------------------------------
    # Opt-in time zone (tz_aware_v1). Without "tz" / "tz_mode" in the request
    # nothing below runs and the bridge behaves exactly as before.
    # ------------------------------------------------------------------
    def _orm_resolve_tz(self, tz=None, tz_mode=None):
        """Return the IANA time zone to apply, or None for legacy behaviour.

        An explicit "tz" wins over "tz_mode"; "tz_mode": "company" uses the
        bridge time zone reported by /health (connector owner, then company).
        """
        if tz in (None, "") and tz_mode in (None, ""):
            return None
        if tz not in (None, ""):
            if not bridge_tz.is_valid_tz(tz):
                raise StydOrmError("tz_invalid", "tz must be a valid IANA time zone name.")
            return tz
        if tz_mode != "company":
            raise StydOrmError("tz_invalid", 'tz_mode must be "company".')
        return self.env["styd.odoo.bridge.service"]._get_bridge_tz()

    def _orm_resolve_lang(self, lang=None):
        """M-R4: a language for the read's names, or None (the default). Only an
        active res.lang code is accepted."""
        if lang in (None, ""):
            return None
        if not isinstance(lang, str) or lang not in dict(self.env["res.lang"].get_installed()):
            raise StydOrmError("lang_invalid", "lang must be the code of a language active in this Odoo.")
        return lang

    def _orm_resolve_companies(self, company_ids=None):
        """M-R5: the companies a read runs for, in order (the first is the read's
        company: on 18+ company-dependent values such as account codes are that
        company's). Without company_ids: the scope as before. With them: an
        ordered list of distinct ids, all inside the scope (the connector
        owner's companies; the member's own over the channel)."""
        scope = self._orm_scope_companies()
        if company_ids is None:
            return scope
        if not isinstance(company_ids, list) or not company_ids or len(company_ids) > ORM_MAX_COMPANY_IDS:
            raise StydOrmError("company_invalid", "company_ids must be a non-empty list of company ids.")
        for cid in company_ids:
            if not isinstance(cid, int) or isinstance(cid, bool) or cid < 1:
                raise StydOrmError("company_invalid", "company_ids must be a non-empty list of company ids.")
        if len(set(company_ids)) != len(company_ids):
            raise StydOrmError("company_invalid", "company_ids must not repeat a company.")
        if not set(company_ids) <= set(scope.ids):
            raise StydOrmError("company_invalid", "company_ids must be companies this read may use.")
        return scope.browse(company_ids)

    def _orm_scoped(self, base, companies, tz=None, lang=None):
        """The model to read with: the companies in order as allowed_company_ids,
        then the optional tz and lang."""
        scoped = base.with_context(allowed_company_ids=companies.ids)
        if tz:
            scoped = scoped.with_context(tz=tz)
        if lang:
            scoped = scoped.with_context(lang=lang)
        return scoped

    def _orm_localize_leaf(self, field, operator, value, tz):
        """Rewrite one datetime leaf whose value is local time into UTC leaves.

        Returns a list of domain elements (one leaf, or a small prefix-notation
        expression). A date-only value means the whole local day, with the same
        operator semantics Odoo uses for dates on datetime fields.
        """
        try:
            parsed = bridge_tz.parse_datetime_value(value)
        except ValueError:
            raise StydOrmError("domain_invalid", "Invalid date value for %s." % _short(field))
        if parsed is None or operator not in ("=", "!=", ">", "<", ">=", "<="):
            return [(field, operator, value)]
        moment, is_date = parsed

        if not is_date:
            if moment.tzinfo is not None:
                utc = moment.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            else:
                utc = bridge_tz.local_to_utc(moment, tz)
            return [(field, operator, bridge_tz.format_utc(utc))]

        start = bridge_tz.format_utc(bridge_tz.local_to_utc(moment, tz))
        end = bridge_tz.format_utc(bridge_tz.local_to_utc(moment + datetime.timedelta(days=1), tz))
        if operator == ">=":
            return [(field, ">=", start)]
        if operator == "<":
            return [(field, "<", start)]
        if operator == ">":
            return [(field, ">=", end)]
        if operator == "<=":
            return [(field, "<", end)]
        if operator == "=":
            return ["&", (field, ">=", start), (field, "<", end)]
        # "!=": outside the day, or unset (Odoo's != also matches empty values).
        return ["|", "|", (field, "=", False), (field, "<", start), (field, ">=", end)]

    def _orm_localize_domain(self, meta, domain, tz):
        if not tz or not domain:
            return domain
        out = []
        for element in domain:
            if isinstance(element, str):
                out.append(element)
                continue
            field, operator, value = element
            if meta[field].get("type") != "datetime":
                out.append(element)
                continue
            out.extend(self._orm_localize_leaf(field, operator, value, tz))
        return out

    def _orm_localize_records(self, meta, records, fields, tz):
        datetime_fields = [f for f in fields if meta.get(f, {}).get("type") == "datetime"]
        if not tz or not datetime_fields:
            return records
        for record in records:
            for fname in datetime_fields:
                moment = bridge_tz.parse_server_datetime(record.get(fname))
                if moment is not None:
                    record[fname] = bridge_tz.utc_to_local(moment, tz).isoformat()
        return records

    def _orm_group_ranges(self, meta, raw, group_by, tz):
        """Bucket bounds of date/datetime groups, as local ISO strings."""
        ranges = {}
        raw_ranges = raw.get("__range") or {}
        for gb in group_by:
            ftype = meta[gb].get("type")
            if ftype not in ("date", "datetime"):
                continue
            bounds = None
            for key, value in raw_ranges.items():
                if key.split(":")[0] == gb:
                    bounds = value
                    break
            if not bounds:
                ranges[gb] = False
                continue
            if ftype == "date":
                ranges[gb] = {"from": bounds.get("from"), "to": bounds.get("to")}
                continue
            converted = {}
            for side in ("from", "to"):
                moment = bridge_tz.parse_server_datetime(bounds.get(side))
                converted[side] = bridge_tz.utc_to_local(moment, tz).isoformat() if moment else None
            ranges[gb] = converted
        return ranges

    # ------------------------------------------------------------------
    # Odoo 20 read_group adapter
    # ------------------------------------------------------------------
    def _orm_read_group_rows(self, model, domain, group_by, agg_specs, limit=None, order=None):
        """Rows shaped like Odoo 19 read_group(..., lazy=False), from _read_group().

        Mirrors BaseModel.read_group and _read_group_format_result of Odoo 19
        for what the bridge allows: plain group_by fields (dates are grouped by
        month), "field:func" aggregates and an order on those names.
        """
        annotated = {}
        for gb in group_by:
            ftype = model._fields[gb].type
            annotated[gb] = "%s:month" % gb if ftype in ("date", "datetime") else gb
        aggregates = {"__count": "__count"}
        for spec in agg_specs:
            aggregates[spec.split(":")[0]] = spec

        if order:
            terms = []
            for term in order.split(","):
                term = term.strip()
                if not term:
                    continue
                fname, _sep, direction = term.partition(" ")
                key = annotated.get(fname) or aggregates.get(fname) or fname
                terms.append(("%s %s" % (key, direction.strip())).strip())
            order_spec = ", ".join(terms)
        else:
            order_spec = ", ".join(annotated.values())

        rows = model._read_group(
            domain,
            list(annotated.values()),
            list(aggregates.values()),
            limit=limit,
            order=order_spec or None,
        )

        locale = get_lang(model.env).code
        tz_name = model.env.context.get("tz")
        tzinfo = bridge_tz.get_tzinfo(tz_name) if tz_name else None
        out = []
        for row in rows:
            values = dict(zip(itertools.chain(annotated, aggregates), row))
            for gb in group_by:
                field = model._fields[gb]
                value = values[gb]
                if isinstance(value, models.BaseModel):
                    values[gb] = (value.id, value.sudo().display_name) if value else False
                elif field.type in ("date", "datetime"):
                    if value and isinstance(value, (datetime.date, datetime.datetime)):
                        range_start = value
                        range_end = value + relativedelta(months=1)
                        if field.type == "datetime":
                            fmt = bridge_tz.SERVER_DATETIME_FORMAT
                            if tzinfo is not None:
                                range_start = bridge_tz.localize(range_start, tzinfo).astimezone(datetime.timezone.utc)
                                range_end = bridge_tz.localize(range_end, tzinfo).astimezone(datetime.timezone.utc)
                            label = babel.dates.format_datetime(
                                range_start, format="MMMM yyyy", tzinfo=tzinfo, locale=locale,
                            )
                        else:
                            fmt = "%Y-%m-%d"
                            label = babel.dates.format_date(value, format="MMMM yyyy", locale=locale)
                        values[gb] = label
                        values.setdefault("__range", {})[gb] = {
                            "from": range_start.strftime(fmt),
                            "to": range_end.strftime(fmt),
                        }
                    elif not value:
                        values.setdefault("__range", {})[gb] = False
            out.append(values)
        return out

    def _orm_run_read_group(self, model, domain, group_by, agg_specs, limit=None, order=None):
        if ORM_USE_PRIVATE_READ_GROUP:
            return self._orm_read_group_rows(model, domain, group_by, agg_specs, limit=limit, order=order)
        return model.read_group(
            domain=domain,
            fields=agg_specs,
            groupby=group_by,
            lazy=False,
            limit=limit,
            orderby=order,
        )

    def _orm_list_models(self):
        out = []
        # M-R6: HR models are listed only over the channel (as the member); the
        # sudo routes never list or read them.
        names = self.MODEL_ALLOWLIST | ORM_HR_MODELS if self._orm_member_rights() else self.MODEL_ALLOWLIST
        for model_name in sorted(names):
            if model_name not in self.env:
                continue
            model = self._orm_base(model_name)
            allowed = True
            if self._orm_member_rights():
                allowed = model_has_access(model, "read")
            out.append({
                "model": model_name,
                "name": model_name,
                "label": model._description or model_name,
                "transient": bool(model._transient),
                "allowed": allowed,
            })
        return out

    def _orm_model_fields(self, model_name):
        self._orm_check_model(model_name)
        model = self._orm_base(model_name)
        if self._orm_member_rights():
            model_check_access(model, "read")
        meta = model.fields_get()
        hr_allowed = ORM_HR_FIELDS.get(model_name)
        out = []
        for fname in sorted(meta):
            if self._orm_is_forbidden_field(fname):
                continue
            if hr_allowed is not None and fname not in hr_allowed:
                continue  # M-R6: only the wall's fields are described
            info = meta[fname]
            ftype = info.get("type")
            out.append({
                "name": fname,
                "string": info.get("string"),
                "help": info.get("help") or None,
                "type": ftype,
                "relation": info.get("relation") or None,
                "relation_field": info.get("relation_field") or None,
                "required": bool(info.get("required")),
                "readonly": bool(info.get("readonly")),
                "store": bool(info.get("store")),
                "searchable": bool(info.get("searchable")),
                "groupable": bool(info.get("store")) and ftype in self.GROUPABLE_FIELD_TYPES,
                "selection": info.get("selection") if ftype == "selection" else None,
            })
        return out

    def _orm_search_read(self, model, domain=None, fields=None, limit=None, offset=None, order=None,
                         tz=None, tz_mode=None, lang=None, company_ids=None):
        self._orm_check_model(model)
        base = self._orm_base(model)
        if self._orm_member_rights():
            model_check_access(base, "read")
        meta = base.fields_get()

        self._orm_hr_require_named(model, fields)
        safe_fields = self._orm_validate_fields(meta, fields, model=model)
        valid_domain = self._orm_validate_domain(meta, domain, model=model)
        valid_order = self._orm_validate_order(meta, order)
        safe_fields = self._orm_default_fields_without_pay(model, fields, safe_fields, valid_domain)
        self._orm_check_walls(model, valid_domain, self._orm_touched(safe_fields, valid_domain, valid_order))
        resolved_limit = self._orm_resolve_limit(limit)
        resolved_offset = self._orm_resolve_offset(offset)
        resolved_tz = self._orm_resolve_tz(tz, tz_mode)
        resolved_lang = self._orm_resolve_lang(lang)
        valid_domain = self._orm_localize_domain(meta, valid_domain, resolved_tz)

        companies = self._orm_resolve_companies(company_ids)
        final_domain = self._orm_company_domain(model, companies) + valid_domain
        scoped = self._orm_scoped(base, companies, resolved_tz, resolved_lang)

        records = scoped.search_read(
            domain=final_domain,
            fields=safe_fields,
            offset=resolved_offset,
            limit=resolved_limit,
            order=valid_order,
        )
        records = self._orm_localize_records(meta, records, safe_fields, resolved_tz)
        total = scoped.search_count(final_domain)
        result = {
            "records": records,
            "returned_count": len(records),
            "count": total,
            "limit": resolved_limit,
            "offset": resolved_offset,
            "truncated": (resolved_offset + len(records)) < total,
        }
        if resolved_tz:
            result["tz"] = resolved_tz
            result["datetime_format"] = ORM_TZ_DATETIME_FORMAT
        return result

    def _orm_read_group(self, model, domain=None, group_by=None, aggregates=None, limit=None, order=None,
                        tz=None, tz_mode=None, lang=None, company_ids=None):
        self._orm_check_model(model)
        base = self._orm_base(model)
        if self._orm_member_rights():
            model_check_access(base, "read")
        meta = base.fields_get()

        self._orm_hr_require_named(model, group_by or aggregates)
        valid_group_by = self._orm_validate_group_by(meta, group_by, model=model)
        agg_specs, agg_names = self._orm_validate_aggregates(meta, aggregates)
        valid_domain = self._orm_validate_domain(meta, domain, model=model)
        resolved_limit = self._orm_resolve_limit(limit)
        valid_order = self._orm_validate_group_order(order, valid_group_by, agg_names)
        self._orm_check_walls(model, valid_domain, self._orm_touched(
            (), valid_domain, valid_order, valid_group_by, agg_names))
        resolved_tz = self._orm_resolve_tz(tz, tz_mode)
        resolved_lang = self._orm_resolve_lang(lang)
        valid_domain = self._orm_localize_domain(meta, valid_domain, resolved_tz)

        companies = self._orm_resolve_companies(company_ids)
        final_domain = self._orm_company_domain(model, companies) + valid_domain
        scoped = self._orm_scoped(base, companies, resolved_tz, resolved_lang)

        raw_groups = self._orm_run_read_group(
            scoped,
            final_domain,
            valid_group_by,
            agg_specs,
            limit=resolved_limit,
            order=valid_order,
        )

        groups = []
        for raw in raw_groups:
            clean = {gb: raw.get(gb) for gb in valid_group_by}
            for name in agg_names:
                clean[name] = raw.get(name)
            clean["count"] = raw.get("__count")
            if resolved_tz:
                clean["ranges"] = self._orm_group_ranges(meta, raw, valid_group_by, resolved_tz)
            groups.append(clean)

        result = {
            "groups": groups,
            "group_by": valid_group_by,
            "aggregates": agg_specs,
            "returned_count": len(groups),
            "limit": resolved_limit,
        }
        if resolved_tz:
            result["tz"] = resolved_tz
        return result