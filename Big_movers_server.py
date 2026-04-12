#!/usr/bin/env python3
# Big Movers Viewer Server
# Usage: python Big_movers_server.py
# Then open http://localhost:5051/ in browser

import csv
import os
import sys
import json
import math
import urllib.request
import urllib.parse
import urllib.error
import ssl
from datetime import date
from flask import Flask, jsonify, send_from_directory, request, Response

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Make the local `classifier` package importable regardless of cwd
sys.path.insert(0, SCRIPT_DIR)
app = Flask(__name__, static_folder=SCRIPT_DIR, static_url_path="")

AI_CLASSIFICATIONS_FILE = os.path.join(SCRIPT_DIR, "ai_classifications.json")
SETUP_DEFINITIONS_FILE = os.path.join(SCRIPT_DIR, "setup_definitions.json")
REVIEWS_FILE = os.path.join(SCRIPT_DIR, "reviews.json")

# Path configuration
RESULTS_CSV = os.path.join(SCRIPT_DIR, "big_movers_result.csv")
STOCKS_DIRS = [
    os.path.join(SCRIPT_DIR, "collected_stocks"),
]

# SPY benchmark data source (UI "VS" overlay)
SPY_HIST_CSV = os.path.join(SCRIPT_DIR, "SPY Historical Data.csv")
_SPY_BARS_CACHE = None

# Twelve Data API key (loaded from ../.env or ./.env)
TWELVE_API_KEY = None
for env_path in [
    os.path.join(SCRIPT_DIR, ".env"),
    os.path.join(SCRIPT_DIR, "..", ".env"),
]:
    if os.path.exists(env_path):
        with open(env_path, "r") as _ef:
            for _line in _ef:
                _line = _line.strip()
                if _line.startswith("TWELVE_API_KEY="):
                    TWELVE_API_KEY = _line.split("=", 1)[1].strip()
                    break
        if TWELVE_API_KEY:
            break

def _normalize_date_maybe(raw):
    s = str(raw or "").strip()
    if not s:
        return ""
    # Already ISO-like
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    # MM/DD/YYYY -> YYYY-MM-DD
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        mm = s[0:2]
        dd = s[3:5]
        yyyy = s[6:10]
        if mm.isdigit() and dd.isdigit() and yyyy.isdigit():
            return f"{yyyy}-{mm}-{dd}"
    return s

def _parse_float_maybe(x):
    try:
        if x is None:
            return None
        s = str(x).strip()
        if not s:
            return None
        # tolerate thousands separators
        s = s.replace(",", "")
        v = float(s)
        return v
    except (ValueError, TypeError):
        return None

def _parse_volume_maybe(x):
    """
    Parse volume like:
    - 52.00M
    - 1.23B
    - 450K
    - plain numeric
    """
    try:
        if x is None:
            return 0.0
        s = str(x).strip()
        if not s:
            return 0.0
        s = s.replace(",", "")
        if s.lower() == "nan":
            return 0.0

        mult = 1.0
        last = s[-1].upper()
        if last == "M":
            mult = 1e6
            s = s[:-1]
        elif last == "B":
            mult = 1e9
            s = s[:-1]
        elif last == "K":
            mult = 1e3
            s = s[:-1]

        v = float(s)
        return v * mult
    except (ValueError, TypeError):
        return 0.0

def _load_spy_bars():
    global _SPY_BARS_CACHE
    if _SPY_BARS_CACHE is not None:
        return _SPY_BARS_CACHE

    if not os.path.exists(SPY_HIST_CSV):
        _SPY_BARS_CACHE = []
        return _SPY_BARS_CACHE

    bars = []
    try:
        with open(SPY_HIST_CSV, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Support both:
                # - Date, Price, Open, High, Low, Vol.
                # - DateTime, Open, High, Low, Close, Volume
                raw_date = row.get("Date") or row.get("DateTime")
                date_str = _normalize_date_maybe(raw_date)
                if not date_str:
                    continue
                o = _parse_float_maybe(row.get("Open"))
                h = _parse_float_maybe(row.get("High"))
                l = _parse_float_maybe(row.get("Low"))
                c = _parse_float_maybe(row.get("Close"))
                if c is None:
                    c = _parse_float_maybe(row.get("Price"))
                v = _parse_volume_maybe(row.get("Volume"))
                if not v:
                    v = _parse_volume_maybe(row.get("Vol."))
                if c is None or c <= 0:
                    continue
                if o is None or h is None or l is None:
                    continue
                bars.append({
                    "time": date_str,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                })
    except Exception:
        bars = []

    bars.sort(key=lambda x: x.get("time") or "")
    _SPY_BARS_CACHE = bars
    return _SPY_BARS_CACHE


def _resolve_index_html_path():
    # Repo uses Big_movers.html; tolerate lowercase for clones on case-sensitive FS
    for name in ("Big_movers.html", "big_movers.html"):
        p = os.path.join(SCRIPT_DIR, name)
        if os.path.exists(p):
            return p
    return None


@app.route("/")
def index():
    html_path = _resolve_index_html_path()
    if not html_path:
        return f"Big_movers.html not found in {SCRIPT_DIR}", 404
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content, mimetype="text/html")


@app.route("/api/results")
def api_results():
    if not os.path.exists(RESULTS_CSV):
        return jsonify({"error": "big_movers_result.csv not found"}), 404
    rows = []
    with open(RESULTS_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return jsonify(rows)


@app.route("/api/ohlcv")
def api_ohlcv():
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    # Special-case SPY: serve from SPY Historical Data.csv
    if symbol == "SPY":
        try:
            return jsonify(_load_spy_bars())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Search configured directories
    path = None
    for d in STOCKS_DIRS:
        for fname in [f"{symbol}.csv", f"{symbol.lower()}.csv"]:
            c = os.path.join(d, fname)
            if os.path.exists(c):
                path = c
                break
        if path:
            break

    if not path:
        return jsonify({"error": f"{symbol}.csv not found in any configured directory"}), 404

    bars = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return jsonify([])
            # Detect CSV column layout
            if len(header) >= 2 and "date" in (header[1] or "").lower():
                fmt = "new"
            elif len(header) >= 1 and "date" in (header[0] or "").lower():
                fmt = "noindex"
            else:
                fmt = "old"
            for row in reader:
                try:
                    if fmt == "new":
                        # [idx, date, open, high, low, close, volume]
                        if len(row) < 7:
                            continue
                        t = row[1].strip()
                        o = float(row[2])
                        h = float(row[3])
                        l = float(row[4])
                        c = float(row[5])
                        v = float(row[6])
                    elif fmt == "noindex":
                        # [DateTime, Open, High, Low, Close, Volume]
                        if len(row) < 6:
                            continue
                        raw_t = row[0].strip()
                        if len(raw_t) == 10 and raw_t[2] == '/':
                            parts = raw_t.split('/')
                            t = f"{parts[2]}-{parts[0]:>02}-{parts[1]:>02}"
                        else:
                            t = raw_t
                        o = float(row[1])
                        h = float(row[2])
                        l = float(row[3])
                        c = float(row[4])
                        v = float(row[5])
                    else:
                        # [date, close, open, high, low, volume, ...]
                        if len(row) < 6:
                            continue
                        t = row[0].strip()
                        c = float(row[1])
                        o = float(row[2])
                        h = float(row[3])
                        l = float(row[4])
                        v = float(row[5])
                    if c <= 0:
                        continue
                    bars.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v})
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    bars.sort(key=lambda x: x["time"])
    return jsonify(bars)


DRAWINGS_FILE = os.path.join(SCRIPT_DIR, "drawings.json")
METADATA_FILE = os.path.join(SCRIPT_DIR, "metadata.json")


def _atomic_json_write(path, data):
    """Write JSON to a temp file then rename (atomic on POSIX)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


@app.route("/api/drawings", methods=["GET", "POST"])
def api_drawings():
    if request.method == "GET":
        if not os.path.exists(DRAWINGS_FILE):
            return jsonify({})
        try:
            with open(DRAWINGS_FILE, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception:
            return jsonify({})
    else:
        try:
            data = request.get_json(silent=True) or {}
            _atomic_json_write(DRAWINGS_FILE, data)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@app.route("/api/metadata", methods=["GET", "POST"])
def api_metadata():
    if request.method == "GET":
        if not os.path.exists(METADATA_FILE):
            return jsonify({})
        try:
            with open(METADATA_FILE, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception:
            return jsonify({})
    else:
        try:
            data = request.get_json(silent=True) or {}
            _atomic_json_write(METADATA_FILE, data)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@app.route("/api/fetch-ticker", methods=["POST"])
def api_fetch_ticker():
    """Fetch OHLCV from Twelve Data API. Saves to collected_stocks/ and optionally
    appends to results CSV. Supports both new tickers and extending existing ones."""
    if not TWELVE_API_KEY:
        return jsonify({"error": "TWELVE_API_KEY not found in .env"}), 500

    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").strip().upper()
    start_date = (body.get("start_date") or "").strip()
    end_date = (body.get("end_date") or "").strip() or str(date.today())
    extend = body.get("extend", False)  # If true, append to existing CSV

    if not symbol:
        return jsonify({"error": "symbol required"}), 400
    if not start_date and not extend:
        return jsonify({"error": "start_date required for new tickers"}), 400

    csv_path = os.path.join(STOCKS_DIRS[0], f"{symbol}.csv")

    # For extend mode, find the last date in existing CSV
    if extend and os.path.exists(csv_path):
        last_date = None
        try:
            with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    if len(row) >= 2:
                        # Try column 1 (new format) or column 0 (noindex)
                        d = row[1].strip() if len(row) >= 7 else row[0].strip()
                        if d and len(d) >= 10:
                            last_date = d[:10]
        except Exception:
            pass
        if last_date:
            # Start from the day after the last date
            from datetime import datetime, timedelta
            try:
                ld = datetime.strptime(last_date, "%Y-%m-%d")
                start_date = (ld + timedelta(days=1)).strftime("%Y-%m-%d")
            except ValueError:
                start_date = last_date
        if not start_date:
            return jsonify({"error": "Could not determine last date in existing CSV"}), 400
        # If start_date is already past end_date, nothing to fetch
        if start_date > end_date:
            return jsonify({"message": "Already up to date", "bars_added": 0, "symbol": symbol})

    # Fetch from Twelve Data API
    params = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": "1day",
        "start_date": start_date,
        "end_date": end_date,
        "outputsize": "5000",
        "apikey": TWELVE_API_KEY,
    })
    url = f"https://api.twelvedata.com/time_series?{params}"

    try:
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except ImportError:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "BigMovers/1.0"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return jsonify({"error": f"API HTTP error: {e.code}"}), 502
    except Exception as e:
        return jsonify({"error": f"API request failed: {str(e)}"}), 502

    if data.get("status") == "error":
        return jsonify({"error": data.get("message", "Unknown API error")}), 400

    values = data.get("values", [])
    if not values:
        return jsonify({"message": "No data returned from API", "bars_added": 0, "symbol": symbol})

    # Parse API response into bars
    new_bars = []
    for v in values:
        try:
            t = v["datetime"][:10]  # YYYY-MM-DD
            o = float(v["open"])
            h = float(v["high"])
            l = float(v["low"])
            c = float(v["close"])
            vol = float(v["volume"])
            if c <= 0:
                continue
            new_bars.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": vol})
        except (KeyError, ValueError):
            continue

    new_bars.sort(key=lambda x: x["time"])

    # Write/append to CSV in "noindex" format: DateTime,Open,High,Low,Close,Volume
    os.makedirs(STOCKS_DIRS[0], exist_ok=True)
    if extend and os.path.exists(csv_path):
        # Read existing dates to avoid duplicates
        existing_dates = set()
        try:
            with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    if len(row) >= 2:
                        d = row[1].strip() if len(row) >= 7 else row[0].strip()
                        if d:
                            existing_dates.add(d[:10])
        except Exception:
            pass
        new_bars = [b for b in new_bars if b["time"] not in existing_dates]
        if new_bars:
            with open(csv_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                for b in new_bars:
                    writer.writerow([b["time"], b["open"], b["high"], b["low"], b["close"], int(b["volume"])])
    else:
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["DateTime", "Open", "High", "Low", "Close", "Volume"])
            for b in new_bars:
                writer.writerow([b["time"], b["open"], b["high"], b["low"], b["close"], int(b["volume"])])

    # Compute summary stats for the result row
    if new_bars:
        all_bars = new_bars
        if extend and os.path.exists(csv_path):
            # Re-read full CSV to compute stats from all data
            all_bars = []
            try:
                with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    for row in reader:
                        if len(row) >= 6:
                            d = row[0].strip()
                            if len(row) >= 7:
                                d = row[1].strip()
                            all_bars.append({
                                "time": d[:10] if d else "",
                                "close": float(row[4] if len(row) < 7 else row[5]),
                                "volume": float(row[5] if len(row) < 7 else row[6]),
                            })
            except Exception:
                all_bars = new_bars

        closes = [b["close"] for b in all_bars if b.get("close")]
        volumes = [b.get("volume", 0) for b in all_bars]
        low_price = min(closes) if closes else 0
        high_price = max(closes) if closes else 0
        low_idx = closes.index(low_price) if closes else 0
        high_idx = closes.index(high_price) if closes else 0
        gain_pct = ((high_price / low_price) - 1) * 100 if low_price > 0 else 0
        avg_vol = sum(volumes) / len(volumes) if volumes else 0
        avg_vol_b = round(avg_vol / 1e9, 2)
        times = [b["time"] for b in all_bars if b.get("time")]
        low_date = times[low_idx] if low_idx < len(times) else start_date
        high_date = times[high_idx] if high_idx < len(times) else end_date
        year = start_date[:4] if start_date else str(date.today().year)

        result_row = {
            "year": year,
            "symbol": symbol,
            "gain_pct": str(round(gain_pct, 2)),
            "low_date": low_date,
            "high_date": high_date,
            "low_price": str(round(low_price, 3)),
            "high_price": str(round(high_price, 3)),
            "avg_vol_b": str(avg_vol_b),
        }
    else:
        result_row = None

    return jsonify({
        "ok": True,
        "symbol": symbol,
        "bars_added": len(new_bars),
        "total_bars": len(new_bars),
        "result_row": result_row,
    })


@app.route("/api/remove-ticker", methods=["POST"])
def api_remove_ticker():
    """Remove a ticker from results CSV and optionally delete its OHLCV CSV."""
    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").strip().upper()
    year = str(body.get("year", "")).strip()
    delete_csv = body.get("delete_csv", False)

    if not symbol or not year:
        return jsonify({"error": "symbol and year required"}), 400

    # Remove from results CSV
    removed = False
    if os.path.exists(RESULTS_CSV):
        rows = []
        fieldnames = None
        with open(RESULTS_CSV, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                if row.get("symbol") == symbol and str(row.get("year", "")).strip() == year:
                    removed = True
                    continue
                rows.append(row)
        if removed and fieldnames:
            with open(RESULTS_CSV, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

    # Optionally delete the OHLCV CSV file
    csv_deleted = False
    if delete_csv:
        for d in STOCKS_DIRS:
            for fname in [f"{symbol}.csv", f"{symbol.lower()}.csv"]:
                p = os.path.join(d, fname)
                if os.path.exists(p):
                    os.remove(p)
                    csv_deleted = True

    return jsonify({"ok": True, "removed_from_results": removed, "csv_deleted": csv_deleted})


@app.route("/api/add-result", methods=["POST"])
def api_add_result():
    """Append a row to big_movers_result.csv."""
    body = request.get_json(silent=True) or {}
    required = ["year", "symbol", "gain_pct", "low_date", "high_date", "low_price", "high_price", "avg_vol_b"]
    for k in required:
        if k not in body:
            return jsonify({"error": f"Missing field: {k}"}), 400

    # Check for duplicate
    if os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("symbol") == body["symbol"] and row.get("year") == str(body["year"]):
                    # Update existing row instead
                    rows = []
                    f.seek(0)
                    reader2 = csv.DictReader(f)
                    fieldnames = reader2.fieldnames
                    for r in reader2:
                        if r.get("symbol") == body["symbol"] and r.get("year") == str(body["year"]):
                            r.update({k: str(body[k]) for k in required})
                        rows.append(r)
                    with open(RESULTS_CSV, "w", encoding="utf-8", newline="") as wf:
                        writer = csv.DictWriter(wf, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(rows)
                    return jsonify({"ok": True, "action": "updated"})

    # Append new row
    write_header = not os.path.exists(RESULTS_CSV) or os.path.getsize(RESULTS_CSV) == 0
    with open(RESULTS_CSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=required)
        if write_header:
            writer.writeheader()
        writer.writerow({k: str(body[k]) for k in required})

    return jsonify({"ok": True, "action": "added"})


# ---------- Classifier endpoints (indicators, pivot, AI classifications) ----------


def _series_from_column(df, col):
    """Return a list of {time, value} dicts for a dataframe column, skipping NaN."""
    if col not in df.columns:
        return []
    out = []
    series = df[col]
    idx = df.index
    for ts, val in zip(idx, series):
        try:
            if val is None:
                continue
            fv = float(val)
        except (TypeError, ValueError):
            continue
        if math.isnan(fv) or math.isinf(fv):
            continue
        try:
            tstr = ts.strftime("%Y-%m-%d")
        except AttributeError:
            tstr = str(ts)[:10]
        out.append({"time": tstr, "value": fv})
    return out


@app.route("/api/indicators")
def api_indicators():
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol required"}), 400
    try:
        from classifier.indicators import (
            load_ticker_bars,
            load_spy_benchmark,
            compute_all_indicators,
        )
        bars = load_ticker_bars(symbol, os.path.join(SCRIPT_DIR, "collected_stocks"))
        try:
            spy = load_spy_benchmark(SPY_HIST_CSV)
        except Exception:
            spy = None
        indic = compute_all_indicators(bars, benchmark=spy)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    cols = [
        "sma50", "sma150", "sma200", "ema10", "ema20",
        "avg_vol_50", "rel_vol", "adr_pct_20", "atr_20", "rs_vs_spy_63d",
    ]
    payload = {"symbol": symbol}
    for c in cols:
        payload[c] = _series_from_column(indic, c)

    swings_out = []
    for s in (indic.attrs.get("swings") or []):
        d = s.get("date")
        try:
            tstr = d.strftime("%Y-%m-%d")
        except AttributeError:
            tstr = str(d)[:10]
        swings_out.append({
            "time": tstr,
            "kind": s.get("kind"),
            "price": float(s.get("price", 0.0)),
        })
    payload["swings"] = swings_out
    return jsonify(payload)


@app.route("/api/pivot")
def api_pivot():
    symbol = (request.args.get("symbol") or "").strip().upper()
    year = (request.args.get("year") or "").strip()
    if not symbol or not year:
        return jsonify({"error": "symbol and year required"}), 400

    # Look up the matching row in results CSV
    match = None
    if not os.path.exists(RESULTS_CSV):
        return jsonify({"error": "big_movers_result.csv not found"}), 404
    try:
        with open(RESULTS_CSV, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("symbol", "").strip().upper() == symbol and str(row.get("year", "")).strip() == year:
                    match = row
                    break
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if match is None:
        return jsonify({"pivot": None})

    low_date = _normalize_date_maybe(match.get("low_date"))
    high_date = _normalize_date_maybe(match.get("high_date"))
    if not low_date or not high_date:
        return jsonify({"pivot": None})

    try:
        import pandas as pd
        from classifier.indicators import (
            load_ticker_bars,
            load_spy_benchmark,
            compute_all_indicators,
        )
        from classifier.pivot import find_breakout_pivot

        bars = load_ticker_bars(symbol, os.path.join(SCRIPT_DIR, "collected_stocks"))
        try:
            spy = load_spy_benchmark(SPY_HIST_CSV)
        except Exception:
            spy = None
        indic = compute_all_indicators(bars, benchmark=spy)
        ld = pd.to_datetime(low_date)
        hd = pd.to_datetime(high_date)
        pivot = find_breakout_pivot(indic, ld, hd)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if pivot is None:
        return jsonify({"pivot": None})

    def _date_str(v):
        try:
            return v.strftime("%Y-%m-%d")
        except AttributeError:
            return str(v)[:10]

    out = {
        "pivot_date": _date_str(pivot.get("pivot_date")),
        "base_start": _date_str(pivot.get("base_start")),
        "base_end": _date_str(pivot.get("base_end")),
        "base_high": pivot.get("base_high"),
        "base_low": pivot.get("base_low"),
        "base_depth_pct": pivot.get("base_depth_pct"),
        "breakout_rel_vol": pivot.get("breakout_rel_vol"),
    }
    return jsonify({"pivot": out})


@app.route("/api/ai-classifications")
def api_ai_classifications():
    if not os.path.exists(AI_CLASSIFICATIONS_FILE):
        return jsonify({})
    try:
        with open(AI_CLASSIFICATIONS_FILE, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai-classifications/override", methods=["POST"])
def api_ai_classifications_override():
    body = request.get_json(silent=True) or {}
    move_key = (body.get("move_key") or "").strip()
    if not move_key:
        return jsonify({"error": "move_key required"}), 400

    data = {}
    if os.path.exists(AI_CLASSIFICATIONS_FILE):
        try:
            with open(AI_CLASSIFICATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}

    entry = data.get(move_key) or {}
    entry["user_primary"] = body.get("user_primary")
    if "user_secondary" in body:
        entry["user_secondary"] = body.get("user_secondary")
    entry["user_reviewed"] = True
    entry["user_reviewed_at"] = str(date.today())
    if "user_note" in body:
        entry["user_note"] = body.get("user_note")
    data[move_key] = entry

    try:
        _atomic_json_write(AI_CLASSIFICATIONS_FILE, data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True, "entry": entry})


@app.route("/api/setup-definitions")
def api_setup_definitions():
    if not os.path.exists(SETUP_DEFINITIONS_FILE):
        return jsonify({"setups": []})
    try:
        with open(SETUP_DEFINITIONS_FILE, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reviews")
def api_reviews_get():
    if not os.path.exists(REVIEWS_FILE):
        return jsonify({})
    try:
        with open(REVIEWS_FILE, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reviews/<move_key>")
def api_review_get_one(move_key):
    if not os.path.exists(REVIEWS_FILE):
        return jsonify({"error": "no reviews"}), 404
    try:
        with open(REVIEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        entry = data.get(move_key)
        if entry is None:
            return jsonify({"error": f"{move_key} not reviewed"}), 404
        return jsonify(entry)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reviews/<move_key>", methods=["POST"])
def api_review_save(move_key):
    body = request.get_json(silent=True) or {}
    data = {}
    if os.path.exists(REVIEWS_FILE):
        try:
            with open(REVIEWS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    data[move_key] = body
    try:
        _atomic_json_write(REVIEWS_FILE, data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("Chart Studies: http://localhost:5051/")
    if TWELVE_API_KEY:
        print(f"  Twelve Data API: configured (key: ...{TWELVE_API_KEY[-4:]})")
    else:
        print("  Twelve Data API: NOT configured (no .env found)")
    app.run(host="127.0.0.1", port=5051, debug=False)