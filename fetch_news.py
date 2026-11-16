"""Stáhne RSS, vyfiltruje válečné zprávy podle tvých zájmů, ohodnotí důležitost,
uloží historii (data/history.json) a výsledek (site/news.json). Bez AI, bez API klíčů.
Ladění: DEBUG=1 python fetch_news.py  (vypíše, co a proč filtr zahodil)"""
import calendar, html, json, os, re, time, unicodedata
from datetime import datetime, timezone
import feedparser

DEBUG = bool(os.environ.get("DEBUG"))
HIST = "data/history.json"

# ---------- NASTAVENÍ (uprav podle sebe) ----------
# název: (url, váha zdroje 0-5, typ zdroje)
FEEDS = {
    "BBC World": ("http://feeds.bbci.co.uk/news/world/rss.xml", 4, "veřejnoprávní"),
    "DW": ("https://rss.dw.com/rdf/rss-en-world", 3, "veřejnoprávní"),
    "ČT24 svět": ("https://ct24.ceskatelevize.cz/rss/svet", 3, "veřejnoprávní"),
    "iROZHLAS": ("https://www.irozhlas.cz/rss/irozhlas", 3, "veřejnoprávní"),
    "The Guardian": ("https://www.theguardian.com/world/rss", 4, "nezávislé"),
    "Kyiv Independent": ("https://kyivindependent.com/feed/", 3, "nezávislé"),
    "Times of Israel": ("https://www.timesofisrael.com/feed/", 3, "nezávislé"),
    "Al Jazeera": ("https://www.aljazeera.com/xml/rss/all.xml", 3, "státní"),  # financuje Katar
    "TASS": ("https://tass.com/rss/v2.xml", 1, "státní"),  # ruská státní agentura, bere se s rezervou
}

# téma: (tvůj zájem 1-3, klíčová slova bez diakritiky). Slovo končící $ musí sedět celé.
TOPICS = {
    "Ukrajina": (3, ["ukrajin", "ukrain", "kyiv", "kyjev", "zelensk", "donbas", "kharkiv", "charkov",
                     "zaporiz", "kremlin", "putin", "russia", "rusk"]),
    "Blízký východ": (3, ["gaza", "izrael", "israel", "hamas", "hezbollah", "hizballah", "libanon",
                          "lebanon", "iran", "tehran", "west bank", "zapadni breh", "houthi", "husi$",
                          "yemen", "jemen", "syri"]),
    "Sudán": (2, ["sudan", "khartoum", "chartum", "rsf$"]),
    "Další konflikty": (1, ["myanmar", "sahel", "mali$", "congo", "kongo", "taiwan", "tchaj",
                            "kashmir", "somalia", "haiti"]),
}

# bez těchto slov článek nepovažujeme za válečný
WAR = ["war$", "wars$", "valk", "attack", "utok", "strike", "nalet", "missile", "raket", "drone",
       "dron", "troops", "vojsk", "vojak", "vojensk", "army", "armad", "frontline", "front line",
       "frontov", "offensive", "ofenziv", "ceasefire", "primeri", "killed", "zabit", "casualt",
       "obet", "bomb", "shelling", "ostrel", "invasion", "invaz", "hostage", "rukojm", "sanction",
       "sankc", "nuclear", "jadern", "military"]
HIGH = ["killed", "dead$", "zabit", "mrtv", "nuclear", "jadern", "ceasefire", "primeri",
        "offensive", "ofenziv", "invasion", "invaz", "massacre", "masakr", "mobiliz", "escalat",
        "eskal", "breaking", "ultimatum", "capture", "dobyt", "peace deal", "mirov"]
MID = ["missile", "raket", "drone", "dron", "strike", "nalet", "sanction", "sankc", "talks",
       "jednan", "hostage", "rukojm", "wounded", "ranen", "evacuat", "evakuac"]

# slovníček pro spojování stejné události napříč jazyky (začátek slova -> společný tvar)
CANON = {"kyjev": "kyiv", "kyiv": "kyiv", "ukrajin": "ukraine", "ukrain": "ukraine", "rusk": "russia",
         "russia": "russia", "izrael": "israel", "israel": "israel", "zelensk": "zelensky",
         "gaza": "gaza", "gazy": "gaza", "gaze": "gaza", "gazu": "gaza", "iran": "iran",
         "teheran": "tehran", "tehran": "tehran", "libanon": "lebanon", "lebanon": "lebanon",
         "syri": "syria", "sudan": "sudan", "chartum": "khartoum", "khartoum": "khartoum",
         "zabit": "killed", "zabij": "killed", "kill": "killed", "mrtv": "dead", "dead": "dead",
         "raket": "missile", "missile": "missile", "utok": "attack", "utoc": "attack",
         "attack": "attack", "nalet": "strike", "strike": "strike", "dron": "drone",
         "jadern": "nuclear", "nuclear": "nuclear", "primeri": "ceasefire", "ceasefire": "ceasefire",
         "sankc": "sanctions", "sanction": "sanctions", "rukojm": "hostage", "hostage": "hostage",
         "ofenziv": "offensive", "offensive": "offensive", "jednan": "talks", "talks": "talks",
         "vojak": "troops", "troops": "troops", "soldier": "troops", "hamas": "hamas",
         "hezbollah": "hezbollah", "putin": "putin", "charkov": "kharkiv", "kharkiv": "kharkiv"}

KEEP_DAYS = 7     # jak dlouho držet historii
SIMILAR = 0.35    # podobnost nadpisů pro spojení stejné události
# ----------------------------------------------------


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def has(text, words):
    out = []
    for w in words:
        pat = r"\b" + re.escape(w[:-1]) + r"\b" if w.endswith("$") else r"\b" + re.escape(w)
        if re.search(pat, text):
            out.append(w)
    return out


def tokens(title):
    out = set()
    for t in re.findall(r"[a-z0-9]{3,}", norm(title)):
        mapped = next((c for s, c in CANON.items() if t.startswith(s)), None)
        if mapped or len(t) >= 4:
            out.add(mapped or t)
    return out


def similar(a, b):
    inter = len(a & b)
    return inter >= 2 and inter / len(a | b) >= SIMILAR


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def stars(s):
    return 5 if s >= 70 else 4 if s >= 52 else 3 if s >= 36 else 2 if s >= 24 else 1


def fetch(now):
    found = []
    for source, (url, weight, typ) in FEEDS.items():
        feed = feedparser.parse(url, agent="valecna-ctecka/2.0")
        if not feed.entries:
            print(f"[!] {source}: žádné články (zkontroluj adresu kanálu)")
            continue
        kept = 0
        for e in feed.entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            ts = calendar.timegm(ts) if ts else now
            if now - ts > KEEP_DAYS * 86400:
                continue
            title, summary = clean(e.get("title")), clean(e.get("summary"))
            text = norm(title + " " + summary)
            topics = [(n, w) for n, (w, kws) in TOPICS.items() if has(text, kws)]
            if not topics or not has(text, WAR):
                if DEBUG:
                    why = "žádné téma" if not topics else "chybí válečné slovo"
                    print(f"  zahozeno ({why}) [{source}] {title}")
                continue
            topic, interest = max(topics, key=lambda t: t[1])
            kept += 1
            found.append({"title": title, "summary": summary[:240], "link": e.get("link", ""),
                          "source": source, "type": typ, "topic": topic, "ts": int(ts),
                          "w": weight, "i": interest})
        print(f"{source}: {len(feed.entries)} článků, {kept} prošlo filtrem")
    return found


def build(recs, now):
    for r in recs:
        r["_t"] = tokens(r["title"])
        r["_txt"] = norm(r["title"] + " " + r["summary"])
    recs.sort(key=lambda r: (-r["w"], -r["ts"]))  # nejdůvěryhodnější zdroj se stane hlavní kartou
    clusters = []
    for r in recs:
        c = next((c for c in clusters if abs(c[0]["ts"] - r["ts"]) <= 48 * 3600
                  and similar(c[0]["_t"], r["_t"])), None)
        if c:
            c.append(r)
        else:
            clusters.append([r])
    out = []
    for c in clusters:
        rep, per_source = c[0], {}
        for m in c:
            per_source.setdefault(m["source"], m)
        also = [{"source": s, "link": m["link"], "type": m["type"]}
                for s, m in per_source.items() if s != rep["source"]]
        text = " ".join(m["_txt"] for m in c)
        newest = max(m["ts"] for m in c)
        age_h = (now - newest) / 3600
        fresh = {m["source"] for m in c if now - m["ts"] < 3 * 3600}
        s = max(m["i"] for m in c) * 8                          # tvůj zájem o téma
        s += min(len(has(text, HIGH)) * 12, 36)                 # závažná slova
        s += min(len(has(text, MID)) * 5, 15)                   # středně závažná
        s += min(len(also) * 12, 36)                            # více zdrojů
        s += min(max(len(fresh) - 1, 0) * 6, 18)                # rychlé šíření: víc zdrojů za 3 h
        s += rep["w"] * 2                                       # důvěra ke zdroji
        s += 10 if age_h < 3 else 6 if age_h < 12 else 3 if age_h < 24 else 0
        score = min(int(s), 100)
        out.append({"title": rep["title"], "summary": rep["summary"], "link": rep["link"],
                    "source": rep["source"], "type": rep["type"], "topic": rep["topic"],
                    "ts": newest, "first_seen": min(m.get("first_seen", m["ts"]) for m in c),
                    "score": score, "stars": stars(score), "also": also,
                    "types": sorted({m["type"] for m in c})})
    out.sort(key=lambda x: (-x["score"], -x["ts"]))
    return out


def main():
    now = int(time.time())
    try:
        with open(HIST, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = {}
    for r in fetch(now):
        if r["link"] and r["link"] not in hist:
            r["first_seen"] = now
            hist[r["link"]] = r
    hist = {k: v for k, v in hist.items() if now - v["ts"] <= KEEP_DAYS * 86400}
    os.makedirs("data", exist_ok=True)
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False)
    items = build([dict(v) for v in hist.values()], now)
    out = {"updated": datetime.now(timezone.utc).isoformat(), "topics": list(TOPICS),
           "types": sorted({v[2] for v in FEEDS.values()}), "items": items}
    with open("site/news.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"Uloženo {len(items)} událostí (historie: {len(hist)} článků).")


if __name__ == "__main__":
    main()
