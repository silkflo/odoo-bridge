import json
import logging

from werkzeug.wrappers import Response

from odoo import http
from odoo.http import request

# Read-only ORM primitives ported from the validated 16.0 implementation so the
# STYD Data Guide can load Odoo models on Odoo 15. The allowlist / field-filter /
# read-only guarantees live in bridge_orm.py and are identical to 16.0/17.0.
from odoo.addons.styd_odoo_bridge.models.bridge_orm import (
    ORM_ACCESS_MODE,
    StydOrmError,
)

_logger = logging.getLogger(__name__)


class StydBridgeApi(http.Controller):
    def _json_response(self, payload, status=200):
        # Build a werkzeug Response DIRECTLY rather than via request.make_response,
        # so the response does not depend on the request type, and attach the JSON
        # content-type plus no-store / nosniff headers. All bridge routes (GET and the
        # POST ORM routes) are type="http"; the POST routes work on Odoo 15 because
        # STYD sends their body with a text/plain Content-Type so Odoo's legacy
        # framework dispatches them as plain HTTP (see the note on bridge_search_read).
        body = json.dumps(payload, default=str)
        return Response(
            body,
            status=status,
            headers=[
                ("Content-Type", "application/json"),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ],
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

        enabled = icp.get_param("styd_odoo_bridge.enabled", default="False")
        expected_token = icp.get_param("styd_odoo_bridge.token", default="")

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

        if not expected_token:
            return {
                "ok": False,
                "response": self._error_response(
                    "bridge_token_missing",
                    "Bridge token is not configured in Odoo settings.",
                    status=500,
                ),
            }

        if not provided_token or provided_token != expected_token:
            return {
                "ok": False,
                "response": self._error_response(
                    "unauthorized",
                    "Missing or invalid bearer token.",
                    status=401,
                ),
            }

        return {"ok": True}

    def _get_service(self):
        return request.env["styd.odoo.bridge.service"].sudo()

    def _build_user_search_payload(self, service, query):
        directory = service.build_user_directory_snapshot_payload()
        users = directory.get("users", [])

        q = str(query or "").strip().lower()
        if q:
            users = [
                user for user in users
                if q in str(user.get("login") or "").lower()
                or q in str(user.get("name") or "").lower()
                or q in str(user.get("email") or "").lower()
            ]

        return {
            "bridge_version": directory.get("bridge_version"),
            "snapshot_version": directory.get("snapshot_version"),
            "generated_at_utc": directory.get("generated_at_utc"),
            "query": query or "",
            "count": len(users),
            "users": users,
        }

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
        payload = service.build_health_payload()

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
            payload = service.build_security_snapshot_payload()
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
            payload = service.build_user_directory_snapshot_payload()
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
            payload = service.build_capability_snapshot_payload()
            return self._json_response(payload, status=200)
        except Exception as exc:
            return self._error_response(
                "capability_snapshot_build_failed",
                str(exc),
                status=500,
            )

    # ------------------------------------------------------------------
    # Read-only ORM endpoints (ported from the validated 16.0/17.0 module for
    # STYD Data Guide support).
    #
    # Same routes, response shapes, allowlist, field-filtering and read-only
    # behavior as 16.0. They reuse 15.0's existing access control (plaintext
    # token via _check_bridge_access) and 15.0's existing _json_response (which
    # already uses the Odoo-15-compatible `response.status_code = status`
    # pattern). 15.0 has no audit-log model, so — exactly like the existing
    # health/security/users/capabilities endpoints above — these do not write
    # audit rows.
    # ------------------------------------------------------------------
    def _get_orm(self):
        return request.env["styd.odoo.bridge.orm"].sudo()

    def _parse_json_body(self):
        """Parse the request body as a JSON object. Returns {} for an empty
        body and None for invalid JSON (the caller maps None -> invalid_json).

        The POST ORM routes are type="http", so the body is read from the raw request
        stream. The request.jsonrequest check is a harmless fallback: it is populated
        only if a request is ever dispatched via Odoo's JSON layer, and is None on the
        normal type="http" path."""
        jsonrequest = getattr(request, "jsonrequest", None)
        if isinstance(jsonrequest, dict):
            return jsonrequest
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
            models = orm.orm_list_models()
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
            fields = orm.orm_model_fields(model)
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

    # Odoo 15 compatibility: the POST ORM routes are type="http" (same as 16.0+).
    # Odoo 15's legacy HTTP framework routes any request whose Content-Type is
    # application/json through its JSON-RPC dispatcher, which cannot return the plain
    # {"ok": true, ...} contract — a type="http" route is rejected ("request of type
    # 'json'") and a type="json" route wraps (and even str()s) the response into a
    # JSON-RPC envelope. So STYD sends the bridge POST body with Content-Type
    # text/plain, which keeps Odoo 15 on the plain-HTTP dispatcher; the handler reads
    # the raw body via _parse_json_body. This is transparent to Odoo 16-19, whose
    # type="http" handlers also read the raw body and ignore the request Content-Type.
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
            result = orm.orm_search_read(
                model=model,
                domain=body.get("domain"),
                fields=body.get("fields"),
                limit=body.get("limit"),
                offset=body.get("offset"),
                order=body.get("order"),
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

    # type="http" — see the Odoo 15 compatibility note on bridge_search_read.
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
            result = orm.orm_read_group(
                model=model,
                domain=body.get("domain"),
                group_by=body.get("group_by"),
                aggregates=body.get("aggregates"),
                limit=body.get("limit"),
                order=body.get("order"),
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