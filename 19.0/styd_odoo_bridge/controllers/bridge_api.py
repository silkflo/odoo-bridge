import datetime
import decimal
import hashlib
import hmac
import json
import logging

from odoo import SUPERUSER_ID, api, http
from odoo.http import request

from odoo.addons.styd_odoo_bridge.models.bridge_orm import (
    ORM_ACCESS_MODE,
    StydOrmError,
)

_logger = logging.getLogger(__name__)


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


class StydBridgeApi(http.Controller):
    # Maximum length of the free-text "detail" we persist on an audit row.
    AUDIT_DETAIL_MAX_LEN = 500

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

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------
    def _token_fingerprint(self):
        """Return a NON-reversible fingerprint of the *presented* bearer token,
        for audit correlation only. Never returns (or logs) the raw token.

        Format: "<short sha256>...<last 4 chars>" e.g. "9f1c2a4b7d3e...8a2f".
        """
        try:
            token = self._extract_bearer_token()
        except Exception:
            token = None

        if not token:
            return None

        try:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            last4 = token[-4:] if len(token) >= 4 else ""
            return "{}...{}".format(digest[:12], last4)
        except Exception:
            return None

    def _audit_log(self, endpoint, outcome, reason_code, http_status, detail=None):
        """Best-effort audit write on a SEPARATE cursor + commit.

        A dedicated cursor is used so the audit row survives even when the main
        request transaction is rolled back (which is what happens on denied or
        error responses). This method must NEVER raise: audit logging is not
        allowed to break the bridge response -- but failures are LOGGED (never
        silently swallowed) so they are visible in the server / docker logs.

        We deliberately never store (or log): the raw token, the Authorization
        header, business row data, or prompts.
        """
        try:
            method = None
            source_ip = None
            try:
                method = request.httprequest.method
                source_ip = request.httprequest.remote_addr
            except Exception:
                pass

            safe_detail = None
            if detail:
                safe_detail = str(detail)[: self.AUDIT_DETAIL_MAX_LEN]

            values = {
                "endpoint": endpoint,
                "method": method,
                "outcome": outcome,
                "reason_code": reason_code,
                "http_status": http_status,
                "source_ip": source_ip,
                "token_fingerprint": self._token_fingerprint(),
                "detail": safe_detail,
            }

            # Separate cursor taken from the CURRENT REQUEST's registry, plus
            # explicit superuser (su) mode, so the create bypasses the read-only
            # ACL (the model grants no create rights to any group) and survives a
            # rollback of the request transaction. Odoo 19 does not expose a
            # top-level odoo.registry(), so we use request.env.registry.
            with request.env.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["styd.odoo.bridge.access.log"].sudo().create(values)
                cr.commit()
        except Exception:
            # Best-effort: never break the bridge response, but surface the
            # failure (with traceback) instead of swallowing it. Only
            # non-sensitive fields are logged -- never the raw token, the
            # Authorization header, or business data.
            _logger.exception(
                "STYD bridge: audit log write FAILED; bridge response is "
                "unaffected (endpoint=%s, outcome=%s, reason=%s, status=%s).",
                endpoint, outcome, reason_code, http_status,
            )

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------
    def _check_bridge_access(self, endpoint):
        icp = request.env["ir.config_parameter"].sudo()

        service = request.env["styd.odoo.bridge.service"]

        enabled = icp.get_param("styd_odoo_bridge.enabled", default="False")
        expected_hash = icp.get_param("styd_odoo_bridge.token_hash", default="") or ""
        legacy_token = icp.get_param("styd_odoo_bridge.token", default="") or ""

        if str(enabled).lower() not in ("1", "true", "yes", "on"):
            self._audit_log(
                endpoint,
                "denied",
                "bridge_disabled",
                403,
                "Speak To Your Database bridge is disabled in Odoo settings.",
            )
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
            self._audit_log(
                endpoint,
                "denied",
                "bridge_token_missing",
                500,
                "Bridge token is not configured in Odoo settings.",
            )
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
        # plaintext token for backward compatibility until it is rotated.
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
            self._audit_log(
                endpoint,
                "denied",
                "unauthorized",
                401,
                "Missing or invalid bearer token.",
            )
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
        endpoint = "/styd_bridge/v1/health"
        access = self._check_bridge_access(endpoint)
        if not access["ok"]:
            return access["response"]

        service = self._get_service()

        try:
            payload = service.build_health_payload()
        except Exception as exc:
            # Preserve the original behaviour (no JSON error shape existed here),
            # but record the failure before re-raising.
            self._audit_log(endpoint, "error", "health_build_failed", 500, str(exc))
            raise

        self._audit_log(endpoint, "granted", "ok", 200)
        return self._json_response(payload, status=200)

    @http.route(
        "/styd_bridge/v1/security/snapshot",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_security_snapshot(self, **kwargs):
        endpoint = "/styd_bridge/v1/security/snapshot"
        access = self._check_bridge_access(endpoint)
        if not access["ok"]:
            return access["response"]

        service = self._get_service()

        try:
            payload = service.build_security_snapshot_payload()
        except Exception as exc:
            self._audit_log(endpoint, "error", "snapshot_build_failed", 500, str(exc))
            return self._error_response(
                "snapshot_build_failed",
                str(exc),
                status=500,
            )

        self._audit_log(endpoint, "granted", "ok", 200)
        return self._json_response(payload, status=200)

    @http.route(
        "/styd_bridge/v1/users/directory",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_users_directory(self, **kwargs):
        endpoint = "/styd_bridge/v1/users/directory"
        access = self._check_bridge_access(endpoint)
        if not access["ok"]:
            return access["response"]

        service = self._get_service()

        try:
            payload = service.build_user_directory_snapshot_payload()
        except Exception as exc:
            self._audit_log(endpoint, "error", "user_directory_build_failed", 500, str(exc))
            return self._error_response(
                "user_directory_build_failed",
                str(exc),
                status=500,
            )

        self._audit_log(endpoint, "granted", "ok", 200)
        return self._json_response(payload, status=200)

    @http.route(
        "/styd_bridge/v1/users/search",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_users_search(self, **kwargs):
        endpoint = "/styd_bridge/v1/users/search"
        access = self._check_bridge_access(endpoint)
        if not access["ok"]:
            return access["response"]

        service = self._get_service()
        query = kwargs.get("q")

        try:
            payload = self._build_user_search_payload(service, query)
        except Exception as exc:
            self._audit_log(endpoint, "error", "user_search_failed", 500, str(exc))
            return self._error_response(
                "user_search_failed",
                str(exc),
                status=500,
            )

        self._audit_log(endpoint, "granted", "ok", 200)
        return self._json_response(payload, status=200)

    @http.route(
        "/styd_bridge/v1/capabilities",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def bridge_capabilities(self, **kwargs):
        endpoint = "/styd_bridge/v1/capabilities"
        access = self._check_bridge_access(endpoint)
        if not access["ok"]:
            return access["response"]

        service = self._get_service()

        try:
            payload = service.build_capability_snapshot_payload()
        except Exception as exc:
            self._audit_log(endpoint, "error", "capability_snapshot_build_failed", 500, str(exc))
            return self._error_response(
                "capability_snapshot_build_failed",
                str(exc),
                status=500,
            )

        self._audit_log(endpoint, "granted", "ok", 200)
        return self._json_response(payload, status=200)

    # ------------------------------------------------------------------
    # Read-only ORM endpoints (Phase 5B MVP)
    # ------------------------------------------------------------------
    def _get_orm(self):
        return request.env["styd.odoo.bridge.orm"].sudo()

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
        endpoint = "/styd_bridge/v1/models"
        access = self._check_bridge_access(endpoint)
        if not access["ok"]:
            return access["response"]

        orm = self._get_orm()
        try:
            models = orm.orm_list_models()
        except Exception as exc:
            _logger.warning("STYD bridge: /models failed (error_type=%s)", type(exc).__name__)
            self._audit_log(endpoint, "error", "orm_error", 500, "models listing failed")
            return self._error_response("orm_error", "Failed to list models.", status=500)

        self._audit_log(endpoint, "granted", "ok", 200, "models=%d" % len(models))
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
        endpoint = "/styd_bridge/v1/models/<model>/fields"
        access = self._check_bridge_access(endpoint)
        if not access["ok"]:
            return access["response"]

        orm = self._get_orm()
        try:
            fields = orm.orm_model_fields(model)
        except StydOrmError as exc:
            self._audit_log(endpoint, "denied", exc.code, 400, "model=%s" % str(model)[:64])
            return self._error_response(exc.code, exc.message, status=400)
        except Exception as exc:
            _logger.warning("STYD bridge: fields failed (model=%s, error_type=%s)", str(model)[:64], type(exc).__name__)
            self._audit_log(endpoint, "error", "orm_error", 500, "model=%s" % str(model)[:64])
            return self._error_response("orm_error", "Failed to read fields.", status=500)

        self._audit_log(endpoint, "granted", "ok", 200, "model=%s fields=%d" % (str(model)[:64], len(fields)))
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
        endpoint = "/styd_bridge/v1/search-read"
        access = self._check_bridge_access(endpoint)
        if not access["ok"]:
            return access["response"]

        body = self._parse_json_body()
        if body is None:
            self._audit_log(endpoint, "denied", "invalid_json", 400, None)
            return self._error_response("invalid_json", "Request body must be a valid JSON object.", status=400)

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
            self._audit_log(endpoint, "denied", exc.code, 400, "model=%s" % str(model)[:64])
            return self._error_response(exc.code, exc.message, status=400)
        except Exception as exc:
            _logger.warning("STYD bridge: search-read failed (model=%s, error_type=%s)", str(model)[:64], type(exc).__name__)
            self._audit_log(endpoint, "error", "orm_error", 500, "model=%s" % str(model)[:64])
            return self._error_response("orm_error", "Query failed.", status=500)

        self._audit_log(endpoint, "granted", "ok", 200, "model=%s rows=%s" % (str(model)[:64], result.get("returned_count")))
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
        endpoint = "/styd_bridge/v1/read-group"
        access = self._check_bridge_access(endpoint)
        if not access["ok"]:
            return access["response"]

        body = self._parse_json_body()
        if body is None:
            self._audit_log(endpoint, "denied", "invalid_json", 400, None)
            return self._error_response("invalid_json", "Request body must be a valid JSON object.", status=400)

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
            self._audit_log(endpoint, "denied", exc.code, 400, "model=%s" % str(model)[:64])
            return self._error_response(exc.code, exc.message, status=400)
        except Exception as exc:
            _logger.warning("STYD bridge: read-group failed (model=%s, error_type=%s)", str(model)[:64], type(exc).__name__)
            self._audit_log(endpoint, "error", "orm_error", 500, "model=%s" % str(model)[:64])
            return self._error_response("orm_error", "Query failed.", status=500)

        self._audit_log(endpoint, "granted", "ok", 200, "model=%s groups=%s" % (str(model)[:64], result.get("returned_count")))
        payload = {"ok": True, "access_mode": ORM_ACCESS_MODE, "model": model}
        payload.update(result)
        return self._json_response(payload, status=200)
