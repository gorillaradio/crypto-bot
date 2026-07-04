import re

# base symbol -> lowercase match terms. Names are high-precision and always included.
# A bare ticker is added ONLY when it is not a common English word (BTC/ETH/XRP/…);
# ambiguous tickers (SOL/OP/NEAR/TON/UNI/LINK/DOT/…) are matched by name only.
# Extend this map as the universe grows; every new entry deserves a precision test.
COIN_TERMS: dict[str, list[str]] = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "ether", "eth"],
    "SOL": ["solana"],
    "XRP": ["xrp", "ripple"],
    "BNB": ["bnb"],
    "ADA": ["cardano", "ada"],
    "DOGE": ["dogecoin"],
    "AVAX": ["avalanche", "avax"],
    "LINK": ["chainlink"],
    "POL": ["polygon", "matic"],
    "DOT": ["polkadot"],
    "TRX": ["tron", "trx"],
    "LTC": ["litecoin", "ltc"],
    "SHIB": ["shiba inu", "shib"],
    "UNI": ["uniswap"],
    "ATOM": ["cosmos", "atom"],
    "XLM": ["stellar", "xlm"],
    "NEAR": ["near protocol"],
    "APT": ["aptos", "apt"],
    "ARB": ["arbitrum", "arb"],
    "OP": ["optimism"],
    "SUI": ["sui network"],
    "TON": ["toncoin"],
    "XMR": ["monero", "xmr"],
    "AAVE": ["aave"],
    "MKR": ["maker dao", "makerdao"],
    "INJ": ["injective"],
    "FIL": ["filecoin"],
    "HBAR": ["hedera", "hbar"],
}


def match_symbols(text: str) -> list[str]:
    t = (text or "").lower()
    hits: list[str] = []
    for base, terms in COIN_TERMS.items():
        for term in terms:
            if re.search(r"\b" + re.escape(term) + r"\b", t):
                hits.append(base)
                break
    return sorted(hits)
