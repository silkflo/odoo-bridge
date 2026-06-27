import json

from odoo import http
from odoo.http import request


class StydBridgeApi(http.Controller):
    def _json_response(self, payload, status=200):
        response = request.make_response(
            json.dumps(payload, default=str),
            headers=[
            ("Content-Type", "application/json"),
            ],
        )
        response.status_code = status
        return response

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
                    "STYD bridge is disabled in Odoo settings.",
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