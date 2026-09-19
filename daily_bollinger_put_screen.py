#!/usr/bin/env python3
"""
Daily Bollinger put-selling screener.

Rule:
  Current Strategy 1/2 signal
  + Historically Effective for that exact strategy
  + SPY regime is Bullish or Sideways/Transitional
  = Qualified candidate

Price data: Massive REST aggregates.
Earnings: Massive Benzinga Earnings when entitled, otherwise optional yfinance fallback.
Telegram: Bot API sendMessage/sendPhoto/sendDocument.

IMPORTANT: The signal is known at close t. The next trading day's Open is the first
permitted live entry. Since this job runs before that next Open, the current Close is
used only as a provisional strike-reference price.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

# -----------------------------------------------------------------------------
# HARD-CODED UNIVERSE: copied from S&P500nETF.txt exactly as requested.
# Do not dynamically replace this list from Wikipedia or another source.
# -----------------------------------------------------------------------------
STOCKS: Dict[str, str] = {'A': 'Agilent Technologies', 'AAPL': 'Apple Inc.', 'ABBV': 'AbbVie', 'ABNB': 'Airbnb', 'ABT': 'Abbott Laboratories', 'ACGL': 'Arch Capital Group', 'ACN': 'Accenture', 'ADBE': 'Adobe Inc.', 'ADI': 'Analog Devices', 'ADM': 'Archer Daniels Midland', 'ADP': 'Automatic Data Processing', 'ADSK': 'Autodesk', 'AEE': 'Ameren', 'AEP': 'American Electric Power', 'AES': 'AES Corporation', 'AFL': 'Aflac', 'AIG': 'American International Group', 'AIZ': 'Assurant', 'AJG': 'Arthur J. Gallagher & Co.', 'AKAM': 'Akamai Technologies', 'ALB': 'Albemarle Corporation', 'ALGN': 'Align Technology', 'ALL': 'Allstate', 'ALLE': 'Allegion', 'AMAT': 'Applied Materials', 'AMCR': 'Amcor', 'AMD': 'Advanced Micro Devices', 'AME': 'Ametek', 'AMGN': 'Amgen', 'AMP': 'Ameriprise Financial', 'AMT': 'American Tower', 'AMZN': 'Amazon', 'ANET': 'Arista Networks', 'AON': 'Aon', 'AOS': 'A. O. Smith', 'APA': 'APA Corporation', 'APD': 'Air Products and Chemicals', 'APH': 'Amphenol', 'APO': 'Apollo Global Management', 'APP': 'AppLovin', 'APTV': 'Aptiv', 'ARE': 'Alexandria Real Estate Equities', 'ARES': 'Ares Management', 'ATO': 'Atmos Energy', 'AVB': 'AvalonBay Communities', 'AVGO': 'Broadcom', 'AVY': 'Avery Dennison', 'AWK': 'American Water Works', 'AXON': 'Axon Enterprise', 'AXP': 'American Express', 'AZO': 'AutoZone', 'BA': 'Boeing', 'BAC': 'Bank of America', 'BALL': 'Ball Corporation', 'BAX': 'Baxter International', 'BBY': 'Best Buy', 'BDX': 'Becton Dickinson', 'BEN': 'Franklin Resources', 'BF-B': 'Brown–Forman', 'BG': 'Bunge Global SA', 'BIIB': 'Biogen', 'BK': 'Bank of New York Mellon', 'BKNG': 'Booking Holdings', 'BKR': 'Baker Hughes', 'BLDR': 'Builders FirstSource', 'BLK': 'BlackRock', 'BMY': 'Bristol Myers Squibb', 'BR': 'Broadridge Financial Solutions', 'BRK-B': 'Berkshire Hathaway', 'BRO': 'Brown & Brown', 'BSX': 'Boston Scientific', 'BX': 'Blackstone', 'BXP': 'Boston Properties', 'C': 'Citigroup', 'CAG': 'Conagra Brands', 'CAH': 'Cardinal Health', 'CARR': 'Carrier Global', 'CAT': 'Caterpillar Inc.', 'CB': 'Chubb Limited', 'CBOE': 'Cboe Global Markets', 'CBRE': 'CBRE Group', 'CCI': 'Crown Castle', 'CCL': 'Carnival Corporation', 'CDNS': 'Cadence Design Systems', 'CDW': 'CDW', 'CEG': 'Constellation Energy', 'CF': 'CF Industries', 'CFG': 'Citizens Financial Group', 'CHD': 'Church & Dwight', 'CHRW': 'C.H. Robinson', 'CHTR': 'Charter Communications', 'CI': 'Cigna', 'CIEN': 'Ciena', 'CINF': 'Cincinnati Financial', 'CL': 'Colgate-Palmolive', 'CLX': 'Clorox', 'CMCSA': 'Comcast', 'CME': 'CME Group', 'CMG': 'Chipotle Mexican Grill', 'CMI': 'Cummins', 'CMS': 'CMS Energy', 'CNC': 'Centene Corporation', 'CNP': 'CenterPoint Energy', 'COF': 'Capital One', 'COIN': 'Coinbase', 'COO': 'The Cooper Companies', 'COP': 'ConocoPhillips', 'COR': 'Cencora', 'COST': 'Costco', 'CPAY': 'Corpay', 'CPB': 'Campbell Soup Company', 'CPRT': 'Copart', 'CPT': 'Camden Property Trust', 'CRH': 'CRH plc', 'CRL': 'Charles River Laboratories', 'CRM': 'Salesforce', 'CRWD': 'CrowdStrike', 'CSCO': 'Cisco', 'CSGP': 'CoStar Group', 'CSX': 'CSX Corporation', 'CTAS': 'Cintas', 'CTRA': 'Coterra', 'CTSH': 'Cognizant', 'CTVA': 'Corteva', 'CVNA': 'Carvana', 'CVS': 'CVS Health', 'CVX': 'Chevron Corporation', 'D': 'Dominion Energy', 'DAL': 'Delta Air Lines', 'DASH': 'DoorDash', 'DD': 'DuPont', 'DDOG': 'Datadog', 'DE': 'John Deere', 'DECK': 'Deckers Outdoor Corporation', 'DELL': 'Dell Technologies', 'DG': 'Dollar General', 'DGX': 'Quest Diagnostics', 'DHI': 'D.R. Horton', 'DHR': 'Danaher Corporation', 'DIS': 'Walt Disney Company (The)', 'DLR': 'Digital Realty', 'DLTR': 'Dollar Tree', 'DOC': 'Healthpeak Properties', 'DOV': 'Dover Corporation', 'DOW': 'Dow Inc.', 'DPZ': "Domino's", 'DRI': 'Darden Restaurants', 'DTE': 'DTE Energy', 'DUK': 'Duke Energy', 'DVA': 'DaVita', 'DVN': 'Devon Energy', 'DXCM': 'Dexcom', 'EA': 'Electronic Arts', 'EBAY': 'eBay', 'ECL': 'Ecolab', 'ED': 'Consolidated Edison', 'EFX': 'Equifax', 'EG': 'Everest Group', 'EIX': 'Edison International', 'EL': 'Estée Lauder Companies (The)', 'ELV': 'Elevance Health', 'EME': 'EMCOR Group', 'EMR': 'Emerson Electric', 'EOG': 'EOG Resources', 'EPAM': 'EPAM Systems', 'EQIX': 'Equinix', 'EQR': 'Equity Residential', 'EQT': 'EQT Corporation', 'ERIE': 'Erie Indemnity', 'ES': 'Eversource', 'ESS': 'Essex Property Trust', 'ETN': 'Eaton Corporation', 'ETR': 'Entergy', 'EVRG': 'Evergy', 'EW': 'Edwards Lifesciences', 'EXC': 'Exelon', 'EXE': 'Expand Energy Corporation', 'EXPD': 'Expeditors', 'EXPE': 'Expedia Group', 'EXR': 'Extra Space Storage', 'F': 'Ford Motor Company', 'FANG': 'Diamondback Energy', 'FAST': 'Fastenal', 'FCX': 'Freeport-McMoRan', 'FDS': 'FactSet', 'FDX': 'FedEx', 'FE': 'FirstEnergy', 'FFIV': 'F5, Inc.', 'FICO': 'Fair Isaac', 'FIS': 'FIS', 'FISV': 'Fiserv', 'FITB': 'Fifth Third Bank', 'FIX': 'Comfort Systems USA', 'FOX': 'Fox Corporation (Class B)', 'FOXA': 'Fox Corporation (Class A)', 'FRT': 'Federal Realty', 'FSLR': 'First Solar', 'FTNT': 'Fortinet', 'FTV': 'Fortive', 'GD': 'General Dynamics', 'GDDY': 'GoDaddy', 'GE': 'GE Aerospace', 'GEHC': 'GE HealthCare', 'GEN': 'Gen Digital', 'GEV': 'GE Vernova', 'GILD': 'Gilead Sciences', 'GIS': 'General Mills', 'GL': 'Globe Life', 'GLW': 'Corning Inc.', 'GM': 'General Motors', 'GNRC': 'Generac', 'GOOG': 'Alphabet Inc. (Class C)', 'GOOGL': 'Alphabet Inc. (Class A)', 'GPC': 'Genuine Parts Company', 'GPN': 'Global Payments', 'GRMN': 'Garmin', 'GS': 'Goldman Sachs', 'GWW': 'W.W. Grainger', 'HAL': 'Halliburton', 'HAS': 'Hasbro', 'HBAN': 'Huntington Bancshares', 'HCA': 'HCA Healthcare', 'HD': 'Home Depot (The)', 'HIG': 'Hartford (The)', 'HII': 'Huntington Ingalls Industries', 'HLT': 'Hilton Worldwide', 'HOLX': 'Hologic', 'HON': 'Honeywell', 'HOOD': 'Robinhood', 'HPE': 'Hewlett Packard Enterprise', 'HPQ': 'HP Inc.', 'HRL': 'Hormel Foods', 'HSIC': 'Henry Schein', 'HST': 'Host Hotels & Resorts', 'HSY': 'The Hershey Company', 'HUBB': 'Hubbell Incorporated', 'HUM': 'Humana', 'HWM': 'Howmet Aerospace', 'IBKR': 'Interactive Brokers', 'IBM': 'IBM', 'ICE': 'Intercontinental Exchange', 'IDXX': 'IDEXX Laboratories', 'IEX': 'IDEX Corporation', 'IFF': 'International Flavors & Fragrances', 'INCY': 'Incyte', 'INTC': 'Intel', 'INTU': 'Intuit', 'INVH': 'Invitation Homes', 'IP': 'International Paper', 'IQV': 'IQVIA', 'IR': 'Ingersoll Rand', 'IRM': 'Iron Mountain', 'ISRG': 'Intuitive Surgical', 'IT': 'Gartner', 'ITW': 'Illinois Tool Works', 'IVZ': 'Invesco', 'J': 'Jacobs Solutions', 'JBHT': 'J.B. Hunt', 'JBL': 'Jabil', 'JCI': 'Johnson Controls', 'JKHY': 'Jack Henry & Associates', 'JNJ': 'Johnson & Johnson', 'JPM': 'JPMorgan Chase', 'KDP': 'Keurig Dr Pepper', 'KEY': 'KeyCorp', 'KEYS': 'Keysight', 'KHC': 'Kraft Heinz', 'KIM': 'Kimco Realty', 'KKR': 'KKR', 'KLAC': 'KLA Corporation', 'KMB': 'Kimberly-Clark', 'KMI': 'Kinder Morgan', 'KO': 'Coca-Cola Company (The)', 'KR': 'Kroger', 'KVUE': 'Kenvue', 'L': 'Loews Corporation', 'LDOS': 'Leidos', 'LEN': 'Lennar', 'LH': 'Labcorp', 'LHX': 'L3Harris', 'LII': 'Lennox International', 'LIN': 'Linde plc', 'LLY': 'Lilly (Eli)', 'LMT': 'Lockheed Martin', 'LNT': 'Alliant Energy', 'LOW': "Lowe's", 'LRCX': 'Lam Research', 'LULU': 'Lululemon Athletica', 'LUV': 'Southwest Airlines', 'LVS': 'Las Vegas Sands', 'LW': 'Lamb Weston', 'LYB': 'LyondellBasell', 'LYV': 'Live Nation Entertainment', 'MA': 'Mastercard', 'MAA': 'Mid-America Apartment Communities', 'MAR': 'Marriott International', 'MAS': 'Masco', 'MCD': "McDonald's", 'MCHP': 'Microchip Technology', 'MCK': 'McKesson', 'MCO': "Moody's Corporation", 'MDLZ': 'Mondelez International', 'MDT': 'Medtronic', 'MET': 'MetLife', 'META': 'Meta Platforms', 'MGM': 'MGM Resorts', 'MKC': 'McCormick & Company', 'MLM': 'Martin Marietta Materials', 'MMM': '3M', 'MNST': 'Monster Beverage', 'MO': 'Altria', 'MOH': 'Molina Healthcare', 'MOS': 'Mosaic Company (The)', 'MPC': 'Marathon Petroleum', 'MPWR': 'Monolithic Power Systems', 'MRK': 'Merck & Co.', 'MRNA': 'Moderna', 'MRSH': 'Marsh (formerly Marsh McLennan)', 'MS': 'Morgan Stanley', 'MSCI': 'MSCI', 'MSFT': 'Microsoft', 'MSI': 'Motorola Solutions', 'MTB': 'M&T Bank', 'MTCH': 'Match Group', 'MTD': 'Mettler Toledo', 'MU': 'Micron Technology', 'NCLH': 'Norwegian Cruise Line Holdings', 'NDAQ': 'Nasdaq, Inc.', 'NDSN': 'Nordson Corporation', 'NEE': 'NextEra Energy', 'NEM': 'Newmont', 'NFLX': 'Netflix', 'NI': 'NiSource', 'NKE': 'Nike, Inc.', 'NOC': 'Northrop Grumman', 'NOW': 'ServiceNow', 'NRG': 'NRG Energy', 'NSC': 'Norfolk Southern', 'NTAP': 'NetApp', 'NTRS': 'Northern Trust', 'NUE': 'Nucor', 'NVDA': 'Nvidia', 'NVR': 'NVR, Inc.', 'NWS': 'News Corp (Class B)', 'NWSA': 'News Corp (Class A)', 'NXPI': 'NXP Semiconductors', 'O': 'Realty Income', 'ODFL': 'Old Dominion Freight Line', 'OKE': 'ONEOK', 'OMC': 'Omnicom Group', 'ON': 'ON Semiconductor', 'ORCL': 'Oracle Corporation', 'ORLY': "O'Reilly Auto Parts", 'OTIS': 'Otis Worldwide', 'OXY': 'Occidental Petroleum', 'PANW': 'Palo Alto Networks', 'PAYC': 'Paycom', 'PAYX': 'Paychex', 'PCAR': 'PACCAR', 'PCG': 'PG&E Corporation', 'PEG': 'Public Service Enterprise Group', 'PEP': 'PepsiCo', 'PFE': 'Pfizer', 'PFG': 'Principal Financial Group', 'PG': 'Procter & Gamble', 'PGR': 'Progressive Corporation', 'PH': 'Parker-Hannifin', 'PHM': 'PulteGroup', 'PKG': 'Packaging Corporation of America', 'PLD': 'Prologis', 'PLTR': 'Palantir Technologies', 'PM': 'Philip Morris International', 'PNC': 'PNC Financial Services', 'PNR': 'Pentair', 'PNW': 'Pinnacle West', 'PODD': 'Insulet', 'POOL': 'Pool Corporation', 'PPG': 'PPG Industries', 'PPL': 'PPL Corporation', 'PRU': 'Prudential Financial', 'PSA': 'Public Storage', 'PSKY': 'Paramount Skydance Corporation', 'PSX': 'Phillips 66', 'PTC': 'PTC', 'PWR': 'Quanta Services', 'PYPL': 'PayPal', 'Q': 'Qnity Electronics, Inc.', 'QCOM': 'Qualcomm', 'RCL': 'Royal Caribbean Group', 'REG': 'Regency Centers', 'REGN': 'Regeneron', 'RF': 'Regions Financial', 'RJF': 'Raymond James', 'RL': 'Ralph Lauren', 'RMD': 'ResMed', 'ROK': 'Rockwell Automation', 'ROL': 'Rollins, Inc.', 'ROP': 'Roper Technologies', 'ROST': 'Ross Stores', 'RSG': 'Republic Services', 'RTX': 'RTX Corporation', 'RVTY': 'Revvity', 'SBAC': 'SBA Communications', 'SBUX': 'Starbucks', 'SCHW': 'Charles Schwab Corporation', 'SHW': 'Sherwin-Williams', 'SJM': 'J.M. Smucker Company (The)', 'SLB': 'Schlumberger', 'SMCI': 'Super Micro Computer', 'SNA': 'Snap-on', 'SNDK': 'Sandisk Corporation', 'SNPS': 'Synopsys', 'SO': 'Southern Company', 'SOLV': 'Solventum', 'SPG': 'Simon Property Group', 'SPGI': 'S&P Global', 'SRE': 'Sempra Energy', 'STE': 'STERIS', 'STLD': 'Steel Dynamics', 'STT': 'State Street Corporation', 'STX': 'Seagate Technology', 'STZ': 'Constellation Brands', 'SW': 'Smurfit Westrock plc', 'SWK': 'Stanley Black & Decker', 'SWKS': 'Skyworks Solutions', 'SYF': 'Synchrony Financial', 'SYK': 'Stryker Corporation', 'SYY': 'Sysco', 'T': 'AT&T', 'TAP': 'Molson Coors', 'TDG': 'TransDigm Group', 'TDY': 'Teledyne Technologies', 'TECH': 'Bio-Techne', 'TEL': 'TE Connectivity', 'TER': 'Teradyne', 'TFC': 'Truist', 'TGT': 'Target Corporation', 'TJX': 'TJX Companies', 'TKO': 'TKO Group Holdings', 'TMO': 'Thermo Fisher Scientific', 'TMUS': 'T-Mobile US', 'TPL': 'Texas Pacific Land', 'TPR': 'Tapestry, Inc.', 'TRGP': 'Targa Resources', 'TRMB': 'Trimble', 'TROW': 'T. Rowe Price', 'TRV': 'Travelers Companies (The)', 'TSCO': 'Tractor Supply', 'TSLA': 'Tesla, Inc.', 'TSN': 'Tyson Foods', 'TT': 'Trane Technologies', 'TTD': 'The Trade Desk, Inc.', 'TTWO': 'Take-Two Interactive', 'TXN': 'Texas Instruments', 'TXT': 'Textron', 'TYL': 'Tyler Technologies', 'UAL': 'United Airlines', 'UBER': 'Uber', 'UDR': 'UDR, Inc.', 'UHS': 'Universal Health Services', 'ULTA': 'Ulta Beauty', 'UNH': 'UnitedHealth Group', 'UNP': 'Union Pacific Corporation', 'UPS': 'UPS', 'URI': 'United Rentals', 'USB': 'U.S. Bancorp', 'V': 'Visa Inc.', 'VICI': 'VICI Properties', 'VLO': 'Valero Energy', 'VLTO': 'Veralto', 'VMC': 'Vulcan Materials', 'VRSK': 'Verisk', 'VRSN': 'Verisign', 'VRTX': 'Vertex Pharmaceuticals', 'VST': 'Vistra', 'VTR': 'Ventas', 'VTRS': 'Viatris', 'VZ': 'Verizon', 'WAB': 'Wabtec', 'WAT': 'Waters Corporation', 'WBD': 'Warner Bros. Discovery', 'WDAY': 'Workday', 'WDC': 'Western Digital', 'WEC': 'WEC Energy Group', 'WELL': 'Welltower', 'WFC': 'Wells Fargo', 'WM': 'Waste Management', 'WMB': 'Williams Companies', 'WMT': 'Walmart', 'WRB': 'W. R. Berkley Corporation', 'WSM': 'Williams-Sonoma', 'WST': 'West Pharmaceutical Services', 'WTW': 'Willis Towers Watson', 'WY': 'Weyerhaeuser', 'WYNN': 'Wynn Resorts', 'XEL': 'Xcel Energy', 'XOM': 'ExxonMobil', 'XYL': 'Xylem Inc.', 'XYZ': 'Block, Inc.', 'YUM': 'Yum! Brands', 'ZBH': 'Zimmer Biomet', 'ZBRA': 'Zebra Technologies', 'ZTS': 'Zoetis', 'GLD': 'SPDR Gold Shares', 'ITA': 'iShares U.S. Aerospace & Defense ETF', 'IWM': 'iShares Russell 2000 ETF', 'QQQ': 'Invesco QQQ Trust', 'SPY': 'SPDR S&P 500 ETF Trust'}
ETFS = {"SPY", "QQQ", "IWM", "GLD", "ITA"}

# Massive generally uses dot notation for these share classes.
MASSIVE_SYMBOL_OVERRIDES = {"BRK-B": "BRK.B", "BF-B": "BF.B"}

MASSIVE_BASE = "https://api.massive.com"


@dataclass
class Config:
    bb_lookback: int = 20
    bb_std: float = 2.0
    bw_percentile_window: int = 252
    squeeze_threshold_pct: float = 20.0
    recent_squeeze_days: int = 5
    expansion_min_growth: float = 0.0
    atr_period: int = 14
    rsi_period: int = 14
    ma50: int = 50
    ma200: int = 200
    volume_window: int = 20
    s1_y_window: int = 5
    s1_pullback_window: int = 10
    s1_confirmation_window: int = 5
    s1_confirmation_mode: str = "prev_high"
    s1_pullback_fraction: float = 0.5
    s1_cooldown: int = 5
    s2_recovery_window: int = 10
    s2_cooldown: int = 5
    history_calendar_days: int = 650
    request_timeout: int = 40
    max_retries: int = 7
    min_seconds_between_calls: float = 0.15


# ------------------------------ HTTP helpers ---------------------------------

def request_json(url: str, params: dict, cfg: Config) -> dict:
    """GET JSON with retry/backoff for 429/5xx."""
    last_err = None
    for attempt in range(cfg.max_retries):
        try:
            r = requests.get(url, params=params, timeout=cfg.request_timeout)
            if r.status_code == 429:
                wait = min(60, 2 ** attempt)
                retry_after = r.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after))
                    except Exception:
                        pass
                time.sleep(wait)
                continue
            if 500 <= r.status_code < 600:
                time.sleep(min(30, 2 ** attempt))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt + 1 < cfg.max_retries:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"Request failed after retries: {url}: {last_err}")


def massive_symbol(ticker: str) -> str:
    return MASSIVE_SYMBOL_OVERRIDES.get(ticker, ticker)


def fetch_massive_daily(ticker: str, api_key: str, cfg: Config, end_date: date) -> pd.DataFrame:
    """Fetch enough adjusted daily OHLCV from Massive for indicators/state machine."""
    symbol = massive_symbol(ticker)
    start_date = end_date - timedelta(days=cfg.history_calendar_days)
    url = (
        f"{MASSIVE_BASE}/v2/aggs/ticker/{symbol}/range/1/day/"
        f"{start_date.isoformat()}/{end_date.isoformat()}"
    )
    data = request_json(url, {
        "adjusted": "true",
        "sort": "asc",
        "limit": 5000,
        "apiKey": api_key,
    }, cfg)
    rows = data.get("results") or []
    if not rows:
        raise ValueError("No OHLCV returned")
    d = pd.DataFrame(rows)
    required = {"t", "o", "h", "l", "c", "v"}
    if not required.issubset(d.columns):
        raise ValueError(f"Missing aggregate fields: {sorted(required - set(d.columns))}")
    out = pd.DataFrame({
        "Date": pd.to_datetime(d["t"], unit="ms", utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize(),
        "Open": pd.to_numeric(d["o"], errors="coerce"),
        "High": pd.to_numeric(d["h"], errors="coerce"),
        "Low": pd.to_numeric(d["l"], errors="coerce"),
        "Close": pd.to_numeric(d["c"], errors="coerce"),
        "Volume": pd.to_numeric(d["v"], errors="coerce"),
    })
    out = out.dropna(subset=["Date", "Open", "High", "Low", "Close"]).drop_duplicates("Date", keep="last")
    out = out.sort_values("Date").reset_index(drop=True)
    if len(out) < 280:
        raise ValueError(f"Insufficient history ({len(out)} bars)")
    time.sleep(cfg.min_seconds_between_calls)
    return out


# ----------------------------- Indicators ------------------------------------

def rolling_percentile_last(arr: np.ndarray) -> float:
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return np.nan
    last = arr[-1]
    return 100.0 * np.mean(arr <= last)


def compute_indicators(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    d = df.copy()
    close, high, low = d["Close"], d["High"], d["Low"]

    d["BB_Mid"] = close.rolling(cfg.bb_lookback, min_periods=cfg.bb_lookback).mean()
    sd = close.rolling(cfg.bb_lookback, min_periods=cfg.bb_lookback).std(ddof=0)
    d["BB_Upper"] = d["BB_Mid"] + cfg.bb_std * sd
    d["BB_Lower"] = d["BB_Mid"] - cfg.bb_std * sd
    d["BandWidth"] = (d["BB_Upper"] - d["BB_Lower"]) / d["BB_Mid"].replace(0, np.nan)

    d["BW_Percentile"] = d["BandWidth"].rolling(
        cfg.bw_percentile_window,
        min_periods=max(60, min(cfg.bw_percentile_window, 126)),
    ).apply(rolling_percentile_last, raw=True)
    d["Recent_Squeeze_Percentile"] = (
        d["BW_Percentile"].shift(1).rolling(cfg.recent_squeeze_days, min_periods=1).min()
    )
    d["BW_Growth_1D"] = d["BandWidth"].pct_change(fill_method=None)
    d["Expansion"] = (
        (d["Recent_Squeeze_Percentile"] <= cfg.squeeze_threshold_pct)
        & (d["BW_Growth_1D"] > cfg.expansion_min_growth)
    )

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    d["ATR"] = tr.rolling(cfg.atr_period, min_periods=cfg.atr_period).mean()
    d["ATR_Pct"] = d["ATR"] / close.replace(0, np.nan)

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/cfg.rsi_period, min_periods=cfg.rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/cfg.rsi_period, min_periods=cfg.rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    d["RSI"] = 100 - 100/(1 + rs)
    d.loc[(avg_loss == 0) & (avg_gain > 0), "RSI"] = 100.0
    d.loc[(avg_loss == 0) & (avg_gain == 0), "RSI"] = 50.0

    d["MA50"] = close.rolling(cfg.ma50, min_periods=cfg.ma50).mean()
    d["MA200"] = close.rolling(cfg.ma200, min_periods=cfg.ma200).mean()
    d["MA200_Slope"] = d["MA200"].pct_change(20, fill_method=None)
    d["Above_50DMA"] = close > d["MA50"]
    d["Above_200DMA"] = close > d["MA200"]
    d["Volume_MA20"] = d["Volume"].rolling(cfg.volume_window, min_periods=cfg.volume_window).mean()
    return d


def spy_regime(spy: pd.DataFrame) -> Tuple[str, float, float, float]:
    latest = spy.iloc[-1]
    close = float(latest["Close"])
    ma200 = float(latest["MA200"]) if pd.notna(latest["MA200"]) else np.nan
    slope = float(latest["MA200_Slope"]) if pd.notna(latest["MA200_Slope"]) else np.nan
    if not np.isfinite(ma200) or not np.isfinite(slope):
        return "Unknown", close, ma200, slope
    if close > ma200 and slope > 0:
        return "Bullish", close, ma200, slope
    if close < ma200 and slope < 0:
        return "Bearish", close, ma200, slope
    return "Sideways/Transitional", close, ma200, slope


# ------------------------------ Signal logic ---------------------------------

def confirmation_passes(d: pd.DataFrame, idx: int, mode: str = "prev_high") -> bool:
    if idx <= 0:
        return False
    row, prev = d.iloc[idx], d.iloc[idx-1]
    if mode == "prev_high":
        return bool(row["Close"] > prev["High"])
    if mode == "bullish_close":
        return bool(row["Close"] > row["Open"])
    if mode == "sma5":
        sma5 = d["Close"].rolling(5, min_periods=5).mean().iloc[idx]
        return bool(np.isfinite(sma5) and row["Close"] > sma5)
    raise ValueError(mode)


def detect_strategy1(df: pd.DataFrame, cfg: Config) -> List[dict]:
    """Same real-time Strategy 1 state machine as the historical backtest."""
    signals: List[dict] = []
    n = len(df)
    last_signal_idx = -10**9
    breakout = (df["Expansion"] & (df["Close"] > df["BB_Upper"]).fillna(False)).to_numpy()
    for i in np.flatnonzero(breakout):
        if i - last_signal_idx <= cfg.s1_cooldown or i + 2 >= n:
            continue
        br = df.iloc[i]
        x_upper, x_close, x_low = float(br["BB_Upper"]), float(br["Close"]), float(br["Low"])
        if not all(np.isfinite(v) and v > 0 for v in [x_upper, x_close, x_low]):
            continue
        peak_price = float(br["High"])
        peak_idx = i
        confirm_peak_idx = None
        for j in range(i+1, min(n-1, i+cfg.s1_y_window)+1):
            h = float(df.iloc[j]["High"])
            if np.isfinite(h) and h > peak_price:
                peak_price, peak_idx = h, j
            if j > peak_idx:
                cur, prev = df.iloc[j], df.iloc[j-1]
                if cur["High"] < prev["High"] and cur["Close"] < prev["Close"]:
                    confirm_peak_idx = j
                    break
        if confirm_peak_idx is None or peak_price <= x_upper:
            continue
        pullback_level = peak_price - cfg.s1_pullback_fraction * (peak_price - x_upper)
        pullback_idx = None
        for j in range(confirm_peak_idx+1, min(n-1, confirm_peak_idx+cfg.s1_pullback_window)+1):
            if df.iloc[j]["Low"] <= pullback_level:
                pullback_idx = j
                break
        if pullback_idx is None:
            continue
        signal_idx = None
        for j in range(pullback_idx, min(n-1, pullback_idx+cfg.s1_confirmation_window)+1):
            if confirmation_passes(df, j, cfg.s1_confirmation_mode):
                signal_idx = j
                break
        if signal_idx is None:
            continue
        sr = df.iloc[signal_idx]
        signals.append({
            "strategy": "Strategy1", "signal_idx": int(signal_idx), "signal_date": sr["Date"],
            "x": x_upper, "x_upper": x_upper, "x_close": x_close, "x_low": x_low,
            "squeeze_percentile": br.get("Recent_Squeeze_Percentile", np.nan),
            "expansion_growth_1d": br.get("BW_Growth_1D", np.nan),
        })
        last_signal_idx = signal_idx
    return signals


def detect_strategy2(df: pd.DataFrame, cfg: Config) -> List[dict]:
    """Same Strategy 2 logic as the historical backtest."""
    signals: List[dict] = []
    n = len(df)
    last_signal_idx = -10**9
    setup = (df["Expansion"] & (df["Low"] <= df["BB_Lower"]).fillna(False)).to_numpy()
    for i in np.flatnonzero(setup):
        if i - last_signal_idx <= cfg.s2_cooldown or i + 1 >= n:
            continue
        x = float(df.iloc[i]["Low"])
        if not np.isfinite(x) or x <= 0:
            continue
        signal_idx = None
        for j in range(i+1, min(n-1, i+cfg.s2_recovery_window)+1):
            cur, prev = df.iloc[j], df.iloc[j-1]
            if np.isfinite(cur["BB_Mid"]) and prev["Close"] <= prev["BB_Mid"] and cur["Close"] > cur["BB_Mid"]:
                signal_idx = j
                break
        if signal_idx is None:
            continue
        sr = df.iloc[signal_idx]
        signals.append({
            "strategy": "Strategy2", "signal_idx": int(signal_idx), "signal_date": sr["Date"],
            "x": x, "x_upper": np.nan, "x_close": np.nan, "x_low": x,
            "squeeze_percentile": df.iloc[i].get("Recent_Squeeze_Percentile", np.nan),
            "expansion_growth_1d": df.iloc[i].get("BW_Growth_1D", np.nan),
        })
        last_signal_idx = signal_idx
    return signals


# ------------------------- Historical effectiveness --------------------------

def load_effectiveness(path: Path) -> Dict[Tuple[str, str], dict]:
    if not path.exists():
        raise FileNotFoundError(f"Missing historical effectiveness file: {path}")
    df = pd.read_csv(path)
    required = {"ticker", "strategy", "classification"}
    if not required.issubset(df.columns):
        raise ValueError(f"stock_effectiveness.csv missing {required - set(df.columns)}")

    # The historical script used this column name even though its content is the selected method string.
    method_col = None
    for c in ["is_selected_strike_method", "selected_strike_method", "best_robust_strike_method"]:
        if c in df.columns:
            method_col = c
            break

    out = {}
    for _, r in df.iterrows():
        key = (str(r["ticker"]).upper(), str(r["strategy"]))
        out[key] = {
            "classification": str(r.get("classification", "Insufficient Data")),
            "oos_signal_count": int(r.get("oos_signal_count", 0)) if pd.notna(r.get("oos_signal_count", np.nan)) else 0,
            "oos_touch_pct": r.get("oos_touch_pct", np.nan),
            "oos_breach_pct": r.get("oos_breach_pct", np.nan),
            "oos_terminal_itm_pct": r.get("oos_terminal_itm_pct", np.nan),
            "oos_median_forward_return": r.get("oos_median_forward_return", np.nan),
            "selected_method": str(r.get(method_col, "")) if method_col else "",
        }
    return out


def strike_from_method(method: str, provisional_entry: float, atr: float, signal: dict) -> float:
    m = (method or "").strip().upper()
    if m.startswith("OTM_") and m.endswith("PCT"):
        try:
            p = float(m.split("_")[1].replace("PCT", "")) / 100.0
            return provisional_entry * (1 - p)
        except Exception:
            pass
    if m.startswith("ATR_"):
        try:
            mult = float(m.split("_", 1)[1])
            return provisional_entry - mult * atr
        except Exception:
            pass
    if m in {"TECH_X", "X", "TECHNICAL_X"}:
        return float(signal.get("x", np.nan))
    return np.nan


# ------------------------------ Earnings -------------------------------------

def get_next_earnings_massive(ticker: str, api_key: str, cfg: Config, asof: date) -> Optional[dict]:
    if ticker in ETFS:
        return {"date": None, "days": None, "status": "N/A — ETF", "source": "ETF"}
    url = f"{MASSIVE_BASE}/benzinga/v1/earnings"
    params = {
        "ticker": massive_symbol(ticker),
        "date.gte": asof.isoformat(),
        "sort": "date.asc",
        "limit": 10,
        "apiKey": api_key,
    }
    try:
        data = request_json(url, params, cfg)
    except Exception:
        return None
    future = []
    for r in data.get("results") or []:
        try:
            d = pd.Timestamp(r.get("date")).date()
            if d >= asof:
                future.append((d, r))
        except Exception:
            continue
    if not future:
        return None
    d, r = min(future, key=lambda x: x[0])
    return {
        "date": d, "days": (d-asof).days,
        "status": str(r.get("date_status", "unknown")), "source": "Massive/Benzinga"
    }


def get_next_earnings_yfinance(ticker: str, asof: date) -> Optional[dict]:
    if ticker in ETFS:
        return {"date": None, "days": None, "status": "N/A — ETF", "source": "ETF"}
    try:
        import yfinance as yf
        ed = yf.Ticker(ticker).get_earnings_dates(limit=8)
        if ed is None or len(ed) == 0:
            return None
        idx = pd.to_datetime(ed.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        dates = sorted({x.date() for x in idx if x.date() >= asof})
        if not dates:
            return None
        d = dates[0]
        return {"date": d, "days": (d-asof).days, "status": "provider date", "source": "yfinance fallback"}
    except Exception:
        return None


def get_next_earnings(ticker: str, api_key: str, cfg: Config, asof: date) -> dict:
    if ticker in ETFS:
        return {"date": None, "days": None, "status": "N/A — ETF", "source": "ETF"}
    x = get_next_earnings_massive(ticker, api_key, cfg, asof)
    if x:
        return x
    x = get_next_earnings_yfinance(ticker, asof)
    if x:
        return x
    return {"date": None, "days": None, "status": "Unknown", "source": "Unavailable"}


# ------------------------------- Chart ---------------------------------------

def make_candidate_chart(df: pd.DataFrame, ticker: str, company: str, signal: dict,
                         strike: float, hist: dict, regime: str, earnings: dict,
                         output_path: Path) -> None:
    """
    6-month OHLC chart.
    - Bollinger Bands have NO legend entries.
    - Proposed strike runs across the full chart and is labelled with its price.
    - Signal is labelled with exact date and price.
    - Technical X is labelled with its price.
    """
    sig_idx = int(signal["signal_idx"])
    start = max(0, len(df) - 126)
    w = df.iloc[start:].copy().reset_index(drop=True)
    # Translate original signal index into window coordinates.
    local_sig_idx = sig_idx - start
    if local_sig_idx < 0 or local_sig_idx >= len(w):
        return

    x = mdates.date2num(w["Date"].to_numpy(dtype="datetime64[ns]"))
    fig, ax = plt.subplots(figsize=(15, 8))

    # Minimal OHLC marks. No forced colors/styles; matplotlib defaults are used.
    for xi, o, h, l, c in zip(x, w["Open"], w["High"], w["Low"], w["Close"]):
        ax.vlines(xi, l, h, linewidth=0.65)
        ax.hlines(o, xi-0.18, xi, linewidth=0.8)
        ax.hlines(c, xi, xi+0.18, linewidth=0.8)

    # Bollinger lines: deliberately no legend labels.
    ax.plot(x, w["BB_Upper"], linewidth=1.0)
    ax.plot(x, w["BB_Mid"], linewidth=1.0)
    ax.plot(x, w["BB_Lower"], linewidth=1.0)

    # Direct right-edge BB labels instead of a legend.
    last_x = x[-1]
    pad_x = max((x[-1]-x[0]) * 0.012, 1.0)
    for col, label in [("BB_Upper", "Upper BB"), ("BB_Mid", "Middle BB"), ("BB_Lower", "Lower BB")]:
        v = w[col].iloc[-1]
        if pd.notna(v):
            ax.text(last_x + pad_x, float(v), f"{label} {float(v):.2f}", va="center", fontsize=8)

    x_level = float(signal.get("x", np.nan))
    if np.isfinite(x_level):
        ax.axhline(x_level, linewidth=1.3, linestyle="--")
        ax.text(x[0], x_level, f" X = {x_level:.2f}", va="bottom", fontsize=9)

    if np.isfinite(strike):
        # REQUIRED: proposed strike across entire chart.
        ax.axhline(strike, linewidth=3.5)
        ax.text(
            x[0] + (x[-1]-x[0]) * 0.02,
            strike,
            f" PROPOSED PUT STRIKE = {strike:.2f} ",
            va="bottom", fontsize=11, fontweight="bold"
        )

    sig_row = df.iloc[sig_idx]
    sig_date = pd.Timestamp(signal["signal_date"])
    sig_price = float(sig_row["Close"])
    sig_x = mdates.date2num(sig_date.to_pydatetime())
    ax.scatter([sig_x], [sig_price], s=90, zorder=6)
    ax.annotate(
        f"{signal['strategy']} SIGNAL\n{sig_date:%Y-%m-%d}\nPrice = {sig_price:.2f}",
        xy=(sig_x, sig_price),
        xytext=(18, 28), textcoords="offset points",
        arrowprops={"arrowstyle": "->"},
        fontsize=10, fontweight="bold"
    )

    # Vertical signal date guide.
    ax.axvline(sig_x, linewidth=0.8, linestyle=":")

    earn_date = earnings.get("date")
    earn_txt = "ETF — no earnings" if ticker in ETFS else (
        f"Next earnings: {earn_date} ({earnings.get('days')}d)" if earn_date else "Next earnings: Unknown"
    )
    if earnings.get("days") is not None and earnings.get("days") <= 30:
        earn_txt += " | EARNINGS <30D"

    title = (
        f"{ticker} — {company} | {signal['strategy']} | {hist.get('classification')} | SPY: {regime}\n"
        f"Signal {sig_date:%Y-%m-%d} @ {sig_price:.2f} | Proposed strike {strike:.2f} | {earn_txt}"
    )
    ax.set_title(title)
    ax.set_ylabel("Price")
    ax.set_xlabel("Date")
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.autofmt_xdate()
    ax.grid(alpha=0.18)
    # No legend: all critical values are annotated directly.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=170, bbox_inches="tight")
    plt.close(fig)


# ------------------------------ Telegram -------------------------------------

def telegram_send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=30)
    r.raise_for_status()


def telegram_send_photo(token: str, chat_id: str, photo_path: Path, caption: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    with photo_path.open("rb") as f:
        r = requests.post(url, data={"chat_id": chat_id, "caption": caption[:1024]}, files={"photo": f}, timeout=60)
    r.raise_for_status()


def telegram_send_document(token: str, chat_id: str, file_path: Path, caption: str = "") -> None:
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with file_path.open("rb") as f:
        r = requests.post(url, data={"chat_id": chat_id, "caption": caption[:1024]}, files={"document": f}, timeout=90)
    r.raise_for_status()


# ----------------------------- Output helpers --------------------------------

def pct(v) -> str:
    try:
        if pd.isna(v): return "N/A"
        return f"{100*float(v):.1f}%"
    except Exception:
        return "N/A"


def current_signal(signals: List[dict], latest_date: pd.Timestamp) -> Optional[dict]:
    hits = [s for s in signals if pd.Timestamp(s["signal_date"]).normalize() == latest_date.normalize()]
    return hits[-1] if hits else None


def candidate_caption(row: dict) -> str:
    e = row.get("next_earnings_date") or "Unknown"
    ew = "YES" if row.get("earnings_within_30_days") is True else ("NO" if row.get("earnings_within_30_days") is False else "UNKNOWN")
    return (
        f"{row['ticker']} | {row['strategy']} | {row['classification']} | SPY {row['spy_regime']}\n"
        f"Signal: {row['signal_date']} @ {row['signal_close']:.2f}\n"
        f"Provisional entry ref: {row['provisional_entry_reference']:.2f}\n"
        f"Strike method: {row['historical_strike_method']} | Proposed strike: {row['proposed_strike']:.2f}\n"
        f"Hist OOS: {row['historical_oos_signals']} | Touch {row['historical_touch_pct_text']} | Terminal ITM {row['historical_terminal_itm_pct_text']}\n"
        f"Earnings: {e} | within 30d: {ew}"
    )


def write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("status\nNo rows\n")
        return
    pd.DataFrame(rows).to_csv(path, index=False)


# -------------------------------- Main ----------------------------------------

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--effectiveness-file", default="stock_effectiveness.csv")
    p.add_argument("--output-root", default="output")
    p.add_argument("--asof", default=None, help="Optional YYYY-MM-DD for testing")
    p.add_argument("--max-tickers", type=int, default=0, help="0=all; useful for tests")
    p.add_argument("--no-telegram", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config()
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not api_key:
        print("ERROR: MASSIVE_API_KEY is not set", file=sys.stderr)
        return 2
    if not args.no_telegram and (not tg_token or not tg_chat):
        print("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set", file=sys.stderr)
        return 2

    if args.asof:
        asof = pd.Timestamp(args.asof).date()
    else:
        from zoneinfo import ZoneInfo
        asof = datetime.now(ZoneInfo("Asia/Singapore")).date()
    outdir = Path(args.output_root) / asof.isoformat()
    chart_dir = outdir / "charts"
    outdir.mkdir(parents=True, exist_ok=True)
    eff = load_effectiveness(Path(args.effectiveness_file))

    errors, rejected, candidates = [], [], []
    strategy_signal_counts = {"Strategy1": 0, "Strategy2": 0}

    # SPY first: its latest bar defines the data date and market regime.
    print("Loading SPY for market regime...")
    spy_raw = fetch_massive_daily("SPY", api_key, cfg, asof)
    spy = compute_indicators(spy_raw, cfg)
    regime, spy_close, spy_ma200, spy_slope = spy_regime(spy)
    latest_market_date = pd.Timestamp(spy.iloc[-1]["Date"])
    data_fresh = (asof - latest_market_date.date()).days <= 4
    print(f"SPY {latest_market_date.date()} close={spy_close:.2f} MA200={spy_ma200:.2f} slope20={spy_slope:.4%} regime={regime}")

    tickers = list(STOCKS.items())
    if args.max_tickers > 0:
        # Ensure SPY stays included for a test run.
        tickers = tickers[:args.max_tickers]
    total = len(tickers)

    for idx, (ticker, company) in enumerate(tickers, 1):
        try:
            if ticker == "SPY":
                d = spy.copy()
            else:
                d = compute_indicators(fetch_massive_daily(ticker, api_key, cfg, asof), cfg)
            latest = d.iloc[-1]
            data_date = pd.Timestamp(latest["Date"])
            if data_date.normalize() != latest_market_date.normalize():
                rejected.append({"date": data_date.date(), "ticker": ticker, "company": company, "strategy": "N/A", "reason": f"stale_vs_SPY_{latest_market_date.date()}"})
                print(f"[{idx}/{total}] {ticker}: stale {data_date.date()} (SPY {latest_market_date.date()})")
                continue

            s1 = current_signal(detect_strategy1(d, cfg), data_date)
            s2 = current_signal(detect_strategy2(d, cfg), data_date)
            for strategy, sig in [("Strategy1", s1), ("Strategy2", s2)]:
                if sig is None:
                    continue
                strategy_signal_counts[strategy] += 1
                hist = eff.get((ticker, strategy), {
                    "classification": "Insufficient Data", "oos_signal_count": 0,
                    "oos_touch_pct": np.nan, "oos_breach_pct": np.nan,
                    "oos_terminal_itm_pct": np.nan, "oos_median_forward_return": np.nan,
                    "selected_method": ""
                })
                classification = hist["classification"]
                if classification != "Effective":
                    rejected.append({"date": data_date.date(), "ticker": ticker, "company": company, "strategy": strategy, "classification": classification, "reason": f"historical_classification_{classification}"})
                    continue
                if regime == "Bearish":
                    rejected.append({"date": data_date.date(), "ticker": ticker, "company": company, "strategy": strategy, "classification": classification, "reason": "SPY_Bearish"})
                    continue
                if regime == "Unknown":
                    rejected.append({"date": data_date.date(), "ticker": ticker, "company": company, "strategy": strategy, "classification": classification, "reason": "SPY_regime_unknown"})
                    continue

                signal_idx = int(sig["signal_idx"])
                signal_row = d.iloc[signal_idx]
                signal_close = float(signal_row["Close"])
                atr = float(signal_row["ATR"])
                method = hist.get("selected_method", "")
                strike = strike_from_method(method, signal_close, atr, sig)
                if not np.isfinite(strike) or strike <= 0:
                    rejected.append({"date": data_date.date(), "ticker": ticker, "company": company, "strategy": strategy, "classification": classification, "reason": f"cannot_compute_strike_method_{method}"})
                    continue

                earnings = get_next_earnings(ticker, api_key, cfg, data_date.date())
                earn_date = earnings.get("date")
                earn_days = earnings.get("days")
                earn_warn = (earn_days is not None and earn_days <= 30)

                row = {
                    "date": data_date.date(), "ticker": ticker, "company": company,
                    "asset_type": "ETF" if ticker in ETFS else "Stock",
                    "strategy": strategy, "classification": classification,
                    "signal_date": pd.Timestamp(sig["signal_date"]).date(),
                    "signal_close": signal_close,
                    "entry_status": "Next Trading Day Open",
                    "provisional_entry_reference": signal_close,
                    "technical_x": float(sig.get("x", np.nan)),
                    "historical_strike_method": method,
                    "proposed_strike": float(strike),
                    "atr14_dollars": atr,
                    "atr14_pct": float(signal_row["ATR_Pct"]) if pd.notna(signal_row["ATR_Pct"]) else np.nan,
                    "bb_upper": float(signal_row["BB_Upper"]), "bb_mid": float(signal_row["BB_Mid"]), "bb_lower": float(signal_row["BB_Lower"]),
                    "squeeze_percentile": sig.get("squeeze_percentile", np.nan),
                    "expansion_growth_1d": sig.get("expansion_growth_1d", np.nan),
                    "rsi14": float(signal_row["RSI"]) if pd.notna(signal_row["RSI"]) else np.nan,
                    "above_50dma": bool(signal_row["Above_50DMA"]), "above_200dma": bool(signal_row["Above_200DMA"]),
                    "historical_oos_signals": hist.get("oos_signal_count", 0),
                    "historical_oos_touch_pct": hist.get("oos_touch_pct", np.nan),
                    "historical_oos_breach_pct": hist.get("oos_breach_pct", np.nan),
                    "historical_oos_terminal_itm_pct": hist.get("oos_terminal_itm_pct", np.nan),
                    "historical_oos_median_forward_return": hist.get("oos_median_forward_return", np.nan),
                    "historical_touch_pct_text": pct(hist.get("oos_touch_pct", np.nan)),
                    "historical_terminal_itm_pct_text": pct(hist.get("oos_terminal_itm_pct", np.nan)),
                    "spy_regime": regime, "spy_close": spy_close, "spy_ma200": spy_ma200, "spy_ma200_slope20": spy_slope,
                    "next_earnings_date": str(earn_date) if earn_date else ("N/A — ETF" if ticker in ETFS else "Unknown"),
                    "days_until_earnings": earn_days,
                    "earnings_within_30_days": earn_warn if earn_days is not None else None,
                    "earnings_date_status": earnings.get("status"), "earnings_source": earnings.get("source"),
                    "candidate_status": "QUALIFIED",
                }
                candidates.append(row)
                chart_path = chart_dir / f"{ticker}_{strategy}.png"
                make_candidate_chart(d, ticker, company, sig, strike, hist, regime, earnings, chart_path)
                row["chart_path"] = str(chart_path)
                print(f">>> QUALIFIED: {ticker} | {strategy} | Effective | {regime} | Strike={strike:.2f}")

            if idx == 1 or idx % 25 == 0 or idx == total:
                print(f"[{idx}/{total}] {ticker} | S1={bool(s1)} | S2={bool(s2)}")
        except Exception as e:
            errors.append({
                "ticker": ticker, "stage": "daily_screen", "error_type": type(e).__name__,
                "error": str(e), "traceback_tail": " | ".join(traceback.format_exc().strip().splitlines()[-3:])
            })
            print(f"WARNING {ticker}: {type(e).__name__}: {e}")

    cand_csv = outdir / "qualified_candidates.csv"
    rej_csv = outdir / "rejected_candidates.csv"
    err_csv = outdir / "errors.csv"
    write_csv(cand_csv, candidates)
    write_csv(rej_csv, rejected)
    write_csv(err_csv, errors)

    summary_lines = [
        f"Bollinger Put Screen — {latest_market_date.date()}",
        "",
        "MARKET ENVIRONMENT",
        f"SPY Close: {spy_close:.2f}",
        f"SPY 200DMA: {spy_ma200:.2f}",
        f"SPY 200DMA 20-day slope: {spy_slope:.2%}",
        f"SPY regime: {regime}",
        f"Latest market-data date: {latest_market_date.date()}",
        f"Data fresh: {'YES' if data_fresh else 'NO — WARNING: MARKET DATA MAY BE STALE'}",
        f"Trading filter allowed: {'YES' if regime in {'Bullish','Sideways/Transitional'} else 'NO'}",
        "",
        f"Current Strategy 1 signals: {strategy_signal_counts['Strategy1']}",
        f"Current Strategy 2 signals: {strategy_signal_counts['Strategy2']}",
        f"Qualified candidates: {len(candidates)}",
        f"Errors: {len(errors)}",
    ]
    if candidates:
        summary_lines += ["", "QUALIFIED CANDIDATES"]
        for r in candidates:
            earn_flag = " ⚠ EARNINGS <30D" if r.get("earnings_within_30_days") is True else ""
            summary_lines += [
                f"{r['ticker']} | {r['strategy']} | Effective | Strike {r['proposed_strike']:.2f} | "
                f"Hist ITM {r['historical_terminal_itm_pct_text']} | Earnings {r['next_earnings_date']}{earn_flag}"
            ]
    else:
        summary_lines += ["", "No stocks or ETFs fit the criteria today."]

    summary_text = "\n".join(summary_lines)
    summary_path = outdir / "daily_summary.txt"
    summary_path.write_text(summary_text, encoding="utf-8")
    print("\n" + summary_text)

    if not args.no_telegram:
        telegram_send_message(tg_token, tg_chat, summary_text[:4096])
        if candidates:
            for r in candidates:
                cp = Path(r["chart_path"])
                if cp.exists():
                    telegram_send_photo(tg_token, tg_chat, cp, candidate_caption(r))
            telegram_send_document(tg_token, tg_chat, cand_csv, "Qualified candidate CSV")
        # Explicit no-candidate delivery is already in summary_text.

    metadata = {
        "run_time": datetime.now().isoformat(timespec="seconds"),
        "latest_market_date": str(latest_market_date.date()),
        "spy_regime": regime,
        "qualified_candidates": len(candidates),
        "strategy1_signals": strategy_signal_counts["Strategy1"],
        "strategy2_signals": strategy_signal_counts["Strategy2"],
        "errors": len(errors),
    }
    (outdir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
