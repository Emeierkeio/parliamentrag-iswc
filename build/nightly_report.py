#!/usr/bin/env python3
"""Morning dashboard email on the nightly update-data run.

  build/nightly_report.py            (cron on the VPS, 05:00 UTC)
  build/nightly_report.py --dry-run  (write the HTML to /tmp and print a summary)

Sources:
- step lines (✓/✗, duration) of the last run in the cron log /var/log/parliamentrag-nightly.log;
- per-step output in the latest build/logs/update-data-*.log, split on the
  "════ [n] label" headers that update_data.sh writes, to count failed HTTP
  requests per host, timeouts, warnings and tracebacks;
- node and relationship counts in Neo4j (count store, cheap), compared with the
  previous run kept in report-history.jsonl;
- questions received (ChatHistory) in the last 24 hours;
- the two SPARQL endpoints, the four public sites, backup log, disk, RAM, containers;
- visitors of yesterday from the Plausible Stats API, when PLAUSIBLE_API_KEY is set.

Recipient and keys live outside the repo, in /opt/parliamentrag-job/report.env
(REPORT_TO, BREVO_API_KEY, optional PLAUSIBLE_API_KEY); the Neo4j password comes from .env.
"""
import html
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "build" / "logs"
STATE = Path("/opt/parliamentrag-job/report-history.jsonl")
REPORT_ENV = Path("/opt/parliamentrag-job/report.env")
BACKUP_LOG = Path("/var/log/parliamentrag-backup.log")
NIGHTLY_LOG = Path("/var/log/parliamentrag-nightly.log")
SENDER = {"name": "ParliamentRAG", "email": "news@parliamentrag.it"}
ANSI = re.compile(r"\x1b\[[0-9;]*m")
UA = {"User-Agent": "Mozilla/5.0 ParliamentRAG-report"}
SPARQL = {
    "dati.camera.it": "https://dati.camera.it/sparql?query=SELECT%20*%20WHERE%20%7B%3Fs%20%3Fp%20%3Fo%7D%20LIMIT%201&format=json",
    "dati.senato.it": "https://dati.senato.it/sparql?query=SELECT%20*%20WHERE%20%7B%3Fs%20%3Fp%20%3Fo%7D%20LIMIT%201&format=json",
}
SITES = ["www.parliamentrag.it", "www.stenografo.it", "www.fascicoli.it", "www.scranno.it"]
PLAUSIBLE_SITES = ["parliamentrag.it", "stenografo.it", "fascicoli.it", "scranno.it"]
# Labels shown per chamber; the rest are shown as totals.
BY_CHAMBER = ["Session", "Debate", "Speech", "Vote", "IndividualVote", "ParliamentaryAct"]
# Senate nodes carry no common label (Scope_senato_19 is only on chunks): they are
# told apart by the session they hang from or by their id/uri prefix.
SENATE_COUNT = {
    "Session": "MATCH (n:Session {chamber:'senato'}) RETURN count(n) AS c",
    "Debate": "MATCH (:Session {chamber:'senato'})-[:HAS_DEBATE]->(n:Debate) RETURN count(n) AS c",
    "Speech": "MATCH (n:Speech) WHERE n.id STARTS WITH 'sen_' RETURN count(n) AS c",
    "Vote": "MATCH (:Session {chamber:'senato'})-[:HAS_VOTE]->(n:Vote) RETURN count(n) AS c",
    "IndividualVote": "MATCH (n:IndividualVote) WHERE n.id STARTS WITH 'iv_senato' RETURN count(n) AS c",
    "ParliamentaryAct": "MATCH (n:ParliamentaryAct) WHERE n.uri CONTAINS 'senato' RETURN count(n) AS c",
}
TOTALS = ["Chunk", "Deputy", "Senator", "Person", "SpeakerDebateSummary", "EurovocConcept",
          "MistoComponent", "ChatHistory", "UserFeedback"]
RELS = ["VOTED", "SPOKEN_BY", "PRIMARY_SIGNATORY", "CO_SIGNATORY", "ON_ACT", "MEMBER_OF_GROUP",
        "MEMBER_OF_COMPONENT", "HAS_SUBJECT", "CITES"]
LABEL_IT = {
    "Session": "Sedute", "Debate": "Dibattiti", "Speech": "Interventi", "Vote": "Votazioni",
    "IndividualVote": "Voti individuali", "ParliamentaryAct": "Atti", "Chunk": "Chunk (indice RAG)",
    "Deputy": "Deputati", "Senator": "Senatori", "Person": "Persone", "SpeakerDebateSummary": "Riassunti per oratore",
    "EurovocConcept": "Concetti Eurovoc", "MistoComponent": "Componenti Misto", "ChatHistory": "Domande salvate",
    "UserFeedback": "Feedback utenti",
}
HTTP_FAIL = re.compile(r"(?:HTTP Error|Server Error:?|status(?: code)?:?)\s*(5\d\d|429|403)|\b(5\d\d) (?:Server Error|Bad Gateway|Service)", re.I)
HOST = re.compile(r"https?://([a-z0-9.-]+)", re.I)
TIMEOUT = re.compile(r"timed? ?out|ReadTimeout|ConnectTimeout", re.I)

INK, MUTED, LINE, PAPER, GREEN, RED, AMBER, BLUE = "#12171a", "#5c6468", "#dcdad2", "#f6f5f1", "#167a68", "#b3261e", "#9a6700", "#2d5f8f"
SANS = "font-family:Helvetica,Arial,sans-serif;"
MONO = "font-family:Menlo,Consolas,monospace;"


def env(path: Path) -> dict:
    vals = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    return vals


# ── run log ──────────────────────────────────────────────────────────────────

def step_lines() -> tuple[list[dict], bool]:
    text = ANSI.sub("", NIGHTLY_LOG.read_text(errors="replace")) if NIGHTLY_LOG.exists() else ""
    text = text.rsplit("Updating demo DB at", 1)[-1]
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*([✓✗]) \[(\d+)\] (.+?)(?: \(rc=(\d+), ([^)]+)\)| \(([^)]+)\))?\s*$", line)
        if m:
            out.append({"n": int(m.group(2)), "ok": m.group(1) == "✓", "label": m.group(3).strip(),
                        "rc": int(m.group(4)) if m.group(4) else 0, "dur": m.group(5) or m.group(6) or ""})
    return out, "FAILED." in text


def dur_s(s: str) -> int:
    total = 0
    for v, u in re.findall(r"(\d+)([hms])", s):
        total += int(v) * {"h": 3600, "m": 60, "s": 1}[u]
    return total


def step_sections(log: Path) -> dict[int, str]:
    text = ANSI.sub("", log.read_text(errors="replace"))
    parts = re.split(r"^════ \[(\d+)\] .*$", text, flags=re.M)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def section_stats(body: str) -> dict:
    fails, hosts = Counter(), Counter()
    for line in body.splitlines():
        m = HTTP_FAIL.search(line)
        if m:
            fails[m.group(1) or m.group(2)] += 1
            h = HOST.search(line)
            hosts[h.group(1) if h else "senza indirizzo nel log"] += 1
    return {
        "http": sum(fails.values()), "codes": dict(fails), "hosts": dict(hosts),
        "timeouts": len(TIMEOUT.findall(body)),
        "warnings": len(re.findall(r"WARNING|\bwarn\b|! ", body)),
        "tracebacks": body.count("Traceback (most recent call last)"),
    }


# ── database ─────────────────────────────────────────────────────────────────

def db_counts(cfg: dict) -> dict:
    from neo4j import GraphDatabase
    drv = GraphDatabase.driver(cfg.get("REPORT_NEO4J", "bolt://localhost:7687"),
                               auth=(cfg.get("NEO4J_USER", "neo4j"), cfg["NEO4J_PASSWORD"]))
    out = {"nodes": {}, "rels": {}, "fresh": {}}
    with drv.session() as s:
        for lab in BY_CHAMBER:
            tot = s.run(f"MATCH (n:{lab}) RETURN count(n) AS c").single()["c"]
            sen = s.run(SENATE_COUNT[lab]).single()["c"]
            out["nodes"][lab] = {"camera": tot - sen, "senato": sen}
        for lab in TOTALS:
            out["nodes"][lab] = {"tot": s.run(f"MATCH (n:{lab}) RETURN count(n) AS c").single()["c"]}
        for rel in RELS:
            out["rels"][rel] = s.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c").single()["c"]
        for r in s.run("MATCH (x:Session) RETURN coalesce(x.chamber,'camera') AS c, max(x.date) AS d, count(x) AS n"):
            out["fresh"][r["c"]] = {"session": str(r["d"])}
        for r in s.run("MATCH (x:Session)-[:HAS_DEBATE]->(:Debate)<-[:FOR_DEBATE]-(:SpeakerDebateSummary) "
                       "RETURN coalesce(x.chamber,'camera') AS c, max(x.date) AS d"):
            out["fresh"].setdefault(r["c"], {})["summary"] = str(r["d"])
        for r in s.run("MATCH (x:Session)-[:HAS_VOTE]->(:Vote) RETURN coalesce(x.chamber,'camera') AS c, max(x.date) AS d"):
            out["fresh"].setdefault(r["c"], {})["vote"] = str(r["d"])
        q = s.run("MATCH (c:ChatHistory) WHERE c.timestamp IS NOT NULL AND datetime(c.timestamp) >= datetime() - duration('P1D') "
                  "RETURN count(c) AS n").single()
        out["questions_24h"] = q["n"]
    drv.close()
    return out


def archive_counts() -> dict:
    try:
        r = subprocess.run(["docker", "exec", "parliament-archivio", "psql", "-U", "archivio", "-d", "archivio", "-Atc",
                            "select relname, n_live_tup from pg_stat_user_tables order by 1"],
                           capture_output=True, text=True, timeout=30)
        return {k: int(v) for k, v in (l.split("|") for l in r.stdout.split() if "|" in l)}
    except Exception:
        return {}


# ── services ─────────────────────────────────────────────────────────────────

def probe(url: str) -> tuple[str, int]:
    t = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            code = str(r.status)
    except urllib.error.HTTPError as e:
        code = str(e.code)
    except Exception as e:
        code = type(e).__name__
    return code, int((time.monotonic() - t) * 1000)


def machine() -> dict:
    du = shutil.disk_usage("/")
    mem = {}
    try:
        for l in Path("/proc/meminfo").read_text().splitlines():
            k, v = l.split(":")
            mem[k] = int(v.split()[0]) // 1024
    except Exception:
        pass
    try:
        ps = subprocess.run(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"], capture_output=True, text=True, timeout=15).stdout.split("\n")
        containers = [l.split("|") for l in ps if "|" in l]
    except Exception:
        containers = []
    backup = "log assente"
    if BACKUP_LOG.exists():
        ends = [l for l in BACKUP_LOG.read_text(errors="replace").splitlines() if "fine rc=" in l]
        backup = ends[-1] if ends else "nessuna riga «fine»"
    return {"disk_used": du.used / du.total, "disk_free_gb": du.free / 1e9,
            "ram_total": mem.get("MemTotal", 0), "ram_avail": mem.get("MemAvailable", 0),
            "containers": containers, "backup": backup}


def plausible(cfg: dict) -> dict:
    key = cfg.get("PLAUSIBLE_API_KEY")
    if not key:
        return {}
    y = (date.today() - timedelta(days=1)).isoformat()
    out = {}
    for site in PLAUSIBLE_SITES:
        body = json.dumps({"site_id": site, "metrics": ["visitors", "pageviews"], "date_range": [y, y]}).encode()
        req = urllib.request.Request("https://plausible.io/api/v2/query", data=body,
                                     headers={"Authorization": f"Bearer {key}", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                m = json.load(r)["results"][0]["metrics"]
                out[site] = {"visitors": m[0], "pageviews": m[1]}
        except Exception as e:
            out[site] = {"errore": type(e).__name__}
    return out


# ── history ──────────────────────────────────────────────────────────────────

def history() -> list[dict]:
    if not STATE.exists():
        return []
    return [json.loads(l) for l in STATE.read_text().splitlines() if l.strip()]


def flat(db: dict) -> dict:
    f = {}
    for lab, v in db.get("nodes", {}).items():
        for k, n in v.items():
            f[f"{lab}.{k}"] = n
    for rel, n in db.get("rels", {}).items():
        f[f"rel.{rel}"] = n
    return f


# ── html ─────────────────────────────────────────────────────────────────────

def fmt(n) -> str:
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else html.escape(str(n))


def delta(now, prev) -> str:
    if prev is None or not isinstance(now, int):
        return f'<span style="color:{MUTED}">n.d.</span>'
    d = now - prev
    if d == 0:
        return f'<span style="color:{MUTED}">0</span>'
    col = GREEN if d > 0 else RED
    return f'<span style="color:{col};font-weight:600">{"+" if d > 0 else "−"}{fmt(abs(d))}</span>'


def tile(label: str, value: str, note: str = "", col: str = INK) -> str:
    return (f'<td style="padding:6px;width:25%;vertical-align:top"><div style="border:1px solid {LINE};border-radius:8px;padding:12px 12px 10px;background:#fff">'
            f'<div style="{MONO}font-size:10px;letter-spacing:1px;text-transform:uppercase;color:{MUTED}">{label}</div>'
            f'<div style="{SANS}font-size:24px;line-height:30px;font-weight:700;color:{col};margin-top:4px">{value}</div>'
            f'<div style="{SANS}font-size:12px;color:{MUTED}">{note}</div></div></td>')


def table(head: list[str], rows: list[list[str]], align: str = "left") -> str:
    th = "".join(f'<th style="{SANS}font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:{MUTED};text-align:{"left" if i == 0 else align};padding:6px 8px;border-bottom:2px solid {INK}">{h}</th>' for i, h in enumerate(head))
    tr = "".join("<tr>" + "".join(f'<td style="{SANS}font-size:13px;padding:6px 8px;border-bottom:1px solid {LINE};text-align:{"left" if i == 0 else align};vertical-align:top">{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:6px 0 4px">{th and "<tr>" + th + "</tr>"}{tr}</table>'


def h2(t: str) -> str:
    return f'<h2 style="{SANS}font-size:16px;margin:26px 0 4px;color:{INK}">{t}</h2>'


def code_badge(code: str) -> str:
    col = GREEN if code == "200" else RED
    return f'<span style="{MONO}font-size:12px;color:#fff;background:{col};border-radius:4px;padding:1px 6px">{html.escape(code)}</span>'


def build(cfg: dict) -> tuple[str, str, dict]:
    today = datetime.now(timezone.utc).date().isoformat()
    logs = sorted(LOGS.glob("update-data-*.log"))
    log = logs[-1] if logs else None
    steps, died = step_lines()
    secs = step_sections(log) if log else {}
    for s in steps:
        s.update(section_stats(secs.get(s["n"], "")))
    ran_today = bool(log) and log.name[12:20] == today.replace("-", "")
    failed = [s for s in steps if not s["ok"]]
    http_total = sum(s["http"] for s in steps)
    hosts = Counter()
    for s in steps:
        hosts.update(s["hosts"])
    total_s = sum(dur_s(s["dur"]) for s in steps)

    try:
        db = db_counts(cfg)
    except Exception as e:
        db = {"errore": str(e)[:200]}
    arch = archive_counts()
    hist = history()
    prev = flat(hist[-1]["db"]) if hist and hist[-1].get("date") != today else (flat(hist[-2]["db"]) if len(hist) > 1 else {})
    cur = flat(db)
    sp = {h: probe(u) for h, u in SPARQL.items()}
    sites = {s: probe(f"https://{s}/") for s in SITES}
    mach = machine()
    vis = plausible(cfg)

    if not ran_today:
        verdict, vcol = "NON È PARTITO stanotte", RED
    elif died:
        verdict, vcol = "INTERROTTO", RED
    elif failed:
        verdict, vcol = f"completato, {len(failed)} passi falliti", AMBER
    elif http_total:
        verdict, vcol = f"completato, {http_total} richieste fallite", AMBER
    else:
        verdict, vcol = "tutto ok", GREEN
    subject = f"Job notturno {today}: {verdict}"

    new_speech = sum(cur.get(f"Speech.{c}", 0) - prev.get(f"Speech.{c}", cur.get(f"Speech.{c}", 0)) for c in ("camera", "senato"))
    new_votes = sum(cur.get(f"Vote.{c}", 0) - prev.get(f"Vote.{c}", cur.get(f"Vote.{c}", 0)) for c in ("camera", "senato"))
    visitors = sum(v.get("visitors", 0) for v in vis.values()) if vis else None

    parts = [f'<div style="background:{PAPER};padding:20px 14px">'
             f'<div style="max-width:720px;margin:0 auto">'
             f'<div style="{MONO}font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{MUTED}">ParliamentRAG · job notturno · {today}</div>'
             f'<h1 style="{SANS}font-size:26px;line-height:32px;margin:6px 0 2px;color:{vcol}">{html.escape(verdict)}</h1>'
             f'<div style="{SANS}font-size:13px;color:{MUTED}">Durata {total_s // 60} min · {len(steps) - len(failed)}/{len(steps)} passi ok · log {html.escape(log.name if log else "assente")}</div>']

    parts.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:14px 0 0"><tr>'
                 + tile("Passi falliti", str(len(failed)), "su " + str(len(steps)), RED if failed else GREEN)
                 + tile("Richieste fallite", fmt(http_total), ", ".join(f"{h} {n}" for h, n in hosts.most_common(2)) or "nessuna", RED if http_total else GREEN)
                 + tile("Nuovi interventi", fmt(new_speech) if prev else "n.d.", "rispetto al giro prima")
                 + tile("Nuove votazioni", fmt(new_votes) if prev else "n.d.", "rispetto al giro prima")
                 + '</tr><tr>'
                 + tile("Domande 24 h", fmt(db.get("questions_24h", "n.d.")), "salvate in ChatHistory")
                 + tile("Visite ieri", fmt(visitors) if visitors is not None else "n.d.", "Plausible, 4 siti" if vis else "manca PLAUSIBLE_API_KEY")
                 + tile("SPARQL Camera", sp["dati.camera.it"][0], "adesso", GREEN if sp["dati.camera.it"][0] == "200" else RED)
                 + tile("SPARQL Senato", sp["dati.senato.it"][0], "adesso", GREEN if sp["dati.senato.it"][0] == "200" else RED)
                 + '</tr></table>')

    # freshness
    fr = db.get("fresh", {})
    parts.append(h2("Freschezza dei dati"))
    parts.append(table(["", "Ultima seduta", "Ultima votazione", "Ultimo riassunto"],
                       [[c.capitalize(), fmt(fr.get(c, {}).get("session", "?")), fmt(fr.get(c, {}).get("vote", "?")), fmt(fr.get(c, {}).get("summary", "?"))]
                        for c in ("camera", "senato")]))

    # steps
    parts.append(h2("Passi del job"))
    rows = []
    for s in steps:
        codes = " ".join(f"{k}×{v}" for k, v in s["codes"].items())
        rows.append([f'<span style="color:{GREEN if s["ok"] else RED};font-weight:700">{"✓" if s["ok"] else "✗"}</span> {s["n"]}. {html.escape(s["label"])}',
                     html.escape(s["dur"].replace(", ", "")),
                     f'<span style="color:{RED if s["http"] else MUTED}">{fmt(s["http"])}</span>' + (f'<br><span style="{MONO}font-size:11px;color:{MUTED}">{codes}</span>' if codes else ""),
                     fmt(s["timeouts"]), fmt(s["warnings"]), fmt(s["tracebacks"])])
    parts.append(table(["Passo", "Durata", "HTTP falliti", "Timeout", "Warning", "Traceback"], rows, "right"))

    # sources
    if hosts:
        parts.append(h2("Richieste fallite per fonte"))
        parts.append(table(["Host", "Richieste fallite", "Stato adesso"],
                           [[html.escape(h), fmt(n), code_badge(sp[h][0]) if h in sp else "–"] for h, n in hosts.most_common()], "right"))

    # database
    parts.append(h2("Contenuto del database"))
    if "errore" in db:
        parts.append(f'<p style="{SANS}color:{RED}">Neo4j non raggiungibile: {html.escape(db["errore"])}</p>')
    else:
        rows = []
        for lab in BY_CHAMBER:
            c, s_ = cur[f"{lab}.camera"], cur[f"{lab}.senato"]
            rows.append([LABEL_IT[lab], fmt(c), delta(c, prev.get(f"{lab}.camera")), fmt(s_), delta(s_, prev.get(f"{lab}.senato"))])
        parts.append(table(["", "Camera", "Δ", "Senato", "Δ"], rows, "right"))
        rows = [[LABEL_IT[lab], fmt(cur[f"{lab}.tot"]), delta(cur[f"{lab}.tot"], prev.get(f"{lab}.tot"))] for lab in TOTALS]
        rows += [[f'<span style="{MONO}font-size:12px">{r}</span>', fmt(cur[f"rel.{r}"]), delta(cur[f"rel.{r}"], prev.get(f"rel.{r}"))] for r in RELS]
        parts.append(table(["Altri nodi e relazioni", "Totale", "Δ"], rows, "right"))
    if arch:
        parts.append(table(["Archivio Postgres", "Righe"], [[html.escape(k), fmt(v)] for k, v in arch.items()], "right"))

    # services
    parts.append(h2("Servizi e macchina"))
    rows = [[html.escape(s), code_badge(c), f"{ms} ms"] for s, (c, ms) in sites.items()]
    rows += [[f"SPARQL {h}", code_badge(c), f"{ms} ms"] for h, (c, ms) in sp.items()]
    parts.append(table(["Servizio", "Stato", "Risposta"], rows, "right"))
    ram_used = 1 - mach["ram_avail"] / mach["ram_total"] if mach["ram_total"] else 0
    rows = [["Disco", f'{mach["disk_used"]:.0%} usato', f'{mach["disk_free_gb"]:.0f} GB liberi'],
            ["RAM", f"{ram_used:.0%} usata", f'{mach["ram_avail"]:,} MB disponibili'.replace(",", ".")],
            ["Backup", html.escape(mach["backup"]), ""]]
    rows += [[html.escape(n), html.escape(st), ""] for n, st in mach["containers"]]
    parts.append(table(["", "", ""], rows, "right"))
    if vis:
        parts.append(table(["Visite di ieri (Plausible)", "Visitatori", "Pagine viste"],
                           [[s, fmt(v.get("visitors", v.get("errore", "?"))), fmt(v.get("pageviews", ""))] for s, v in vis.items()], "right"))

    # trend
    entry = {"date": today, "verdict": verdict, "failed": len(failed), "http": http_total, "minutes": total_s // 60,
             "new_speech": new_speech if prev else None, "new_votes": new_votes if prev else None,
             "questions": db.get("questions_24h"), "visitors": visitors, "db": {k: db[k] for k in ("nodes", "rels") if k in db}}
    trend = [h for h in hist if h.get("date") != today][-6:] + [entry]
    parts.append(h2("Ultimi 7 giri"))
    parts.append(table(["Data", "Esito", "Min", "Passi ✗", "HTTP ✗", "Interventi +", "Votazioni +", "Domande"],
                       [[t["date"], html.escape(t["verdict"]), fmt(t["minutes"]), fmt(t["failed"]), fmt(t["http"]),
                         fmt(t["new_speech"]) if t.get("new_speech") is not None else "n.d.",
                         fmt(t["new_votes"]) if t.get("new_votes") is not None else "n.d.",
                         fmt(t["questions"]) if t.get("questions") is not None else "n.d."] for t in trend], "right"))
    parts.append(f'<p style="{SANS}font-size:12px;color:{MUTED};margin-top:18px">Δ = differenza rispetto al giro precedente. '
                 f'«HTTP falliti» conta le righe di log con un errore 5xx, 403 o 429, anche quando il passo è riuscito con i dati del giorno prima. '
                 f'Log completo sul VPS: /opt/parliamentrag-job/build/logs/{html.escape(log.name if log else "")}</p></div></div>')
    return subject, "".join(parts), entry


def main() -> int:
    cfg = {**env(ROOT / ".env"), **env(REPORT_ENV)}
    subject, body, entry = build(cfg)
    if "--dry-run" in sys.argv or not cfg.get("REPORT_TO"):
        Path("/tmp/nightly_report.html").write_text(body)
        print(subject, "→ /tmp/nightly_report.html")
        return 0
    payload = {"sender": SENDER, "to": [{"email": cfg["REPORT_TO"]}], "subject": subject, "htmlContent": body}
    req = urllib.request.Request("https://api.brevo.com/v3/smtp/email", data=json.dumps(payload).encode(),
                                 headers={"api-key": cfg["BREVO_API_KEY"], "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(subject, "→", r.status)
    hist = [h for h in history() if h.get("date") != entry["date"]] + [entry]
    STATE.write_text("".join(json.dumps(h, ensure_ascii=False) + "\n" for h in hist[-60:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
