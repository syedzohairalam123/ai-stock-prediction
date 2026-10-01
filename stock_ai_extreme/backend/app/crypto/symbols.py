"""
Symbol mapping + asset catalogue + industry taxonomy.

Providers disagree about symbols: Binance spot uses ``BTCUSDT``, CoinGecko uses
``bitcoin``, a user types ``BTC`` or ``BTC/USDT``. :class:`SymbolMappingService`
is the single place that reconciles them, so no other module ever assumes two
providers' symbols are identical (spec §51).

The industry classification is a **documented internal table** (spec §45) — the
value is stated here, with its basis, rather than inferred at runtime. It is
descriptive (what an asset *is*), not an opinion about its quality.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class AssetMapping:
    internal: str        # canonical internal symbol, e.g. "BTC"
    name: str
    display: str         # human display, e.g. "BTC/USDT"
    binance: Optional[str]    # Binance spot symbol (None = no USDT pair)
    coingecko_id: Optional[str]
    industry: str
    #: True when a real-time Binance stream is available for this asset.
    streaming: bool


#: Documented industry taxonomy. `basis` explains what qualifies an asset here.
INDUSTRY_TAXONOMY: Dict[str, Dict[str, str]] = {
    "Layer 1": {"label": "Layer 1", "basis": "Base settlement chain with its own consensus and native token."},
    "Layer 2": {"label": "Layer 2", "basis": "Scaling network settling to a Layer 1 (rollup/sidechain)."},
    "DeFi": {"label": "DeFi", "basis": "Decentralised finance protocol token (lending, DEX, derivatives)."},
    "Oracle": {"label": "Oracle", "basis": "Data-feed network supplying off-chain information on-chain."},
    "Interoperability": {"label": "Interoperability", "basis": "Cross-chain messaging / shared-security protocol."},
    "Infrastructure": {"label": "Infrastructure", "basis": "Storage, modular data availability or node infrastructure."},
    "AI": {"label": "AI", "basis": "Network whose core product is machine-learning compute, data or agents."},
    "Gaming": {"label": "Gaming", "basis": "Game platform or gaming ecosystem token."},
    "Meme": {"label": "Meme", "basis": "Community/meme asset with no protocol revenue claim."},
    "Payments": {"label": "Payments", "basis": "Chain or token positioned primarily as a payment rail."},
    "Exchange": {"label": "Exchange", "basis": "Native token of a centralised exchange."},
    "Stablecoins": {"label": "Stablecoins", "basis": "Fiat-pegged asset; price volatility is structurally low."},
}


def _a(internal, name, display, binance, coingecko_id, industry, streaming=True) -> AssetMapping:
    return AssetMapping(internal, name, display, binance, coingecko_id, industry, streaming)


#: Curated, documented catalogue. Keep it explicit — never generate symbols.
ASSET_CATALOG: tuple[AssetMapping, ...] = (
    _a("BTC", "Bitcoin", "BTC/USDT", "BTCUSDT", "bitcoin", "Layer 1"),
    _a("ETH", "Ethereum", "ETH/USDT", "ETHUSDT", "ethereum", "Layer 1"),
    _a("SOL", "Solana", "SOL/USDT", "SOLUSDT", "solana", "Layer 1"),
    _a("BNB", "BNB", "BNB/USDT", "BNBUSDT", "binancecoin", "Exchange"),
    _a("XRP", "XRP", "XRP/USDT", "XRPUSDT", "ripple", "Payments"),
    _a("ADA", "Cardano", "ADA/USDT", "ADAUSDT", "cardano", "Layer 1"),
    _a("AVAX", "Avalanche", "AVAX/USDT", "AVAXUSDT", "avalanche-2", "Layer 1"),
    _a("TRX", "TRON", "TRX/USDT", "TRXUSDT", "tron", "Layer 1"),
    _a("NEAR", "NEAR Protocol", "NEAR/USDT", "NEARUSDT", "near", "Layer 1"),
    _a("SUI", "Sui", "SUI/USDT", "SUIUSDT", "sui", "Layer 1"),
    _a("APT", "Aptos", "APT/USDT", "APTUSDT", "aptos", "Layer 1"),
    _a("ARB", "Arbitrum", "ARB/USDT", "ARBUSDT", "arbitrum", "Layer 2"),
    _a("OP", "Optimism", "OP/USDT", "OPUSDT", "optimism", "Layer 2"),
    _a("POL", "Polygon", "POL/USDT", "POLUSDT", "polygon-ecosystem-token", "Layer 2"),
    _a("IMX", "Immutable", "IMX/USDT", "IMXUSDT", "immutable-x", "Layer 2"),
    _a("LINK", "Chainlink", "LINK/USDT", "LINKUSDT", "chainlink", "Oracle"),
    _a("DOT", "Polkadot", "DOT/USDT", "DOTUSDT", "polkadot", "Interoperability"),
    _a("ATOM", "Cosmos", "ATOM/USDT", "ATOMUSDT", "cosmos", "Interoperability"),
    _a("TIA", "Celestia", "TIA/USDT", "TIAUSDT", "celestia", "Infrastructure"),
    _a("FIL", "Filecoin", "FIL/USDT", "FILUSDT", "filecoin", "Infrastructure"),
    _a("UNI", "Uniswap", "UNI/USDT", "UNIUSDT", "uniswap", "DeFi"),
    _a("AAVE", "Aave", "AAVE/USDT", "AAVEUSDT", "aave", "DeFi"),
    _a("INJ", "Injective", "INJ/USDT", "INJUSDT", "injective-protocol", "DeFi"),
    _a("FET", "Artificial Superintelligence", "FET/USDT", "FETUSDT", "fetch-ai", "AI"),
    _a("RNDR", "Render", "RNDR/USDT", "RENDERUSDT", "render-token", "AI"),
    _a("SAND", "The Sandbox", "SAND/USDT", "SANDUSDT", "the-sandbox", "Gaming"),
    _a("AXS", "Axie Infinity", "AXS/USDT", "AXSUSDT", "axie-infinity", "Gaming"),
    _a("DOGE", "Dogecoin", "DOGE/USDT", "DOGEUSDT", "dogecoin", "Meme"),
    _a("SHIB", "Shiba Inu", "SHIB/USDT", "SHIBUSDT", "shiba-inu", "Meme"),
    _a("LTC", "Litecoin", "LTC/USDT", "LTCUSDT", "litecoin", "Payments"),
    _a("USDC", "USD Coin", "USDC/USDT", "USDCUSDT", "usd-coin", "Stablecoins"),
)


class SymbolError(ValueError):
    """Raised for a symbol that is not in the documented catalogue."""


class SymbolMappingService:
    """One resolver for every provider's symbol convention."""

    def __init__(self, catalog: tuple[AssetMapping, ...] = ASSET_CATALOG) -> None:
        self._by_internal: Dict[str, AssetMapping] = {a.internal: a for a in catalog}
        # Accept several user/provider spellings and normalize to the internal id.
        self._aliases: Dict[str, str] = {}
        for asset in catalog:
            self._aliases[asset.internal.upper()] = asset.internal
            self._aliases[asset.display.upper()] = asset.internal
            if asset.binance:
                self._aliases[asset.binance.upper()] = asset.internal
            if asset.coingecko_id:
                self._aliases[asset.coingecko_id.upper()] = asset.internal
        # Common quote-suffixed spellings for streaming assets.
        for asset in catalog:
            if asset.binance:
                quote = asset.binance[len(asset.internal):]
                self._aliases.setdefault(f"{asset.internal}{quote}", asset.internal)
                self._aliases.setdefault(f"{asset.internal}/{quote}", asset.internal)

    # ------------------------------------------------------------------ query
    def resolve(self, symbol: str) -> AssetMapping:
        """Resolve any accepted spelling to its canonical mapping, or raise."""
        if not symbol or not symbol.strip():
            raise SymbolError("Symbol is required.")
        key = symbol.strip().upper()
        internal = self._aliases.get(key)
        if internal is None:
            raise SymbolError(f"Unsupported symbol {symbol!r}.")
        return self._by_internal[internal]

    def get(self, internal: str) -> Optional[AssetMapping]:
        return self._by_internal.get((internal or "").upper())

    def list_assets(self) -> List[Dict[str, object]]:
        return [self.to_dict(a) for a in self._by_internal.values()]

    def by_industry(self) -> Dict[str, List[str]]:
        grouped: Dict[str, List[str]] = {}
        for asset in self._by_internal.values():
            grouped.setdefault(asset.industry, []).append(asset.internal)
        return grouped

    def streaming_assets(self) -> List[AssetMapping]:
        return [a for a in self._by_internal.values() if a.streaming and a.binance]

    @staticmethod
    def to_dict(asset: AssetMapping) -> Dict[str, object]:
        return {
            "symbol": asset.internal,
            "name": asset.name,
            "display": asset.display,
            "binance_symbol": asset.binance,
            "coingecko_id": asset.coingecko_id,
            "industry": asset.industry,
            "streaming": asset.streaming,
        }


#: Process-wide singleton.
symbol_service = SymbolMappingService()
