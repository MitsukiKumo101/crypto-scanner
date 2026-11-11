"""Connection test: checks that we can reach our data sources.
Writes the results to data/connection_report.json"""

import datetime
import json
import os
import urllib.request


def get_json(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "crypto-scanner/0.1", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def test_top100():
    url = (
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
    )
    data = get_json(url)
    if len(data) < 100:
        raise ValueError("only " + str(len(data)) + " coins returned")
    return "got " + str(len(data)) + " coins, number 1 is " + data[0]["symbol"].upper()


def test_candles(pair, interval, minimum):
    url = "https://api.kraken.com/0/public/OHLC?pair=" + pair + "&interval=" + str(interval)
    data = get_json(url)
    if data.get("error"):
        raise ValueError(str(data["error"]))
    result = data["result"]
    key = [k for k in result if k != "last"][0]
    candles = result[key]
    times = [c[0] for c in candles]
    if times != sorted(times):
        raise ValueError("candles are out of order")
    if len(candles) < minimum:
        raise ValueError("only " + str(len(candles)) + " candles, need " + str(minimum))
    return "got " + str(len(candles)) + " candles"


TESTS = [
    ("Top 100 list (CoinGecko)", test_top100),
    ("Bitcoin daily candles (Kraken)", lambda: test_candles("XBTUSD", 1440, 200)),
    ("Bitcoin 4-hour candles (Kraken)", lambda: test_candles("XBTUSD", 240, 200)),
    ("Bitcoin weekly candles (Kraken)", lambda: test_candles("XBTUSD", 10080, 100)),
    ("Ethereum daily candles (Kraken)", lambda: test_candles("ETHUSD", 1440, 200)),
]

report = {
    "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "tests": [],
}

for name, test in TESTS:
    try:
        report["tests"].append({"name": name, "ok": True, "detail": test()})
    except Exception as error:
        report["tests"].append(
            {"name": name, "ok": False, "detail": type(error).__name__ + ": " + str(error)}
        )

report["all_ok"] = all(t["ok"] for t in report["tests"])

os.makedirs("data", exist_ok=True)
with open("data/connection_report.json", "w") as f:
    json.dump(report, f, indent=2)

for t in report["tests"]:
    print(("PASS  " if t["ok"] else "FAIL  ") + t["name"] + " - " + t["detail"])
