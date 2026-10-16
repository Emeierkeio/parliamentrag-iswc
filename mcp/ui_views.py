"""
Viste MCP Apps (estensione io.modelcontextprotocol/ui, specifica 2026-01-26).

Ogni vista è una pagina HTML autonoma che l'host mostra in un iframe sotto la
chiamata dello strumento. La pagina fa l'handshake ui/initialize, riceve il
risultato con ui/notifications/tool-result e lo disegna. Niente risorse
esterne: la CSP di default consente solo script e stili inline e immagini
data:. I link si aprono con ui/open-link, perché l'iframe è in sandbox.

Colori e tipi come il sito www.parliamentrag.it; tema chiaro o scuro dall'host.
"""

# Ponte JSON-RPC con l'host, comune alle viste. Chiama window.disegna(params)
# a ogni risultato dello strumento e window.lingua() per la lingua dell'host.
_PONTE = r"""
(function () {
  var seq = 0, attese = {}, contesto = {};
  function invia(m) { window.parent.postMessage(m, "*"); }
  function richiesta(method, params) {
    return new Promise(function (ok) {
      var id = ++seq; attese[id] = ok;
      invia({ jsonrpc: "2.0", id: id, method: method, params: params || {} });
    });
  }
  function tema(ctx) {
    if (!ctx) return;
    Object.assign(contesto, ctx);
    if (ctx.theme) document.documentElement.dataset.theme = ctx.theme;
  }
  window.lingua = function () {
    return String(contesto.locale || navigator.language || "it").slice(0, 2) === "it" ? "it" : "en";
  };
  window.apri = function (url) {
    richiesta("ui/open-link", { url: url }).catch(function () {});
  };
  window.addEventListener("message", function (e) {
    var m = e.data;
    if (!m || m.jsonrpc !== "2.0") return;
    if (m.id != null && !m.method) {
      if (attese[m.id]) { attese[m.id](m.result || {}); delete attese[m.id]; }
      return;
    }
    if (m.method === "ui/notifications/tool-result") { window.disegna(m.params || {}); misura(); }
    else if (m.method === "ui/notifications/host-context-changed") tema(m.params);
    else if (m.id != null) invia({ jsonrpc: "2.0", id: m.id, result: {} });
  });
  function misura() {
    var r = document.documentElement.getBoundingClientRect();
    invia({ jsonrpc: "2.0", method: "ui/notifications/size-changed",
            params: { width: Math.ceil(r.width), height: Math.ceil(r.height) } });
  }
  if (window.ResizeObserver) new ResizeObserver(misura).observe(document.documentElement);
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (a) { e.preventDefault(); window.apri(a.href); }
  });
  richiesta("ui/initialize", {
    protocolVersion: "2026-01-26",
    clientInfo: { name: document.title, version: "1.0.0" },
    appCapabilities: { availableDisplayModes: ["inline"] }
  }).then(function (r) {
    tema(r.hostContext);
    invia({ jsonrpc: "2.0", method: "ui/notifications/initialized", params: {} });
    misura();
  });
  /* Dal risultato: structuredContent, oppure il primo blocco di testo JSON */
  window.datiDa = function (p) {
    var d = null;
    if (p.structuredContent) d = p.structuredContent;
    var blocchi = p.content || [];
    for (var i = 0; !d && i < blocchi.length; i++) {
      if (blocchi[i].type === "text") { try { d = JSON.parse(blocchi[i].text); } catch (err) {} }
    }
    /* I dati che servono solo alla vista (seggi dell'emiciclo) arrivano in _meta,
       che l'host non mette nel contesto del modello */
    if (d && p._meta && p._meta.seat_map && !d.seat_map) d.seat_map = p._meta.seat_map;
    return d;
  };
  window.esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
})();
"""

_STILE = r"""
:root {
  --carta: #f6f5f1; --foglio: #fffdf8; --inchiostro: #12171a; --inchiostro-2: #4a5157;
  --inchiostro-3: #7a8086; --filetto: #e4e1d8; --accento: #2d5f8f; --si: #1f7a55; --no: #b3261e;
  --forse: #8a6d1a; --sans: var(--font-sans, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif);
  --serif: Georgia, "Times New Roman", serif; --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
:root[data-theme="dark"] {
  --carta: #15191c; --foglio: #1b2024; --inchiostro: #eceae4; --inchiostro-2: #c3c1bb;
  --inchiostro-3: #8d918f; --filetto: #2e3439; --accento: #7fb0dc; --si: #4fb184; --no: #ef6b61; --forse: #d6b45a;
}
* { box-sizing: border-box; }
html, body { margin: 0; background: transparent; }
body { font: 14px/1.5 var(--sans); color: var(--inchiostro); padding: 14px 16px 12px; background: var(--carta); }
a { color: var(--accento); text-decoration: underline; text-underline-offset: 2px; cursor: pointer; }
.testa { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.marchio { display: flex; align-items: center; gap: 8px; font-weight: 600; letter-spacing: -0.01em; }
.marchio svg { width: 20px; height: 16px; }
.etichetta { font: 11px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--inchiostro-3); }
.mark { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; font-size: 11px; font-weight: 700; color: #fff; flex: none; }
.mark[data-e="pass"] { background: var(--si); } .mark[data-e="fail"] { background: var(--no); }
.mark[data-e="na"] { background: var(--inchiostro-3); }
.vuoto { color: var(--inchiostro-3); }
"""

_MARCHIO = (
    '<svg viewBox="15 15 194 153" aria-hidden="true"><path d="M 35.91 139.73 A 81 81 0 1 1 188.09 139.73" '
    'fill="none" stroke="currentColor" stroke-width="32" stroke-linecap="round"/>'
    '<circle cx="112" cy="146" r="22" fill="#2D5F8F"/></svg>'
)


VERIFY_VIEW = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verifica ParliamentRAG</title>
<style>""" + _STILE + r"""
.sigillo { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 14px; }
.voce { display: flex; gap: 8px; align-items: flex-start; padding: 10px 12px; background: var(--foglio); border: 1px solid var(--filetto); border-radius: 10px; }
.voce b { display: block; font-size: 13px; }
.voce span.n { font: 12px var(--mono); color: var(--inchiostro-2); }
.voce[data-e="fail"] { border-color: color-mix(in srgb, var(--no) 40%, var(--filetto)); }
@media (max-width: 520px) { .sigillo { grid-template-columns: 1fr; } }
details { border-top: 1px solid var(--filetto); padding: 8px 0; }
summary { cursor: pointer; font-weight: 600; font-size: 13px; list-style: none; display: flex; justify-content: space-between; gap: 8px; }
summary::-webkit-details-marker { display: none; }
summary::after { content: "+"; color: var(--inchiostro-3); font-weight: 400; }
details[open] summary::after { content: "–"; }
.gruppi { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.chip { font: 12px var(--mono); padding: 2px 8px; border-radius: 999px; border: 1px solid var(--filetto); background: var(--foglio); }
.chip[data-c="no"] { color: var(--no); border-color: color-mix(in srgb, var(--no) 45%, var(--filetto)); text-decoration: line-through; }
ul { list-style: none; margin: 8px 0 0; padding: 0; }
li { display: flex; gap: 8px; align-items: baseline; padding: 6px 0; border-bottom: 1px solid var(--filetto); font-size: 13px; }
li:last-child { border-bottom: 0; }
li .chi { flex: 1; min-width: 0; }
li .dx { font: 12px var(--mono); color: var(--inchiostro-2); white-space: nowrap; }
.cit { font-family: var(--serif); font-size: 14px; line-height: 1.45; }
.fonte { font-size: 12px; color: var(--inchiostro-2); margin-top: 2px; }
.nota { font-size: 12px; color: var(--no); margin-top: 6px; }
.piede { margin-top: 10px; font-size: 12px; color: var(--inchiostro-3); }
</style></head><body>
<div class="testa"><span class="marchio">""" + _MARCHIO + r"""<span>ParliamentRAG</span></span><span class="etichetta" id="ambito"></span></div>
<div id="corpo"><p class="vuoto" id="attesa"></p></div>
<script>""" + _PONTE + r"""
(function () {
  var T = {
    it: { attesa: "Verifica in corso…", gruppi: "Tutti i gruppi", voci: "Voci autorevoli", cit: "Citazioni esatte",
          presenti: "presenti", mancano: "Mancano", tutti: "Ci sono tutte le voci.", autorevoli: "autorevoli",
          esatte: "esatte", nessuna: "nessuna", gov: "Governo", rel: "relatore", nom: "nominato",
          su: " su ", senza: "senza punteggio", tema: " tra chi ha parlato del tema", fuori: "non ha parlato del tema", res: "Resoconto", sbagliato: "scritto come",
          stati: { exact: "Esatta", omissions: "Salta delle parole", modified: "Non coincide", not_found: "Non trovata" },
          vicino: "il nome di chi parla non compare vicino", detta: "Detta da",
          piede: "Controllo deterministico sui dati ufficiali di Camera e Senato, senza modelli di AI.",
          sito: "Verifica una risposta su www.parliamentrag.it/verifica", ambito: "Parlamento · XIX legislatura" },
    en: { attesa: "Checking…", gruppi: "All groups", voci: "Authoritative voices", cit: "Exact quotes",
          presenti: "present", mancano: "Missing", tutti: "Every voice is there.", autorevoli: "authoritative",
          esatte: "exact", nessuna: "none", gov: "Government", rel: "rapporteur", nom: "named",
          su: " of ", senza: "not ranked", tema: " among those who spoke on the topic", fuori: "did not speak on the topic", res: "Record", sbagliato: "written as",
          stati: { exact: "Exact", omissions: "Skips words", modified: "Does not match", not_found: "Not found" },
          vicino: "the speaker's name is not near the quote", detta: "Said by",
          piede: "Deterministic check on the official data of the Chamber and the Senate, with no AI model.",
          sito: "Check an answer at www.parliamentrag.it/verifica", ambito: "Italian Parliament · 19th legislature" }
  };
  var L = function () { return T[window.lingua()]; };
  var M = { pass: "✓", fail: "✕", na: "–" };
  document.getElementById("attesa").textContent = L().attesa;

  window.disegna = function (p) {
    var r = window.datiDa(p), t = L(), esc = window.esc;
    if (!r || !r.outcome) return;
    document.getElementById("ambito").textContent = t.ambito;
    var o = r.outcome, g = r.groups || {}, a = r.authority || {}, q = r.quotes || [];
    var voci = a.voices || [];
    var autorevoli = voci.filter(function (v) { return v.authoritative; }).length;
    var esatte = q.filter(function (x) { return x.status === "exact" && x.speaker_named_nearby !== false; }).length;
    var dett = r.groups_detail || [];
    function voce(e, nome, n) {
      return '<div class="voce" data-e="' + e + '"><span class="mark" data-e="' + e + '">' + M[e] + "</span><div><b>" + nome + '</b><span class="n">' + n + "</span></div></div>";
    }
    var h = '<div class="sigillo">' +
      voce(o.groups, t.gruppi, (dett.length ? dett.filter(function (x) { return x.status !== "missing"; }).length + t.su + dett.length : (g.present || []).length) + " " + t.presenti) +
      voce(o.authority, t.voci, voci.length ? autorevoli + t.su + voci.length + " " + t.autorevoli : t.nessuna) +
      voce(o.quotes, t.cit, q.length ? esatte + t.su + q.length + " " + t.esatte : t.nessuna) + "</div>";

    /* Gruppi */
    var mancano = (g.missing || []);
    h += '<details' + (o.groups === "fail" ? " open" : "") + "><summary>" + t.gruppi + "<span></span></summary>";
    h += '<div class="gruppi">' + dett.map(function (x) {
      return '<span class="chip" data-c="' + (x.status === "missing" ? "no" : "si") + '" title="' + esc(x.label) + '">' + esc(x.key === "Governo" && window.lingua() === "en" ? "Government" : x.key) + "</span>";
    }).join("") + "</div>";
    (r.group_mismatches || []).forEach(function (m) {
      h += '<p class="nota">' + esc(m.name) + " " + t.sbagliato + " (" + esc(m.group_written) + ") → " + esc(m.voice || m.group) + "</p>";
    });
    if (!dett.length && mancano.length) h += '<p class="nota">' + t.mancano + ": " + esc(mancano.join(", ")) + "</p>";
    h += "</details>";

    /* Voci */
    h += '<details' + (o.authority === "fail" ? " open" : "") + "><summary>" + t.voci + "<span></span></summary>";
    if (!voci.length) h += '<p class="vuoto">' + t.nessuna + "</p>";
    else h += "<ul>" + voci.map(function (v) {
      var e = v.authoritative ? "pass" : v.authoritative === false ? "fail" : "na";
      var perche = v.role === "governo" ? t.gov : v.role === "relatore" ? t.rel : v.on_topic === false ? t.fuori
        : v.rank ? v.rank + t.su + (v.pool_size || v.group_size) + (v.pool === "speakers_on_topic" ? t.tema : "") : t.senza;
      return '<li><span class="mark" data-e="' + e + '">' + M[e] + '</span><span class="chi">' + esc(v.name) + ' <span class="etichetta">' + esc(v.group || "") + (v.source === "named" ? " · " + t.nom : "") + '</span></span><span class="dx">' + esc(perche) + "</span></li>";
    }).join("") + "</ul>";
    h += "</details>";

    /* Citazioni */
    h += '<details' + (o.quotes === "fail" ? " open" : "") + "><summary>" + t.cit + "<span></span></summary>";
    if (!q.length) h += '<p class="vuoto">' + t.nessuna + "</p>";
    else h += "<ul>" + q.map(function (x) {
      var ok = x.status === "exact" && x.speaker_named_nearby !== false;
      var e = ok ? "pass" : "fail";
      var stato = t.stati[x.status] || x.status;
      if (x.status === "exact" && x.speaker_named_nearby === false) stato = t.stati.exact + ", " + t.vicino;
      var fonte = x.speaker ? (x.status === "exact" ? "" : t.detta + " ") + esc(x.speaker) + (x.group ? ", " + esc(x.group) : "") + (x.date ? ", " + esc(x.date) : "") +
        (x.record_url ? ' · <a href="' + esc(x.record_url) + '">' + t.res + "</a>" : "") : "";
      return '<li><span class="mark" data-e="' + e + '">' + M[e] + '</span><span class="chi"><span class="etichetta">' + esc(stato) + '</span><div class="cit">«' + esc(x.quote) + '»</div>' + (fonte ? '<div class="fonte">' + fonte + "</div>" : "") + "</span></li>";
    }).join("") + "</ul>";
    h += "</details>";

    h += '<p class="piede">' + t.piede + ' <a href="https://www.parliamentrag.it/verifica">' + t.sito + "</a></p>";
    document.getElementById("corpo").innerHTML = h;
  };
})();
</script></body></html>"""


HEMICYCLE_VIEW = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Emiciclo ParliamentRAG</title>
<style>""" + _STILE + r"""
:root { --assente: #cfc9bd; } :root[data-theme="dark"] { --assente: #4a5054; }
h1 { font: 600 17px/1.3 var(--serif); margin: 0; }
.sotto { font-size: 12.5px; color: var(--inchiostro-2); margin: 3px 0 0; }
.capo { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
.esito { flex: none; font: 600 11px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase;
  padding: 6px 9px; border-radius: 999px; color: #fff; background: var(--inchiostro-3); }
.esito[data-o="approved"] { background: var(--si); } .esito[data-o="rejected"] { background: var(--no); }
.barra { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: var(--filetto); }
.barra i { display: block; height: 100%; }
.voci { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 8px 0 12px; font-size: 12.5px; color: var(--inchiostro-2); }
.voci span { display: inline-flex; align-items: center; gap: 6px; }
.voci b { font: 600 13px var(--mono); color: var(--inchiostro); }
.pt { width: 9px; height: 9px; border-radius: 50%; display: inline-block; flex: none; }
.f { background: var(--si); } .c { background: var(--no); } .a { background: var(--forse); } .x { background: var(--assente); }
.grafico { position: relative; background: var(--foglio); border: 1px solid var(--filetto); border-radius: 12px; padding: 10px 10px 4px; }
.grafico svg { display: block; width: 100%; height: auto; touch-action: manipulation; }
.grafico circle { transition: opacity .15s; }
.grafico svg.filtro circle.s:not(.su) { opacity: .16; }
.grafico circle.s.qui { stroke: var(--inchiostro); stroke-width: 2; }
.etic { position: absolute; pointer-events: none; transform: translate(-50%, calc(-100% - 10px));
  background: var(--inchiostro); color: var(--carta); font-size: 12px; line-height: 1.35;
  padding: 6px 9px; border-radius: 6px; white-space: nowrap; box-shadow: 0 4px 14px rgba(0,0,0,.18); display: none; }
.etic b { font-weight: 600; } .etic span { opacity: .75; }
.gruppi { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 6px; margin-top: 10px; }
.gruppo { all: unset; box-sizing: border-box; cursor: pointer; padding: 7px 9px; border: 1px solid var(--filetto);
  border-radius: 8px; background: var(--foglio); font-size: 12px; }
.gruppo:hover, .gruppo[aria-pressed="true"] { border-color: var(--accento); }
.gruppo:focus-visible { outline: 2px solid var(--accento); outline-offset: 1px; }
.gruppo .nome { display: flex; justify-content: space-between; gap: 6px; font-weight: 600; margin-bottom: 5px; }
.gruppo .nome small { font: 11px var(--mono); color: var(--inchiostro-3); font-weight: 400; }
.gruppo .barra { height: 5px; }
.gruppo .cifre { margin-top: 4px; font: 11px var(--mono); color: var(--inchiostro-2); display: flex; gap: 8px; }
.piede { margin-top: 10px; font-size: 11.5px; color: var(--inchiostro-3); }
.segreto { padding: 12px; background: var(--foglio); border: 1px solid var(--filetto); border-radius: 10px; }
</style></head><body>
<div class="testa"><span class="marchio">""" + _MARCHIO + r"""<span>ParliamentRAG</span></span><span class="etichetta" id="ambito"></span></div>
<div id="corpo"><p class="vuoto" id="attesa"></p></div>
<script>""" + _PONTE + r"""
(function () {
  var T = {
    it: { attesa: "Carico il voto…", esiti: { approved: "Approvata", rejected: "Respinta" },
          f: "Favorevoli", c: "Contrari", a: "Astenuti", x: "Assenti", pres: "presenti",
          voto: { f: "favorevole", c: "contrario", a: "astenuto", x: "assente" },
          ambiti: { camera: "Camera · XIX legislatura", senato: "Senato · XIX legislatura" },
          segreto: "Voto segreto", grafico: "Immagine",
          spiega: "Nel voto segreto i voti dei singoli parlamentari non sono pubblici: non c'è un emiciclo da disegnare. Sono ufficiali solo i totali.",
          nodati: "Per questa votazione non ci sono i voti dei singoli parlamentari.",
          gruppi: "Tocca un gruppo per evidenziarlo",
          piede: { camera: "Un punto per deputato, raggruppati per gruppo: non è la posizione reale in Aula.",
                   senato: "Ogni senatore al suo posto nella pianta dell'Aula di Palazzo Madama." } },
    en: { attesa: "Loading the vote…", esiti: { approved: "Approved", rejected: "Rejected" },
          f: "In favour", c: "Against", a: "Abstained", x: "Absent", pres: "present",
          voto: { f: "in favour", c: "against", a: "abstained", x: "absent" },
          ambiti: { camera: "Chamber of Deputies · 19th legislature", senato: "Senate · 19th legislature" },
          segreto: "Secret ballot", grafico: "Image",
          spiega: "In a secret ballot individual votes are not public: there is no hemicycle to draw. Only the totals are official.",
          nodati: "There are no individual votes for this roll call.",
          gruppi: "Tap a group to highlight it",
          piede: { camera: "One dot per deputy, grouped by group: not the real seat in the Chamber.",
                   senato: "Each senator on their seat in the plan of the Senate chamber." } }
  };
  var L = function () { return T[window.lingua()]; };
  var COD = ["f", "c", "a", "x"];
  var COL = { f: "var(--si)", c: "var(--no)", a: "var(--forse)", x: "var(--assente)" };
  document.getElementById("attesa").textContent = L().attesa;

  function barra(n, tot) {
    return '<div class="barra">' + COD.map(function (k) {
      return n[k] ? '<i class="' + k + '" style="width:' + (100 * n[k] / tot).toFixed(2) + '%"></i>' : "";
    }).join("") + "</div>";
  }

  window.disegna = function (p) {
    var t = L(), esc = window.esc, d = window.datiDa(p) || {}, blocchi = p.content || [];
    var aula = d.chamber === "senato" ? "senato" : "camera";
    document.getElementById("ambito").textContent = t.ambiti[aula];
    var tot = d.official_totals || {}, m = d.seat_map;
    var h = '<div class="capo"><div><h1>' + esc(d.subject || d.description || "") + "</h1>" +
      (d.subject && d.description ? '<p class="sotto">' + esc(d.description) + "</p>" : "") + "</div>" +
      (d.outcome ? '<span class="esito" data-o="' + esc(d.outcome) + '">' + esc(t.esiti[d.outcome] || d.outcome) + "</span>" : "") + "</div>";

    if (d.available === false) {
      h += '<div class="segreto">' + (d.secret_vote ? "<b>" + t.segreto + "</b><p>" + t.spiega + "</p>" : "<p>" + t.nodati + "</p>") + "</div>";
      h += '<div class="voci"><span><b>' + esc(tot.in_favor) + "</b> " + t.f + "</span><span><b>" + esc(tot.against) + "</b> " + t.c +
           "</span><span><b>" + esc(tot.abstained) + "</b> " + t.a + "</span><span><b>" + esc(tot.present) + "</b> " + t.pres + "</span></div>";
      document.getElementById("corpo").innerHTML = h;
      return;
    }

    if (!m) {  // older server: picture only
      var img = "";
      blocchi.forEach(function (b) {
        if (b.type === "image" && b.data) img = '<img alt="" style="width:100%" src="data:' + esc(b.mimeType || "image/png") + ";base64," + b.data + '">';
      });
      document.getElementById("corpo").innerHTML = h + '<div class="grafico">' + img + "</div>";
      return;
    }

    var n = { f: m.tally.favor, c: m.tally.against, a: m.tally.abstain, x: m.tally.absent };
    var tutti = n.f + n.c + n.a + n.x;
    h += barra(n, tutti);
    h += '<div class="voci">' + COD.map(function (k) {
      return n[k] ? '<span><i class="pt ' + k + '"></i><b>' + n[k] + "</b> " + t[k] + "</span>" : "";
    }).join("") + (tot.present != null ? "<span><b>" + esc(tot.present) + "</b> " + t.pres + "</span>" : "") + "</div>";

    // hemicycle
    var W = m.box[0], H = m.box[1], r = m.dot;
    var svg = '<svg viewBox="0 0 ' + W + " " + (H + 8) + '" role="img" aria-label="' + esc(d.subject || "") + '">';
    (m.empty || []).forEach(function (e) {
      svg += '<circle cx="' + e[0] + '" cy="' + e[1] + '" r="' + r + '" fill="none" stroke="var(--filetto)" stroke-width="1.5"/>';
    });
    m.seats.forEach(function (s, i) {
      svg += '<circle class="s" data-i="' + i + '" data-g="' + esc(s[4]) + '" cx="' + s[0] + '" cy="' + s[1] + '" r="' + r +
             '" fill="' + COL[s[2]] + '"><title>' + esc(s[3]) + " · " + esc(s[4]) + " · " + t.voto[s[2]] + "</title></circle>";
    });
    svg += "</svg>";
    h += '<div class="grafico">' + svg + '<div class="etic" id="etic"></div></div>';

    // groups, in arc order
    var conta = {};
    m.seats.forEach(function (s) {
      var g = conta[s[4]] || (conta[s[4]] = { f: 0, c: 0, a: 0, x: 0 });
      g[s[2]]++;
    });
    h += '<p class="piede" style="margin:10px 0 0">' + t.gruppi + "</p><div class=\"gruppi\">";
    Object.keys(m.groups).forEach(function (g) {
      var c = conta[g] || { f: 0, c: 0, a: 0, x: 0 }, k = c.f + c.c + c.a + c.x;
      h += '<button class="gruppo" type="button" aria-pressed="false" data-g="' + esc(g) + '" title="' + esc(m.groups[g]) + '">' +
           '<div class="nome"><span>' + esc(g) + "</span><small>" + k + "</small></div>" + barra(c, k) +
           '<div class="cifre">' + COD.map(function (q) {
             return c[q] ? '<span><i class="pt ' + q + '"></i> ' + c[q] + "</span>" : "";
           }).join("") + "</div></button>";
    });
    h += "</div>";
    h += '<p class="piede">' + t.piede[aula] + (d.image_png_url ? ' <a href="' + esc(d.image_png_url) + '">' + t.grafico + "</a>" : "") + "</p>";
    document.getElementById("corpo").innerHTML = h;

    // interaction: label on hover or tap, highlight a group
    var box = document.querySelector(".grafico"), el = box.querySelector("svg"), etic = document.getElementById("etic");
    var qui = null;
    function mostra(c) {
      if (qui) qui.classList.remove("qui");
      if (!c) { etic.style.display = "none"; qui = null; return; }
      var s = m.seats[+c.getAttribute("data-i")];
      qui = c; c.classList.add("qui");
      etic.innerHTML = "<b>" + esc(s[3]) + "</b><br><span>" + esc(m.groups[s[4]] || s[4]) + "</span><br>" +
        '<i class="pt ' + s[2] + '"></i> ' + t.voto[s[2]];
      var a = box.getBoundingClientRect(), b = c.getBoundingClientRect();
      var x = b.left + b.width / 2 - a.left;
      etic.style.display = "block";
      var w = etic.offsetWidth / 2;
      etic.style.left = Math.max(w + 4, Math.min(a.width - w - 4, x)) + "px";
      etic.style.top = (b.top - a.top) + "px";
    }
    el.addEventListener("pointerover", function (e) { if (e.target.classList.contains("s")) mostra(e.target); });
    el.addEventListener("pointerleave", function () { mostra(null); });
    el.addEventListener("click", function (e) { mostra(e.target.classList.contains("s") ? e.target : null); });
    var scelto = null;
    document.querySelectorAll(".gruppo").forEach(function (b) {
      b.addEventListener("click", function () {
        var g = b.getAttribute("data-g");
        scelto = scelto === g ? null : g;
        document.querySelectorAll(".gruppo").forEach(function (o) { o.setAttribute("aria-pressed", String(o.getAttribute("data-g") === scelto)); });
        el.classList.toggle("filtro", !!scelto);
        el.querySelectorAll("circle.s").forEach(function (c) { c.classList.toggle("su", c.getAttribute("data-g") === scelto); });
      });
    });
  };
})();
</script></body></html>"""
