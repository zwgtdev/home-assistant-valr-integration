"""Constants for the VALR integration."""

from dataclasses import dataclass

DOMAIN = "valr"
PLATFORMS = ["sensor"]

CONF_ACCOUNT_NAME = "account_name"
CONF_API_KEY = "api_key"
CONF_API_SECRET = "api_secret"
CONF_AUTH_METHOD = "auth_method"
CONF_SPOT_PAIRS = "spot_pairs"
CONF_FUTURES_PAIRS = "futures_pairs"
CONF_SUBACCOUNTS = "subaccounts"
CONF_VALUATION_CURRENCIES = "valuation_currencies"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_OTT_TOKEN = "ott_token"
CONF_PARTNER_API_KEY = "partner_api_key"
CONF_PARTNER_API_SECRET = "partner_api_secret"

AUTH_METHOD_DIRECT = "direct"
AUTH_METHOD_OTT = "ott"

DEFAULT_UPDATE_INTERVAL = 60
DEFAULT_VALUATION_CURRENCIES = ["BTC", "USDC", "ZAR"]

API_URL = "https://api.valr.com"
SHARED_KEY = "_shared"

MARKET_DATA = "market_data"
BALANCE_DATA = "balance_data"
BALANCE_ERRORS = "balance_errors"

PRIMARY_SUBACCOUNT_ID = "primary"
PRIMARY_SUBACCOUNT_NAME = "Primary"

VALUATION_CURRENCIES = ["BTC", "USDC", "ZAR"]


@dataclass(frozen=True)
class QuoteAssetInfo:
    """Display unit and icon for a quote asset."""

    unit: str
    icon: str


QUOTE_ASSET_CONFIG: dict[str, QuoteAssetInfo] = {
    "BTC": QuoteAssetInfo("BTC", "mdi:bitcoin"),
    "USDC": QuoteAssetInfo("USD", "mdi:currency-usd"),
    "USDT": QuoteAssetInfo("USD", "mdi:currency-usd"),
    "ZAR": QuoteAssetInfo("ZAR", "mdi:cash"),
    "USD": QuoteAssetInfo("USD", "mdi:currency-usd"),
    "ETH": QuoteAssetInfo("ETH", "mdi:ethereum"),
}

QUOTE_ASSET_KEYS_SORTED = sorted(QUOTE_ASSET_CONFIG, key=len, reverse=True)
FIAT_UNITS = {"USD", "ZAR"}
