"""
india_earnings_dashboard.py
----------------------------
Fetches real earnings data (today / tomorrow / this week) for the FULL live
NIFTY 200 (India) and S&P 500 (USA) constituent lists — pulled fresh on
every run from NSE's archives and Wikipedia respectively, sector-mapped
automatically, no manual ticker maintenance needed — using Yahoo Finance
(via the free `yfinance` library), and renders it into an interactive HTML
dashboard with an India/USA tab toggle (sticky ticker header, sector
filters, horizontal cards, sparklines, surprise heatmap, etc.)

If you'd rather scan a small curated list instead of the full ~700-ticker
universe (e.g. for a quick test run), set USE_FULL_NIFTY200=false and/or
USE_FULL_SP500=false as environment variables — see section 1c below.

Install requirements first:
    pip install yfinance pandas lxml

Run:
    python india_earnings_dashboard.py

Output:
    docs/index.html   <-- open this in a browser, or serve via GitHub Pages
    (fixed filename, overwritten on every run — plays nicely with git and
    with GitHub Pages, which can publish this folder directly)

TELEGRAM ALERTS:
  After each run, a message listing every company reporting earnings
  TOMORROW (India + USA) is sent to a Telegram chat via a bot.
  Credentials are read in this order:
    1. Environment variables — TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
       TELEGRAM_ENABLED, TELEGRAM_MARKETS. This is how GitHub Actions
       secrets reach the script in CI (see README / workflow file).
    2. telegram_config.py (a separate file, next to this script) — a
       local fallback for running on your own machine.
  If credentials are missing, still placeholders, or TELEGRAM_ENABLED is
  not truthy, the alert is silently skipped (the HTML dashboard is still
  generated as normal).

NOTE ON DATA COVERAGE (please read):
  Yahoo Finance's free data does NOT reliably provide:
    - Promoter holding %          -> shown as "Not available"
    - Pre-market / Post-market flag for the result -> shown as "Not specified"
  Everything else (EPS estimate/actual, revenue estimate/actual, surprise %,
  last-4-quarter EPS trend, 7-day price sparkline, market cap category,
  RSI, Fibonacci zone) is pulled live, for both the India and USA tabs.
"""

import csv
import io
import json
import os
import time
import datetime
import html
import urllib.request
import urllib.parse
import urllib.error
import yfinance as yf

# Toggle whether to pull the FULL live NIFTY 200 / S&P 500 constituent
# lists at runtime (recommended) or fall back to the small curated lists
# further down this file. Override via env vars if you want a quick/small
# run (e.g. while testing), or if the live sources are ever unreachable
# from your network:
#   USE_FULL_NIFTY200=false
#   USE_FULL_SP500=false
USE_FULL_NIFTY200 = os.environ.get("USE_FULL_NIFTY200", "true").strip().lower() in ("1", "true", "yes", "on")
USE_FULL_SP500 = os.environ.get("USE_FULL_SP500", "true").strip().lower() in ("1", "true", "yes", "on")

try:
    import telegram_config as tg_cfg
except ImportError:
    tg_cfg = None

# ---------------------------------------------------------------------
# 1. COMPANY LIST — edit freely. `sector` must be one of the 6 categories
#    below (or "Other") so it maps to the dashboard's color system.
#    ticker suffix: .NS = NSE, .BO = BSE
# ---------------------------------------------------------------------

SECTOR_COLORS = {
    "Technology": "#4C8DFF",
    "Energy":     "#F5A524",
    "Banking":    "#2BB673",
    "FMCG":       "#A78BFA",
    "Automobile": "#C1440E",
    "Pharma":     "#2DD4BF",
    "Other":      "#8B96A6",
}

INDIA_COMPANIES = [
    {"ticker": "TCS.NS",        "sector": "Technology"},
    {"ticker": "INFY.NS",       "sector": "Technology"},
    {"ticker": "HCLTECH.NS",    "sector": "Technology"},
    {"ticker": "WIPRO.NS",      "sector": "Technology"},
    {"ticker": "RELIANCE.NS",   "sector": "Energy"},
    {"ticker": "ONGC.NS",       "sector": "Energy"},
    {"ticker": "HDFCBANK.NS",   "sector": "Banking"},
    {"ticker": "ICICIBANK.NS",  "sector": "Banking"},
    {"ticker": "SBIN.NS",       "sector": "Banking"},
    {"ticker": "KOTAKBANK.NS",  "sector": "Banking"},
    {"ticker": "HINDUNILVR.NS", "sector": "FMCG"},
    {"ticker": "ITC.NS",        "sector": "FMCG"},
    {"ticker": "TATAMOTORS.NS", "sector": "Automobile"},
    {"ticker": "MARUTI.NS",     "sector": "Automobile"},
    {"ticker": "SUNPHARMA.NS",  "sector": "Pharma"},
    {"ticker": "DRREDDY.NS",    "sector": "Pharma"},
]

# Add your own tickers here — just give a ticker + sector
# NOTE: entries already present in INDIA_COMPANIES above (INFY, WIPRO,
# HDFCBANK, KOTAKBANK, ITC, ICICIBANK, SBIN, ONGC, RELIANCE, HCLTECH,
# SUNPHARMA, MARUTI, DRREDDY, TCS, HINDUNILVR) were left out here to
# avoid duplicate cards.
CUSTOM_COMPANIES = [
    # ── Rank 1–10 ────────────────────────────────────────────
    {"ticker": "ADANIPOWER.NS", "sector": "Energy"},
    {"ticker": "ETERNAL.NS",    "sector": "Other"},
    {"ticker": "JIOFIN.NS",     "sector": "Banking"},
    {"ticker": "UNIONBANK.NS",  "sector": "Banking"},
    {"ticker": "TATASTEEL.NS",  "sector": "Other"},
    {"ticker": "VEDL.NS",       "sector": "Other"},
    # ── Rank 11–20 ───────────────────────────────────────────
    {"ticker": "CANBK.NS",      "sector": "Banking"},
    {"ticker": "COALINDIA.NS",  "sector": "Energy"},
    {"ticker": "IRFC.NS",       "sector": "Other"},
    {"ticker": "HINDZINC.NS",   "sector": "Other"},
    {"ticker": "VBL.NS",        "sector": "FMCG"},
    {"ticker": "ADANIGREEN.NS", "sector": "Energy"},
    # ── Rank 21–30 ───────────────────────────────────────────
    {"ticker": "BEL.NS",        "sector": "Other"},
    {"ticker": "PNB.NS",        "sector": "Banking"},
    {"ticker": "MOTHERSON.NS",  "sector": "Automobile"},
    {"ticker": "BPCL.NS",       "sector": "Energy"},
    {"ticker": "POWERGRID.NS",  "sector": "Energy"},
    {"ticker": "GAIL.NS",       "sector": "Energy"},
    {"ticker": "SHRIRAMFIN.NS", "sector": "Banking"},
    # ── Rank 31–40 ───────────────────────────────────────────
    {"ticker": "IOC.NS",        "sector": "Energy"},
    {"ticker": "PFC.NS",        "sector": "Banking"},
    {"ticker": "ADANIENSOL.NS", "sector": "Energy"},
    {"ticker": "BANKBARODA.NS", "sector": "Banking"},
    {"ticker": "TATAPOWER.NS",  "sector": "Energy"},
    {"ticker": "BHARTIARTL.NS", "sector": "Other"},
    {"ticker": "NTPC.NS",       "sector": "Energy"},
    {"ticker": "TATACAP.NS",    "sector": "Banking"},
    {"ticker": "TMPV.NS",       "sector": "Automobile"},
    # ── Rank 41–50 ───────────────────────────────────────────
    {"ticker": "SBILIFE.NS",    "sector": "Banking"},
    {"ticker": "RECLTD.NS",     "sector": "Banking"},
    {"ticker": "HINDALCO.NS",   "sector": "Other"},
    {"ticker": "TMCV.NS",       "sector": "Automobile"},
    {"ticker": "CIPLA.NS",      "sector": "Pharma"},
    {"ticker": "CGPOWER.NS",    "sector": "Other"},
    {"ticker": "BAJFINANCE.NS", "sector": "Banking"},
    {"ticker": "GODREJCP.NS",   "sector": "FMCG"},
    {"ticker": "AMBUJACEM.NS",  "sector": "Other"},
    # ── Rank 51–60 ───────────────────────────────────────────
    {"ticker": "TECHM.NS",      "sector": "Technology"},
    {"ticker": "AXISBANK.NS",   "sector": "Banking"},
    {"ticker": "NESTLEIND.NS",  "sector": "FMCG"},
    {"ticker": "HDFCLIFE.NS",   "sector": "Banking"},
    {"ticker": "MAXHEALTH.NS",  "sector": "Pharma"},
    {"ticker": "M&M.NS",        "sector": "Automobile"},
    {"ticker": "ADANIPORTS.NS", "sector": "Other"},
    {"ticker": "MAZDOCK.NS",    "sector": "Other"},
    {"ticker": "ADANIENT.NS",   "sector": "Other"},
    {"ticker": "INDHOTEL.NS",   "sector": "Other"},
    # ── Rank 61–70 ───────────────────────────────────────────
    {"ticker": "LT.NS",         "sector": "Other"},
    {"ticker": "DLF.NS",        "sector": "Other"},
    {"ticker": "JSWSTEEL.NS",   "sector": "Other"},
    {"ticker": "TRENT.NS",      "sector": "Other"},
    {"ticker": "LODHA.NS",      "sector": "Other"},
    {"ticker": "TATACONSUM.NS", "sector": "FMCG"},
    {"ticker": "CHOLAFIN.NS",   "sector": "Banking"},
    {"ticker": "JINDALSTEL.NS", "sector": "Other"},
    {"ticker": "GRASIM.NS",     "sector": "Other"},
    # ── Rank 71–80 ───────────────────────────────────────────
    {"ticker": "HYUNDAI.NS",    "sector": "Automobile"},
    {"ticker": "HDFCAMC.NS",    "sector": "Banking"},
    {"ticker": "UNITDSPR.NS",   "sector": "FMCG"},
    {"ticker": "TITAN.NS",      "sector": "Other"},
    {"ticker": "LTM.NS",        "sector": "Other"},
    {"ticker": "BAJAJFINSV.NS", "sector": "Banking"},
    {"ticker": "HAL.NS",        "sector": "Other"},
    {"ticker": "TVSMOTOR.NS",   "sector": "Automobile"},
    {"ticker": "INDIGO.NS",     "sector": "Other"},
    {"ticker": "ZYDUSLIFE.NS",  "sector": "Pharma"},
    # ── Rank 81–90 ───────────────────────────────────────────
    {"ticker": "MUTHOOTFIN.NS", "sector": "Banking"},
    {"ticker": "ENRIN.NS",      "sector": "Other"},
    {"ticker": "PIDILITIND.NS", "sector": "Other"},
    {"ticker": "CUMMINSIND.NS", "sector": "Other"},
    {"ticker": "BRITANNIA.NS",  "sector": "FMCG"},
    {"ticker": "ASIANPAINT.NS", "sector": "Other"},
    {"ticker": "EICHERMOT.NS",  "sector": "Automobile"},
    {"ticker": "APOLLOHOSP.NS", "sector": "Pharma"},
    {"ticker": "ULTRACEMCO.NS", "sector": "Other"},
    # ── Rank 91–100 ──────────────────────────────────────────
    {"ticker": "ABB.NS",        "sector": "Other"},
    {"ticker": "DIVISLAB.NS",   "sector": "Pharma"},
    {"ticker": "SIEMENS.NS",    "sector": "Other"},
    {"ticker": "SOLARINDS.NS",  "sector": "Other"},
    {"ticker": "TORNTPHARM.NS", "sector": "Pharma"},
    {"ticker": "DMART.NS",      "sector": "Other"},
    {"ticker": "BAJAJ-AUTO.NS", "sector": "Automobile"},
    {"ticker": "BAJAJHLDNG.NS", "sector": "Banking"},
    {"ticker": "BOSCHLTD.NS",   "sector": "Automobile"},
    {"ticker": "SHREECEM.NS",   "sector": "Other"},
    # ── Sector ETFs (BEES) ───────────────────────────────────
    # ETFs don't report company earnings, so these will typically be
    # skipped by fetch_company (no earnings-dates data) — left in for
    # completeness in case a future data source adds fund-level events.
    {"ticker": "NIFTYBEES.NS",  "sector": "Other"},
    {"ticker": "BANKBEES.NS",   "sector": "Other"},
    {"ticker": "ITBEES.NS",     "sector": "Other"},
    {"ticker": "AUTOBEES.NS",   "sector": "Other"},
    {"ticker": "PHARMABEES.NS", "sector": "Other"},
    {"ticker": "GOLDBEES.NS",   "sector": "Other"},
    {"ticker": "SILVERBEES.NS", "sector": "Other"},
]

# This ~100-company curated list is now only a FALLBACK, used if the live
# NIFTY 200 fetch (see fetch_nifty200_list() below) fails or is disabled via
# USE_FULL_NIFTY200=false.
ALL_COMPANIES_STATIC = INDIA_COMPANIES + CUSTOM_COMPANIES


# ---------------------------------------------------------------------
# 1b. USA COMPANY LIST — grouped by S&P sector-ETF ticker (XLK, XLF, …)
# ---------------------------------------------------------------------

USA_SECTOR_NAMES = {
    "XLK":   "Technology",
    "XLC":   "Communication Services",
    "XLY":   "Consumer Discretionary",
    "XLP":   "Consumer Staples",
    "XLV":   "Health Care",
    "XLF":   "Financials",
    "XLI":   "Industrials",
    "XLE":   "Energy",
    "XLB":   "Materials",
    "XLRE":  "Real Estate",
    "XLU":   "Utilities",
    "Other": "Other",
}

USA_SECTOR_COLORS = {
    "XLK":   "#4C8DFF",   # Technology
    "XLC":   "#8B5CF6",   # Communication Services
    "XLY":   "#F0554A",   # Consumer Discretionary
    "XLP":   "#34D399",   # Consumer Staples
    "XLV":   "#2DD4BF",   # Health Care
    "XLF":   "#22C55E",   # Financials
    "XLI":   "#F5A524",   # Industrials
    "XLE":   "#EAB308",   # Energy
    "XLB":   "#C1440E",   # Materials
    "XLRE":  "#FB923C",   # Real Estate
    "XLU":   "#60A5FA",   # Utilities
    "Other": "#8B96A6",
}

SECTOR_MAP = {
    **{s: "XLK" for s in [
        # Technology (16)
        "NVDA", "MSFT", "AAPL", "AVGO", "AMD", "ORCL", "ADBE", "PANW",
        "NOW", "SNPS", "CRM", "CSCO", "INTC", "QCOM", "AMAT", "LRCX",
        # Extras: SMCI, PLTR (added to the S&P 500 in Sept 2024 — was
        # previously missing from this curated list)
        "SMCI", "PLTR",
    ]},
    **{s: "XLC" for s in [
        # Communication Services (12)
        "GOOGL", "GOOG", "META", "NFLX", "CMCSA", "DIS",
        "TMUS", "VZ", "T", "CHTR", "SPOT", "RBLX",
    ]},
    **{s: "XLY" for s in [
        # Consumer Discretionary (13 — COST moved to Staples)
        "AMZN", "TSLA", "HD", "MCD", "TJX", "BKNG",
        "LOW", "SBUX", "NKE", "MAR", "ROST", "EBAY", "LULU",
    ]},
    **{s: "XLP" for s in [
        # Consumer Staples (10 — COST kept here as primary)
        "WMT", "PG", "KO", "PEP", "COST", "PM", "MO", "MDLZ", "CL", "MNST",
    ]},
    **{s: "XLV" for s in [
        # Health Care (16)
        "LLY", "UNH", "JNJ", "MRK", "ABBV", "TMO", "AMGN", "BMY",
        "GILD", "ISRG", "VRTX", "CVS", "CI", "MDT", "SYK", "REGN",
    ]},
    **{s: "XLF" for s in [
        # Financials (16)
        "JPM", "BAC", "MS", "GS", "V", "MA", "AXP", "BLK",
        "SPGI", "C", "WFC", "SCHW", "COF", "PGR", "CB", "MMC",
        # Extras: HOOD, SOFI
        "HOOD", "SOFI",
    ]},
    **{s: "XLI" for s in [
        # Industrials (15)
        "GE", "CAT", "UNP", "HON", "LMT", "UPS", "RTX", "DE",
        "FDX", "BA", "GEV", "ETN", "ADP", "FAST", "CTAS",
    ]},
    **{s: "XLE" for s in [
        # Energy (12 — NEE, SO, DUK, CEG, VST kept here as listed)
        "XOM", "CVX", "COP", "NEE", "SO", "DUK", "CEG", "VST",
        "SLB", "EOG", "KMI", "PSX",
    ]},
    **{s: "XLB" for s in [
        # Materials (8)
        "LIN", "FCX", "SHW", "NEM", "APD", "ECL", "NUE", "DOW",
    ]},
    **{s: "XLRE" for s in [
        # Real Estate (10)
        "PLD", "AMT", "EQIX", "DLR", "WELL", "SPG", "PSA", "O", "CBRE", "VTR",
    ]},
    **{s: "XLU" for s in [
        # Utilities (7 — SO/DUK/NEE deduplicated to XLE above)
        "EXC", "XEL", "AEP", "SRE", "D", "PEG", "WEC",
    ]},
}

# Also just a FALLBACK now — used if the live S&P 500 fetch (see
# fetch_sp500_list() below) fails or is disabled via USE_FULL_SP500=false.
ALL_COMPANIES_USA_STATIC = [{"ticker": t, "sector": s} for t, s in SECTOR_MAP.items()]


# ---------------------------------------------------------------------
# 1c. Live index-constituent fetchers (NIFTY 200 from NSE, S&P 500 from
#     Wikipedia). Both return None on any failure so the caller can fall
#     back to the static lists above — network hiccups or a source
#     changing its page/file layout should never crash the whole run.
# ---------------------------------------------------------------------

# NSE's own "Industry" classification (from the NIFTY 200 constituent
# file) mapped onto this dashboard's 6-category sector taxonomy. Anything
# not listed here (Capital Goods, Metals & Mining, Realty, Chemicals,
# Construction, Services, Telecommunication, Consumer Durables/Services,
# Textiles, etc.) falls into "Other".
NIFTY_INDUSTRY_TO_SECTOR = {
    "Information Technology": "Technology",
    "Oil Gas & Consumable Fuels": "Energy",
    "Power": "Energy",
    "Financial Services": "Banking",
    "Fast Moving Consumer Goods": "FMCG",
    "Automobile and Auto Components": "Automobile",
    "Healthcare": "Pharma",
}

# GICS Sector (as published on Wikipedia's S&P 500 constituent table) ->
# the matching SPDR Select Sector ETF ticker used throughout this dashboard.
GICS_SECTOR_TO_ETF = {
    "Information Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}


def fetch_nifty200_list():
    """Downloads the live NIFTY 200 constituent list straight from NSE's
    archives (columns: Company Name, Industry, Symbol, Series, ISIN Code)
    and maps each company onto our sector taxonomy. Returns None on any
    failure (network error, unexpected/short file, etc.) so main() can
    fall back to ALL_COMPANIES_STATIC."""
    url = "https://archives.nseindia.com/content/indices/ind_nifty200list.csv"
    req = urllib.request.Request(url, headers={
        # A plain urllib default User-Agent gets blocked by NSE's archives
        # host, so we ask for the CSV like a regular browser would.
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"),
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [nifty200] live fetch failed ({e}) — will use the static fallback list")
        return None

    try:
        reader = csv.DictReader(io.StringIO(raw))
        companies = []
        for row in reader:
            symbol = (row.get("Symbol") or "").strip()
            industry = (row.get("Industry") or "").strip()
            if not symbol or symbol.upper().startswith("DUMMY"):
                # NSE lists a few "Dummy ..." placeholder rows around
                # demergers/corporate actions — these aren't real tickers.
                continue
            sector = NIFTY_INDUSTRY_TO_SECTOR.get(industry, "Other")
            companies.append({"ticker": f"{symbol}.NS", "sector": sector})
    except Exception as e:
        print(f"  [nifty200] couldn't parse live CSV ({e}) — will use the static fallback list")
        return None

    if len(companies) < 150:
        print(f"  [nifty200] only parsed {len(companies)} rows (expected ~200) "
              "— will use the static fallback list")
        return None

    print(f"  [nifty200] using {len(companies)} live NIFTY 200 constituents")
    return companies


def fetch_sp500_list():
    """Downloads the live S&P 500 constituent table from Wikipedia and maps
    each company's GICS Sector onto the matching SPDR sector-ETF bucket.
    Returns None on any failure so main() can fall back to
    ALL_COMPANIES_USA_STATIC."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        import pandas as pd
        # Wikipedia's first table on that page is the constituent list:
        # Symbol | Security | GICS Sector | GICS Sub-Industry | ...
        df = pd.read_html(url)[0]
        companies = []
        for _, row in df.iterrows():
            # Yahoo Finance uses a hyphen where Wikipedia uses a dot for
            # dual-class tickers, e.g. BRK.B -> BRK-B, BF.B -> BF-B.
            symbol = str(row["Symbol"]).strip().replace(".", "-")
            gics = str(row["GICS Sector"]).strip()
            sector = GICS_SECTOR_TO_ETF.get(gics, "Other")
            companies.append({"ticker": symbol, "sector": sector})
    except Exception as e:
        print(f"  [sp500] live fetch failed ({e}) — will use the static fallback list")
        return None

    if len(companies) < 400:
        print(f"  [sp500] only parsed {len(companies)} rows (expected ~500) "
              "— will use the static fallback list")
        return None

    # Belt-and-braces: make sure PLTR is present even if Wikipedia's table
    # layout hiccups on a given run, since it's the ticker that prompted
    # this fallback logic in the first place.
    if not any(c["ticker"] == "PLTR" for c in companies):
        companies.append({"ticker": "PLTR", "sector": "XLK"})

    print(f"  [sp500] using {len(companies)} live S&P 500 constituents")
    return companies


def build_india_universe():
    """Returns the list of {ticker, sector} dicts to scan for India, live
    NIFTY 200 constituents by default, falling back to the static list."""
    if USE_FULL_NIFTY200:
        live = fetch_nifty200_list()
        if live:
            return live
    return ALL_COMPANIES_STATIC


def build_usa_universe():
    """Returns the list of {ticker, sector} dicts to scan for the USA, live
    S&P 500 constituents by default, falling back to the static list."""
    if USE_FULL_SP500:
        live = fetch_sp500_list()
        if live:
            return live
    return ALL_COMPANIES_USA_STATIC


# ---------------------------------------------------------------------
# 2. Helpers
# ---------------------------------------------------------------------

def market_cap_category(market_cap):
    """Rough Large/Mid/Small split based on market cap in INR."""
    if market_cap is None:
        return "N/A"
    cr = market_cap / 1e7  # INR -> crore
    if cr >= 20000:
        return "Large"
    if cr >= 5000:
        return "Mid"
    return "Small"


def market_cap_category_us(market_cap):
    """Rough Large/Mid/Small split based on market cap in USD."""
    if market_cap is None:
        return "N/A"
    b = market_cap / 1e9  # USD -> billions
    if b >= 10:
        return "Large"
    if b >= 2:
        return "Mid"
    return "Small"


def to_crore(value):
    """Convert a raw currency figure to crore (₹1 Cr = 1e7)."""
    if value is None:
        return None
    return round(value / 1e7, 1)


def to_million_usd(value):
    """Convert a raw USD figure to millions (used for US revenue estimates)."""
    if value is None:
        return None
    return round(value / 1e6, 1)


def classify_when(earnings_date, today, tomorrow, week_end):
    if earnings_date == today:
        return "today"
    if earnings_date == tomorrow:
        return "tomorrow"
    if today < earnings_date <= week_end:
        return "week"
    return None


# ---------------------------------------------------------------------
# 3. Fetch data for one company
# ---------------------------------------------------------------------

def fetch_company(ticker, sector, today, tomorrow, week_end, market="IN", pause=0.4):
    try:
        tk = yf.Ticker(ticker)

        edf = tk.get_earnings_dates(limit=12)
        if edf is None or edf.empty:
            print(f"  [--] {ticker}: yfinance returned no earnings-dates data at all")
            return None
        edf = edf.sort_index()

        # Upcoming earnings row within our window (today..week_end)
        upcoming_rows = [
            (idx.date(), row) for idx, row in edf.iterrows()
            if classify_when(idx.date(), today, tomorrow, week_end) is not None
        ]
        if not upcoming_rows:
            future_dates = [idx.date() for idx in edf.index if idx.date() >= today]
            nearest = min(future_dates) if future_dates else None
            if nearest:
                print(f"  [--] {ticker}: nearest upcoming earnings date is {nearest} "
                      f"(outside the {today}..{week_end} window)")
            else:
                print(f"  [--] {ticker}: no future earnings date found "
                      f"(latest on record is {edf.index.max().date()})")
            return None
        earn_date, earn_row = upcoming_rows[0]
        when = classify_when(earn_date, today, tomorrow, week_end)

        # Past reported rows (for last-quarter actuals + 4-quarter trend)
        past = edf[edf["Reported EPS"].notna()].sort_index(ascending=False)
        last4_eps = list(past["Reported EPS"].head(4).iloc[::-1]) if not past.empty else []
        last_actual_eps = past["Reported EPS"].iloc[0] if not past.empty else None
        last_estimate_eps = past["EPS Estimate"].iloc[0] if not past.empty else None
        surprise = None
        if last_actual_eps is not None and last_estimate_eps not in (None, 0):
            surprise = round((last_actual_eps - last_estimate_eps) / abs(last_estimate_eps) * 100, 1)

        # Company info (name, exchange, market cap)
        info = {}
        try:
            info = tk.get_info()
        except Exception:
            pass

        if market == "US":
            currency = "$"
            exch_code = (info.get("exchange") or "").upper()
            exch = {
                "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ",
                "NYQ": "NYSE", "ASE": "NYSE American", "PCX": "NYSE Arca",
                "BATS": "BATS",
            }.get(exch_code, exch_code or "US")
            cap_cat = market_cap_category_us(info.get("marketCap"))
            sector_key = sector if sector in USA_SECTOR_COLORS else "Other"
        else:
            currency = "₹"
            exch = "BSE" if ticker.upper().endswith(".BO") else "NSE"
            cap_cat = market_cap_category(info.get("marketCap"))
            sector_key = sector if sector in SECTOR_COLORS else "Other"

        # Revenue estimate (best effort, from calendar)
        rev_est = None
        try:
            cal = tk.calendar or {}
            raw_rev = cal.get("Revenue Average")
            rev_est = to_million_usd(raw_rev) if market == "US" else to_crore(raw_rev)
        except Exception:
            pass

        # 7-day price history for sparkline
        spark = []
        try:
            # dropna() removes the still-forming "today" candle, which
            # yfinance often returns as NaN before the session closes.
            hist = tk.history(period="10d")["Close"].dropna().tail(7)
            spark = [round(v, 2) for v in hist.tolist()]
        except Exception:
            pass

        # RSI (14-period, Wilder's smoothing) off ~6 months of daily closes
        rsi_val = None
        try:
            closes = tk.history(period="6mo")["Close"].dropna()
            if len(closes) >= 15:
                delta = closes.diff()
                gain = delta.clip(lower=0)
                loss = -delta.clip(upper=0)
                avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
                avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
                rs = avg_gain / avg_loss
                rsi_series = 100 - (100 / (1 + rs))
                last_rsi = rsi_series.dropna().iloc[-1] if not rsi_series.dropna().empty else None
                rsi_val = round(float(last_rsi), 1) if last_rsi is not None else None
        except Exception:
            pass

        # 52-week Fibonacci retracement — standard levels (0/23.6/38.2/50/
        # 61.8/78.6/100) drawn between the swing low and swing high, and
        # WHICH ZONE the last close currently falls into (e.g. the classic
        # "golden pocket" between the 38.2% and 61.8% levels).
        FIB_LEVELS = [0, 23.6, 38.2, 50, 61.8, 78.6, 100]
        fib_low = fib_high = fib_level = None
        fib_zone_label = fib_zone_low = fib_zone_high = None
        try:
            yr = tk.history(period="1y")["Close"].dropna()
            if len(yr) >= 2:
                fib_high = round(float(yr.max()), 2)
                fib_low = round(float(yr.min()), 2)
                if fib_high > fib_low:
                    last_close = float(yr.iloc[-1])
                    fib_level = round((last_close - fib_low) / (fib_high - fib_low) * 100, 1)
                    fib_level_clamped = min(max(fib_level, 0), 100)
                    for lo, hi in zip(FIB_LEVELS[:-1], FIB_LEVELS[1:]):
                        if lo <= fib_level_clamped <= hi:
                            fib_zone_label = f"{lo:g}% – {hi:g}%"
                            fib_zone_low = round(fib_low + (lo / 100) * (fib_high - fib_low), 2)
                            fib_zone_high = round(fib_low + (hi / 100) * (fib_high - fib_low), 2)
                            break
        except Exception:
            pass

        return {
            "name": info.get("longName", ticker.split(".")[0]),
            "ticker": ticker.split(".")[0],
            "exch": exch,
            "sector": sector_key,
            "market": market,
            "currency": currency,
            "cap": cap_cat,
            "when": when,
            "time": "Not specified",
            "epsEst": round(float(earn_row.get("EPS Estimate")), 2) if earn_row.get("EPS Estimate") not in (None,) else None,
            "revEst": rev_est,
            "epsAct": round(float(last_actual_eps), 2) if last_actual_eps is not None else None,
            "revAct": None,  # actual revenue not reliably available pre-report via this API
            "surprise": surprise,
            "promoter": None,
            "eps4q": [round(float(v), 2) for v in last4_eps] if last4_eps else [0, 0, 0, 0],
            "spark": spark if len(spark) >= 2 else [1, 1],
            "rsi": rsi_val,
            "fibLow": fib_low,
            "fibHigh": fib_high,
            "fibLevel": fib_level,
            "fibZoneLabel": fib_zone_label,
            "fibZoneLow": fib_zone_low,
            "fibZoneHigh": fib_zone_high,
        }

    except Exception as e:
        print(f"  [warn] Skipping {ticker}: {e}")
        return None
    finally:
        time.sleep(pause)


# ---------------------------------------------------------------------
# 4. HTML template (dashboard UI) — data is injected as JSON
# ---------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Earnings Announcements — India &amp; USA</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{{
    --ink:#0E141C; --surface:#161F2B; --surface-2:#1C2735; --hairline:#2A3646;
    --text:#EAEEF3; --text-muted:#8B96A6; --text-faint:#5C6779;
    --accent:#E3B341; --accent-ink:#0E141C; --pos:#34D399; --neg:#F0554A;
  }}
  *{{box-sizing:border-box;}}
  html,body{{margin:0;padding:0;}}
  body{{background:var(--ink); color:var(--text); font-family:'Inter',sans-serif; -webkit-font-smoothing:antialiased; min-height:100vh;}}
  .mono{{font-family:'IBM Plex Mono',monospace; font-variant-numeric:tabular-nums;}}
  button{{cursor:pointer; font-family:inherit;}}
  .ticker-wrap{{background:#0A0F15; border-bottom:1px solid var(--hairline); overflow:hidden; white-space:nowrap; position:sticky; top:0; z-index:40;}}
  .ticker-track{{display:inline-flex; gap:36px; padding:6px 0; animation:scroll-left 32s linear infinite;}}
  .ticker-wrap:hover .ticker-track{{animation-play-state:paused;}}
  @keyframes scroll-left{{from{{transform:translateX(0);}} to{{transform:translateX(-50%);}}}}
  .tick-item{{font-family:'IBM Plex Mono',monospace; font-size:11.5px; color:var(--text-muted); display:inline-flex; align-items:center; gap:6px;}}
  .tick-item b{{color:var(--text); font-weight:600;}}
  .tick-item.up{{color:var(--pos);}} .tick-item.down{{color:var(--neg);}}
  header{{position:sticky; top:26px; z-index:39; background:rgba(14,20,28,.92); backdrop-filter:blur(10px); border-bottom:1px solid var(--hairline); padding:18px 28px 14px;}}
  .header-row{{display:flex; align-items:center; gap:20px; flex-wrap:wrap; max-width:1280px; margin:0 auto;}}
  .brand{{display:flex; align-items:baseline; gap:10px; margin-right:auto;}}
  .brand .mark{{width:9px;height:9px;border-radius:2px;background:var(--accent); display:inline-block; transform:rotate(45deg);}}
  h1{{font-size:19px; font-weight:600; margin:0; letter-spacing:-.01em; font-family:'Space Grotesk',sans-serif;}}
  .brand .sub{{color:var(--text-faint); font-size:12px; font-family:'IBM Plex Mono',monospace;}}
  .search-box{{position:relative; flex:1 1 240px; max-width:320px;}}
  .search-box input{{width:100%; background:var(--surface); border:1px solid var(--hairline); color:var(--text); font-size:13px; padding:9px 12px 9px 32px; border-radius:7px;}}
  .search-box input::placeholder{{color:var(--text-faint);}}
  .search-box input:focus{{outline:none; border-color:var(--accent);}}
  .search-box svg{{position:absolute; left:10px; top:50%; transform:translateY(-50%); opacity:.5;}}
  select.pill-select{{background:var(--surface); border:1px solid var(--hairline); color:var(--text); font-size:13px; padding:8px 12px; border-radius:7px; font-family:'IBM Plex Mono',monospace;}}
  select.pill-select:focus{{outline:none; border-color:var(--accent);}}
  .exch-toggle{{display:flex; background:var(--surface); border:1px solid var(--hairline); border-radius:7px; overflow:hidden;}}
  .exch-toggle button{{background:none; border:none; color:var(--text-muted); font-size:12.5px; font-family:'IBM Plex Mono',monospace; padding:8px 13px;}}
  .exch-toggle button.active{{background:var(--accent); color:var(--accent-ink); font-weight:600;}}
  .chip-row{{max-width:1280px; margin:12px auto 0; display:flex; gap:8px; flex-wrap:wrap;}}
  .date-toggle{{max-width:1280px; margin:12px auto 0; width:fit-content;}}
  .date-toggle button{{font-weight:600;}}
  .chip{{border:1px solid var(--hairline); background:var(--surface); color:var(--text-muted); font-size:12.5px; padding:6px 13px; border-radius:20px; display:flex; align-items:center; gap:6px;}}
  .chip .dot{{width:7px;height:7px;border-radius:50%;}}
  .chip.active{{color:var(--text); border-color:currentColor;}}
  .chip:hover{{border-color:var(--text-faint);}}
  main{{max-width:1280px; margin:0 auto; padding:22px 28px 60px;}}
  .result-count{{color:var(--text-faint); font-size:12.5px; font-family:'IBM Plex Mono',monospace; margin-bottom:14px;}}
  .cards{{display:flex; flex-direction:column; gap:10px;}}
  .card{{background:var(--surface); border:1px solid var(--hairline); border-radius:10px; display:grid; grid-template-columns:250px 1fr 210px; align-items:center; position:relative; overflow:hidden; transition:border-color .15s;}}
  .card:hover{{border-color:var(--text-faint);}}
  .card .sector-bar{{position:absolute; left:0; top:0; bottom:0; width:4px;}}
  .c-left{{display:flex; align-items:center; gap:12px; padding:16px 18px 16px 22px;}}
  .logo{{width:42px; height:42px; border-radius:8px; background:var(--surface-2); display:flex; align-items:center; justify-content:center; font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:15px; flex-shrink:0; border:1px solid var(--hairline);}}
  .co-name{{font-size:14px; font-weight:600; line-height:1.25;}}
  .co-ticker{{font-family:'IBM Plex Mono',monospace; font-size:11.5px; color:var(--text-faint); margin-top:2px;}}
  .badges{{display:flex; gap:5px; margin-top:6px; flex-wrap:wrap;}}
  .pill{{font-size:10px; padding:2px 7px; border-radius:20px; font-weight:600;}}
  .pill-sector{{color:#0E141C;}}
  .pill-outline{{border:1px solid var(--hairline); color:var(--text-muted); background:none;}}
  .c-center{{display:grid; grid-template-columns:repeat(3,1fr); grid-auto-rows:min-content; gap:12px 14px; padding:14px 10px; border-left:1px solid var(--hairline); border-right:1px solid var(--hairline); height:100%;}}
  .metric{{display:flex; flex-direction:column; justify-content:center; gap:3px;}}
  .metric .label{{font-size:10px; color:var(--text-faint); text-transform:uppercase; letter-spacing:.06em;}}
  .metric .value{{font-family:'IBM Plex Mono',monospace; font-size:14px; font-weight:500;}}
  .metric .value.pending{{color:var(--text-faint); font-style:italic; font-weight:400;}}
  .surprise.pos{{color:var(--pos);}} .surprise.neg{{color:var(--neg);}}
  .trend-bars{{display:flex; align-items:flex-end; gap:2px; height:22px; margin-top:2px;}}
  .trend-bars div{{width:5px; background:var(--hairline); border-radius:1px;}}
  .trend-bars div.latest{{background:var(--accent);}}
  .c-right{{display:flex; flex-direction:column; align-items:flex-end; gap:8px; padding:14px 20px 14px 14px;}}
  .spark-row{{display:flex; align-items:center; gap:8px;}}
  .spark-chg{{font-family:'IBM Plex Mono',monospace; font-size:11.5px;}}
  .actions{{display:flex; align-items:center; gap:8px;}}
  .btn-report{{background:none; border:1px solid var(--hairline); color:var(--text); font-size:11.5px; padding:6px 12px; border-radius:6px; font-weight:500;}}
  .btn-report:hover{{border-color:var(--accent); color:var(--accent);}}
  .watch-btn{{background:none; border:1px solid var(--hairline); border-radius:6px; width:29px; height:29px; display:flex; align-items:center; justify-content:center; color:var(--text-faint);}}
  .watch-btn.active{{color:var(--accent); border-color:var(--accent);}}
  .result-time{{font-size:10.5px; color:var(--text-faint); font-family:'IBM Plex Mono',monospace;}}
  .when-badge{{display:inline-block; padding:1px 7px; border-radius:20px; font-weight:700; letter-spacing:.02em;}}
  .when-badge.today{{background:rgba(227,179,65,.16); color:var(--accent);}}
  .section-title{{font-family:'Space Grotesk',sans-serif; font-size:14px; font-weight:600; margin:36px 0 12px; display:flex; align-items:center; gap:8px;}}
  .section-title .tag{{font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:var(--text-faint); font-weight:400;}}
  .heatmap{{display:flex; gap:6px; flex-wrap:wrap;}}
  .heat-cell{{width:64px; padding:9px 6px; border-radius:7px; text-align:center; font-family:'IBM Plex Mono',monospace;}}
  .heat-cell .t{{font-size:10.5px; font-weight:600; color:#0E141C;}}
  .heat-cell .p{{font-size:11px; font-weight:600; color:#0E141C;}}
  footer{{max-width:1280px; margin:30px auto 0; padding:18px 28px 0; border-top:1px solid var(--hairline); color:var(--text-faint); font-size:11.5px; line-height:1.6;}}
  .modal-backdrop{{position:fixed; inset:0; background:rgba(6,9,13,.7); display:none; align-items:center; justify-content:center; z-index:100; padding:20px;}}
  .modal-backdrop.open{{display:flex;}}
  .modal{{background:var(--surface); border:1px solid var(--hairline); border-radius:12px; max-width:560px; width:100%; padding:26px 28px; position:relative;}}
  .modal-close{{position:absolute; top:16px; right:16px; background:none; border:none; color:var(--text-faint); font-size:20px;}}
  .modal h2{{font-family:'Space Grotesk',sans-serif; font-size:18px; margin:0 0 2px;}}
  .modal .m-sub{{color:var(--text-faint); font-size:12px; font-family:'IBM Plex Mono',monospace; margin-bottom:18px;}}
  .modal-grid{{display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:18px;}}
  .modal-grid .metric{{background:var(--surface-2); padding:10px 12px; border-radius:8px;}}
  @media (max-width:880px){{
    .card{{grid-template-columns:1fr;}}
    .c-center{{border:none; border-top:1px solid var(--hairline); border-bottom:1px solid var(--hairline); grid-template-columns:repeat(2,1fr);}}
    .c-right{{align-items:flex-start; flex-direction:row; justify-content:space-between;}}
  }}
  @media (prefers-reduced-motion: reduce){{ .ticker-track{{animation:none;}} }}
</style>
</head>
<body>
<div class="ticker-wrap"><div class="ticker-track" id="tickerTrack"></div></div>
<header>
  <div class="header-row">
    <div class="brand">
      <span class="mark"></span>
      <div><h1 id="pageTitle">Earnings Announcements</h1><div class="sub" id="dateSub">—</div></div>
    </div>
    <div class="exch-toggle" id="marketToggle">
      <button data-mk="IN" class="active">India</button>
      <button data-mk="US">USA</button>
    </div>
    <div class="search-box">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8B96A6" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
      <input id="searchInput" type="text" placeholder="Search company or ticker…">
    </div>
    <div class="exch-toggle" id="exchToggle"></div>
  </div>
  <div class="exch-toggle date-toggle" id="dateToggle">
    <button data-date="today">Today</button>
    <button data-date="tomorrow">Tomorrow</button>
    <button data-date="week" class="active">This week</button>
  </div>
  <div class="chip-row" id="sectorChips"></div>
</header>
<main>
  <div class="section-title" style="margin-top:0;">Surprise heatmap <span class="tag">EPS actual vs. estimate, last reported quarter</span></div>
  <div class="heatmap" id="heatmap"></div>
  <div class="result-count" id="resultCount" style="margin-top:32px;"></div>
  <div class="cards" id="cardsWrap"></div>
</main>
<footer id="pageFooter">
  Generated by india_earnings_dashboard.py using free Yahoo Finance data (via yfinance) on {generated_on}.
  Figures shown in local currency (₹ Cr for India, $ for USA) where applicable. Promoter holding and
  pre/post-market timing are not reliably available from this data source and are marked accordingly.
  Always verify with official exchange filings before making investment decisions.
</footer>
<div class="modal-backdrop" id="modalBackdrop"><div class="modal" id="modalBody"></div></div>
<script>
const MARKETS = {{
  IN: {{
    label: 'India',
    sectors: {sector_colors_in_json},
    sectorNames: null,
    companies: {companies_in_json},
    indexes: {indexes_in_json},
    exch: ['ALL','NSE','BSE'],
    currencyNote: '₹ Cr (crore)',
  }},
  US: {{
    label: 'USA',
    sectors: {sector_colors_us_json},
    sectorNames: {sector_names_us_json},
    companies: {companies_us_json},
    indexes: {indexes_us_json},
    exch: ['ALL','NASDAQ','NYSE'],
    currencyNote: '$ (USD)',
  }},
}};
let state = {{ market:'IN', search:'', exch:'ALL', date:'week', sectors:new Set(), watchlist:new Set() }};

function formatMoney(num, currency){{
  if(num === null || num === undefined) return null;
  if(currency === '$'){{
    const isNeg = num < 0; const abs = Math.abs(num);
    const val = abs >= 1000 ? (abs/1000).toFixed(2) + 'B' : abs.toFixed(0) + 'M';
    return (isNeg?'-':'') + '$' + val;
  }}
  const isNeg = num < 0; num = Math.abs(num);
  let s = num.toFixed(0);
  let last3 = s.slice(-3);
  let rest = s.slice(0,-3);
  if(rest !== '') last3 = ',' + last3;
  rest = rest.replace(/\\B(?=(\\d{{2}})+(?!\\d))/g, ',');
  return (isNeg?'-':'') + '₹' + rest + last3 + ' Cr';
}}

function currentMarket(){{ return MARKETS[state.market]; }}

function renderTicker(){{
  const items = currentMarket().indexes.map(i => `<span class="tick-item ${{i.up?'up':'down'}}"><b>${{i.n}}</b> ${{i.v}} ${{i.chg}}</span>`).join('');
  document.getElementById('tickerTrack').innerHTML = items + items;
}}

function renderChips(){{
  const wrap = document.getElementById('sectorChips');
  const m = currentMarket();
  const label = (key) => (m.sectorNames && m.sectorNames[key]) ? m.sectorNames[key] : key;
  const allChip = `<button class="chip ${{state.sectors.size===0?'active':''}}" data-sector="__all">All sectors</button>`;
  const chips = Object.entries(m.sectors).map(([key,color])=>{{
    const active = state.sectors.has(key);
    return `<button class="chip ${{active?'active':''}}" data-sector="${{key}}" style="${{active?`color:${{color}};`:''}}"><span class="dot" style="background:${{color}}"></span>${{label(key)}}</button>`;
  }}).join('');
  wrap.innerHTML = allChip + chips;
  wrap.querySelectorAll('.chip').forEach(btn=>{{
    btn.addEventListener('click', ()=>{{
      const s = btn.dataset.sector;
      if(s === '__all'){{ state.sectors.clear(); }}
      else{{ if(state.sectors.has(s)) state.sectors.delete(s); else state.sectors.add(s); }}
      renderChips(); renderAll();
    }});
  }});
}}

function renderExchToggle(){{
  const wrap = document.getElementById('exchToggle');
  const opts = currentMarket().exch;
  wrap.innerHTML = opts.map((ex,i)=>`<button data-ex="${{ex}}" class="${{i===0?'active':''}}">${{ex==='ALL'?'All':ex}}</button>`).join('');
  wrap.querySelectorAll('button').forEach(btn=>{{
    btn.addEventListener('click', ()=>{{
      wrap.querySelectorAll('button').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      state.exch = btn.dataset.ex;
      renderAll();
    }});
  }});
}}

document.getElementById('marketToggle').querySelectorAll('button').forEach(btn=>{{
  btn.addEventListener('click', ()=>{{
    document.querySelectorAll('#marketToggle button').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    state.market = btn.dataset.mk;
    state.exch = 'ALL';
    state.sectors.clear();
    document.getElementById('pageTitle').textContent = `Earnings Announcements — ${{currentMarket().label}}`;
    renderTicker(); renderChips(); renderExchToggle(); updateDateSub(); renderAll();
  }});
}});

function sparkSVG(data, positive){{
  const w=72,h=26,pad=2;
  const min=Math.min(...data), max=Math.max(...data);
  const range=(max-min)||1;
  const pts = data.map((d,i)=>{{
    const x = pad + (i/(data.length-1||1))*(w-2*pad);
    const y = h - pad - ((d-min)/range)*(h-2*pad);
    return `${{x.toFixed(1)}},${{y.toFixed(1)}}`;
  }}).join(' ');
  const color = positive ? '#34D399' : '#F0554A';
  return `<svg width="${{w}}" height="${{h}}" viewBox="0 0 ${{w}} ${{h}}"><polyline points="${{pts}}" fill="none" stroke="${{color}}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}}

function fibZoneColor(level){{
  if(level===null || level===undefined) return 'var(--text-muted)';
  if(level<=38.2) return '#34D399';   // near the 52w low  — green
  if(level<=61.8) return '#E3B341';   // the "golden pocket" — gold
  return '#F0554A';                   // near the 52w high — red
}}

function trendBars(eps4q){{
  const vals = eps4q.length ? eps4q : [0,0,0,0];
  const max = Math.max(...vals, 1);
  return vals.map((v,i)=>{{
    const h = Math.max(4, Math.round((v/max)*22));
    const cls = i===vals.length-1 ? 'latest' : '';
    return `<div class="${{cls}}" style="height:${{h}}px" title="Q${{i+1}}: ${{v}}"></div>`;
  }}).join('');
}}

function cardHTML(c){{
  const m = currentMarket();
  const color = m.sectors[c.sector] || '#8B96A6';
  const sectorLabel = (m.sectorNames && m.sectorNames[c.sector]) ? m.sectorNames[c.sector] : c.sector;
  const initials = c.ticker.slice(0,2);
  const reported = c.epsAct !== null;
  const hasSpark = c.spark && c.spark.length > 1;
  const pctChg = hasSpark ? ((c.spark[c.spark.length-1]-c.spark[0])/c.spark[0]*100) : 0;
  const positive = pctChg >= 0;
  const watched = state.watchlist.has(c.ticker);
  const whenLabel = c.when === 'today'
    ? `<span class="when-badge today">Today</span>`
    : (c.when === 'tomorrow' ? 'Tomorrow' : 'This week');

  return `
  <div class="card" data-ticker="${{c.ticker}}">
    <div class="sector-bar" style="background:${{color}}"></div>
    <div class="c-left">
      <div class="logo" style="color:${{color}}; border-color:${{color}}55;">${{initials}}</div>
      <div>
        <div class="co-name">${{c.name}}</div>
        <div class="co-ticker">${{c.ticker}} · ${{c.exch}}</div>
        <div class="badges">
          <span class="pill pill-sector" style="background:${{color}}">${{sectorLabel}}</span>
          <span class="pill pill-outline">${{c.cap}}${{c.cap!=='N/A' ? ' Cap' : ''}}</span>
        </div>
      </div>
    </div>
    <div class="c-center">
      <div class="metric">
        <div class="label">EPS Estimate</div>
        <div class="value mono ${{c.epsEst===null?'pending':''}}">${{c.epsEst!==null? c.currency+c.epsEst.toFixed(2) : 'N/A'}}</div>
      </div>
      <div class="metric">
        <div class="label">Revenue Estimate</div>
        <div class="value mono ${{c.revEst===null?'pending':''}}">${{c.revEst!==null? formatMoney(c.revEst, c.currency) : 'N/A'}}</div>
      </div>
      <div class="metric">
        <div class="label">Actual EPS (last qtr)</div>
        <div class="value mono ${{reported?'':'pending'}}">${{reported? c.currency+c.epsAct.toFixed(2) : 'Awaited'}}</div>
      </div>
      <div class="metric">
        <div class="label">Surprise % (last qtr)</div>
        ${{c.surprise!==null
          ? `<div class="value mono surprise ${{c.surprise>=0?'pos':'neg'}}">${{c.surprise>=0?'+':''}}${{c.surprise.toFixed(1)}}%</div>`
          : `<div class="value mono pending">—</div>`}}
        <div class="trend-bars">${{trendBars(c.eps4q)}}</div>
      </div>
      <div class="metric">
        <div class="label">RSI (14)</div>
        ${{c.rsi!==null
          ? `<div class="value mono ${{c.rsi>=70?'neg':(c.rsi<=30?'pos':'')}}">${{c.rsi.toFixed(1)}}${{c.rsi>=70?' · OB':(c.rsi<=30?' · OS':'')}}</div>`
          : `<div class="value mono pending">N/A</div>`}}
      </div>
      <div class="metric">
        <div class="label">Fibonacci Zone</div>
        ${{c.fibZoneLabel!==null
          ? `<div class="value mono" style="font-size:12px; color:${{fibZoneColor(c.fibLevel)}};">${{c.currency}}${{c.fibZoneLow.toFixed(2)}} – ${{c.currency}}${{c.fibZoneHigh.toFixed(2)}}</div>
             <div style="font-size:10.5px; color:${{fibZoneColor(c.fibLevel)}}; font-family:'IBM Plex Mono',monospace;">${{c.fibZoneLabel}} zone</div>`
          : `<div class="value mono pending">N/A</div>`}}
      </div>
    </div>
    <div class="c-right">
      <div class="result-time">${{c.time}} · ${{whenLabel}}</div>
      <div class="spark-row">
        ${{hasSpark ? sparkSVG(c.spark, positive) : ''}}
        ${{hasSpark ? `<span class="spark-chg" style="color:${{positive?'#34D399':'#F0554A'}}">${{positive?'+':''}}${{pctChg.toFixed(1)}}%</span>` : ''}}
      </div>
      <div class="actions">
        <button class="btn-report" data-report="${{c.ticker}}">View report</button>
        <button class="watch-btn ${{watched?'active':''}}" data-watch="${{c.ticker}}" title="Add to watchlist">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="${{watched?'currentColor':'none'}}" stroke="currentColor" stroke-width="2"><path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/></svg>
        </button>
      </div>
    </div>
  </div>`;
}}

function renderHeatmap(list){{
  const reported = list.filter(c=>c.epsAct!==null && c.surprise!==null);
  document.getElementById('heatmap').innerHTML = reported.map(c=>{{
    const s = c.surprise;
    const bg = s>=0 ? `rgba(52,211,153,${{Math.min(0.25+Math.abs(s)/20,0.9)}})` : `rgba(240,85,74,${{Math.min(0.25+Math.abs(s)/20,0.9)}})`;
    return `<div class="heat-cell" style="background:${{bg}}" title="${{c.name}}"><div class="t">${{c.ticker}}</div><div class="p">${{s>=0?'+':''}}${{s.toFixed(1)}}%</div></div>`;
  }}).join('') || `<div style="color:var(--text-faint); font-size:12.5px;">No reported results yet in the current filter.</div>`;
}}

function getFiltered(){{
  return currentMarket().companies.filter(c=>{{
    if(state.exch !== 'ALL' && c.exch !== state.exch) return false;
    if(state.sectors.size > 0 && !state.sectors.has(c.sector)) return false;
    if(state.search && !(c.name.toLowerCase().includes(state.search) || c.ticker.toLowerCase().includes(state.search))) return false;
    if(state.date === 'today' && c.when !== 'today') return false;
    if(state.date === 'tomorrow' && c.when !== 'tomorrow') return false;
    return true;
  }});
}}

function renderAll(){{
  const list = getFiltered();
  document.getElementById('cardsWrap').innerHTML = list.map(cardHTML).join('') ||
    `<div style="color:var(--text-faint); padding:40px 0; text-align:center; font-size:13px;">No companies match these filters.</div>`;
  document.getElementById('resultCount').textContent = `${{list.length}} compan${{list.length===1?'y':'ies'}} · ${{state.date === 'today' ? "today's" : state.date === 'tomorrow' ? "tomorrow's" : "this week's"}} announcements`;
  renderHeatmap(list);
  attachCardEvents();
}}

function attachCardEvents(){{
  document.querySelectorAll('[data-watch]').forEach(btn=>{{
    btn.addEventListener('click', (e)=>{{
      e.stopPropagation();
      const t = btn.dataset.watch;
      if(state.watchlist.has(t)) state.watchlist.delete(t); else state.watchlist.add(t);
      renderAll();
    }});
  }});
  document.querySelectorAll('[data-report]').forEach(btn=>{{
    btn.addEventListener('click', ()=> openModal(btn.dataset.report));
  }});
}}

function openModal(ticker){{
  const m = currentMarket();
  const c = m.companies.find(x=>x.ticker===ticker);
  const color = m.sectors[c.sector] || '#8B96A6';
  const sectorLabel = (m.sectorNames && m.sectorNames[c.sector]) ? m.sectorNames[c.sector] : c.sector;
  const reported = c.epsAct !== null;
  const hasSpark = c.spark && c.spark.length > 1;
  document.getElementById('modalBody').innerHTML = `
    <button class="modal-close" id="modalClose">&times;</button>
    <h2>${{c.name}}</h2>
    <div class="m-sub">${{c.ticker}} · ${{c.exch}} · <span style="color:${{color}}">${{sectorLabel}}</span></div>
    <div class="modal-grid">
      <div class="metric"><div class="label">EPS Estimate</div><div class="value mono">${{c.epsEst!==null?c.currency+c.epsEst.toFixed(2):'N/A'}}</div></div>
      <div class="metric"><div class="label">Revenue Estimate</div><div class="value mono">${{c.revEst!==null?formatMoney(c.revEst, c.currency):'N/A'}}</div></div>
      <div class="metric"><div class="label">Actual EPS (last qtr)</div><div class="value mono ${{reported?'':'pending'}}">${{reported?c.currency+c.epsAct.toFixed(2):'Awaited'}}</div></div>
      <div class="metric"><div class="label">Actual Revenue</div><div class="value mono pending">Not available</div></div>
      <div class="metric"><div class="label">Promoter Holding</div><div class="value mono pending">Not available</div></div>
      <div class="metric"><div class="label">Result Time</div><div class="value mono">${{c.time}}</div></div>
      <div class="metric"><div class="label">RSI (14)</div><div class="value mono ${{c.rsi!==null?(c.rsi>=70?'neg':(c.rsi<=30?'pos':'')):'pending'}}">${{c.rsi!==null?c.rsi.toFixed(1)+(c.rsi>=70?' (Overbought)':(c.rsi<=30?' (Oversold)':'')):'N/A'}}</div></div>
      <div class="metric"><div class="label">Fibonacci Zone (52W)</div><div class="value mono ${{c.fibZoneLabel===null?'pending':''}}" style="${{c.fibZoneLabel!==null?'color:'+fibZoneColor(c.fibLevel)+';':''}}">${{c.fibZoneLabel!==null?c.currency+c.fibZoneLow.toFixed(2)+' – '+c.currency+c.fibZoneHigh.toFixed(2)+' ('+c.fibZoneLabel+')':'N/A'}}</div></div>
    </div>
    <div class="label" style="margin-bottom:6px;">EPS — last 4 quarters</div>
    <div class="trend-bars" style="height:36px; gap:4px; margin-bottom:18px;">
      ${{(c.eps4q.length?c.eps4q:[0,0,0,0]).map((v,i,arr)=>{{
        const max=Math.max(...arr,1); const h=Math.max(6,Math.round((v/max)*34));
        return `<div style="width:16px;height:${{h}}px;background:${{i===arr.length-1?color:'var(--hairline)'}};border-radius:2px;" title="${{c.currency}}${{v}}"></div>`;
      }}).join('')}}
    </div>
    ${{hasSpark ? `<div class="label" style="margin-bottom:6px;">Price — last sessions</div>${{sparkSVG(c.spark, c.spark[c.spark.length-1]>=c.spark[0]).replace('width="72" height="26"','width="220" height="46"')}}` : ''}}
  `;
  document.getElementById('modalBackdrop').classList.add('open');
  document.getElementById('modalClose').addEventListener('click', closeModal);
}}
function closeModal(){{ document.getElementById('modalBackdrop').classList.remove('open'); }}
document.getElementById('modalBackdrop').addEventListener('click', (e)=>{{ if(e.target.id === 'modalBackdrop') closeModal(); }});

document.getElementById('searchInput').addEventListener('input', (e)=>{{ state.search = e.target.value.trim().toLowerCase(); renderAll(); }});
document.getElementById('dateToggle').querySelectorAll('button').forEach(btn=>{{
  btn.addEventListener('click', ()=>{{
    document.querySelectorAll('#dateToggle button').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    state.date = btn.dataset.date;
    updateDateSub();
    renderAll();
  }});
}});

function updateDateSub(){{
  const today = new Date();
  const locale = state.market === 'US' ? 'en-US' : 'en-IN';
  const opts = {{weekday:'long', month:'long', day:'numeric'}};
  const label = state.date==='today' ? today.toLocaleDateString(locale, opts)
    : state.date==='tomorrow' ? new Date(today.getTime()+86400000).toLocaleDateString(locale, opts)
    : 'Week of ' + today.toLocaleDateString(locale, {{month:'long', day:'numeric'}});
  document.getElementById('dateSub').textContent = label;
}}

renderTicker();
renderChips();
renderExchToggle();
updateDateSub();
renderAll();
</script>
</body>
</html>
"""

def fetch_indexes(targets):
    """Live index quotes. Falls back to a '—' placeholder for any index
    Yahoo doesn't return a usable price for."""
    out = []
    for t in targets:
        row = {"n": t["n"], "v": "—", "chg": "", "up": True}
        try:
            hist = yf.Ticker(t["ticker"]).history(period="5d")["Close"].dropna()
            if len(hist) >= 2:
                last, prev = hist.iloc[-1], hist.iloc[-2]
                chg_pct = (last - prev) / prev * 100
                row["v"] = f"{last:,.2f}"
                row["chg"] = f"{'+' if chg_pct >= 0 else ''}{chg_pct:.2f}%"
                row["up"] = bool(chg_pct >= 0)
        except Exception:
            pass  # keep the '—' placeholder for this index
        out.append(row)
    return out


INDIA_INDEX_TARGETS = [
    {"n": "NIFTY 50", "ticker": "^NSEI"},
    {"n": "SENSEX", "ticker": "^BSESN"},
    {"n": "BANK NIFTY", "ticker": "^NSEBANK"},
]

USA_INDEX_TARGETS = [
    {"n": "S&P 500", "ticker": "^GSPC"},
    {"n": "NASDAQ", "ticker": "^IXIC"},
    {"n": "DOW JONES", "ticker": "^DJI"},
]


# ---------------------------------------------------------------------
# 4b. Telegram alert — "tomorrow's earnings" notification
#     Credentials are read in this order:
#       1. Environment variables (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ...)
#          — this is what GitHub Actions secrets get injected as. Use this
#          path when running in CI.
#       2. telegram_config.py (kept separate on purpose) — a local fallback
#          for running the script on your own machine.
# ---------------------------------------------------------------------

def _tg_setting(name, default=None):
    """Environment variable first (GitHub Actions secrets land here),
    telegram_config.py second (local fallback), then default."""
    env_val = os.environ.get(name)
    if env_val not in (None, ""):
        return env_val
    if tg_cfg is not None:
        return getattr(tg_cfg, name, default)
    return default


def _tg_enabled():
    env_val = os.environ.get("TELEGRAM_ENABLED")
    if env_val is not None and env_val != "":
        return env_val.strip().lower() in ("1", "true", "yes", "on")
    if tg_cfg is not None:
        return bool(getattr(tg_cfg, "TELEGRAM_ENABLED", False))
    return False


def _telegram_ready():
    """Returns True only if Telegram alerts are enabled and real
    (non-placeholder) credentials are available, from either env vars or
    telegram_config.py."""
    if not _tg_enabled():
        print("  [telegram] Telegram alerts are disabled (TELEGRAM_ENABLED "
              "is not set/true) — skipping alert.")
        return False
    token = _tg_setting("TELEGRAM_BOT_TOKEN", "") or ""
    chat_id = _tg_setting("TELEGRAM_CHAT_ID", "") or ""
    if not token or "PUT_YOUR" in token or not chat_id or "PUT_YOUR" in str(chat_id):
        print("  [telegram] Bot token / chat ID are missing or still look like "
              "placeholders — skipping alert. Set TELEGRAM_BOT_TOKEN and "
              "TELEGRAM_CHAT_ID as env vars (GitHub Actions secrets) or in "
              "telegram_config.py for local runs.")
        return False
    return True


def send_telegram_message(text):
    """Sends a single message via the Telegram Bot API using only the
    standard library (no extra pip dependency needed)."""
    token = _tg_setting("TELEGRAM_BOT_TOKEN")
    chat_id = _tg_setting("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError as e:
        print(f"  [telegram] send failed: HTTP {e.code} — {e.read().decode(errors='ignore')}")
    except Exception as e:
        print(f"  [telegram] send failed: {e}")
    return False


def _format_table(companies):
    """Builds an aligned, monospace-friendly text table (Company / EPS /
    RSI / Fib Range) for a list of companies. All values are HTML-escaped
    since this ends up inside a <pre> block under HTML parse_mode."""
    headers = ("Company", "EPS", "RSI", "Fib Range")
    rows = []
    for c in companies:
        eps = f"{c['currency']}{c['epsEst']:.2f}" if c.get("epsEst") is not None else "–"
        rsi = f"{c['rsi']:.1f}" if c.get("rsi") is not None else "–"
        fib_label = c.get("fibZoneLabel")
        fib = fib_label.replace("–", "→") if fib_label else "–"
        rows.append((html.escape(c["ticker"]), html.escape(eps), html.escape(rsi), html.escape(fib)))

    col_widths = [
        max(len(headers[i]), max((len(r[i]) for r in rows), default=0)) + 2
        for i in range(4)
    ]
    header_line = "".join(headers[i].ljust(col_widths[i]) for i in range(4)).rstrip()
    lines = [header_line, "-" * len(header_line)]
    for r in rows:
        lines.append("".join(r[i].ljust(col_widths[i]) for i in range(4)).rstrip())
    return "\n".join(lines)


def build_tomorrow_message(companies_in, companies_us):
    """Builds a Telegram-ready (HTML parse-mode) message listing every
    company reporting earnings TOMORROW, as an aligned monospace table
    per market: Company (ticker), EPS estimate, RSI, and Fibonacci zone."""
    tomorrow_in = [c for c in companies_in if c["when"] == "tomorrow"]
    tomorrow_us = [c for c in companies_us if c["when"] == "tomorrow"]

    tomorrow_date = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%A, %d %B %Y")
    parts = [f"<b>📅 Earnings Tomorrow — {tomorrow_date}</b>"]

    def _section(flag_title, companies):
        if not companies:
            return
        table = _format_table(companies)
        parts.append(f"\n<b>{flag_title}</b>\n<pre>{table}</pre>")

    if _tg_setting("TELEGRAM_MARKETS", "BOTH") in ("IN", "BOTH"):
        _section("🇮🇳 INDIA", tomorrow_in)
    if _tg_setting("TELEGRAM_MARKETS", "BOTH") in ("US", "BOTH"):
        _section("🇺🇸 USA", tomorrow_us)

    if len(parts) == 1:
        parts.append("\nNo companies reporting tomorrow in the tracked list.")

    return "\n".join(parts)


def notify_telegram_tomorrow(companies_in, companies_us):
    if not _telegram_ready():
        return
    message = build_tomorrow_message(companies_in, companies_us)
    # Telegram's hard cap is 4096 characters per message — chunk if needed.
    chunks = [message[i:i + 4000] for i in range(0, len(message), 4000)] or [message]
    ok_all = True
    for chunk in chunks:
        ok_all = send_telegram_message(chunk) and ok_all
    if ok_all:
        print("  [telegram] Tomorrow's earnings alert sent.")


# ---------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------

def main():
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    week_end = today + datetime.timedelta(days=7)

    print("Fetching index quotes...")
    indexes_in = fetch_indexes(INDIA_INDEX_TARGETS)
    indexes_us = fetch_indexes(USA_INDEX_TARGETS)

    print("Building company universe (live NIFTY 200 / S&P 500 lookups)...")
    all_companies_in = build_india_universe()
    all_companies_usa = build_usa_universe()

    # Scanning the full ~700-ticker universe (each needs 2 Yahoo Finance
    # calls plus a pause) typically takes 15-30+ minutes and can occasionally
    # hit Yahoo's rate limiting. If that's a problem for your run cadence,
    # set USE_FULL_NIFTY200=false / USE_FULL_SP500=false to fall back to the
    # much smaller curated lists further up this file.
    print(f"Fetching data for {len(all_companies_in)} India companies...")
    companies_in = []
    for entry in all_companies_in:
        result = fetch_company(entry["ticker"], entry["sector"], today, tomorrow, week_end, market="IN")
        if result:
            companies_in.append(result)
            print(f"  [ok] {entry['ticker']} -> {result['when']}")

    print(f"Fetching data for {len(all_companies_usa)} USA companies...")
    companies_us = []
    for entry in all_companies_usa:
        result = fetch_company(entry["ticker"], entry["sector"], today, tomorrow, week_end, market="US")
        if result:
            companies_us.append(result)
            print(f"  [ok] {entry['ticker']} -> {result['when']}")

    html = HTML_TEMPLATE.format(
        generated_on=today.strftime("%B %d, %Y"),
        sector_colors_in_json=json.dumps(SECTOR_COLORS),
        sector_colors_us_json=json.dumps(USA_SECTOR_COLORS),
        sector_names_us_json=json.dumps(USA_SECTOR_NAMES),
        companies_in_json=json.dumps(companies_in),
        companies_us_json=json.dumps(companies_us),
        indexes_in_json=json.dumps(indexes_in),
        indexes_us_json=json.dumps(indexes_us),
    )

    # Save next to this script file, not wherever the process's current
    # working directory happens to be (e.g. your home folder if you
    # launched python from there or via a shortcut/IDE default).
    # Written to docs/index.html on purpose: with GitHub Pages configured
    # to serve from the "main" branch / "docs" folder, this file is
    # published automatically at https://<username>.github.io/<repo>/
    # (no filename needed in the URL). Override the folder with the
    # DASHBOARD_OUTPUT_DIR env var if you want it somewhere else.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.environ.get("DASHBOARD_OUTPUT_DIR", os.path.join(script_dir, "docs"))
    os.makedirs(output_dir, exist_ok=True)
    out_file = os.path.join(output_dir, "index.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n{len(companies_in)} India compan(y/ies) with announcements in the next 7 days.")
    print(f"{len(companies_us)} USA compan(y/ies) with announcements in the next 7 days.")
    print(f"Dashboard saved to: {out_file}")

    print("\nSending Telegram alert for tomorrow's earnings...")
    notify_telegram_tomorrow(companies_in, companies_us)


if __name__ == "__main__":
    main()
