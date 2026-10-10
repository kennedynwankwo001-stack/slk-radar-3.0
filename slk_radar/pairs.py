"""The 23 forex pairs the radar scans."""

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "AUDNZD", "AUDCAD", "NZDCAD", "AUDCHF", "CADCHF",
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPNZD", "GBPCAD",
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURNZD", "EURCAD",
]


def td_symbol(pair: str) -> str:
    """EURUSD -> EUR/USD (the Twelve Data symbol)."""
    p = pair.replace("/", "").upper()
    return f"{p[:3]}/{p[3:]}"
