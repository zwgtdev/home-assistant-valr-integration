# VALR Integration for Home Assistant

<p align="center">
  <img src="custom_components/valr/valr-app-icon.png" alt="VALR" width="160">
</p>

Custom Home Assistant integration for VALR wallet balances and market prices.

## Features

- UI configuration flow for VALR API credentials.
- VALR One-Time Token (OTT) exchange flow for third-party integration setup.
- Select subaccounts from the Home Assistant UI.
- Balance sensors per selected subaccount in BTC, USDC, and/or ZAR equivalents.
- Select spot and perpetual futures pairs from the Home Assistant UI.
- Price sensors with daily change, 24-hour high/low, bid/ask, mark price, and volume attributes.
- Options flow for changing subaccounts, valuation currencies, pairs, and polling interval.

## Installation

Copy this repository into Home Assistant as a custom integration or install through HACS as a custom repository, then restart Home Assistant.

## Configuration

1. Go to **Settings** > **Devices & Services**.
2. Add the **VALR** integration.
3. Choose either VALR One-Time Token (OTT) or existing API credentials.
4. For OTT, enter the partner API key/secret and the `VALROT...` token. The integration exchanges the token and stores only the returned VALR API credentials.
5. Select subaccounts, valuation currencies, spot pairs, futures pairs, and update interval.

The integration uses VALR REST endpoints from `https://docs.valr.com`.

## HACS

This repository is structured as a HACS custom integration. Add it to HACS as a custom repository with category **Integration**.
