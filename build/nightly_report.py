#!/usr/bin/env python3
"""Morning email with the outcome of the nightly update-data run.

  build/nightly_report.py            (cron on the VPS, 05:00 UTC)
  build/nightly_report.py --dry-run  (print the email instead of sending it)

Reads the latest build/logs/update-data-*.log, the last line of the backup
log, the newest session per chamber in Neo4j and the state of the two SPARQL
endpoints, then sends one email through the Brevo transactional API.
Recipient and Brevo key live outside the repo, in /opt/parliamentrag-job/report.env
(REPORT_TO, BREVO_API_KEY); the Neo4j password comes from .env.
"""
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "build" / "logs"
REPORT_ENV = Path("/opt/parliamentrag-job/report.env")
BACKUP_LOG = Path("/var/log/parliamentrag-backup.log")
SENDER = {"name": "ParliamentRAG", "email": "news@parliamentrag.it"}
ANSI = re.compile(r"\x1b\[[0-9;]*m")
SPARQL = {
    "Camera": "https://dati.camera.it/sparql?query=SELECT%20*%20WHERE%20%7B%3Fs%20%3Fp%20%3Fo%7D%20LIMIT%201&format=json",
    "Senato": "https://dati.senato.it/sparql?query=SELECT%20*%20WHERE%20%7B%3Fs%20%3Fp%20%3Fo%7D%20LIMIT%201&format=json",
}


def env(path: Path) -> dict:
    vals = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    return vals


def latest_log() -> Path | None:
    logs = sorted(LOGS.glob("update-data-*.log"))
    return logs[-1] if logs else None


def steps(log: Path) -> tuple[list[tuple[bool, str]], bool]:
    """Step lines (ok, label) printed by update_data.sh, and whether it died."""
    text = ANSI.sub("", log.read_text(errors="replace"))
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*([✓✗]) (?:\[\d+\] )?(.+)$", line)
        if m:
            out.append((m.group(1) == "✓", m.group(2).strip()))
    return out, "FAILED." in text


def newest_sessions(cfg: dict) -> dict:
    try:
        from neo4j import GraphDatabase
        drv = GraphDatabase.driver(cfg.get("REPORT_NEO4J", "bolt://localhost:7687"),
                                   auth=(cfg.get("NEO4J_USER", "neo4j"), cfg["NEO4J_PASSWORD"]))
        with drv.session() as s:
            rows = s.run("MATCH (x:Session) RETURN coalesce(x.chamber,'camera') AS c, max(x.date) AS d")
            got = {r["c"]: str(r["d"]) for r in rows}
        drv.close()
        return got
    except Exception as exc:  # the email still goes out
        return {"errore": str(exc)[:120]}


def sparql_status() -> dict:
    out = {}
    for name, url in SPARQL.items():
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ParliamentRAG-report"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out[name] = str(r.status)
        except urllib.error.HTTPError as e:
            out[name] = str(e.code)
        except Exception as e:
            out[name] = type(e).__name__
    return out


def backup_line() -> str:
    if not BACKUP_LOG.exists():
        return "log assente"
    lines = [l for l in BACKUP_LOG.read_text(errors="replace").splitlines() if "fine rc=" in l]
    return lines[-1] if lines else "nessuna riga «fine»"


def build(log: Path | None, cfg: dict) -> tuple[str, str]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if log is None:
        return f"Job notturno {today}: nessun log", "<p>Nessun log update-data trovato.</p>"
    rows, died = steps(log)
    failed = [l for ok, l in rows if not ok]
    fresh = log.name[len("update-data-"):len("update-data-") + 8]
    stale = fresh != today.replace("-", "")
    if stale:
        verdict = "NON È PARTITO stanotte"
    elif died:
        verdict = "INTERROTTO"
    elif failed:
        verdict = f"completato con {len(failed)} passi falliti"
    else:
        verdict = "tutto ok"
    subject = f"Job notturno {today}: {verdict}"

    sess = newest_sessions(cfg)
    sp = sparql_status()
    li = "".join(
        f'<li style="color:{"#167a68" if ok else "#b3261e"}">{"✓" if ok else "✗"} {html.escape(l)}</li>'
        for ok, l in rows)
    body = f"""<div style="font-family:Helvetica,Arial,sans-serif;font-size:15px;line-height:22px;color:#12171a">
<p><b>{html.escape(subject)}</b></p>
<p>Ultima seduta nel database: Camera {html.escape(sess.get("camera", "?"))}, Senato {html.escape(sess.get("senato", "?"))}
{("<br>Errore Neo4j: " + html.escape(sess["errore"])) if "errore" in sess else ""}</p>
<p>SPARQL adesso: Camera {sp["Camera"]}, Senato {sp["Senato"]} (200 = funziona)</p>
<p>Backup: {html.escape(backup_line())}</p>
<p>Passi ({len(rows) - len(failed)} ok, {len(failed)} falliti):</p>
<ul style="padding-left:18px;margin:0">{li}</ul>
<p style="color:#5c6468;font-size:13px">Log completo sul VPS: /opt/parliamentrag-job/build/logs/{html.escape(log.name)}</p>
</div>"""
    return subject, body


def main() -> int:
    cfg = {**env(ROOT / ".env"), **env(REPORT_ENV)}
    subject, body = build(latest_log(), cfg)
    if "--dry-run" in sys.argv or not cfg.get("REPORT_TO"):
        print(subject)
        print(re.sub(r"<[^>]+>", "", body))
        return 0
    payload = {"sender": SENDER, "to": [{"email": cfg["REPORT_TO"]}], "subject": subject, "htmlContent": body}
    req = urllib.request.Request("https://api.brevo.com/v3/smtp/email", data=json.dumps(payload).encode(),
                                 headers={"api-key": cfg["BREVO_API_KEY"], "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(subject, "→", r.status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
