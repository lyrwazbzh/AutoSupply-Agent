#!/usr/bin/env python3
"""Redis feature smoke: cache invalidation, login limiter, and per-user activity."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def call(base: str, path: str, *, method: str = "GET", token: str | None = None,
         body: dict | None = None, ip: str = "198.51.100.10") -> tuple[int, dict, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json", "X-Real-IP": ip}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        response = urlopen(request, timeout=10)
        raw = response.read()
        return response.status, json.loads(raw or b"{}"), dict(response.headers)
    except HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw or b"{}"), dict(exc.headers)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    # Use a dedicated synthetic IP so earlier smoke logins cannot affect this counter.
    limiter_ip = "198.51.100.240"
    for attempt in range(1, 12):
        status, payload, headers = call(
            args.base_url, "/api/auth/login", method="POST",
            body={"username": "missing-user", "password": "invalid-password"}, ip=limiter_ip)
        if attempt <= 10:
            expect(status == 401, f"login attempt {attempt}: expected 401, got {status}")
        else:
            expect(status == 429, f"login attempt 11: expected 429, got {status}")
            expect(payload.get("code") == 429, "rate-limit envelope code is not 429")
            expect(int(headers.get("Retry-After", "0")) > 0, "Retry-After is missing")

    status, payload, _ = call(
        args.base_url, "/api/auth/login", method="POST",
        body={"username": args.username, "password": args.password}, ip="198.51.100.241")
    expect(status == 200 and payload.get("code") == 200, "admin login failed")
    token = payload["data"]["accessToken"]

    status, payload, _ = call(args.base_url, "/api/parts/page?current=1&size=10", token=token)
    expect(status == 200, "part page failed")
    parts = payload.get("data", {}).get("records", [])
    expect(bool(parts), "part fixture is empty")
    part = parts[0]
    part_id = int(part["id"])

    # Detail reads populate cache and record activity even when later reads hit cache.
    for _ in range(3):
        status, detail, _ = call(args.base_url, f"/api/parts/get/{part_id}", token=token)
        expect(status == 200 and detail.get("data", {}).get("id") == part_id, "part detail failed")

    original_price = Decimal(str(part["purchasePrice"]))
    changed_price = original_price + Decimal("1.00")
    price_query = urlencode({"purchasePrice": str(changed_price)})
    status, _, _ = call(args.base_url, f"/api/parts/update-price/{part_id}?{price_query}", method="PATCH", token=token)
    expect(status == 200, "part price update failed")
    status, detail, _ = call(args.base_url, f"/api/parts/get/{part_id}", token=token)
    expect(Decimal(str(detail["data"]["purchasePrice"])) == changed_price,
           "part cache was not invalidated after price update")
    restore_query = urlencode({"purchasePrice": str(original_price)})
    call(args.base_url, f"/api/parts/update-price/{part_id}?{restore_query}", method="PATCH", token=token)
    status, _, _ = call(args.base_url, f"/api/parts/get/{part_id}", token=token)
    expect(status == 200, "part detail did not recover after price restore")

    for endpoint in ("recent", "frequent"):
        status, activity, _ = call(args.base_url, f"/api/parts/{endpoint}?limit=10", token=token)
        expect(status == 200, f"part {endpoint} endpoint failed")
        expect(any(int(item["id"]) == part_id for item in activity.get("data", [])),
               f"part missing from {endpoint}")

    status, payload, _ = call(args.base_url, "/api/suppliers/page?current=1&size=10", token=token)
    suppliers = payload.get("data", {}).get("records", [])
    expect(status == 200 and suppliers, "supplier fixture is empty")
    supplier_id = int(suppliers[0]["id"])
    status, _, _ = call(args.base_url, f"/api/suppliers/get/{supplier_id}", token=token)
    expect(status == 200, "supplier detail failed")
    for endpoint in ("recent", "frequent"):
        status, activity, _ = call(args.base_url, f"/api/suppliers/{endpoint}?limit=10", token=token)
        expect(status == 200, f"supplier {endpoint} endpoint failed")
        expect(any(int(item["id"]) == supplier_id for item in activity.get("data", [])),
               f"supplier missing from {endpoint}")

    print("Redis feature smoke passed")


if __name__ == "__main__":
    main()
