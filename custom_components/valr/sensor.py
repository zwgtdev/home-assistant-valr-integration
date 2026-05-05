"""VALR sensor entities."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BALANCE_DATA,
    CONF_ACCOUNT_NAME,
    CONF_FUTURES_PAIRS,
    CONF_SPOT_PAIRS,
    CONF_SUBACCOUNTS,
    CONF_VALUATION_CURRENCIES,
    DEFAULT_VALUATION_CURRENCIES,
    DOMAIN,
    FIAT_UNITS,
    MARKET_DATA,
    PRIMARY_SUBACCOUNT_ID,
    QUOTE_ASSET_CONFIG,
    QUOTE_ASSET_KEYS_SORTED,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up VALR sensors from a config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    account_coordinator = entry_data["account_coordinator"]
    market_coordinator = hass.data[DOMAIN]["_shared"]["market_coordinator"]
    entity_registry = async_get_entity_registry(hass)

    account_name = config_entry.data.get(CONF_ACCOUNT_NAME, "Account")
    spot_pairs = _entry_value(config_entry, CONF_SPOT_PAIRS, [])
    futures_pairs = _entry_value(config_entry, CONF_FUTURES_PAIRS, [])
    subaccounts = _entry_value(config_entry, CONF_SUBACCOUNTS, [PRIMARY_SUBACCOUNT_ID])
    valuation_currencies = _entry_value(
        config_entry, CONF_VALUATION_CURRENCIES, DEFAULT_VALUATION_CURRENCIES
    )

    desired_uids = set()
    for pair in spot_pairs:
        desired_uids.add(f"valr_spot_{pair}")
    for pair in futures_pairs:
        desired_uids.add(f"valr_futures_{pair}")
    for subaccount_id in subaccounts:
        for currency in valuation_currencies:
            desired_uids.add(
                f"valr_balance_{config_entry.entry_id}_{_slug(subaccount_id)}_{currency.lower()}"
            )

    for entity in list(entity_registry.entities.values()):
        if entity.config_entry_id != config_entry.entry_id:
            continue
        if entity.unique_id not in desired_uids:
            _LOGGER.debug("Removing stale VALR sensor %s", entity.entity_id)
            entity_registry.async_remove(entity.entity_id)

    sensors: list[SensorEntity] = []
    for pair in spot_pairs:
        uid = f"valr_spot_{pair}"
        if _can_add_price_sensor(entity_registry, config_entry.entry_id, uid):
            sensors.append(ValrPriceSensor(market_coordinator, pair, "spot"))
    for pair in futures_pairs:
        uid = f"valr_futures_{pair}"
        if _can_add_price_sensor(entity_registry, config_entry.entry_id, uid):
            sensors.append(ValrPriceSensor(market_coordinator, pair, "futures"))
    for subaccount_id in subaccounts:
        for currency in valuation_currencies:
            sensors.append(
                ValrBalanceSensor(
                    account_coordinator,
                    market_coordinator,
                    account_name,
                    config_entry.entry_id,
                    subaccount_id,
                    currency,
                )
            )

    async_add_entities(sensors)


def _entry_value(entry: ConfigEntry, key: str, default=None):
    """Return option value falling back to initial config data."""
    return entry.options.get(key, entry.data.get(key, default))


def _can_add_price_sensor(entity_registry, entry_id: str, unique_id: str) -> bool:
    """Return whether this entry can create or restore a shared price sensor."""
    entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    if entity_id is None:
        return True
    entity = entity_registry.async_get(entity_id)
    return bool(entity and entity.config_entry_id == entry_id)


def _slug(value: str) -> str:
    """Create a stable lowercase id fragment."""
    return str(value).lower().replace(" ", "_").replace("-", "_")


def _resolve_quote_asset(symbol: str) -> str | None:
    """Return the quote asset suffix for a pair symbol."""
    pair = symbol.removesuffix("PERP")
    for asset in QUOTE_ASSET_KEYS_SORTED:
        if pair.endswith(asset) and len(pair) > len(asset):
            return asset
    return None


def _to_float(value, default: float | None = None) -> float | None:
    """Safely convert API values to floats."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ValrPriceSensor(CoordinatorEntity, SensorEntity):
    """VALR spot or futures price sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, symbol: str, market_type: str) -> None:
        super().__init__(coordinator)
        self._symbol = symbol
        self._market_type = market_type
        self._attr_name = f"VALR {market_type.capitalize()} {symbol} Price"
        self._attr_unique_id = f"valr_{market_type}_{symbol}"

        quote = _resolve_quote_asset(symbol)
        info = QUOTE_ASSET_CONFIG.get(quote or "")
        if info:
            self._attr_native_unit_of_measurement = info.unit
            self._attr_icon = info.icon
            if info.unit in FIAT_UNITS:
                self._attr_device_class = SensorDeviceClass.MONETARY
        else:
            self._attr_icon = "mdi:chart-line"

    @property
    def _symbol_data(self) -> dict | None:
        data = self.coordinator.data or {}
        return data.get(MARKET_DATA, {}).get(self._symbol)

    @property
    def available(self) -> bool:
        return super().available and self._symbol_data is not None

    @property
    def native_value(self):
        data = self._symbol_data
        if not data:
            return None
        return _to_float(data.get("lastTradedPrice") or data.get("markPrice"))

    @property
    def extra_state_attributes(self) -> dict:
        data = self._symbol_data
        if not data:
            return {}
        return {
            "daily_change_percent": _to_float(data.get("changeFromPrevious")),
            "high_price_24h": _to_float(data.get("highPrice")),
            "low_price_24h": _to_float(data.get("lowPrice")),
            "ask_price": _to_float(data.get("askPrice")),
            "bid_price": _to_float(data.get("bidPrice")),
            "mark_price": _to_float(data.get("markPrice")),
            "base_volume": _to_float(data.get("baseVolume")),
            "quote_volume": _to_float(data.get("quoteVolume")),
            "created": data.get("created"),
        }

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, f"valr_{self._market_type}_market")},
            "name": f"VALR {self._market_type.capitalize()} Market",
            "manufacturer": "VALR",
            "model": "Market Summary",
        }


class ValrBalanceSensor(CoordinatorEntity, SensorEntity):
    """VALR subaccount balance valued in a target currency."""

    _attr_state_class = SensorStateClass.TOTAL

    _attr_icon = "mdi:wallet"


    def __init__(
        self,
        account_coordinator,
        market_coordinator,
        account_name: str,
        entry_id: str,
        subaccount_id: str,
        currency: str,
    ) -> None:
        super().__init__(account_coordinator)
        self._market_coordinator = market_coordinator
        self._account_name = account_name
        self._entry_id = entry_id
        self._subaccount_id = subaccount_id
        self._currency = currency

        subaccount_name = self._subaccount_name
        self._attr_name = f"VALR {account_name} {subaccount_name} Balance {currency}"
        self._attr_unique_id = (
            f"valr_balance_{entry_id}_{_slug(subaccount_id)}_{currency.lower()}"
        )
        self._attr_native_unit_of_measurement = "USD" if currency == "USDC" else currency
        if self._attr_native_unit_of_measurement in FIAT_UNITS:
            self._attr_device_class = SensorDeviceClass.MONETARY
        if currency == "BTC":
            self._attr_icon = "mdi:bitcoin"
        elif currency in {"USDC", "ZAR"}:
            self._attr_icon = "mdi:cash"

    @property
    def _subaccount_data(self) -> dict | None:
        data = self.coordinator.data or {}
        return data.get(BALANCE_DATA, {}).get(self._subaccount_id)

    @property
    def _subaccount_name(self) -> str:
        data = self._subaccount_data
        if data:
            return data.get("name", self._subaccount_id)
        return "Primary" if self._subaccount_id == PRIMARY_SUBACCOUNT_ID else self._subaccount_id

    @property
    def available(self) -> bool:
        return super().available and self._subaccount_data is not None

    @property
    def native_value(self):
        data = self._subaccount_data
        market_data = (self._market_coordinator.data or {}).get(MARKET_DATA, {})
        if not data:
            return None
        total, _ = _value_balances(data.get("balances", {}), self._currency, market_data)
        return round(total, 8 if self._currency == "BTC" else 2)

    @property
    def extra_state_attributes(self) -> dict:
        data = self._subaccount_data
        market_data = (self._market_coordinator.data or {}).get(MARKET_DATA, {})
        if not data:
            return {}
        balances = data.get("balances", {})
        _, included = _value_balances(balances, self._currency, market_data)
        attrs = {
            "subaccount_id": self._subaccount_id,
            "subaccount_name": self._subaccount_name,
            "included_currencies": sorted(included),
            "unpriced_currencies": sorted(set(balances) - included),
        }
        for currency, balance in sorted(balances.items()):
            attrs[f"{currency}_total"] = balance.get("total")
            attrs[f"{currency}_available"] = balance.get("available")
            attrs[f"{currency}_reserved"] = balance.get("reserved")
        return attrs

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, f"valr_account_{self._entry_id}")},
            "name": f"VALR {self._account_name}",
            "manufacturer": "VALR",
            "model": "Wallet Balances",
        }


def _value_balances(
    balances: dict[str, dict[str, float]], target: str, market_data: dict[str, dict]
) -> tuple[float, set[str]]:
    """Value a basket of balances in a target currency."""
    total = 0.0
    included: set[str] = set()
    for currency, balance in balances.items():
        amount = balance.get("total", 0.0)
        if amount == 0:
            included.add(currency)
            continue
        rate = _conversion_rate(currency, target, market_data)
        if rate is None:
            continue
        total += amount * rate
        included.add(currency)
    return total, included


def _conversion_rate(source: str, target: str, market_data: dict[str, dict]) -> float | None:
    """Resolve a direct or inverse conversion rate from VALR market summaries."""
    if source == target:
        return 1.0

    direct = market_data.get(f"{source}{target}")
    if direct:
        return _price_from_summary(direct)

    inverse = market_data.get(f"{target}{source}")
    if inverse:
        price = _price_from_summary(inverse)
        if price:
            return 1 / price
    return None


def _price_from_summary(summary: dict) -> float | None:
    """Return the best available conversion price from a market summary."""
    return _to_float(summary.get("markPrice")) or _to_float(summary.get("lastTradedPrice"))
