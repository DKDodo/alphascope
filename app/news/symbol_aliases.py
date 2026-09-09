"""Static symbol -> company-name-alias mapping used to filter news headlines
down to ones that actually mention the company, before they count toward a
trading decision (see app/news/relevance.py). Yahoo Finance attributes a lot
of headlines to a symbol that never mention the company by name -- general
market/macro noise, another company's story, or a CEO tangent (see
AutoTraderService._passes_news_sentiment for the empirical finding this
addresses) -- and most real headlines about a company use its name, not its
ticker, so ticker-only matching would miss almost everything.

Curation rule for anyone extending this map: prefer the full/common company
name(s). Only add the bare ticker itself as an alias when it is unambiguous
-- NOT when it's 1-2 characters (too weak a signal even with word-boundary
matching, e.g. "V"/"T"/"MA"/"GE") and NOT when it collides with a common
English word or acronym (deliberately omitted for exactly this reason:
LOW/Lowe's, COST/Costco, COP/ConocoPhillips, CRM/Salesforce, CAT/Caterpillar,
BA/Boeing -- collides with "British Airways" -- DOGE/Dogecoin -- collides
with "Department of Government Efficiency" -- SOL/Solana, ADA/Cardano -- a
common first name). Matching is case-insensitive, word-boundary (same
approach as keyword_sentiment.py), so "Meta" won't match inside "Metaverse"
-- but it can't distinguish "Palantir vs. Tesla: Which AI Stock Should You
Buy?" from a headline truly about Tesla; that's an accepted, minor residual
imprecision.

A symbol absent from this map (e.g. a user-added GLOBAL_SYMBOLS ticker via
.env) has no entry here -- callers must fail open, not fail closed -- see
relevance.py's evaluate_relevant_sentiment().
"""
from __future__ import annotations

SYMBOL_NAME_ALIASES: dict[str, list[str]] = {
    # -- Global (GLOBAL_SYMBOLS, app/config.py) --------------------------------
    "AAPL": ["Apple", "AAPL"],
    "MSFT": ["Microsoft", "MSFT"],
    "NVDA": ["Nvidia", "NVDA"],
    "GOOGL": ["Google", "Alphabet", "GOOGL"],
    "AMZN": ["Amazon", "AMZN"],
    "META": ["Meta Platforms", "Meta", "Facebook"],
    "AMD": ["Advanced Micro Devices", "AMD"],
    "ORCL": ["Oracle", "ORCL"],
    "CRM": ["Salesforce"],
    "ADBE": ["Adobe", "ADBE"],
    "INTC": ["Intel", "INTC"],
    "CSCO": ["Cisco", "CSCO"],
    "NFLX": ["Netflix", "NFLX"],
    "DIS": ["Disney", "Walt Disney"],
    "TMUS": ["T-Mobile", "TMUS"],
    "JPM": ["JPMorgan", "JP Morgan", "Chase", "JPM"],
    "V": ["Visa"],
    "MA": ["Mastercard"],
    "BAC": ["Bank of America", "BofA", "BAC"],
    "WFC": ["Wells Fargo", "WFC"],
    "GS": ["Goldman Sachs"],
    "MS": ["Morgan Stanley"],
    "JNJ": ["Johnson & Johnson", "Johnson and Johnson", "JNJ"],
    "UNH": ["UnitedHealth", "UNH"],
    "PFE": ["Pfizer", "PFE"],
    "ABBV": ["AbbVie", "ABBV"],
    "MRK": ["Merck", "MRK"],
    "WMT": ["Walmart", "WMT"],
    "PG": ["Procter & Gamble", "Procter and Gamble"],
    "KO": ["Coca-Cola", "Coca Cola"],
    "PEP": ["PepsiCo", "Pepsi"],
    "COST": ["Costco"],
    "HD": ["Home Depot"],
    "MCD": ["McDonald's", "McDonalds", "MCD"],
    "NKE": ["Nike", "NKE"],
    "TSLA": ["Tesla", "TSLA"],
    "BA": ["Boeing"],
    "CAT": ["Caterpillar"],
    "GE": ["General Electric", "GE Aerospace"],
    "XOM": ["Exxon", "ExxonMobil", "Exxon Mobil", "XOM"],
    "CVX": ["Chevron", "CVX"],
    "COP": ["ConocoPhillips"],
    "VZ": ["Verizon", "VZ"],
    "T": ["AT&T"],
    "UBER": ["Uber"],
    "PYPL": ["PayPal", "PYPL"],
    "SBUX": ["Starbucks", "SBUX"],
    "LOW": ["Lowe's", "Lowes"],
    "TXN": ["Texas Instruments", "TXN"],
    "QCOM": ["Qualcomm", "QCOM"],
    # -- BIST (BIST_SYMBOLS, app/config.py) ------------------------------------
    "AEFES": ["Anadolu Efes", "Efes", "AEFES"],
    "AKBNK": ["Akbank", "AKBNK"],
    "ASELS": ["Aselsan", "ASELS"],
    "ASTOR": ["Astor Enerji", "Astor", "ASTOR"],
    "BIMAS": ["BİM", "BIM", "Bim Birleşik Mağazalar", "BIMAS"],
    "DSTKF": ["Destek Finans Faktoring", "Destek Faktoring", "DSTKF"],
    "EKGYO": ["Emlak Konut", "Emlak Konut GYO", "EKGYO"],
    "ENKAI": ["Enka İnşaat", "Enka Insaat", "Enka", "ENKAI"],
    "EREGL": ["Ereğli Demir Çelik", "Eregli Demir Celik", "Erdemir", "EREGL"],
    "FROTO": ["Ford Otosan", "FROTO"],
    "GARAN": ["Garanti BBVA", "Garanti Bankası", "Garanti Bankasi", "Garanti", "GARAN"],
    "GUBRF": ["Gübre Fabrikaları", "Gubre Fabrikalari", "GUBRF"],
    "ISCTR": ["İş Bankası", "Is Bankasi", "Türkiye İş Bankası", "İşbank", "Isbank", "ISCTR"],
    "KCHOL": ["Koç Holding", "Koc Holding", "KCHOL"],
    "KRDMD": ["Kardemir", "KRDMD"],
    "MGROS": ["Migros", "MGROS"],
    "PETKM": ["Petkim", "PETKM"],
    "PGSUS": ["Pegasus Hava Taşımacılığı", "Pegasus", "PGSUS"],
    "SAHOL": ["Sabancı Holding", "Sabanci Holding", "SAHOL"],
    "SASA": ["SASA Polyester", "SASA"],
    "SISE": ["Şişecam", "Sisecam", "SISE"],
    "TAVHL": ["TAV Havalimanları", "TAV Havalimanlari", "TAV Airports", "TAV", "TAVHL"],
    "TCELL": ["Turkcell", "TCELL"],
    "THYAO": ["Türk Hava Yolları", "Turk Hava Yollari", "Turkish Airlines", "THY", "THYAO"],
    "TOASO": ["Tofaş", "Tofas", "TOASO"],
    "TRALT": ["Türk Altın İşletmeleri", "Turk Altin Isletmeleri", "TRALT"],
    "TTKOM": ["Türk Telekom", "Turk Telekom", "TTKOM"],
    "TUPRS": ["Tüpraş", "Tupras", "TUPRS"],
    "VAKBN": ["VakıfBank", "Vakifbank", "Vakıf Bank", "VAKBN"],
    "YKBNK": ["Yapı Kredi", "Yapi Kredi", "YapıKredi", "YKBNK"],
    # -- Crypto (CRYPTO_SYMBOLS, app/config.py) --------------------------------
    "BTC": ["Bitcoin", "BTC"],
    "ETH": ["Ethereum", "Ether", "ETH"],
    "BNB": ["Binance Coin", "BNB"],
    "SOL": ["Solana"],
    "XRP": ["Ripple", "XRP"],
    "ADA": ["Cardano"],
    "DOGE": ["Dogecoin"],
    "AVAX": ["Avalanche", "AVAX"],
}
