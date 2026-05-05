"""Config flow for the VALR integration."""

from __future__ import annotations

import logging
import time

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ValrApiClient, ValrApiError
from .const import (
    AUTH_METHOD_DIRECT,
    AUTH_METHOD_OTT,
    CONF_ACCOUNT_NAME,
    CONF_API_KEY,
    CONF_API_SECRET,
    CONF_AUTH_METHOD,
    CONF_FUTURES_PAIRS,
    CONF_OTT_TOKEN,
    CONF_PARTNER_API_KEY,
    CONF_PARTNER_API_SECRET,
    CONF_SPOT_PAIRS,
    CONF_SUBACCOUNTS,
    CONF_UPDATE_INTERVAL,
    CONF_VALUATION_CURRENCIES,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VALUATION_CURRENCIES,
    DOMAIN,
    VALUATION_CURRENCIES,
)

_LOGGER = logging.getLogger(__name__)
_symbol_cache: dict = {"spot": [], "futures": [], "ts": 0.0}
_CACHE_TTL = 300


async def _get_symbols(session: aiohttp.ClientSession) -> tuple[list[str], list[str]]:
    """Fetch and cache VALR spot and futures symbols."""
    now = time.monotonic()
    if _symbol_cache["ts"] > now - _CACHE_TTL and _symbol_cache["spot"]:
        return _symbol_cache["spot"], _symbol_cache["futures"]

    pairs = await ValrApiClient(session).pairs()
    symbols = sorted(
        str(item.get("currencyPair") or item.get("symbol"))
        for item in pairs
        if item.get("currencyPair") or item.get("symbol")
    )
    futures = [symbol for symbol in symbols if symbol.endswith("PERP")]
    spot = [symbol for symbol in symbols if not symbol.endswith("PERP")]
    _symbol_cache.update({"spot": spot, "futures": futures, "ts": now})
    return spot, futures


async def _validate_credentials(
    session: aiohttp.ClientSession, api_key: str, api_secret: str
) -> str | None:
    """Validate VALR credentials. Return a config-flow error key or None."""
    try:
        await ValrApiClient(session, api_key, api_secret).balances()
    except ValrApiError as err:
        message = str(err)
        if "401" in message or "403" in message:
            return "invalid_auth"
        return "cannot_connect"
    except aiohttp.ClientError:
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error validating VALR credentials")
        return "unknown"
    return None


async def _exchange_ott(
    session: aiohttp.ClientSession,
    partner_api_key: str,
    partner_api_secret: str,
    ott_token: str,
) -> tuple[dict | None, str | None]:
    """Exchange a VALR OTT for API credentials."""
    try:
        credentials = await ValrApiClient(
            session, partner_api_key, partner_api_secret
        ).exchange_ott(ott_token)
    except ValrApiError as err:
        message = str(err)
        if "404" in message or "-11281" in message:
            return None, "invalid_ott"
        if "401" in message or "403" in message:
            return None, "invalid_partner_auth"
        return None, "cannot_connect"
    except aiohttp.ClientError:
        return None, "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error exchanging VALR OTT")
        return None, "unknown"

    api_key = credentials.get("apiKey") or credentials.get(CONF_API_KEY)
    api_secret = credentials.get("apiSecret") or credentials.get(CONF_API_SECRET)
    if not api_key or not api_secret:
        return None, "invalid_ott_response"
    return {CONF_API_KEY: api_key, CONF_API_SECRET: api_secret}, None


class ValrConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for VALR."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}
        self._subaccount_choices: dict[str, str] = {}

    async def async_step_user(self, user_input=None):
        """Choose the VALR authentication method."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input[CONF_AUTH_METHOD] == AUTH_METHOD_OTT:
                return await self.async_step_ott()
            return await self.async_step_direct()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_AUTH_METHOD,
                        default=AUTH_METHOD_OTT,
                    ): vol.In(
                        {
                            AUTH_METHOD_OTT: "VALR One-Time Token (OTT)",
                            AUTH_METHOD_DIRECT: "Existing API key and secret",
                        }
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_direct(self, user_input=None):
        """Collect and validate direct VALR API credentials."""
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)

        if user_input is not None:
            error = await _validate_credentials(
                session, user_input[CONF_API_KEY], user_input[CONF_API_SECRET]
            )
            if error:
                errors["base"] = error
            else:
                self._data = {**user_input, CONF_AUTH_METHOD: AUTH_METHOD_DIRECT}
                client = ValrApiClient(
                    session, user_input[CONF_API_KEY], user_input[CONF_API_SECRET]
                )
                self._subaccount_choices = await client.subaccounts()
                return await self.async_step_markets()

        return self.async_show_form(
            step_id="direct",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT_NAME): str,
                    vol.Required(CONF_API_KEY): str,
                    vol.Required(CONF_API_SECRET): str,
                }
            ),
            errors=errors,
        )

    async def async_step_ott(self, user_input=None):
        """Collect a VALR OTT and exchange it for API credentials."""
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)

        if user_input is not None:
            credentials, error = await _exchange_ott(
                session,
                user_input[CONF_PARTNER_API_KEY],
                user_input[CONF_PARTNER_API_SECRET],
                user_input[CONF_OTT_TOKEN],
            )
            if error:
                errors["base"] = error
            else:
                assert credentials is not None
                error = await _validate_credentials(
                    session, credentials[CONF_API_KEY], credentials[CONF_API_SECRET]
                )
                if error:
                    errors["base"] = error
                else:
                    self._data = {
                        CONF_ACCOUNT_NAME: user_input[CONF_ACCOUNT_NAME],
                        CONF_API_KEY: credentials[CONF_API_KEY],
                        CONF_API_SECRET: credentials[CONF_API_SECRET],
                        CONF_AUTH_METHOD: AUTH_METHOD_OTT,
                    }
                    client = ValrApiClient(
                        session,
                        credentials[CONF_API_KEY],
                        credentials[CONF_API_SECRET],
                    )
                    self._subaccount_choices = await client.subaccounts()
                    return await self.async_step_markets()

        return self.async_show_form(
            step_id="ott",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT_NAME): str,
                    vol.Required(CONF_PARTNER_API_KEY): str,
                    vol.Required(CONF_PARTNER_API_SECRET): str,
                    vol.Required(CONF_OTT_TOKEN): str,
                }
            ),
            errors=errors,
        )

    async def async_step_markets(self, user_input=None):
        """Collect markets, subaccounts, and valuation options."""
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)

        if user_input is not None:
            data = {**self._data, **user_input}
            return self.async_create_entry(
                title=f"VALR ({data[CONF_ACCOUNT_NAME]})",
                data=data,
            )

        try:
            spot_symbols, futures_symbols = await _get_symbols(session)
        except (aiohttp.ClientError, ValrApiError):
            spot_symbols, futures_symbols = [], []
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error fetching VALR symbols")
            spot_symbols, futures_symbols = [], []
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="markets",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SUBACCOUNTS,
                        default=list(self._subaccount_choices),
                    ): cv.multi_select(self._subaccount_choices),
                    vol.Required(
                        CONF_VALUATION_CURRENCIES,
                        default=DEFAULT_VALUATION_CURRENCIES,
                    ): cv.multi_select(VALUATION_CURRENCIES),
                    vol.Optional(CONF_SPOT_PAIRS, default=[]): cv.multi_select(
                        spot_symbols
                    ),
                    vol.Optional(CONF_FUTURES_PAIRS, default=[]): cv.multi_select(
                        futures_symbols
                    ),
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=DEFAULT_UPDATE_INTERVAL,
                    ): vol.All(vol.Coerce(int), vol.Range(min=30)),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return ValrOptionsFlowHandler()


class ValrOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle VALR options."""

    async def async_step_init(self, user_input=None):
        """Update VALR options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        entry = self.config_entry
        session = async_get_clientsession(self.hass)
        client = ValrApiClient(
            session, entry.data[CONF_API_KEY], entry.data[CONF_API_SECRET]
        )

        try:
            spot_symbols, futures_symbols = await _get_symbols(session)
            subaccount_choices = await client.subaccounts()
        except (aiohttp.ClientError, ValrApiError):
            return self.async_abort(reason="cannot_connect")
        except Exception:
            _LOGGER.exception("Unexpected error preparing VALR options")
            return self.async_abort(reason="unknown")

        current_subaccounts = entry.options.get(
            CONF_SUBACCOUNTS, entry.data.get(CONF_SUBACCOUNTS, list(subaccount_choices))
        )
        current_currencies = entry.options.get(
            CONF_VALUATION_CURRENCIES,
            entry.data.get(CONF_VALUATION_CURRENCIES, DEFAULT_VALUATION_CURRENCIES),
        )
        current_spot = entry.options.get(
            CONF_SPOT_PAIRS, entry.data.get(CONF_SPOT_PAIRS, [])
        )
        current_futures = entry.options.get(
            CONF_FUTURES_PAIRS, entry.data.get(CONF_FUTURES_PAIRS, [])
        )
        current_interval = entry.options.get(
            CONF_UPDATE_INTERVAL, entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SUBACCOUNTS,
                        default=current_subaccounts,
                    ): cv.multi_select(subaccount_choices),
                    vol.Required(
                        CONF_VALUATION_CURRENCIES,
                        default=current_currencies,
                    ): cv.multi_select(VALUATION_CURRENCIES),
                    vol.Optional(CONF_SPOT_PAIRS, default=current_spot): cv.multi_select(
                        spot_symbols
                    ),
                    vol.Optional(
                        CONF_FUTURES_PAIRS, default=current_futures
                    ): cv.multi_select(futures_symbols),
                    vol.Required(
                        CONF_UPDATE_INTERVAL, default=current_interval
                    ): vol.All(vol.Coerce(int), vol.Range(min=30)),
                }
            ),
        )
