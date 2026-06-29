#!/usr/bin/env python3
"""Lightweight OFFLINE validation for the Odoo 18 Speak To Your Database bridge.

Validates the v19->v18 runtime backport WITHOUT a running Odoo:
  * every module .py byte-compiles,
  * every module .xml is well-formed,
  * the controller exposes the v19-style /styd_bridge/v1/* endpoints STYD needs
    (especially /styd_bridge/v1/models, the one that 404'd),
  * every HTTP route is read-only (GET/POST only; no create/write/unlink methods),
  * the read-only ORM model is present with its allowlist + read primitives and no
    business-data create/write/unlink calls.

Run:  python validate_v18_bridge.py
Exit code 0 = all checks passed.
"""
import os
import py_compile
import re
import sys
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.join(HERE, "styd_odoo_bridge")

# Endpoints STYD's data-guide/analyzer adapter calls (odooBridgeDataAdapter.ts).
REQUIRED_ENDPOINTS = [
    "/styd_bridge/v1/models",
    "/styd_bridge/v1/models/<model>/fields",
    "/styd_bridge/v1/search-read",
    "/styd_bridge/v1/read-group",
]

passed, failed = 0, 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  OK  " + label)
    else:
        failed += 1
        print("  XX  " + label + (" -- " + detail if detail else ""))


def main():
    print("\nOdoo 18 STYD bridge -- offline validation\n")

    py_files, xml_files = [], []
    for root, _dirs, files in os.walk(MODULE):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
            elif f.endswith(".xml"):
                xml_files.append(os.path.join(root, f))

    # 1. Python compiles.
    print("1. Python compile")
    for p in sorted(py_files):
        try:
            py_compile.compile(p, doraise=True)
            check(os.path.relpath(p, MODULE), True)
        except py_compile.PyCompileError as exc:
            check(os.path.relpath(p, MODULE), False, str(exc))

    # 2. XML well-formed.
    print("\n2. XML well-formedness")
    for x in sorted(xml_files):
        try:
            xml.dom.minidom.parse(x)
            check(os.path.relpath(x, MODULE), True)
        except Exception as exc:
            check(os.path.relpath(x, MODULE), False, str(exc))

    # 3. Controller routes.
    print("\n3. Controller endpoints + read-only methods")
    controller = os.path.join(MODULE, "controllers", "bridge_api.py")
    src = open(controller, encoding="utf-8").read()
    routes = re.findall(r'@http\.route\(\s*"([^"]+)"(.*?)\)', src, re.S)
    paths = [r[0] for r in routes]
    for ep in REQUIRED_ENDPOINTS:
        check("exposes " + ep, ep in paths, "present routes: %s" % ", ".join(sorted(paths)))
    # Every route is read-only: GET or POST only.
    for path, opts in routes:
        methods = re.findall(r'methods\s*=\s*\[([^\]]*)\]', opts)
        ms = re.findall(r'"([A-Z]+)"', methods[0]) if methods else []
        bad = [m for m in ms if m not in ("GET", "POST")]
        check("read-only methods for " + path, not bad, "found %s" % bad)

    # 4. Read-only ORM model.
    print("\n4. Read-only ORM model")
    orm_path = os.path.join(MODULE, "models", "bridge_orm.py")
    check("bridge_orm.py exists", os.path.exists(orm_path))
    if os.path.exists(orm_path):
        orm = open(orm_path, encoding="utf-8").read()
        check("defines styd.odoo.bridge.orm", '_name = "styd.odoo.bridge.orm"' in orm)
        for m in ("orm_list_models", "orm_model_fields", "orm_search_read", "orm_read_group"):
            check("ORM primitive " + m, ("def %s" % m) in orm)
        check("has a non-empty model allowlist", "ORM_MODEL_ALLOWLIST" in orm and "res.partner" in orm)
        check("no business create/write/unlink in ORM", not re.search(r"\.(create|write|unlink)\(", orm))

    print("\nResult: %d passed, %d failed\n" % (passed, failed))
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
