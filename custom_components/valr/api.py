"""VALR API helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .const import API_URL, PRIMARY_SUBACCOUNT_ID, PRIMARY_SUBACCOUNT_NAME


class ValrApiError(Exception):
    """Raised when VALR returns an API error."""


class ValrApiClient:
    """Small async client for the VALR REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._api_secret = api_secret

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict[str, Any] | None = None,
        signed: bool = False,
        headers: dict | None = None,
        subaccount_id: str | None = None,
    ) -> dict | list:
        """Send a VALR request."""
        method = method.upper()
        body = ""
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":"))
        request_path = path
        if params:
            request_path = f"{path}?{urlencode(params)}"

        request_headers = dict(headers or {})
        if json_body is not None:
            request_headers["Content-Type"] = "application/json"
        if signed:
            if not self._api_key or not self._api_secret:
                raise ValrApiError("Missing VALR API credentials")
            timestamp = str(int(time.time() * 1000))
            payload = f"{timestamp}{method}{request_path}{body}{subaccount_id or ''}"
            signature = hmac.new(
                self._api_secret.encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha512,
            ).hexdigest()
            request_headers.update(
                {
                    "X-VALR-API-KEY": self._api_key,
                    "X-VALR-SIGNATURE": signature,
                    "X-VALR-TIMESTAMP": timestamp,
                }
            )
            if subaccount_id:
                request_headers["X-VALR-SUB-ACCOUNT-ID"] = subaccount_id

        async with self._session.request(
            method,
            f"{API_URL}{request_path}",
            headers=request_headers,
            data=body if json_body is not None else None,
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise ValrApiError(f"VALR API HTTP {resp.status}: {text}")
            if resp.content_type == "application/json":
                return await resp.json()
            return json.loads(await resp.text())

    async def market_summaries(self) -> list[dict]:
        """Return all VALR market summaries."""
        data = await self.request("GET", "/v1/public/marketsummary")
        return data if isinstance(data, list) else []

    async def pairs(self) -> list[dict]:
        """Return all VALR tradeable pairs."""
        data = await self.request("GET", "/v1/public/pairs")
        return data if isinstance(data, list) else []

    async def exchange_ott(self, ott_token: str) -> dict:
        """Exchange a VALR one-time token for API credentials."""
        data = await self.request(
            "POST",
            "/v1/partner/exchange",
            json_body={"ottToken": ott_token},
            signed=True,
        )
        return data if isinstance(data, dict) else {}

    async def balances(self, subaccount_id: str | None = None) -> list[dict]:
        """Return balances for the primary account or a subaccount."""
        if not subaccount_id or subaccount_id == PRIMARY_SUBACCOUNT_ID:
            data = await self.request("GET", "/v1/account/balances", signed=True)
        else:
            data = await self.request(
                "GET",
                "/v1/account/balances",
                signed=True,
                subaccount_id=subaccount_id,
            )
        return data if isinstance(data, list) else []

    async def subaccounts(self) -> dict[str, str]:
        """Return selectable subaccounts keyed by id."""
        choices = {PRIMARY_SUBACCOUNT_ID: PRIMARY_SUBACCOUNT_NAME}
        try:
            data = await self.request("GET", "/v1/account/subaccounts", signed=True)
        except ValrApiError:
            return choices
        if not isinstance(data, list):
            return choices
        for item in data:
            if not isinstance(item, dict):
                continue
            sub_id = str(
                item.get("id")
                or ""
            )
            if not sub_id:
                continue
            choices[sub_id] = str(
                item.get("label")
                or sub_id
            )
        return choices
