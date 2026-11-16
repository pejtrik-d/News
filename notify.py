"""Pošle do Telegramu (1) ranní souhrn top zpráv a (2) upozornění na velmi důležité zprávy.
Potřebuje proměnné TELEGRAM_TOKEN a TELEGRAM_CHAT_ID (v GitHubu jako Secrets).
Bez nich se skript tiše přeskočí. Už odeslané zprávy si pamatuje v data/sent.json."""
import html, json, os, time, urllib.parse, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ALERT_SCORE = int(os.environ.get("ALERT_SCORE", "80"))  # od jakého skóre poslat upozornění
DIGEST_HOUR = 7      # ranní souhrn se pošle při prvním běhu po této hodině (pražský čas)
DIGEST_TOP = 3       # kolik zpráv v souhrnu
MAX_ALERTS = 5       # maximum upozornění na jeden běh
ALERT_MAX_AGE_H = 6  # starší zprávy neoznamujeme
SENT = "data/sent.json"

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT = os.environ.get("TELEGRAM_CHAT_ID")


def send(text):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data, timeout=20)
        return True
    except Exception as e:
        print("Telegram: odeslání selhalo:", e)
        return False


def line(i):
    names = ", ".join([i["source"]] + [a["source"] for a in i["also"]])
    return (f"<b>{html.escape(i['title'])}</b>\n{html.escape(i['topic'])} | důležitost {i['score']}/100 "
            f"| {html.escape(names)}\n{html.escape(i['link'])}")


def main():
    if not TOKEN or not CHAT:
        print("Telegram není nastaven, přeskakuji.")
        return
    items = json.load(open("site/news.json", encoding="utf-8"))["items"]
    try:
        state = json.load(open(SENT, encoding="utf-8"))
    except Exception:
        state = {}
    links = state.get("links", [])
    now = time.time()
    local = datetime.now(ZoneInfo("Europe/Prague"))
    today = local.strftime("%Y-%m-%d")

    if DIGEST_HOUR <= local.hour < 12 and state.get("digest") != today:
        top = [i for i in items if now - i["ts"] < 24 * 3600][:DIGEST_TOP]
        if top:
            body = "\n\n".join(f"{n}. {line(i)}" for n, i in enumerate(top, 1))
            if send("<b>Ranní přehled konfliktů</b>\n\n" + body):
                state["digest"] = today

    alerts = [i for i in items if i["score"] >= ALERT_SCORE and i["link"] not in links
              and now - i["ts"] < ALERT_MAX_AGE_H * 3600]
    for n, i in enumerate(alerts):
        if n < MAX_ALERTS:
            if send("<b>Důležitá zpráva</b>\n\n" + line(i)):
                links.append(i["link"])
        else:
            links.append(i["link"])  # přebytek jen označíme, ať se nehromadí

    state["links"] = links[-300:]
    json.dump(state, open(SENT, "w", encoding="utf-8"))
    print(f"Telegram hotovo, upozornění: {min(len(alerts), MAX_ALERTS)}")


if __name__ == "__main__":
    main()
