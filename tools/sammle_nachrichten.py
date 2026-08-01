#!/usr/bin/env python3
"""Sammelt Nachrichten fuer die Insel-Fehmarn-App zu einer nachrichten.json.

Bewusst NUR Ueberschrift, Datum, Quelle und Link -- keine Artikeltexte und
keine Zusammenfassungen davon. Fremde Texte duerfen nicht uebernommen werden;
verlinken mit Ueberschrift ist der uebliche und unbedenkliche Weg.

Nur Standardbibliothek, damit der GitHub-Action-Lauf ohne Installation
auskommt.
"""
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

RSS1 = {"r": "http://purl.org/rss/1.0/", "dc": "http://purl.org/dc/elements/1.1/"}
KOPF = {"User-Agent": "Insel-Fehmarn-App Nachrichtensammler (Kontakt ueber leschsch77.github.io)"}
ZIEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nachrichten.json")
MAX_EINTRAEGE = 60

# breit = landesweite Quelle, die erst nach Stichwort gefiltert werden muss
QUELLEN = [
    ("fehmarn24", "https://www.fehmarn24.de/fehmarn/rssfeed.rdf", "insel", False),
    ("fehmarn24", "https://www.fehmarn24.de/ostholstein/rssfeed.rdf", "ostholstein", False),
    ("NDR Schleswig-Holstein", "https://www.ndr.de/nachrichten/schleswig-holstein/index-rss.xml", "insel", True),
]

TUNNEL_WOERTER = ["fehmarnbelt", "femern", "tunnel", "beltquerung", "absenktunnel"]
INSEL_WOERTER = TUNNEL_WOERTER + [
    "fehmarn", "burg auf", "puttgarden", "burgtiefe", "orth", "landkirchen",
    "petersdorf", "wulfen", "staberdorf", "sundbruecke", "sundbrücke",
]


def hole(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=KOPF), timeout=30).read()


def text_von(el, *namen):
    """Liest das erste vorhandene Feld, egal ob RSS 2.0 oder RSS 1.0 (Namensraum)."""
    for n in namen:
        w = el.findtext(n)
        if w:
            return w.strip()
        w = el.findtext(f"r:{n}", namespaces=RSS1) or el.findtext(f"dc:{n}", namespaces=RSS1)
        if w:
            return w.strip()
    return ""


def als_datum(roh):
    """Vereinheitlicht die verschiedenen Datumsformate zu ISO. Leer wenn unlesbar."""
    if not roh:
        return ""
    try:
        return parsedate_to_datetime(roh).astimezone(timezone.utc).date().isoformat()
    except Exception:
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", roh)
    return m.group(1) if m else ""


def rubrik_fuer(titel, standard):
    return "tunnel" if any(w in titel.lower() for w in TUNNEL_WOERTER) else standard


def passt(titel, nur_mit_stichwort):
    return (not nur_mit_stichwort) or any(w in titel.lower() for w in INSEL_WOERTER)


def lies_feed(roh, quelle, standard_rubrik, nur_mit_stichwort):
    wurzel = ET.fromstring(roh)
    posten = wurzel.findall(".//item") or wurzel.findall(".//r:item", RSS1)
    raus = []
    for p in posten:
        titel = text_von(p, "title")
        link = text_von(p, "link")
        if not titel or not link or not passt(titel, nur_mit_stichwort):
            continue
        raus.append({
            "titel": titel,
            "link": link,
            "datum": als_datum(text_von(p, "pubDate", "date")),
            "quelle": quelle,
            "rubrik": rubrik_fuer(titel, standard_rubrik),
        })
    return raus


def zusammenfuehren(alt, neu):
    """Neue vor alte, Dubletten per Link raus, nach Datum sortiert.

    Alte Eintraege bleiben absichtlich erhalten: faellt ein Feed einmal aus,
    zeigt die App weiter die letzten bekannten Meldungen statt einer leeren
    Liste.
    """
    zusammen = neu + alt
    gesehen, ergebnis = set(), []
    for e in zusammen:
        if e["link"] in gesehen:
            continue
        gesehen.add(e["link"])
        ergebnis.append(e)
    ergebnis.sort(key=lambda e: e.get("datum", ""), reverse=True)
    return ergebnis[:MAX_EINTRAEGE]


def selftest():
    rss2 = b"""<rss><channel>
      <item><title>Tunnelbau am Fehmarnbelt schreitet voran</title>
            <link>https://beispiel.de/a</link>
            <pubDate>Sat, 01 Aug 2026 08:00:00 +0200</pubDate></item>
      <item><title>Biathletin gibt Interview</title>
            <link>https://beispiel.de/b</link>
            <pubDate>Sat, 01 Aug 2026 07:00:00 +0200</pubDate></item>
    </channel></rss>"""
    alle = lies_feed(rss2, "Test", "insel", False)
    assert len(alle) == 2, alle
    assert alle[0]["rubrik"] == "tunnel", "Tunnel-Stichwort muss die Rubrik setzen"
    assert alle[0]["datum"] == "2026-08-01", alle[0]["datum"]

    gefiltert = lies_feed(rss2, "Test", "insel", True)
    assert len(gefiltert) == 1, "landesweite Quelle darf nur Fehmarn-Bezug durchlassen"

    rss1 = b"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
      <item><title>Sturmflut auf Fehmarn</title><link>https://beispiel.de/c</link>
            <dc:date>2026-07-30T10:00:00+02:00</dc:date></item></rdf:RDF>"""
    eins = lies_feed(rss1, "Test", "insel", True)
    assert eins and eins[0]["datum"] == "2026-07-30", eins

    verschmolzen = zusammenfuehren(alle, eins)
    assert len(verschmolzen) == 3, "alte Eintraege muessen erhalten bleiben"
    assert verschmolzen[0]["datum"] == "2026-08-01", "neueste zuerst"
    nochmal = zusammenfuehren(verschmolzen, eins)
    assert len(nochmal) == 3, "Dubletten duerfen sich nicht anhaeufen"
    print("selftest ok")


def main():
    alt = []
    if os.path.exists(ZIEL):
        try:
            alt = json.load(open(ZIEL, encoding="utf-8")).get("eintraege", [])
        except (ValueError, OSError):
            alt = []

    neu, fehler = [], []
    for quelle, url, rubrik, breit in QUELLEN:
        try:
            neu += lies_feed(hole(url), quelle, rubrik, breit)
        except Exception as e:
            fehler.append(f"{url}: {type(e).__name__}")

    eintraege = zusammenfuehren(alt, neu)
    # Ohne alten Bestand UND ohne neue Treffer nichts schreiben — eine leere
    # Datei waere in der App schlimmer als eine veraltete.
    if not eintraege:
        print("keine Eintraege, Datei bleibt unveraendert. Fehler:", fehler)
        return 1

    json.dump(
        {"stand": datetime.now(timezone.utc).date().isoformat(),
         "anzahl": len(eintraege),
         "eintraege": eintraege},
        open(ZIEL, "w", encoding="utf-8"),
        ensure_ascii=False, indent=1,
    )
    print(f"{len(eintraege)} Eintraege geschrieben ({len(neu)} frisch geholt)")
    if fehler:
        print("Quellen mit Problemen:", fehler)
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
