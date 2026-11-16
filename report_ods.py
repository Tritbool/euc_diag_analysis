#!/usr/bin/env python3
"""Rapport ODS pour logs de diagnostic InMotion (V9).

Autonome : aucun import local. Accepte un log.bin ou un dump hexadécimal
xxd (.txt). Génère un classeur ODS multi-feuilles :
Synthèse / Sorties / Allumages / Événements / Journal / Types / Graphiques.
Exporte aussi les graphiques en PNG dans <rapport>_graphiques/.

Usage :
    pip install odfpy matplotlib
    python3 report_ods.py diag.bin [rapport.ods]
"""
import sys, re, os, struct, tempfile
from datetime import datetime

REC = 64
PERIODIC, PERIODIC2 = 82, 101
EVENTS = {1:"Démarrage (1)",2:"Prêt",3:"Démarrage (2)",4:"Démarrage (3)",5:"Démarrage (4)",
          6:"Bouton/mode",7:"Début roulage",8:"Événement 8",11:"Événement 11",12:"Événement 12",
          13:"Événement 13",17:"Événement 17",18:"Événement 18",20:"Événement 20",
          21:"Événement 21",23:"Événement 23",35:"Événement 35",36:"Événement 36",
          42:"Événement 42",68:"Événement 68",76:"Événement 76",81:"Début de capture",
          82:"Échantillon 10 Hz",83:"Fin de capture",101:"Échantillon à l'arrêt"}

# ---------------- chargement ----------------
def load_bytes(path):
    data = open(path, "rb").read()
    if len(data) > 3 and data[0] == 2 and data[1] == 0 and data[2] == 0 and data[3] == 0:
        return data
    n = min(512, len(data))
    if all(32 <= b < 127 or b in (10, 13, 9) for b in data[:n]):
        out = bytearray()
        for line in data.decode("utf-8", "replace").splitlines():
            c = line.find(":")
            if c < 0:
                continue
            hexpart = line[c+1:].split("  ")[0]
            for h in re.findall(r"[0-9a-fA-F]{2}", hexpart):
                out.append(int(h, 16))
        if out:
            return bytes(out)
    return data

# ---------------- décodage ----------------
def u16(d, o):
    v = struct.unpack_from("<H", d, o)[0]
    return None if v == 0xFFFF else v

def s16(d, o):
    v = struct.unpack_from("<h", d, o)[0]
    return None if v == -1 else v

def temp(d, o):
    v = struct.unpack_from("<H", d, o)[0]
    return (v - 50000) / 100 if 40000 < v < 60000 else None

def temp_half(d, o):
    v = struct.unpack_from("<H", d, o)[0]
    return v / 2 if 0 < v < 200 else None

def clock(d, o):
    v = struct.unpack_from("<I", d, o)[0]
    Y = 2020 + (v & 63); M = (v >> 6) & 15; D = (v >> 10) & 31
    h = (v >> 15) & 31; mi = (v >> 20) & 63; s = (v >> 26) & 63
    if not (1 <= M <= 12 and D >= 1 and h <= 23 and mi <= 59 and s <= 59):
        return None
    try:
        return datetime(Y, M, D, h, mi, s)
    except ValueError:
        return None

def parse(data):
    out = []
    for i in range(len(data) // REC):
        b = data[i*REC:(i+1)*REC]
        if struct.unpack_from("<I", b, 0)[0] != 2 or b == b"\xff"*REC:
            continue
        sc = lambda v, x: None if v is None else v / x
        out.append({
            "pos": len(out), "time": clock(b, 8), "up": struct.unpack_from("<I", b, 12)[0],
            "type": b[16],
            "v1": sc(u16(b, 24), 100), "cur": sc(s16(b, 26), 100), "spd": sc(s16(b, 28), 100),
            "phase": sc(s16(b, 30), 1),
            "pitch": sc(s16(b, 38), 100), "ptarget": sc(s16(b, 40), 100), "roll": sc(s16(b, 42), 100),
            "tiltback": sc(u16(b, 46), 100), "limit": sc(u16(b, 48), 100),
            "tMos": temp(b, 50), "tBoard": temp(b, 52), "tBatt": temp_half(b, 54),
            "soc": u16(b, 56), "tMot": temp(b, 58), "tMot2": temp(b, 60), "v2": sc(u16(b, 62), 100),
        })
    return out

def analyse(entries):
    sessions, cur, prev = [], [], None
    for e in entries:
        if prev is not None and e["up"] < prev - 1000:
            sessions.append(cur); cur = []
        cur.append(e); prev = e["up"]
    if cur:
        sessions.append(cur)

    captures, cc, last = [], None, None
    def finish():
        nonlocal cc
        if not cc:
            return
        samples = cc["before"] + cc["after"]
        if len(samples) >= 10:
            cc["samples"] = samples
            cc["time"] = samples[0]["time"]
            if cc["breakUp"] is None:
                cc["breakUp"] = (cc["before"][-1]["up"] + 100) if cc["before"] else samples[0]["up"]
            captures.append(cc)
        cc = None
    for e in entries:
        periodic = e["type"] in (PERIODIC, PERIODIC2)
        if periodic:
            if cc and last and e["up"] > last["up"] + 1500:
                finish()
            if not cc:
                cc = {"before": [], "after": [], "others": [], "breakUp": None, "trigger": None}
            (cc["after"] if cc["breakUp"] is not None else cc["before"]).append(e)
            last = e
        elif cc:
            if last and e["up"] <= last["up"] + 1500:
                if cc["breakUp"] is None:
                    cc["breakUp"] = e["up"]; cc["trigger"] = e
                cc["others"].append(e)
            else:
                finish(); last = None
    finish()

    rides = []
    for s in sessions:
        sp = [e for e in s if e["type"] == PERIODIC and e["spd"] is not None
              and e["v1"] is not None and 40 < e["v1"] < 100]
        if not sp or max(abs(e["spd"]) for e in sp) < 5:
            continue
        socs = [e["soc"] for e in sp if e["soc"] is not None and e["soc"] <= 100]
        tm = [e["tMos"] for e in sp if e["tMos"] is not None]
        rides.append({
            "session": s, "samples": sp, "start": s[0]["time"], "dur": s[-1]["up"] / 1000,
            "vmax": max(abs(e["spd"]) for e in sp),
            "imax": max(e["cur"] or 0 for e in sp),
            "vmin": min(e["v1"] for e in sp),
            "soc0": socs[0] if socs else None, "soc1": socs[-1] if socs else None,
            "tmax": max(tm) if tm else None, "nev": len(s),
        })

    sessionOf = [-1] * len(entries)
    for i, s in enumerate(sessions):
        for e in s:
            sessionOf[e["pos"]] = i
    capBySess = {}
    for c in captures:
        si = sessionOf[c["samples"][0]["pos"]]
        if si >= 0:
            capBySess[si] = capBySess.get(si, 0) + 1
    counts = {}
    for e in entries:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    return {"entries": entries, "sessions": sessions, "sessionOf": sessionOf,
            "capBySess": capBySess, "rides": rides, "captures": captures, "counts": counts}

# ---------------- graphiques ----------------
def render_charts(log, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    C = {"blue":"#3987e5","red":"#e66767","orange":"#c98500","green":"#199e70",
         "purple":"#9085e9","pink":"#d55181","amber":"#e6a23c"}
    files = []  # (titre, chemin png)

    def save(fig, title):
        p = os.path.join(outdir, f"chart{len(files)}.png")
        fig.savefig(p, dpi=110, bbox_inches="tight")
        plt.close(fig)
        files.append((title, p))

    rs = sorted(log["rides"], key=lambda x: x["start"] or datetime.min)
    xs = list(range(len(rs)))

    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.bar(xs, [r["tmax"] or 0 for r in rs], color=C["red"])
    ax.set_title("Température max par sortie (°C)"); ax.set_xlabel("n° sortie")
    save(fig, "Température max par sortie")

    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(xs, [r["vmin"] for r in rs], color=C["blue"], marker=".")
    ax.set_title("Tension min par sortie (V)"); ax.set_xlabel("n° sortie")
    save(fig, "Tension min par sortie")

    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(xs, [r["soc0"] for r in rs], color=C["green"], marker=".", label="Début")
    ax.plot(xs, [r["soc1"] for r in rs], color=C["orange"], marker=".", label="Fin")
    ax.set_title("Charge batterie par sortie (%)"); ax.set_xlabel("n° sortie"); ax.legend()
    save(fig, "Charge batterie par sortie")

    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(xs, [r["vmax"] for r in rs], color=C["pink"], marker=".")
    ax.set_title("Vitesse max par sortie (km/h)"); ax.set_xlabel("n° sortie")
    save(fig, "Vitesse max par sortie")

    panels = [
        ("Vitesse (km/h)", [("Vitesse", "spd", "blue"), ("Tiltback", "tiltback", "orange")]),
        ("Angles (°)", [("Tangage", "pitch", "blue"), ("Consigne", "ptarget", "orange"),
                        ("Roulis", "roll", "green")]),
        ("Courants (A)", [("Batterie", "cur", "red"), ("Phase (brut)", "phase", "purple")]),
        ("Tension (V)", [("Pack 1", "v1", "blue"), ("Pack 2", "v2", "purple")]),
        ("Charge (%)", [("SOC", "soc", "green")]),
        ("Températures (°C)", [("MOSFET", "tMos", "red"), ("Moteur", "tMot", "amber"),
                               ("Batterie", "tBatt", "green"), ("Carte", "tBoard", "orange")]),
    ]
    for c in log["captures"]:
        sm = c["samples"]
        t0 = sm[0]["up"]
        x = [(e["up"] - t0) / 1000 for e in sm]
        brk = (c["breakUp"] - t0) / 1000
        fig, axes = plt.subplots(2, 3, figsize=(12, 6))
        for ax, (title, series) in zip(axes.flat, panels):
            for label, key, col in series:
                ax.plot(x, [e[key] for e in sm], color=C[col], label=label, linewidth=1)
            if brk is not None:
                ax.axvline(brk, color=C["red"], linestyle="--", linewidth=1)
            ax.set_title(title, fontsize=9)
            ax.legend(fontsize=7)
        trig = f"type {c['trigger']['type']}" if c["trigger"] else "sans déclencheur"
        fig.suptitle(f"Capture du {c['time']} — {len(sm)} échantillons — {trig}", fontsize=10)
        fig.tight_layout()
        save(fig, f"Capture {c['time']} ({trig})")

    return files

# ---------------- ODS ----------------
def build_ods(log, out_path, chart_files):
    from odf.opendocument import OpenDocument
    from odf.style import Style, TextProperties, TableColumnProperties, TableRowProperties
    from odf.text import P
    from odf.draw import Frame, Image as DImage
    from odf.table import Table, TableColumn, TableRow, TableCell
    from odf.office import Spreadsheet

    doc = OpenDocument("application/vnd.oasis.opendocument.spreadsheet")
    doc.spreadsheet = Spreadsheet()
    doc.body.addElement(doc.spreadsheet)

    hdr = Style(name="hdr", family="table-cell")
    hdr.addElement(TextProperties(fontweight="bold", color="#888888"))
    doc.automaticstyles.addElement(hdr)

    colw = Style(name="co", family="table-column")
    colw.addElement(TableColumnProperties(columnwidth="3.2cm"))
    doc.automaticstyles.addElement(colw)

    rowh = Style(name="rh", family="table-row")
    rowh.addElement(TableRowProperties(rowheight="7.6cm"))
    doc.automaticstyles.addElement(rowh)

    def cell(value, header=False):
        c = TableCell(stylename=hdr) if header else TableCell()
        if isinstance(value, datetime):
            c.setAttribute("valuetype", "date")
            c.setAttribute("datevalue", value.strftime("%Y-%m-%dT%H:%M:%S"))
            c.addElement(P(text=str(value.strftime("%Y-%m-%d %H:%M:%S"))))
        elif isinstance(value, bool):
            c.setAttribute("valuetype", "boolean")
            c.setAttribute("value", "1" if value else "0")
            c.addElement(P(text="1" if value else "0"))
        elif isinstance(value, (int, float)):
            c.setAttribute("valuetype", "float")
            c.setAttribute("value", repr(value))
            c.addElement(P(text=repr(value)))
        else:
            c.addElement(P(text="" if value is None else str(value)))
        return c

    def sheet(name, headers, rows):
        t = Table(name=name)
        for _ in headers:
            t.addElement(TableColumn(stylename=colw))
        hr = TableRow()
        for h in headers:
            hr.addElement(cell(h, header=True))
        t.addElement(hr)
        for r in rows:
            tr = TableRow()
            for v in r:
                tr.addElement(cell(v))
            t.addElement(tr)
        doc.spreadsheet.addElement(t)

    fmt = lambda v, n=1: "—" if v is None else round(v, n)

    # --- Synthèse ---
    e, r = log["entries"], log["rides"]
    dates = [x["time"] for x in e if x["time"]]
    socs = [x["soc"] for x in e if x["soc"] is not None and x["soc"] <= 100]
    vmax = max((x["vmax"] for x in r), default=None)
    imax = max((x["imax"] for x in r), default=None)
    vmin = min((x["vmin"] for x in r), default=None)
    tmax = max((x["tmax"] for x in r if x["tmax"] is not None), default=None)
    days = round((dates[-1] - dates[0]).days) if len(dates) >= 2 else 0
    sheet("Synthèse", ["Indicateur", "Valeur", "Détail"], [
        ["Période", f"{dates[0]:%Y-%m-%d} → {dates[-1]:%Y-%m-%d}" if dates else "—", f"{days} jours"],
        ["Mises sous tension", len(log["sessions"]), ""],
        ["Sorties avec roulage", len(r), ""],
        ["Événements capturés", len(log["captures"]), ""],
        ["Vitesse max (km/h)", fmt(vmax), ""],
        ["Courant max (A)", fmt(imax), ""],
        ["Tension min (V)", fmt(vmin, 2), ""],
        ["T° max contrôleur (°C)", fmt(tmax, 0), ""],
        ["Charge min (%)", min(socs) if socs else "—", ""],
        ["Enregistrements", len(e), ""],
    ])

    # --- Sorties ---
    sheet("Sorties",
          ["Date", "Durée (min)", "V max (km/h)", "I max (A)", "V min (V)",
           "Charge début (%)", "Charge fin (%)", "T° max (°C)", "Événements"],
          [[x["start"], round(x["dur"] / 60), fmt(x["vmax"]), fmt(x["imax"]), fmt(x["vmin"], 2),
            x["soc0"], x["soc1"], fmt(x["tmax"], 0), x["nev"]] for x in r])

    # --- Allumages ---
    rows = []
    for i, s in enumerate(log["sessions"]):
        socs = [x["soc"] for x in s if x["soc"] is not None and x["soc"] <= 100]
        soc0 = socs[0] if socs else None
        soc1 = socs[-1] if socs else None
        dur = (s[-1]["up"] - s[0]["up"]) / 1000
        rows.append([s[0]["time"], s[-1]["time"], round(dur), len(s), soc0, soc1,
                     "Recharge" if soc0 is not None and soc1 is not None and soc1 > soc0 else "",
                     log["capBySess"].get(i, 0)])
    sheet("Allumages", ["Début", "Fin", "Durée (s)", "Entrées", "Charge début (%)",
                        "Charge fin (%)", "Recharge", "Captures"], rows)

    # --- Événements ---
    rows = []
    for c in log["captures"]:
        sm = c["samples"]
        t0, t1 = sm[0]["up"], sm[-1]["up"]
        rows.append([c["time"], round((t1 - t0) / 1000, 1), len(sm),
                     len(c["before"]), len(c["after"]),
                     c["trigger"]["type"] if c["trigger"] else "",
                     EVENTS.get(c["trigger"]["type"], "Inconnu") if c["trigger"] else "Sans déclencheur",
                     round((c["breakUp"] - t0) / 1000, 2)])
    sheet("Événements", ["Date", "Durée (s)", "Échantillons", "Avant", "Après",
                          "Type déclencheur", "Libellé", "Rupture (s)"], rows)

    # --- Journal ---
    sheet("Journal",
          ["Date", "Uptime (s)", "Type", "Libellé", "Vitesse (km/h)", "Courant (A)",
           "Pack 1 (V)", "Pack 2 (V)", "Charge (%)", "T° MOSFET (°C)"],
          [[x["time"], round(x["up"] / 1000, 1), x["type"], EVENTS.get(x["type"], "Inconnu"),
            fmt(x["spd"]), fmt(x["cur"]), fmt(x["v1"], 2), fmt(x["v2"], 2), x["soc"],
            fmt(x["tMos"], 0)] for x in e])

    # --- Types ---
    sheet("Types", ["Type", "Libellé", "Occurrences"],
          [[t, EVENTS.get(t, "Inconnu"), n] for t, n in
           sorted(log["counts"].items(), key=lambda kv: -kv[1])])

    # --- Graphiques ---
    if chart_files:
        z = 0
        t = Table(name="Graphiques")
        t.addElement(TableColumn(stylename=colw))
        for title, png in chart_files:
            tr = TableRow()
            tr.addElement(cell(title, header=True))
            t.addElement(tr)
            tr = TableRow(stylename=rowh)
            c = TableCell()
            c.addElement(P(text=""))
            fr = Frame(width="14cm", height="7.2cm", zindex=str(z))
            fr.setAttribute("name", f"Graphique {z + 1}")
            fr.setAttribute("anchortype", "paragraph")
            img = DImage(href=doc.addPicture(png))
            img.setAttribute("type", "simple")
            img.setAttribute("show", "embed")
            img.setAttribute("actuate", "onLoad")
            fr.addElement(img)
            c.addElement(fr)
            tr.addElement(c)
            t.addElement(tr)
            z += 1
        doc.spreadsheet.addElement(t)

    doc.save(out_path)

# ---------------- main ----------------
def main():
    if len(sys.argv) < 2:
        print("Usage : python3 report_ods.py <log.bin|dump.txt> [rapport.ods]")
        sys.exit(1)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else re.sub(r"\.[^.]+$", "", src) + "_rapport.ods"
    data = load_bytes(src)
    entries = parse(data)
    if not entries:
        print(f"ERREUR : aucun enregistrement InMotion reconnu dans {src}.\n"
              f"(fichier de {len(data)} octets — attendu : log.bin 64 o/enregistrement ou dump xxd)")
        sys.exit(1)
    log = analyse(entries)
    chart_files = []
    pngdir = re.sub(r"\.[^.]+$", "", out) + "_graphiques"
    try:
        import shutil
        os.makedirs(pngdir, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            chart_files = render_charts(log, tmp)
            for title, p in chart_files:
                safe = re.sub(r"[^A-Za-z0-9À-ÿ ()_-]+", "_", title)[:80]
                shutil.copy(p, os.path.join(pngdir, safe + ".png"))
            build_ods(log, out, chart_files)
    except ImportError as ex:
        print(f"matplotlib indisponible ({ex}) — ODS généré sans feuille Graphiques.")
        build_ods(log, out, [])
    print(f"{out} : {len(entries)} entrées · {len(log['sessions'])} allumages · "
          f"{len(log['rides'])} sorties · {len(log['captures'])} captures · "
          f"{len(log['counts'])} types · {len(chart_files)} graphiques")
    if chart_files:
        print(f"PNG aussi exportés dans : {pngdir}")

if __name__ == "__main__":
    main()
