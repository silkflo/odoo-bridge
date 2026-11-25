import hmac
import json
import logging

from odoo import http
from odoo.http import request

# Read-only ORM primitives ported from 17.0 so the STYD Data Guide can load
# Odoo models on Odoo 16. The allowlist / field-filter / read-only guarantees
# live in bridge_orm.py and are identical to 17.0.
from odoo.addons.styd_odoo_bridge.models.bridge_orm import (
    ORM_ACCESS_MODE,
    ORM_INTERNAL_CTX_KEYS,
    StydOrmError,
    _json_default,
)

_logger = logging.getLogger(__name__)


class StydBridgeApi(http.Controller):
    def _json_response(self, payload, status=200):
        return request.make_response(
            json.dumps(payload, default=_json_default),
            headers=[
                ("Content-Type", "application/json"),
            ],
            status=status,
        )

    def _error_response(self, error, detail=None, status=400):
        payload = {
            "ok": False,
            "error": error,
        }
        if detail:
            payload["detail"] = detail
        return self._json_response(payload, status=status)

    def _extract_bearer_token(self):
        auth_header = request.httprequest.headers.get("Authorization")
        if not auth_header:
            return None

        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:].strip()
        return token or None

    def _check_bridge_access(self):
        icp = request.env["ir.config_parameter"].sudo()

        service = request.env["styd.odoo.bridge.service"]

        enabled = icp.get_param("styd_odoo_bridge.enabled", default="False")
        expected_hash = icp.get_param("styd_odoo_bridge.token_hash", default="") or ""
        legacy_token = icp.get_param("styd_odoo_bridge.token", default="") or ""

        if str(enabled).lower() not in ("1", "true", "yes", "on"):
            return {
                "ok": False,
                "response": self._error_response(
                    "bridge_disabled",
                    "Speak To Your Database bridge is disabled in Odoo settings.",
                    status=403,
                ),
            }

        provided_token = self._extract_bearer_token()

        if not expected_hash and not legacy_token:
            return {
                "ok": False,
                "response": self._error_response(
                    "bridge_token_missing",
                    "Bridge token is not configured in Odoo settings.",
                    status=500,
                ),
            }

        # Constant-time comparison to avoid leaking the token via timing.
        # Prefer the hashed token (hash-at-rest); fall back to a legacy
        # plaintext token for backward compatibility until it is migrated.
        token_ok = False
        if provided_token:
            if expected_hash:
                token_ok = hmac.compare_digest(
                    service._hash_token(provided_token).encode("utf-8"),
                    expected_hash.encode("utf-8"),
                )
            elif legacy_token:
                token_ok = hmac.compare_digest(
                    provided_token.encode("utf-8"),
                    legacy_token.encode("utf-8"),
                )

        if not token_ok:
            return {
                "ok": False,
                "response": self._error_response(
                    "unauthorized",
                    "Missing or invalid bearer token.",
                    status=401,
                ),
            }

        return {"ok": True}

    def _clean_model(self, name):
        """``name`` with sudo, and without the module's internal context keys
        (member rights, the connector owner): a request never sets them."""
        model = request.env[name].sudo()
        return model.with_context({k: v for k, v in model.env.context.items() if k not in ORM_INTERNAL_CTX_KEYS})

    def _get_service(self):
        return self._clean_model("styd.odoo.bridge.service")

    def _build_user_search_payload(self, service, query):
        return service._build_user_search_payload(query)

    @http.route(
        "/styd_bridge/v1/health",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_health(self, **kwargs):
        access = self._check_bridge_access()
        if not access["ok"]:
            return access["response"]

        service = self._get_service()
        payload = service._build_health_payload()

        return self._json_response(payload, status=200)

    @http.route(
        "/styd_bridge/v1/security/snapshot",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_security_snapshot(self, **kwargs):
        access = self._check_bridge_access()
        if not access["ok"]:
            return access["response"]

        service = self._get_service()

        try:
            payload = service._build_security_snapshot_payload()
            return self._json_response(payload, status=200)
        except Exception as exc:
            return self._error_response(
                "snapshot_build_failed",
                str(exc),
                status=500,
            )

    @http.route(
        "/styd_bridge/v1/users/directory",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_users_directory(self, **kwargs):
        access = self._check_bridge_access()
        if not access["ok"]:
            return access["response"]

        service = self._get_service()

        try:
            payload = service._build_user_directory_snapshot_payload()
            return self._json_response(payload, status=200)
        except Exception as exc:
            return self._error_response(
                "user_directory_build_failed",
                str(exc),
                status=500,
            )

    @http.route(
        "/styd_bridge/v1/users/search",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_users_search(self, **kwargs):
        access = self._check_bridge_access()
        if not access["ok"]:
            return access["response"]

        service = self._get_service()
        query = kwargs.get("q")

        try:
            payload = self._build_user_search_payload(service, query)
            return self._json_response(payload, status=200)
        except Exception as exc:
            return self._error_response(
                "user_search_failed",
                str(exc),
                status=500,
            )

    @http.route(
        "/styd_bridge/v1/capabilities",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_capabilities(self, **kwargs):
        access = self._check_bridge_access()
        if not access["ok"]:
            return access["response"]

        service = self._get_service()

        try:
            payload = service._build_capability_snapshot_payload()
            return self._json_response(payload, status=200)
        except Exception as exc:
            return self._error_response(
                "capability_snapshot_build_failed",
                str(exc),
                status=500,
            )

    # ------------------------------------------------------------------
    # Read-only ORM endpoints (ported from 17.0 for STYD Data Guide support)
    #
    # Same routes, response shapes, allowlist, field-filtering and read-only
    # behavior as 17.0. Adapted only to 16.0's existing access control
    # (bridge token via _check_bridge_access) — 16.0 has no audit-log model,
    # so these endpoints do not write audit rows, exactly like the existing
    # health/security/users/capabilities endpoints above.
    # ------------------------------------------------------------------
    def _get_orm(self):
        return self._clean_model("styd.odoo.bridge.orm")

    def _parse_json_body(self):
        """Parse the request body as a JSON object. Returns {} for an empty
        body and None for invalid JSON (the caller maps None -> invalid_json)."""
        try:
            raw = request.httprequest.get_data(as_text=True)
        except Exception:
            return None
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

    @http.route(
        "/styd_bridge/v1/models",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_models(self, **kwargs):
        access = self._check_bridge_access()
        if not access["ok"]:
            return access["response"]

        orm = self._get_orm()
        try:
            models = orm._orm_list_models()
        except Exception as exc:
            _logger.warning(
                "STYD bridge: /models failed (error_type=%s)", type(exc).__name__
            )
            return self._error_response("orm_error", "Failed to list models.", status=500)

        return self._json_response(
            {"ok": True, "access_mode": ORM_ACCESS_MODE, "models": models},
            status=200,
        )

    @http.route(
        "/styd_bridge/v1/models/<model>/fields",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_model_fields(self, model, **kwargs):
        access = self._check_bridge_access()
        if not access["ok"]:
            return access["response"]

        orm = self._get_orm()
        try:
            fields = orm._orm_model_fields(model)
        except StydOrmError as exc:
            return self._error_response(exc.code, exc.message, status=400)
        except Exception as exc:
            _logger.warning(
                "STYD bridge: fields failed (error_type=%s)", type(exc).__name__
            )
            return self._error_response("orm_error", "Failed to read fields.", status=500)

        return self._json_response(
            {"ok": True, "access_mode": ORM_ACCESS_MODE, "model": model, "fields": fields},
            status=200,
        )

    @http.route(
        "/styd_bridge/v1/search-read",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def bridge_search_read(self, **kwargs):
        access = self._check_bridge_access()
        if not access["ok"]:
            return access["response"]

        body = self._parse_json_body()
        if body is None:
            return self._error_response(
                "invalid_json", "Request body must be a valid JSON object.", status=400
            )

        model = body.get("model")
        orm = self._get_orm()
        try:
            result = orm._orm_search_read(
                model=model,
                domain=body.get("domain"),
                fields=body.get("fields"),
                limit=body.get("limit"),
                offset=body.get("offset"),
                order=body.get("order"),
                tz=body.get("tz"),
                tz_mode=body.get("tz_mode"),
                lang=body.get("lang"),
                company_ids=body.get("company_ids"),
            )
        except StydOrmError as exc:
            return self._error_response(exc.code, exc.message, status=400)
        except Exception as exc:
            _logger.warning(
                "STYD bridge: search-read failed (error_type=%s)", type(exc).__name__
            )
            return self._error_response("orm_error", "Query failed.", status=500)

        payload = {"ok": True, "access_mode": ORM_ACCESS_MODE, "model": model}
        payload.update(result)
        return self._json_response(payload, status=200)

    @http.route(
        "/styd_bridge/v1/read-group",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def bridge_read_group(self, **kwargs):
        access = self._check_bridge_access()
        if not access["ok"]:
            return access["response"]

        body = self._parse_json_body()
        if body is None:
            return self._error_response(
                "invalid_json", "Request body must be a valid JSON object.", status=400
            )

        model = body.get("model")
        orm = self._get_orm()
        try:
            result = orm._orm_read_group(
                model=model,
                domain=body.get("domain"),
                group_by=body.get("group_by"),
                aggregates=body.get("aggregates"),
                limit=body.get("limit"),
                order=body.get("order"),
                tz=body.get("tz"),
                tz_mode=body.get("tz_mode"),
                lang=body.get("lang"),
                company_ids=body.get("company_ids"),
            )
        except StydOrmError as exc:
            return self._error_response(exc.code, exc.message, status=400)
        except Exception as exc:
            _logger.warning(
                "STYD bridge: read-group failed (error_type=%s)", type(exc).__name__
            )
            return self._error_response("orm_error", "Query failed.", status=500)

        payload = {"ok": True, "access_mode": ORM_ACCESS_MODE, "model": model}
        payload.update(result)
        return self._json_response(payload, status=200)