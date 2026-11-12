from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from flask import Flask, Response, current_app, g, jsonify, make_response, redirect, request, send_from_directory, stream_with_context
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pydantic import ValidationError
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

from .auth import (
    clear_auth_cookie,
    create_access_token,
    public_user,
    require_device_key,
    require_page_roles,
    require_roles,
    set_auth_cookie,
    verify_password,
)
from .config import Config
from .db import get_database, iso_utc, public_doc, utc_naive
from .schemas import (
    AnalyticsFilter,
    BusCreate,
    BusUpdate,
    DriverCreate,
    DriverUpdate,
    EventCreate,
    EventFilter,
    LoginSchema,
    SearchFilter,
)
from .services import (
    camera_config,
    compute_analytics,
    compute_stats,
    csv_bytes,
    event_sort,
    events_for_export,
    ingest_event,
    naive_now,
    record_audit,
    xlsx_bytes,
)


def create_app(config: Config | None = None, mongo_client=None) -> Flask:
    config = config or Config.from_env()
    app = Flask(__name__, static_folder=None)
    app.config.update(
        TESTING=config.testing,
        PROPAGATE_EXCEPTIONS=False,
        MAX_CONTENT_LENGTH=1_000_000,
        TRANSPORT_CONFIG=config,
        RATELIMIT_ENABLED=config.rate_limit_enabled,
        RATELIMIT_STORAGE_URI=config.rate_limit_storage_uri,
        PREFERRED_URL_SCHEME="https" if config.environment == "production" else "http",
        SECRET_KEY=os.urandom(32).hex(),
    )
    app.json.sort_keys = False
    db = get_database(config, mongo_client)
    app.extensions["transport_db"] = db

    limiter = Limiter(key_func=get_remote_address, app=app)
    app.extensions["limiter"] = limiter

    CORS(
        app,
        resources={r"/api/*": {"origins": list(config.cors_allowed_origins)}},
        supports_credentials=True,
        allow_headers=["Content-Type", "X-Device-Key"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )

    frontend_dir: Path = config.frontend_dir

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com https://unpkg.com data:; "
            "img-src 'self' data: https:; "
            "media-src 'self' blob: https:; "
            "connect-src 'self' https:; "
            "worker-src 'self' blob:; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self' https://*.e2b.app"
        )
        response.headers["Content-Security-Policy"] = csp
        if request.path.startswith("/api/") or response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        if config.environment == "production" and request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    def validation_details(exc: ValidationError) -> list[dict[str, str]]:
        details = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", [])) or "payload"
            details.append({"field": location, "message": error.get("msg", "Invalid value")})
        return details

    def validate(schema_cls, source: str = "json"):
        if source == "args":
            data = {key: value for key, value in request.args.items() if value != ""}
        else:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return None, (jsonify({"error": "A JSON object is required"}), 400)
        try:
            return schema_cls.model_validate(data), None
        except ValidationError as exc:
            return None, (
                jsonify({"error": "Validation failed", "details": validation_details(exc)}),
                400,
            )

    def mongo_payload(model, *, exclude_unset: bool = False) -> dict[str, Any]:
        data = model.model_dump(exclude_unset=exclude_unset)
        for key, value in list(data.items()):
            if isinstance(value, datetime):
                data[key] = utc_naive(value)
            elif isinstance(value, date):
                data[key] = value.isoformat()
        return data

    def oid_or_none(value: str) -> ObjectId | None:
        return ObjectId(value) if ObjectId.is_valid(value) else None

    def serialize_many(docs) -> list[dict[str, Any]]:
        return [public_doc(doc) for doc in docs]

    def paginated(collection, query: dict, search: SearchFilter, sort: list[tuple[str, int]]):
        total = collection.count_documents(query)
        skip = (search.page - 1) * search.page_size
        docs = collection.find(query).sort(sort).skip(skip).limit(search.page_size)
        return {
            "items": serialize_many(docs),
            "page": search.page,
            "page_size": search.page_size,
            "total": total,
            "pages": math.ceil(total / search.page_size) if total else 0,
        }

    def search_regex(value: str | None) -> dict[str, str] | None:
        if not value:
            return None
        return {"$regex": re.escape(value), "$options": "i"}

    def send_page(filename: str) -> Response:
        return send_from_directory(frontend_dir / "pages", filename, max_age=0)

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def login_page():
        from .auth import authenticate_request

        user, _ = authenticate_request()
        if user:
            return redirect("/dashboard" if user["role"] == "head_admin" else "/manage")
        return send_from_directory(frontend_dir, "index.html", max_age=0)

    @app.get("/login")
    def login_alias():
        return redirect("/")

    @app.get("/dashboard")
    @require_page_roles("head_admin")
    def dashboard_page():
        return send_page("dashboard.html")

    @app.get("/logs")
    @require_page_roles("head_admin")
    def logs_page():
        return send_page("logs.html")

    @app.get("/analytics")
    @require_page_roles("head_admin")
    def analytics_page():
        return send_page("analytics.html")

    @app.get("/drivers")
    @require_page_roles("head_admin", "transport_office")
    def drivers_page():
        return send_page("drivers.html")

    @app.get("/buses")
    @require_page_roles("head_admin", "transport_office")
    def buses_page():
        return send_page("buses.html")

    @app.get("/driver-details")
    @require_page_roles("head_admin", "transport_office")
    def driver_details_page():
        return send_page("driver-details.html")

    @app.get("/audit")
    @require_page_roles("head_admin")
    def audit_page():
        return send_page("audit.html")

    @app.get("/manage")
    @require_page_roles("transport_office")
    def manage_page():
        return send_page("manage.html")

    @app.get("/assets/<path:filename>")
    def assets(filename: str):
        return send_from_directory(frontend_dir / "assets", filename)

    @app.get("/js/<path:filename>")
    def scripts(filename: str):
        return send_from_directory(frontend_dir / "js", filename)

    @app.get("/vendor/<path:filename>")
    def vendor(filename: str):
        return send_from_directory(frontend_dir / "vendor", filename, max_age=86400)

    # ------------------------------------------------------------------- auth
    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "srm-trp-transport", "time": iso_utc(naive_now())})

    @app.post("/api/auth/login")
    @limiter.limit(config.login_rate_limit)
    def login():
        payload, error = validate(LoginSchema)
        if error:
            return error
        user = db.users.find_one({"email": payload.email})
        if not user or not user.get("active", True) or not verify_password(user.get("password_hash", ""), payload.password):
            record_audit(db, None, "login_failed", "users", payload.email, flask_request=request)
            return jsonify({"error": "Invalid email or password"}), 401
        safe_user = public_user(user)
        token, expires_at = create_access_token(config, user)
        response = make_response(jsonify({"user": safe_user, "expires_at": iso_utc(expires_at)}))
        set_auth_cookie(response, token, config)
        record_audit(db, safe_user, "login", "users", str(user["_id"]), flask_request=request)
        return response

    @app.get("/api/auth/me")
    @require_roles()
    def me():
        return jsonify({"user": g.current_user})

    @app.post("/api/auth/logout")
    @require_roles()
    def logout():
        record_audit(db, g.current_user, "logout", "users", g.current_user.get("id"), flask_request=request)
        response = make_response(jsonify({"ok": True}))
        clear_auth_cookie(response, config)
        return response

    # ------------------------------------------------------------ config/stats
    @app.get("/api/config")
    @require_roles("head_admin")
    def config_endpoint():
        return jsonify(camera_config(config))

    @app.get("/api/stats")
    @require_roles("head_admin")
    def stats():
        return jsonify(compute_stats(db, config))

    @app.get("/api/analytics")
    @require_roles("head_admin")
    def analytics():
        payload, error = validate(AnalyticsFilter, source="args")
        if error:
            return error
        return jsonify(compute_analytics(db, payload, config))

    # ------------------------------------------------------------------ events
    @app.get("/api/events")
    @require_roles("head_admin")
    def list_events():
        event_filter, error = validate(EventFilter, source="args")
        if error:
            return error
        query_payload = event_filter.model_dump()
        skip = (event_filter.page - 1) * event_filter.page_size
        from .services import build_event_query

        query = build_event_query(event_filter, config)
        total = db.events.count_documents(query)
        docs = db.events.find(query).sort(event_sort()).skip(skip).limit(event_filter.page_size)
        return jsonify(
            {
                "items": serialize_many(docs),
                "filters": {
                    "date": query_payload.get("date").isoformat() if query_payload.get("date") else None,
                    "date_from": iso_utc(event_filter.date_from) if event_filter.date_from else None,
                    "date_to": iso_utc(event_filter.date_to) if event_filter.date_to else None,
                    "bus_number": event_filter.bus_number,
                    "gate": event_filter.gate,
                    "direction": event_filter.direction,
                    "flagged": event_filter.flagged,
                },
                "page": event_filter.page,
                "page_size": event_filter.page_size,
                "total": total,
                "pages": math.ceil(total / event_filter.page_size) if total else 0,
            }
        )

    @app.post("/api/events")
    @require_device_key
    def create_event():
        payload, error = validate(EventCreate)
        if error:
            return error
        event = ingest_event(db, payload, config, source="device")
        record_audit(
            db,
            {"email": "device-client", "role": "device"},
            "event_ingested",
            "events",
            event.get("id"),
            after=event,
            flask_request=request,
        )
        return jsonify({"event": event}), 201

    @app.get("/api/events/<event_id>")
    @require_roles("head_admin")
    def get_event(event_id: str):
        oid = oid_or_none(event_id)
        if not oid:
            return jsonify({"error": "Not found"}), 404
        doc = db.events.find_one({"_id": oid})
        if not doc:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"event": public_doc(doc)})

    @app.get("/api/export/events.csv")
    @require_roles("head_admin")
    def export_csv():
        event_filter, error = validate(EventFilter, source="args")
        if error:
            return error
        rows = events_for_export(db, event_filter, config)
        response = Response(csv_bytes(rows), mimetype="text/csv; charset=utf-8")
        response.headers["Content-Disposition"] = 'attachment; filename="bus-events.csv"'
        return response

    @app.get("/api/export/events.xlsx")
    @require_roles("head_admin")
    def export_xlsx():
        event_filter, error = validate(EventFilter, source="args")
        if error:
            return error
        rows = events_for_export(db, event_filter, config)
        response = Response(
            xlsx_bytes(rows),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response.headers["Content-Disposition"] = 'attachment; filename="bus-events.xlsx"'
        return response

    @app.get("/api/stream")
    @require_roles("head_admin")
    def stream():
        def generate():
            yield "retry: 5000\n\n"
            while True:
                recent = db.events.find({}, {"_id": 0}).sort(event_sort()).limit(8)
                payload = {
                    "type": "tick",
                    "generated_at": iso_utc(naive_now()),
                    "stats": compute_stats(db, config),
                    "recent_events": serialize_many(recent),
                }
                yield "data: " + json.dumps(payload, default=str) + "\n\n"
                time.sleep(10)

        response = Response(stream_with_context(generate()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    # ----------------------------------------------------------------- drivers
    @app.get("/api/drivers")
    @require_roles("head_admin", "transport_office")
    def list_drivers():
        search, error = validate(SearchFilter, source="args")
        if error:
            return error
        regex = search_regex(search.q)
        query: dict[str, Any] = {}
        if regex:
            query = {"$or": [{"name": regex}, {"bus_number": regex}, {"license_number": regex}]}
        return jsonify(paginated(db.drivers, query, search, [("name", ASCENDING)]))

    @app.post("/api/drivers")
    @require_roles("transport_office")
    def add_driver():
        payload, error = validate(DriverCreate)
        if error:
            return error
        data = mongo_payload(payload)
        if not db.buses.find_one({"bus_number": data["bus_number"]}, {"_id": 1}):
            return jsonify({"error": "Register this bus before assigning a driver"}), 400
        data.update({"created_at": naive_now(), "updated_at": naive_now(), "demo": False})
        result = db.drivers.insert_one(data)
        after = db.drivers.find_one({"_id": result.inserted_id})
        record_audit(db, g.current_user, "create", "drivers", str(result.inserted_id), after=after, flask_request=request)
        return jsonify({"driver": public_doc(after)}), 201

    @app.get("/api/drivers/<driver_id>")
    @require_roles("head_admin", "transport_office")
    def get_driver(driver_id: str):
        oid = oid_or_none(driver_id)
        doc = db.drivers.find_one({"_id": oid}) if oid else None
        if not doc:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"driver": public_doc(doc)})

    @app.route("/api/drivers/<driver_id>", methods=["PUT", "PATCH"])
    @require_roles("transport_office")
    def update_driver(driver_id: str):
        oid = oid_or_none(driver_id)
        before = db.drivers.find_one({"_id": oid}) if oid else None
        if not before:
            return jsonify({"error": "Not found"}), 404
        payload, error = validate(DriverUpdate)
        if error:
            return error
        changes = mongo_payload(payload, exclude_unset=True)
        if not changes:
            return jsonify({"error": "No fields supplied"}), 400
        if "bus_number" in changes and not db.buses.find_one({"bus_number": changes["bus_number"]}, {"_id": 1}):
            return jsonify({"error": "Register this bus before assigning a driver"}), 400
        changes["updated_at"] = naive_now()
        db.drivers.update_one({"_id": oid}, {"$set": changes})
        after = db.drivers.find_one({"_id": oid})
        record_audit(db, g.current_user, "update", "drivers", str(oid), before=before, after=after, flask_request=request)
        return jsonify({"driver": public_doc(after)})

    @app.delete("/api/drivers/<driver_id>")
    @require_roles("transport_office")
    def delete_driver(driver_id: str):
        oid = oid_or_none(driver_id)
        before = db.drivers.find_one({"_id": oid}) if oid else None
        if not before:
            return jsonify({"error": "Not found"}), 404
        db.drivers.delete_one({"_id": oid})
        record_audit(db, g.current_user, "delete", "drivers", str(oid), before=before, flask_request=request)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------- buses
    @app.get("/api/buses")
    @require_roles("head_admin", "transport_office")
    def list_buses():
        search, error = validate(SearchFilter, source="args")
        if error:
            return error
        regex = search_regex(search.q)
        query: dict[str, Any] = {}
        if regex:
            query = {"$or": [{"bus_number": regex}, {"registration_number": regex}, {"route": regex}]}
        return jsonify(paginated(db.buses, query, search, [("bus_number", ASCENDING)]))

    @app.post("/api/buses")
    @require_roles("transport_office")
    def add_bus():
        payload, error = validate(BusCreate)
        if error:
            return error
        data = mongo_payload(payload)
        data.update({"created_at": naive_now(), "updated_at": naive_now(), "demo": False})
        try:
            result = db.buses.insert_one(data)
        except DuplicateKeyError:
            return jsonify({"error": "A bus with this number already exists"}), 409
        after = db.buses.find_one({"_id": result.inserted_id})
        record_audit(db, g.current_user, "create", "buses", str(result.inserted_id), after=after, flask_request=request)
        return jsonify({"bus": public_doc(after)}), 201

    @app.get("/api/buses/<bus_id>")
    @require_roles("head_admin", "transport_office")
    def get_bus(bus_id: str):
        oid = oid_or_none(bus_id)
        doc = db.buses.find_one({"_id": oid}) if oid else None
        if not doc:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"bus": public_doc(doc)})

    @app.route("/api/buses/<bus_id>", methods=["PUT", "PATCH"])
    @require_roles("transport_office")
    def update_bus(bus_id: str):
        oid = oid_or_none(bus_id)
        before = db.buses.find_one({"_id": oid}) if oid else None
        if not before:
            return jsonify({"error": "Not found"}), 404
        payload, error = validate(BusUpdate)
        if error:
            return error
        changes = mongo_payload(payload, exclude_unset=True)
        if not changes:
            return jsonify({"error": "No fields supplied"}), 400
        changes["updated_at"] = naive_now()
        try:
            db.buses.update_one({"_id": oid}, {"$set": changes})
        except DuplicateKeyError:
            return jsonify({"error": "A bus with this number already exists"}), 409
        after = db.buses.find_one({"_id": oid})
        record_audit(db, g.current_user, "update", "buses", str(oid), before=before, after=after, flask_request=request)
        return jsonify({"bus": public_doc(after)})

    @app.delete("/api/buses/<bus_id>")
    @require_roles("transport_office")
    def delete_bus(bus_id: str):
        oid = oid_or_none(bus_id)
        before = db.buses.find_one({"_id": oid}) if oid else None
        if not before:
            return jsonify({"error": "Not found"}), 404
        db.buses.delete_one({"_id": oid})
        record_audit(db, g.current_user, "delete", "buses", str(oid), before=before, flask_request=request)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ search
    @app.get("/api/search")
    @require_roles("head_admin", "transport_office")
    def search():
        search_filter, error = validate(SearchFilter, source="args")
        if error:
            return error
        regex = search_regex(search_filter.q)
        if not regex:
            return jsonify({"drivers": [], "buses": []})
        drivers = db.drivers.find(
            {"$or": [{"name": regex}, {"bus_number": regex}, {"license_number": regex}]}
        ).limit(8)
        buses = db.buses.find(
            {"$or": [{"bus_number": regex}, {"registration_number": regex}, {"route": regex}]}
        ).limit(8)
        return jsonify({"drivers": serialize_many(drivers), "buses": serialize_many(buses)})

    # ------------------------------------------------------------------- audit
    @app.get("/api/audit")
    @require_roles("head_admin")
    def audit_log():
        search, error = validate(SearchFilter, source="args")
        if error:
            return error
        regex = search_regex(search.q)
        query: dict[str, Any] = {}
        if regex:
            query = {
                "$or": [
                    {"actor": regex},
                    {"action": regex},
                    {"collection": regex},
                    {"record_id": regex},
                ]
            }
        return jsonify(paginated(db.audit_logs, query, search, [("timestamp", DESCENDING)]))

    # ------------------------------------------------------------------ errors
    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found"}), 404
        return make_response("Not found", 404)

    @app.errorhandler(405)
    def method_not_allowed(_error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Method not allowed"}), 405
        return make_response("Method not allowed", 405)

    @app.errorhandler(413)
    def payload_too_large(_error):
        return jsonify({"error": "Payload too large"}), 413

    @app.errorhandler(429)
    def rate_limited(_error):
        return jsonify({"error": "Too many requests. Please try again later."}), 429

    @app.errorhandler(DuplicateKeyError)
    def duplicate_key(_error):
        return jsonify({"error": "A duplicate record exists"}), 409

    @app.errorhandler(PyMongoError)
    def database_error(_error):
        current_app.logger.exception("Database request failed")
        if request.path.startswith("/api/"):
            return jsonify({"error": "A temporary data service error occurred"}), 503
        return make_response("Service temporarily unavailable", 503)

    @app.errorhandler(Exception)
    def unhandled_error(error):
        current_app.logger.exception("Unhandled request error: %s", type(error).__name__)
        if request.path.startswith("/api/"):
            return jsonify({"error": "An unexpected server error occurred"}), 500
        return make_response("An unexpected server error occurred", 500)

    return app
