#!/usr/bin/env python3
"""Cross-platform Java ERP contract smoke test using only the Python stdlib."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_HEADERS: dict[str, str] = {}


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req_headers = {"Accept": "application/json", **DEFAULT_HEADERS, **(headers or {})}
    if data is not None:
        req_headers["Content-Type"] = "application/json"
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=req_headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {payload}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc


def require_success(result: dict[str, Any], step: str) -> Any:
    if result.get("code") != 200:
        raise AssertionError(f"{step} failed: {json.dumps(result, ensure_ascii=False)}")
    return result.get("data")


def operation_applied(base_url: str, operation_id: str) -> None:
    data = require_success(
        request_json(base_url, f"/api/operations/{operation_id}"),
        f"operation lookup {operation_id}",
    )
    if not data or not data.get("applied"):
        raise AssertionError(f"operation {operation_id} was not recorded as applied")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("ERP_BASE_URL", "http://localhost:8080"),
        help="Java ERP base URL (default: ERP_BASE_URL or http://localhost:8080)",
    )
    parser.add_argument("--username", default=os.getenv("ERP_SMOKE_USERNAME", ""))
    parser.add_argument("--password", default=os.getenv("ERP_SMOKE_PASSWORD", ""))
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Only verify readiness and supplier/part query contracts",
    )
    parser.add_argument(
        "--bootstrap-fixture",
        action="store_true",
        help="Create one deterministic CI supplier/part when the database is empty",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    health = request_json(base_url, "/actuator/health/readiness")
    if health.get("status") != "UP":
        raise AssertionError(f"readiness is not UP: {health}")

    if args.username or args.password:
        if not args.username or not args.password:
            raise AssertionError("--username and --password must be provided together")
        login = require_success(
            request_json(base_url, "/api/auth/login", method="POST", body={"username": args.username, "password": args.password}),
            "login",
        )
        DEFAULT_HEADERS["Authorization"] = f"Bearer {login['accessToken']}"

    supplier_page = require_success(
        request_json(base_url, "/api/suppliers/page?current=1&size=1"),
        "supplier page",
    )
    part_page = require_success(
        request_json(base_url, "/api/parts/page?current=1&size=1"),
        "part page",
    )
    if args.bootstrap_fixture and not part_page.get("records"):
        fixture = uuid.uuid4().hex[:12]
        supplier = require_success(
            request_json(
                base_url,
                "/api/suppliers/create",
                method="POST",
                body={
                    "supplierCode": f"CI-SUP-{fixture}",
                    "name": "CI smoke supplier",
                    "status": 1,
                },
                headers={"X-Operation-Id": f"ci-supplier-{fixture}"},
            ),
            "bootstrap supplier",
        )
        require_success(
            request_json(
                base_url,
                "/api/parts/create",
                method="POST",
                body={
                    "partCode": f"CI-PART-{fixture}",
                    "name": "CI smoke part",
                    "purchasePrice": 25.5,
                    "supplierId": supplier["id"],
                    "unit": "piece",
                    "stockWarningValue": 1,
                },
                headers={"X-Operation-Id": f"ci-part-{fixture}"},
            ),
            "bootstrap part",
        )
        part_page = require_success(
            request_json(base_url, "/api/parts/page?current=1&size=1"),
            "part page after fixture bootstrap",
        )
    if not supplier_page or "records" not in supplier_page:
        raise AssertionError("supplier response is missing data.records")
    if not part_page or not part_page.get("records"):
        raise AssertionError("part response has no record; seed/import at least one part before smoke")

    part_id = part_page["records"][0]["id"]
    if args.read_only:
        print(f"SMOKE OK (read-only, partId={part_id})")
        return 0

    suffix = uuid.uuid4().hex[:12]
    inbound_op = f"smoke-in-{suffix}"
    outbound_op = f"smoke-out-{suffix}"
    order_op = f"smoke-order-{suffix}"
    idem_key = f"smoke-idem-{suffix}"

    inbound_query = urlencode(
        {"partId": part_id, "quantity": 3, "operationId": inbound_op}
    )
    inbound_headers = {"X-Operation-Id": inbound_op}
    first_inbound = request_json(
        base_url,
        f"/api/inventory/inbound?{inbound_query}",
        method="POST",
        headers=inbound_headers,
    )
    require_success(first_inbound, "inventory inbound")
    replay_inbound = request_json(
        base_url,
        f"/api/inventory/inbound?{inbound_query}",
        method="POST",
        headers=inbound_headers,
    )
    if replay_inbound != first_inbound:
        raise AssertionError("inbound operation replay did not return the original envelope")
    operation_applied(base_url, inbound_op)

    outbound_query = urlencode(
        {"partId": part_id, "quantity": 1, "operationId": outbound_op}
    )
    outbound_headers = {"X-Operation-Id": outbound_op}
    first_outbound = request_json(
        base_url,
        f"/api/inventory/outbound?{outbound_query}",
        method="POST",
        headers=outbound_headers,
    )
    require_success(first_outbound, "inventory outbound")
    replay_outbound = request_json(
        base_url,
        f"/api/inventory/outbound?{outbound_query}",
        method="POST",
        headers=outbound_headers,
    )
    if replay_outbound != first_outbound:
        raise AssertionError("outbound operation replay did not return the original envelope")
    operation_applied(base_url, outbound_op)

    order = {
        "orderNumber": f"PO-{suffix}",
        "status": 1,
        "idempotencyKey": idem_key,
        "totalAmount": 51,
        "orderDetail": [{"partId": part_id, "quantity": 2, "unitPrice": 25.5}],
    }
    first_order = request_json(
        base_url,
        "/api/orders/create",
        method="POST",
        body=order,
        headers={"X-Operation-Id": order_op},
    )
    order_data = require_success(first_order, "order create")
    replay_order = request_json(
        base_url,
        "/api/orders/create",
        method="POST",
        body=order,
        headers={"X-Operation-Id": f"{order_op}-replay"},
    )
    replay_data = require_success(replay_order, "idempotent order replay")
    if not order_data or replay_data.get("id") != order_data.get("id"):
        raise AssertionError("order idempotency returned a different order")
    operation_applied(base_url, order_op)

    by_idem = require_success(
        request_json(
            base_url,
            f"/api/orders/by-idempotency?{urlencode({'idempotencyKey': idem_key})}",
        ),
        "order lookup by idempotency key",
    )
    if not by_idem or by_idem.get("id") != order_data.get("id"):
        raise AssertionError("order lookup by idempotency key returned a different order")

    print(
        "SMOKE OK "
        f"(partId={part_id}, orderId={order_data.get('id')}, "
        f"operations={inbound_op},{outbound_op},{order_op})"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError) as exc:
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
