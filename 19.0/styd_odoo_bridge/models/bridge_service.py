import hashlib
from datetime import datetime, timezone

from odoo import models, release


class StydOdooBridgeService(models.AbstractModel):
    _name = "styd.odoo.bridge.service"
    _description = "Speak To Your Database Bridge Service"

    BRIDGE_VERSION = "0.2.0"

    SNAPSHOT_MODELS = [
        "account.move",
        "account.payment",
        "sale.order",
        "purchase.order",
        "stock.picking",
        "stock.move",
        "res.partner",
        "product.product",
        "product.template",
    ]

    CAPABILITY_MODELS = [
        "res.partner",
        "product.product",
        "product.template",
        "sale.order",
        "purchase.order",
        "stock.picking",
        "stock.move",
        "account.move",
        "account.payment",
    ]

    NOISY_FIELD_NAMES = {
        "id",
        "display_name",
        "__last_update",
        "create_uid",
        "create_date",
        "write_uid",
        "write_date",
        "message_ids",
        "message_follower_ids",
        "message_partner_ids",
        "activity_ids",
        "activity_state",
        "activity_user_id",
        "activity_type_id",
        "activity_type_icon",
        "activity_date_deadline",
        "activity_summary",
        "message_needaction",
        "message_needaction_counter",
        "message_has_error",
        "message_has_error_counter",
        "message_attachment_count",
        "website_message_ids",
        "message_has_sms_error",
        "avatar_1920",
        "avatar_1024",
        "avatar_512",
        "avatar_256",
        "avatar_128",
        "image_1920",
        "image_1024",
        "image_512",
        "image_256",
        "image_128",
    }

    NOISY_FIELD_PREFIXES = (
        "message_",
        "activity_",
        "avatar_",
        "image_",
    )

    NOISY_FIELD_SUFFIXES = (
        "_count",
        "_ids",
    )

    ALLOWED_FIELD_TYPES = {
        "char",
        "text",
        "html",
        "integer",
        "float",
        "monetary",
        "boolean",
        "date",
        "datetime",
        "selection",
        "many2one",
    }

    MAX_SELECTION_VALUES = 50

    USER_DIRECTORY_LIMIT = 100
    INSTALLED_MODULE_LIMIT = 200
    AVAILABLE_MODEL_LIMIT = 300

    IMPORTANT_BUSINESS_MODULES = {
        "account",
        "account_payment",
        "contacts",
        "crm",
        "maintenance",
        "product",
        "project",
        "purchase",
        "purchase_stock",
        "sale",
        "sale_management",
        "sale_stock",
        "stock",
    }

    NOISY_FIELD_STARTSWITH = (
        "property_",
        "same_",
        "quick_",
        "can_",
        "has_",
    )

    NOISY_FIELD_CONTAINS = (
        "token",
        "hash",
        "sequence",
    )

    BUSINESS_COMPUTED_FIELD_ALLOWLIST = {
        ("res.partner", "company_type"),

        ("product.product", "type"),
        ("product.product", "tracking"),
        ("product.product", "purchase_method"),
        ("product.product", "cost_method"),
        ("product.product", "valuation"),
        ("product.product", "service_type"),
        ("product.product", "expense_policy"),
        ("product.product", "invoice_policy"),

        ("product.template", "service_tracking"),
        ("product.template", "tracking"),
        ("product.template", "purchase_method"),
        ("product.template", "cost_method"),
        ("product.template", "valuation"),
        ("product.template", "service_type"),
        ("product.template", "expense_policy"),
        ("product.template", "invoice_policy"),

        ("sale.order", "amount_untaxed"),
        ("sale.order", "amount_tax"),
        ("sale.order", "amount_total"),
        ("sale.order", "invoice_status"),
        ("sale.order", "delivery_status"),

        ("purchase.order", "amount_untaxed"),
        ("purchase.order", "amount_tax"),
        ("purchase.order", "amount_total"),
        ("purchase.order", "invoice_status"),
        ("purchase.order", "receipt_status"),

        ("stock.picking", "move_type"),
        ("stock.picking", "state"),
        ("stock.picking", "scheduled_date"),
        ("stock.picking", "date_done"),

        ("stock.move", "state"),
        ("stock.move", "quantity"),

        ("account.move", "amount_untaxed"),
        ("account.move", "amount_tax"),
        ("account.move", "amount_total"),
        ("account.move", "amount_residual"),
        ("account.move", "payment_state"),

        ("account.payment", "state"),
    }

    EXCLUDED_FIELD_NAMES = {
        "properties_base_definition_id",
        "main_user_id",
        "signup_type",
        "calendar_last_notif_ack",
        "pending_email_template_id",
        "invoice_pdf_report_id",
        "ubl_cii_xml_id",
        "status_in_payment",
        "move_sent_values",
        "invoice_edi_format_store",
        "invoice_source_email",
        "bank_partner_id",
        "journal_group_id",
        "purchase_vendor_bill_id",
        "invoice_vendor_bill_id",
        "statement_id",
        "statement_line_id",
        "tax_cash_basis_rec_id",
        "tax_cash_basis_origin_move_id",
        "payment_transaction_id",
        "source_payment_id",
        "paired_internal_transfer_payment_id",
        "warehouse_address_id",
        "products_availability_state",
        "search_date_category",
        "partner_country_id",
        "purchase_id",
        "sale_id",
        "product_category_id",
        "account_move_id",
        "purchase_line_id",
        "sale_line_id",
        "project_account_id",
        "lang",
        "tz",
    }

    CORE_CAPABILITY_MODULES = {
        "account",
        "account_payment",
        "contacts",
        "crm",
        "maintenance",
        "product",
        "project",
        "purchase",
        "purchase_stock",
        "sale",
        "sale_management",
        "sale_stock",
        "stock",
    }

    ALLOWED_MANY2ONE_RELATIONS = {
        "res.partner",
        "res.users",
        "res.company",
        "res.currency",
        "res.country",
        "res.country.state",
        "product.product",
        "product.template",
        "product.category",
        "product.pricelist",
        "sale.order",
        "purchase.order",
        "stock.picking",
        "stock.move",
        "stock.location",
        "stock.warehouse",
        "stock.picking.type",
        "account.move",
        "account.payment",
        "account.journal",
        "account.payment.term",
        "account.fiscal.position",
        "account.incoterms",
        "account.account",
        "account.payment.method.line",
        "res.partner.bank",
        "crm.team",
        "crm.lead",
        "project.project",
        "project.task",
        "uom.uom",
    }

    def _utc_now_iso(self):
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _get_icp(self):
        return self.env["ir.config_parameter"].sudo()

    def _get_bridge_enabled(self):
        raw = self._get_icp().get_param("styd_odoo_bridge.enabled", default="False")
        return str(raw).lower() in ("1", "true", "yes", "on")

    def _get_bridge_token(self):
        return self._get_icp().get_param("styd_odoo_bridge.token", default="") or ""

    def _get_bridge_token_hash(self):
        return self._get_icp().get_param("styd_odoo_bridge.token_hash", default="") or ""

    def _hash_token(self, token):
        """Return the hex SHA-256 of a bearer token (hash-at-rest).

        The token is high-entropy random, so a single SHA-256 is sufficient and
        is what the controller compares (constant-time) against the stored hash.
        Never logs or returns the raw token.
        """
        if not token:
            return ""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _token_is_configured(self):
        """True if a hashed token OR a legacy plaintext token is configured."""
        return bool(self._get_bridge_token_hash()) or bool(self._get_bridge_token())

    def _has_legacy_plaintext_token(self):
        """True if a legacy plaintext token is still stored (rotation advised)."""
        return bool(self._get_bridge_token())

    def _get_connector_owner_user_id(self):
        raw = self._get_icp().get_param("styd_odoo_bridge.connector_owner_user_id", default="")
        if not raw:
            return None
        try:
            return int(raw)
        except Exception:
            return None

    def _get_connector_owner(self):
        user_id = self._get_connector_owner_user_id()
        if not user_id:
            raise ValueError(
                "Bridge connector owner is not configured. "
                "Please set styd_odoo_bridge.connector_owner_user_id in Odoo settings."
            )

        user = self.env["res.users"].sudo().browse(user_id)
        if not user.exists():
            raise ValueError(
                "Configured bridge connector owner user does not exist."
            )

        return user

    def _get_base_url(self):
        return self._get_icp().get_param("web.base.url", default="") or None

    def _get_database_uuid(self):
        return self._get_icp().get_param("database.uuid", default="") or None

    def _get_odoo_version(self):
        return getattr(release, "version", None)

    def _get_odoo_series(self):
        version = self._get_odoo_version()
        if not version:
            return None

        parts = str(version).split(".")
        if not parts:
            return None

        try:
            major = int(parts[0])
            return f"{major}.0"
        except Exception:
            return str(version)

    def _get_edition(self):
        module_count = self.env["ir.module.module"].sudo().search_count([
            ("name", "=", "web_enterprise"),
            ("state", "=", "installed"),
        ])
        return "enterprise" if module_count else "community"

    def get_supported_features(self):
        return [
            "security_snapshot_v1",
            "odoo_user_directory_v1",
            "odoo_capability_snapshot_v1",
        ]

    def _get_group_xmlid_map(self, groups):
        xmlid_map = {}
        if not groups:
            return xmlid_map

        rows = self.env["ir.model.data"].sudo().search_read(
            [
                ("model", "=", "res.groups"),
                ("res_id", "in", groups.ids),
            ],
            ["module", "name", "res_id"],
        )

        for row in rows:
            module = row.get("module")
            name = row.get("name")
            res_id = row.get("res_id")
            if module and name and res_id:
                xmlid_map[res_id] = f"{module}.{name}"

        return xmlid_map

    def _build_group_payload(self, user):
        sudo_user = user.sudo()

        try:
            if "groups_id" not in sudo_user._fields:
                return []

            groups = sudo_user.groups_id.sorted(
                key=lambda g: (
                    (g.category_id.name if g.category_id else "") or "",
                    g.name or "",
                )
            )
        except Exception:
            return []

        xmlid_map = self._get_group_xmlid_map(groups)

        payload = []
        for group in groups:
            payload.append({
                "id": group.id,
                "xml_id": xmlid_map.get(group.id),
                "name": group.name,
            })
        return payload

    def _user_has_any_group(self, user, xml_ids):
        for xml_id in xml_ids:
            try:
                if user.with_user(user).has_group(xml_id):
                    return True
            except Exception:
                try:
                    group = self.env.ref(xml_id, raise_if_not_found=False)
                    if group and group in user.sudo().groups_id:
                        return True
                except Exception:
                    continue
        return False

    def _build_company_scope_payload(self, user):
        companies = user.sudo().company_ids.sorted(key=lambda c: c.id)

        default_company = user.sudo().company_id
        active_company = default_company

        return {
            "allowed_company_ids": companies.ids,
            "default_company_id": default_company.id if default_company else None,
            "active_company_id": active_company.id if active_company else None,
            "companies": [
                {
                    "id": company.id,
                    "name": company.name,
                }
                for company in companies
            ],
        }

    def _check_model_access(self, user, model_name):
        model = self.env[model_name].with_user(user)

        return {
            "model": model_name,
            "read": bool(model.check_access_rights("read", raise_exception=False)),
            "write": bool(model.check_access_rights("write", raise_exception=False)),
            "create": bool(model.check_access_rights("create", raise_exception=False)),
            "unlink": bool(model.check_access_rights("unlink", raise_exception=False)),
        }

    def _build_model_access_payload(self, user):
        payload = []
        for model_name in self.SNAPSHOT_MODELS:
            try:
                payload.append(self._check_model_access(user, model_name))
            except Exception:
                payload.append({
                    "model": model_name,
                    "read": False,
                    "write": False,
                    "create": False,
                    "unlink": False,
                })
        return payload

    def _has_any_read_access(self, model_access, model_names):
        wanted = set(model_names)
        for row in model_access:
            if row.get("model") in wanted and row.get("read"):
                return True
        return False

    def _build_security_flags(self, company_scope, model_access):
        return {
            "has_multi_company": len(company_scope.get("allowed_company_ids", [])) > 1,
            "has_accounting_access": self._has_any_read_access(
                model_access,
                ["account.move", "account.payment"],
            ),
            "has_sales_access": self._has_any_read_access(
                model_access,
                ["sale.order"],
            ),
            "has_inventory_access": self._has_any_read_access(
                model_access,
                ["stock.picking", "stock.move"],
            ),
        }

    def _build_connector_owner_payload(self, user):
        partner = user.sudo().partner_id
        email = user.sudo().email or (partner.email if partner else None)

        return {
            "odoo_user_id": user.id,
            "login": user.sudo().login or None,
            "name": user.sudo().name or None,
            "email": email or None,
            "is_active": bool(user.sudo().active),
        }

    def _model_exists(self, model_name):
        try:
            return model_name in self.env
        except Exception:
            return False

    def _safe_fields_get(self, model_name):
        if not self._model_exists(model_name):
            return {}

        try:
            return self.env[model_name].sudo().fields_get()
        except Exception:
            return {}

    def _build_installed_modules_payload(self):
        modules = self.env["ir.module.module"].sudo().search(
            [
                ("state", "=", "installed"),
                ("name", "in", list(self.CORE_CAPABILITY_MODULES)),
            ],
            order="name asc",
        )

        payload = []
        for module in modules:
            payload.append({
                "name": module.name,
                "display_name": module.shortdesc or module.name,
                "latest_version": module.latest_version or None,
                "application": bool(module.application),
            })

        return payload

    def _is_allowed_capability_model(self, model_name):
        return model_name in self.CAPABILITY_MODELS and self._model_exists(model_name)

    def _is_useful_field(self, model_name, field_name, info, field_obj):
        if not field_name:
            return False

        if field_name in self.NOISY_FIELD_NAMES:
            return False

        if field_name in self.EXCLUDED_FIELD_NAMES:
            return False

        for prefix in self.NOISY_FIELD_PREFIXES:
            if field_name.startswith(prefix):
                return False

        for prefix in self.NOISY_FIELD_STARTSWITH:
            if field_name.startswith(prefix):
                return False

        for token in self.NOISY_FIELD_CONTAINS:
            if token in field_name:
                return False

        for suffix in self.NOISY_FIELD_SUFFIXES:
            if field_name.endswith(suffix) and info.get("type") in ("one2many", "many2many"):
                return False

        field_type = info.get("type")
        if field_type not in self.ALLOWED_FIELD_TYPES:
            return False

        relation = info.get("relation") or None
        is_stored = bool(getattr(field_obj, "store", False))
        is_computed = bool(getattr(field_obj, "compute", False))
        is_company_dependent = bool(getattr(field_obj, "company_dependent", False))
        is_readonly = bool(info.get("readonly"))

        if is_company_dependent:
            return True

        if field_type == "many2one":
            if relation and relation not in self.ALLOWED_MANY2ONE_RELATIONS:
                return False

            if not is_stored and not is_company_dependent and not is_computed:
                return False

            if is_computed and (model_name, field_name) not in self.BUSINESS_COMPUTED_FIELD_ALLOWLIST:
                return False

            if field_name.endswith("_id") or field_name in (
                "partner_id",
                "company_id",
                "user_id",
                "team_id",
                "journal_id",
                "currency_id",
                "product_id",
                "product_tmpl_id",
                "categ_id",
                "location_id",
                "location_dest_id",
                "warehouse_id",
                "project_id",
            ):
                return True

            return False

        if field_type == "selection":
            if is_computed and (model_name, field_name) not in self.BUSINESS_COMPUTED_FIELD_ALLOWLIST:
                return False
            return True

        if is_computed:
            return (model_name, field_name) in self.BUSINESS_COMPUTED_FIELD_ALLOWLIST

        if is_readonly and not is_stored:
            return False

        return is_stored

    def _is_useful_selection_field(self, field_name, values):
        if not values:
            return False

        if len(values) > self.MAX_SELECTION_VALUES:
            return False

        lowered = str(field_name or "").lower()
        if lowered in (
            "tz",
            "lang",
            "peppol_eas",
            "service_policy",
            "status_in_payment",
            "default_location_dest_id_usage",
            "search_date_category",
        ):
            return False

        return True



    def _build_available_models_payload(self):
        payload = []

        records = self.env["ir.model"].sudo().search(
            [("model", "in", self.CAPABILITY_MODELS)],
            order="model asc",
        )

        by_model = {rec.model: rec for rec in records}

        for model_name in self.CAPABILITY_MODELS:
            if not self._is_allowed_capability_model(model_name):
                continue

            rec = by_model.get(model_name)
            payload.append({
                "model": model_name,
                "display_name": (rec.name if rec else model_name) or model_name,
                "table_name": model_name.replace(".", "_"),
                "state": getattr(rec, "state", None) if rec else None,
                "is_transient": False,
            })

        return payload

    def _normalize_selection_values(self, selection):
        values = []
        if not selection:
            return values

        if callable(selection):
            return values

        try:
            for item in selection:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    values.append({
                        "value": item[0],
                        "label": item[1],
                    })
        except Exception:
            return []

        return values

    def _build_fields_payload(self):
        payload = []

        for model_name in self.CAPABILITY_MODELS:
            if not self._model_exists(model_name):
                continue

            model = self.env[model_name].sudo()
            fields_meta = self._safe_fields_get(model_name)

            for field_name, info in fields_meta.items():
                field_obj = model._fields.get(field_name)
                if not field_obj:
                    continue

                if not self._is_useful_field(model_name, field_name, info, field_obj):
                    continue

                selection_values = self._normalize_selection_values(
                    getattr(field_obj, "selection", None)
                )

                if not self._is_useful_selection_field(field_name, selection_values):
                    selection_values = []

                payload.append({
                    "model": model_name,
                    "field": field_name,
                    "label": info.get("string") or field_name,
                    "type": info.get("type"),
                    "relation": info.get("relation") or None,
                    "required": bool(info.get("required")),
                    "readonly": bool(info.get("readonly")),
                    "stored": bool(getattr(field_obj, "store", False)),
                    "computed": bool(getattr(field_obj, "compute", False)),
                    "company_dependent": bool(getattr(field_obj, "company_dependent", False)),
                    "selection_values": selection_values,
                    "help": info.get("help") or None,
                })

        return payload

    def _build_relations_payload(self, fields_payload):
        payload = []
        seen = set()

        for row in fields_payload:
            relation = row.get("relation")
            if not relation:
                continue

            if relation not in self.ALLOWED_MANY2ONE_RELATIONS:
                continue

            key = (
                row.get("model"),
                row.get("field"),
                relation,
                row.get("type"),
            )
            if key in seen:
                continue
            seen.add(key)

            payload.append({
                "from_model": row.get("model"),
                "field": row.get("field"),
                "to_model": relation,
                "type": row.get("type"),
            })

        return payload

    def _build_selection_values_payload(self, fields_payload):
        payload = []
        for row in fields_payload:
            values = row.get("selection_values") or []
            if values:
                payload.append({
                    "model": row.get("model"),
                    "field": row.get("field"),
                    "values": values,
                })
        return payload    

    def _build_configuration_hints_payload(self):
        return {
            "base_url": self._get_base_url(),
            "database_uuid": self._get_database_uuid(),
            "odoo_version": self._get_odoo_version(),
            "odoo_series": self._get_odoo_series(),
            "edition": self._get_edition(),
            "multi_company_enabled": self.env["res.company"].sudo().search_count([]) > 1,
        }

    def _build_business_capability_snapshot(self, installed_modules):
        installed = {m.get("name") for m in installed_modules}

        return {
            "accounting": "account" in installed or "account_accountant" in installed,
            "sales": "sale" in installed or "sale_management" in installed,
            "purchase": "purchase" in installed,
            "inventory": "stock" in installed,
            "contacts": "contacts" in installed,
        }

    def _build_user_rights_summary(self, user):
        company_scope = self._build_company_scope_payload(user)

        accounting = self._user_has_any_group(user, [
            "account.group_account_invoice",
            "account.group_account_readonly",
            "account.group_account_user",
            "account.group_account_manager",
        ])

        sales = self._user_has_any_group(user, [
            "sales_team.group_sale_salesman",
            "sales_team.group_sale_salesman_all_leads",
            "sales_team.group_sale_manager",
        ])

        inventory = self._user_has_any_group(user, [
            "stock.group_stock_user",
            "stock.group_stock_manager",
        ])

        purchase = self._user_has_any_group(user, [
            "purchase.group_purchase_user",
            "purchase.group_purchase_manager",
        ])

        return {
            "accounting": bool(accounting),
            "sales": bool(sales),
            "purchase": bool(purchase),
            "inventory": bool(inventory),
            "multi_company": len(company_scope.get("allowed_company_ids", [])) > 1,
        }

    def _build_user_directory_payload(self):
        users = self.env["res.users"].sudo().search(
            [("active", "=", True)],
            limit=self.USER_DIRECTORY_LIMIT,
            order="name asc",
        )

        payload = []
        for user in users:
            partner = user.partner_id.sudo() if user.partner_id else None
            email = user.sudo().email or (partner.email if partner else None)
            company_scope = self._build_company_scope_payload(user)
            rights_summary = self._build_user_rights_summary(user)
            groups_payload = self._build_group_payload(user)

            payload.append({
                "odoo_user_id": user.id,
                "login": user.sudo().login or None,
                "name": user.sudo().name or None,
                "email": email or None,
                "is_active": bool(user.sudo().active),
                "allowed_company_ids": company_scope.get("allowed_company_ids", []),
                "default_company_id": company_scope.get("default_company_id"),
                "rights_summary": rights_summary,
                "groups": groups_payload,
            })

        return payload

    def build_health_payload(self):
        return {
            "ok": True,
            "bridge_version": self.BRIDGE_VERSION,
            "odoo_version": self._get_odoo_version(),
            "odoo_series": self._get_odoo_series(),
            "edition": self._get_edition(),
            "database_uuid": self._get_database_uuid(),
            "server_time_utc": self._utc_now_iso(),
            "supported_features": self.get_supported_features(),
        }

    def build_security_snapshot_payload(self):
        user = self._get_connector_owner()

        company_scope = self._build_company_scope_payload(user)
        model_access = self._build_model_access_payload(user)

        payload = {
            "bridge_version": self.BRIDGE_VERSION,
            "snapshot_version": 1,
            "generated_at_utc": self._utc_now_iso(),
            "instance": {
                "base_url": self._get_base_url(),
                "database_uuid": self._get_database_uuid(),
                "odoo_version": self._get_odoo_version(),
                "odoo_series": self._get_odoo_series(),
                "edition": self._get_edition(),
            },
            "connector_owner": self._build_connector_owner_payload(user),
            "company_scope": company_scope,
            "groups": self._build_group_payload(user) or [],
            "model_access": model_access,
            "security_flags": self._build_security_flags(company_scope, model_access),
        }

        return payload

    def build_user_directory_snapshot_payload(self):
        return {
            "bridge_version": self.BRIDGE_VERSION,
            "snapshot_version": 1,
            "generated_at_utc": self._utc_now_iso(),
            "users": self._build_user_directory_payload(),
        }

    def build_capability_snapshot_payload(self):
        installed_modules = self._build_installed_modules_payload()
        available_models = self._build_available_models_payload()
        fields_payload = self._build_fields_payload()
        relations_payload = self._build_relations_payload(fields_payload)
        selection_values_payload = self._build_selection_values_payload(fields_payload)

        return {
            "bridge_version": self.BRIDGE_VERSION,
            "snapshot_version": 1,
            "generated_at_utc": self._utc_now_iso(),
            "instance": {
                "base_url": self._get_base_url(),
                "database_uuid": self._get_database_uuid(),
                "odoo_version": self._get_odoo_version(),
                "odoo_series": self._get_odoo_series(),
                "edition": self._get_edition(),
            },
            "installed_modules": installed_modules,
            "available_models": available_models,
            "fields": fields_payload,
            "relations": relations_payload,
            "selection_values": selection_values_payload,
            "configuration_hints": self._build_configuration_hints_payload(),
            "business_capability_snapshot": self._build_business_capability_snapshot(installed_modules),
        }