"""
config.py — Carga segura de variables de entorno
"""
import os
import pathlib

# Auto-cargar config.env antes de cualquier otra cosa
_env = pathlib.Path(__file__).parent / "config.env"
if _env.exists():
    for _l in _env.read_text().splitlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l and not _l.startswith("sed"):
            _k, _v = _l.split("=", 1)
            _k = _k.strip()
            _v = _v.split("#")[0].strip()
            os.environ[_k] = _v  # forzar, no setdefault

def _get(key, default=None, required=False):
    val = os.environ.get(key, default)
    if required and not val:
        raise EnvironmentError(f"❌ Variable requerida no encontrada: {key}")
    return val

# Telegram
TELEGRAM_TOKEN   = _get("TELEGRAM_TOKEN",   required=True)
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID", required=True)
# Binance
BINANCE_API_KEY    = _get("BINANCE_API_KEY",    required=True)
BINANCE_SECRET_KEY = _get("BINANCE_SECRET_KEY", required=True)
# Estrategia BTC
CAPITAL_USDT        = float(_get("CAPITAL_USDT",         "100.0"))
GANANCIA_OBJETIVO   = float(_get("GANANCIA_OBJETIVO_PCT", "1.0"))
STOP_LOSS_PCT       = float(_get("STOP_LOSS_PCT",         "0.8"))
BAJADA_COMPRA_PCT   = float(_get("BAJADA_COMPRA_PCT",     "0.6"))
CONFIRMA_REBOTE_PCT = float(_get("CONFIRMA_REBOTE_PCT",   "0.2"))
INTERVALO_SEGUNDOS  = int(_get("INTERVALO_SEGUNDOS",      "10"))
# Order Book
ORDERBOOK_RATIO = float(_get("ORDERBOOK_RATIO", "1.3"))
# Modo
PAPER_TRADING = _get("PAPER_TRADING", "true").lower() == "true"
# Par principal
PAR_BTC = "BTCUSDT"
# Indicadores
RSI_PERIODO      = int(_get("RSI_PERIODO",    "14"))
RSI_INTERVALO    = _get("RSI_INTERVALO",      "15m")
RSI_SOBREVENTA   = float(_get("RSI_SOBREVENTA",  "45"))
RSI_SOBRECOMPRA  = float(_get("RSI_SOBRECOMPRA", "70"))
TRAILING_PCT     = float(_get("TRAILING_PCT",    "0.3"))
ATR_PERIODO      = int(_get("ATR_PERIODO",   "14"))
EMA_RAPIDA       = int(_get("EMA_RAPIDA",    "50"))
EMA_LENTA        = int(_get("EMA_LENTA",     "200"))
EMA_INTERVALO    = _get("EMA_INTERVALO",     "15m")
REBOTE_ACTIVO    = _get("REBOTE_ACTIVO",     "true").lower() == "true"
