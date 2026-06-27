from odoo import models

# Access mode reported on every ORM response (MVP policy: sudo + company scope).
ORM_ACCESS_MODE = "sudo_company_scoped"

# MVP model allowlist. Sensitive models (res.users, ir.config_parameter, mail.*,
# ir.attachment, ...) are intentionally excluded.
ORM_MODEL_ALLOWLIST = frozenset({
    "res.partner",
    "sale.order",
    "account.move",
    "account.move.line",
    "product.template",
    "product.product",
})

# A field is forbidden if its lowercased name CONTAINS any of these substrings.
ORM_FORBIDDEN_FIELD_SUBSTRINGS = (
    "password", "passwd", "token", "api_key", "secret", "oauth",
    "reset", "signup", "private_key", "access_token", "refresh_token",
)

# "auth" is treated as a credential hint (see _orm_is_forbidden_field) EXCEPT
# when it appears only inside these benign English word stems -- so genuinely
# useful fields such as author_id / authorized_transaction_ids / authority_id
# are NOT blocked, while auth / auth_token / reauth_* still are. (oauth and the
# *_token / *secret patterns above already cover the common auth secrets.)
ORM_AUTH_SAFE_WORD_STEMS = ("author", "authoriz", "authentic", "authority")

# Domain leaf operators allowed for the MVP. Anything else is rejected.
ORM_ALLOWED_DOMAIN_OPERATORS = frozenset({
    "=", "!=", "in", "not in", ">", "<", ">=", "<=", "ilike", "like",
})

# Field types that may be returned / filtered. Excludes binary, one2many,
# many2many (kept out of the MVP to bound payloads and avoid heavy/relational data).
ORM_RETURNABLE_FIELD_TYPES = frozenset({
    "char", "text", "html", "integer", "float", "monetary", "boolean",
    "date", "datetime", "selection", "many2one",
})

ORM_GROUPABLE_FIELD_TYPES = frozenset({
    "many2one", "selection", "boolean", "date", "datetime", "char", "integer",
})

ORM_NUMERIC_FIELD_TYPES = frozenset({"integer", "float", "monetary"})

# Aggregate functions allowed. Per-group row count is ALWAYS returned as "count"
# (read_group __count), so an explicit count aggregate is unnecessary.
ORM_ALLOWED_AGG_FUNCS = frozenset({"sum", "avg", "max", "min"})

ORM_DEFAULT_LIMIT = 80
ORM_MAX_LIMIT = 200
ORM_MAX_DOMAIN_CLAUSES = 25
ORM_MAX_DOMAIN_IN_VALUES = 200
ORM_MAX_GROUP_BY = 2
ORM_MAX_AGGREGATES = 5


class StydOrmError(Exception):
    """Validation/authorization error for the ORM bridge.

    Carries a stable machine `code` (one of the documented error codes) and a
    safe human `message`. Never contains tokens or raw field values.
    """

    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__("%s: %s" % (code, message))


def _short(value):
    """Bound a user-supplied identifier before putting it in an error message."""
    return str(value)[:64]


class StydOdooBridgeOrm(models.AbstractModel):
    """Read-only ORM primitives for the Speak To Your Database bridge (MVP).

    Only ever calls SAFE ORM methods: fields_get, search_read, search_count,
    read_group. Never write/create/unlink/copy/call_kw. Enforces a model
    allowlist, a forbidden-field blocklist, a domain validator, limit caps, and
    company scope. Runs as sudo() (MVP analytics parity with direct-DB mode) and
    reports access_mode = "sudo_company_scoped".
    """

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

    # ------------------------------------------------------------------
    # Allowlist / model resolution
    # ------------------------------------------------------------------
    def _orm_check_model(self, model_name):
        if not model_name or model_name not in self.MODEL_ALLOWLIST:
            raise StydOrmError("model_not_allowed", "Model is not allowed by this bridge.")
        if model_name not in self.env:
            raise StydOrmError("model_not_allowed", "Model is not available on this Odoo instance.")

    def _orm_is_forbidden_field(self, name):
        low = (name or "").lower()
        if any(bad in low for bad in self.FORBIDDEN_FIELD_SUBSTRINGS):
            return True
        # Treat a remaining "auth" as a credential hint, but ignore benign word
        # stems (author / authorized / authentic / authority) so useful fields
        # are not over-blocked.
        if "auth" in low:
            residue = low
            for stem in self.AUTH_SAFE_WORD_STEMS:
                residue = residue.replace(stem, "")
            if "auth" in residue:
                return True
        return False

    # ------------------------------------------------------------------
    # Company scope (enforced via domain because sudo() bypasses record rules)
    # ------------------------------------------------------------------
    def _orm_scope_companies(self):
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
        if "company_id" in model._fields:
            return ["|", ("company_id", "=", False), ("company_id", "in", companies.ids)]
        return []

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    def _orm_validate_fields(self, meta, fields):
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
            if meta[fname].get("type") not in self.RETURNABLE_FIELD_TYPES:
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

    def _orm_validate_domain(self, meta, domain):
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
            if meta[field].get("type") not in self.RETURNABLE_FIELD_TYPES:
                raise StydOrmError("field_not_allowed", "Domain field type not allowed: %s." % _short(field))
            if operator not in self.ALLOWED_DOMAIN_OPERATORS:
                raise StydOrmError("operator_not_allowed", "Operator not allowed: %s." % _short(operator))
            self._orm_validate_domain_value(operator, value)
            normalized.append((field, operator, value))
        self._orm_check_domain_balanced(normalized)
        return normalized

    def _orm_check_domain_balanced(self, normalized):
        """Reject structurally malformed (unbalanced) prefix-notation domains
        with domain_invalid, instead of letting them reach the ORM as a 500.

        Mirrors Odoo's expression.normalize_domain accounting: '&'/'|' are
        binary, '!' is unary, and consecutive complete terms are implicitly
        AND-ed. A well-formed domain ends with `expected == 0`.
        """
        if not normalized:
            return
        arity = {"&": 2, "|": 2, "!": 1}
        expected = 1
        for token in normalized:
            if expected == 0:
                # implicit AND between two complete expressions
                expected = 1
            if isinstance(token, str):
                expected += arity.get(token, 0) - 1
            else:
                expected -= 1
        if expected != 0:
            raise StydOrmError(
                "domain_invalid",
                "Domain is structurally invalid (unbalanced operators).",
            )

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
        # Clamp to a non-negative integer (lenient; never negative).
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            return 0
        return offset

    def _orm_validate_group_by(self, meta, group_by):
        if not group_by:
            # Phase 5H-D — an empty group_by is a VALID global aggregation: one
            # group over the whole company-scoped, domain-filtered set (e.g.
            # "total unpaid amount"). The aggregate fields are still validated
            # (stored numeric/monetary, not credential) by _orm_validate_aggregates,
            # and the domain / model allowlist / company scope are unchanged. This
            # is read-only and exposes only an aggregate number, no new records.
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
            if not (meta[gb].get("store") and meta[gb].get("type") in self.GROUPABLE_FIELD_TYPES):
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
    # Public read-only ORM primitives
    # ------------------------------------------------------------------
    def orm_list_models(self):
        out = []
        for model_name in sorted(self.MODEL_ALLOWLIST):
            if model_name not in self.env:
                continue
            model = self.env[model_name].sudo()
            out.append({
                "model": model_name,
                "name": model_name,
                "label": model._description or model_name,
                "transient": bool(model._transient),
                "allowed": True,
            })
        return out

    def orm_model_fields(self, model_name):
        self._orm_check_model(model_name)
        model = self.env[model_name].sudo()
        meta = model.fields_get()
        out = []
        for fname in sorted(meta):
            if self._orm_is_forbidden_field(fname):
                continue
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

    def orm_search_read(self, model, domain=None, fields=None, limit=None, offset=None, order=None):
        self._orm_check_model(model)
        base = self.env[model].sudo()
        meta = base.fields_get()

        safe_fields = self._orm_validate_fields(meta, fields)
        valid_domain = self._orm_validate_domain(meta, domain)
        valid_order = self._orm_validate_order(meta, order)
        resolved_limit = self._orm_resolve_limit(limit)
        resolved_offset = self._orm_resolve_offset(offset)

        companies = self._orm_scope_companies()
        # Concatenating two balanced domains implicitly ANDs them in Odoo.
        final_domain = self._orm_company_domain(model, companies) + valid_domain
        scoped = base.with_context(allowed_company_ids=companies.ids)

        records = scoped.search_read(
            domain=final_domain,
            fields=safe_fields,
            offset=resolved_offset,
            limit=resolved_limit,
            order=valid_order,
        )
        total = scoped.search_count(final_domain)
        return {
            "records": records,
            "returned_count": len(records),
            "count": total,
            "limit": resolved_limit,
            "offset": resolved_offset,
            "truncated": (resolved_offset + len(records)) < total,
        }

    def orm_read_group(self, model, domain=None, group_by=None, aggregates=None, limit=None, order=None):
        self._orm_check_model(model)
        base = self.env[model].sudo()
        meta = base.fields_get()

        valid_group_by = self._orm_validate_group_by(meta, group_by)
        agg_specs, agg_names = self._orm_validate_aggregates(meta, aggregates)
        valid_domain = self._orm_validate_domain(meta, domain)
        resolved_limit = self._orm_resolve_limit(limit)
        valid_order = self._orm_validate_group_order(order, valid_group_by, agg_names)

        companies = self._orm_scope_companies()
        final_domain = self._orm_company_domain(model, companies) + valid_domain
        scoped = base.with_context(allowed_company_ids=companies.ids)

        raw_groups = scoped.read_group(
            domain=final_domain,
            fields=agg_specs,
            groupby=valid_group_by,
            lazy=False,
            limit=resolved_limit,
            orderby=valid_order,
        )

        groups = []
        for raw in raw_groups:
            clean = {gb: raw.get(gb) for gb in valid_group_by}
            for name in agg_names:
                clean[name] = raw.get(name)
            clean["count"] = raw.get("__count")
            groups.append(clean)

        return {
            "groups": groups,
            "group_by": valid_group_by,
            "aggregates": agg_specs,
            "returned_count": len(groups),
            "limit": resolved_limit,
        }
