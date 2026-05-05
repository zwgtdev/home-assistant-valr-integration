"""The VALR integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ValrApiClient, ValrApiError
from .const import (
    BALANCE_DATA,
    BALANCE_ERRORS,
    CONF_API_KEY,
    CONF_API_SECRET,
    CONF_FUTURES_PAIRS,
    CONF_SPOT_PAIRS,
    CONF_SUBACCOUNTS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MARKET_DATA,
    PLATFORMS,
    PRIMARY_SUBACCOUNT_ID,
    PRIMARY_SUBACCOUNT_NAME,
    SHARED_KEY,
)

_LOGGER = logging.getLogger(__name__)


def _entry_value(entry: ConfigEntry, key: str, default=None):
    """Return option value falling back to initial config data."""
    return entry.options.get(key, entry.data.get(key, default))


class ValrMarketCoordinator(DataUpdateCoordinator):
    """Fetch public VALR market data shared by all config entries."""

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession, interval: int) -> None:
        self.client = ValrApiClient(session)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_markets",
            update_interval=timedelta(seconds=interval),
        )

    async def _async_update_data(self) -> dict:
        try:
            async with asyncio.timeout(30):
                summaries = await self.client.market_summaries()
        except (aiohttp.ClientError, ValrApiError) as err:
            raise UpdateFailed(f"VALR market update failed: {err}") from err
        except TimeoutError as err:
            raise UpdateFailed("VALR market update timed out") from err

        return {
            MARKET_DATA: {
                item["currencyPair"]: item
                for item in summaries
                if isinstance(item, dict) and item.get("currencyPair")
            }
        }


class ValrAccountCoordinator(DataUpdateCoordinator):
    """Fetch authenticated VALR balances for selected subaccounts."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        api_key: str,
        api_secret: str,
        subaccounts: list[str],
        subaccount_names: dict[str, str],
        interval: int,
    ) -> None:
        self.client = ValrApiClient(session, api_key, api_secret)
        self.subaccounts = subaccounts or [PRIMARY_SUBACCOUNT_ID]
        self.subaccount_names = {
            PRIMARY_SUBACCOUNT_ID: PRIMARY_SUBACCOUNT_NAME,
            **subaccount_names,
        }
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_account",
            update_interval=timedelta(seconds=interval),
        )

    async def _async_update_data(self) -> dict:
        balances: dict[str, dict] = {}
        balance_errors: dict[str, str] = {}
        existing_balances = (self.data or {}).get(BALANCE_DATA, {})
        try:
            async with asyncio.timeout(30):
                for subaccount_id in self.subaccounts:
                    try:
                        raw = await self.client.balances(subaccount_id)
                    except ValrApiError as err:
                        balance_errors[subaccount_id] = str(err)
                        if subaccount_id in existing_balances:
                            balances[subaccount_id] = existing_balances[subaccount_id]
                        _LOGGER.warning(
                            "VALR balance update failed for subaccount %s: %s",
                            subaccount_id,
                            err,
                        )
                        continue

                    balances[subaccount_id] = {
                        "name": self.subaccount_names.get(subaccount_id, subaccount_id),
                        "balances": _normalise_balances(raw),
                    }
        except (aiohttp.ClientError, ValrApiError) as err:
            raise UpdateFailed(f"VALR balance update failed: {err}") from err
        except TimeoutError as err:
            raise UpdateFailed("VALR balance update timed out") from err

        if not balances:
            detail = "; ".join(balance_errors.values()) or "No balances returned"
            raise UpdateFailed(f"VALR balance update failed: {detail}")

        return {BALANCE_DATA: balances, BALANCE_ERRORS: balance_errors}


def _normalise_balances(raw: list[dict]) -> dict[str, dict[str, float]]:
    """Convert VALR balance rows to numeric totals keyed by currency."""
    balances: dict[str, dict[str, float]] = {}
    for item in raw:
        currency = item.get("currency") or item.get("asset")
        if not currency:
            continue
        total = _to_float(item.get("total"), None)
        available = _to_float(item.get("available"), 0.0)
        reserved = _to_float(item.get("reserved"), 0.0)
        if total is None:
            total = available + reserved
        balances[str(currency)] = {
            "total": total,
            "available": available,
            "reserved": reserved,
        }
    return balances


def _to_float(value, default: float | None = 0.0) -> float | None:
    """Safely convert API strings to floats."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _ensure_shared(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Create the shared market coordinator if needed."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    shared = domain_data.get(SHARED_KEY)
    if shared is not None:
        return shared

    session = async_get_clientsession(hass)
    interval = _entry_value(entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    coordinator = ValrMarketCoordinator(hass, session, interval)
    await coordinator.async_config_entry_first_refresh()
    shared = {"market_coordinator": coordinator, "entries": set()}
    domain_data[SHARED_KEY] = shared
    return shared


async def _options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up VALR from a config entry."""
    session = async_get_clientsession(hass)
    shared = await _ensure_shared(hass, entry)
    shared["entries"].add(entry.entry_id)

    client = ValrApiClient(session, entry.data[CONF_API_KEY], entry.data[CONF_API_SECRET])
    subaccount_names = await client.subaccounts()
    interval = _entry_value(entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    account_coordinator = ValrAccountCoordinator(
        hass,
        session,
        entry.data[CONF_API_KEY],
        entry.data[CONF_API_SECRET],
        list(_entry_value(entry, CONF_SUBACCOUNTS, [PRIMARY_SUBACCOUNT_ID])),
        subaccount_names,
        interval,
    )
    await account_coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "account_coordinator": account_coordinator,
    }

    entry.async_on_unload(entry.add_update_listener(_options_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a VALR config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        shared = hass.data[DOMAIN].get(SHARED_KEY)
        if shared:
            shared["entries"].discard(entry.entry_id)
            if not shared["entries"]:
                hass.data[DOMAIN].pop(SHARED_KEY, None)
    return unload_ok
