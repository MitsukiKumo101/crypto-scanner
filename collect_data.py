"""Stage 1b: coverage check.
For each of the top 100 coins, tries to download daily, 4-hour and weekly
candles from Kraken, checks that the data is clean, and writes a report to
data/coverage_report.json so we can see which coins we can analyze."""

import datetime
import json
import os
import time
import urllib.request

PAUSE = float(os.environ.get("REQUEST_PAUSE", "1.2"))  # polite pause between requests
TIMEFRAMES = {"daily": 1440, "4h": 240, "weekly": 10080}  # minutes per candle
MIN_CANDLES = {"daily": 250, "4h": 200, "weekly": 100}
STABLECOINS = {"USDT", "USDC", "DAI", "USDE", "FDUSD", "TUSD", "USDS", "PYUSD", "USD1",
               "USDD", "BUIDL", "USDG", "RLUSD", "USDTB", "USDY", "GUSD", "FRAX"}
KRAKEN_NAMES = {"XBT": "BTC", "XDG": "DOGE"}


def get_json(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "crypto-scanner/0.1", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json_with_retry(url, tries=3):
    last_error = None
    for attempt in range(tries):
        try:
            data = get_json(url)
            if isinstance(data, dict) and data.get("error"):
                raise ValueError(str(data["error"]))
            return data
        except Exception as error:
            last_error = error
            time.sleep(PAUSE * (attempt + 2) * 2)
    raise last_error


def top_100():
    url = (
        "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
        "&order=market_cap_desc&per_page=100&page=1&price_change_percentage=1h,24h,7d,30d"
    )
    return get_json_with_retry(url)


def kraken_usd_pairs():
    """Returns {ticker: kraken pair name} for pairs that trade against USD."""
    data = get_json_with_retry("https://api.kraken.com/0/public/AssetPairs")
    pairs = {}
    for info in data["result"].values():
        wsname = info.get("wsname", "")
        if "/" not in wsname or info.get("status", "online") != "online":
            continue
        base, quote = wsname.split("/")
        if quote != "USD":
            continue
        pairs[KRAKEN_NAMES.get(base, base)] = info["altname"]
    return pairs


def check_candles(raw, minutes, now_seconds):
    """Cleans one list of Kraken candles. Returns (finished_candles, problems)."""
    problems = []
    seconds = minutes * 60
    candles = []
    for row in raw:
        try:
            t, o, h, l, c, v = int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[6])
        except Exception:
            problems.append("unreadable candle")
            continue
        if min(o, h, l, c) <= 0 or v < 0 or h < max(o, c, l) or l > min(o, c, h):
            problems.append("impossible prices at " + str(t))
            continue
        candles.append((t, o, h, l, c, v))

    times = [c[0] for c in candles]
    if times != sorted(times) or len(set(times)) != len(times):
        problems.append("candles out of order or duplicated")
        candles = sorted({c[0]: c for c in candles}.values())

    # Drop any candle that has not finished yet. Finished means it has fully closed.
    finished = [c for c in candles if c[0] + seconds <= now_seconds]
    unfinished = len(candles) - len(finished)

    # Look for missing candles in the most recent stretch.
    recent = finished[-250:]
    gaps = 0
    for a, b in zip(recent, recent[1:]):
        if b[0] - a[0] > seconds * 1.5:
            gaps += 1
    return finished, unfinished, gaps, problems


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    now_seconds = int(now.timestamp())
    report = {"checked_at": now.isoformat(timespec="seconds"), "coins": [], "summary": {}}

    coins = top_100()
    pairs = kraken_usd_pairs()
    print("Top 100 loaded. Kraken has " + str(len(pairs)) + " USD pairs.")

    for coin in coins:
        symbol = coin["symbol"].upper()
        entry = {"rank": coin.get("market_cap_rank"), "symbol": symbol, "name": coin["name"]}
        if symbol in STABLECOINS:
            entry["status"] = "skipped: stablecoin"
        elif symbol not in pairs:
            entry["status"] = "not on Kraken (USD)"
        else:
            entry["status"] = "ok"
            entry["timeframes"] = {}
            for label, minutes in TIMEFRAMES.items():
                try:
                    url = ("https://api.kraken.com/0/public/OHLC?pair=" + pairs[symbol]
                           + "&interval=" + str(minutes))
                    data = get_json_with_retry(url)
                    result = data["result"]
                    key = [k for k in result if k != "last"][0]
                    finished, unfinished, gaps, problems = check_candles(result[key], minutes, now_seconds)
                    info = {"finished_candles": len(finished), "unfinished_dropped": unfinished,
                            "gaps_recent": gaps, "problems": problems[:3]}
                    if finished:
                        info["last_finished_candle"] = datetime.datetime.fromtimestamp(
                            finished[-1][0], datetime.timezone.utc).isoformat(timespec="minutes")
                    if len(finished) < MIN_CANDLES[label]:
                        info["usable"] = False
                        info["why_not"] = "too few candles (" + str(len(finished)) + ")"
                    elif gaps > 0 or problems:
                        info["usable"] = False
                        info["why_not"] = "data has gaps or problems"
                    else:
                        info["usable"] = True
                    entry["timeframes"][label] = info
                except Exception as error:
                    entry["timeframes"][label] = {"usable": False,
                                                  "why_not": type(error).__name__ + ": " + str(error)[:120]}
                time.sleep(PAUSE)
            if not all(tf.get("usable") for tf in entry["timeframes"].values()):
                entry["status"] = "incomplete data"
        report["coins"].append(entry)

    counts = {}
    for entry in report["coins"]:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    report["summary"] = counts

    os.makedirs("data", exist_ok=True)
    with open("data/coverage_report.json", "w") as f:
        json.dump(report, f, indent=1)

    print("SUMMARY")
    for status, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(str(n).rjust(4) + "  " + status)
    missing = [e["symbol"] for e in report["coins"] if e["status"].startswith(("not on", "incomplete"))]
    print("Cannot analyze: " + ", ".join(missing))


if __name__ == "__main__":
    main()
