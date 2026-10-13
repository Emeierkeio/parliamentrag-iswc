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
    if (p.structuredContent) return p.structuredContent;
    var blocchi = p.content || [];
    for (var i = 0; i < blocchi.length; i++) {
      if (blocchi[i].type === "text") { try { return JSON.parse(blocchi[i].text); } catch (err) {} }
    }
    return null;
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
          su: " su ", senza: "senza punteggio", res: "Resoconto", sbagliato: "scritto come",
          stati: { exact: "Esatta", omissions: "Salta delle parole", modified: "Non coincide", not_found: "Non trovata" },
          vicino: "il nome di chi parla non compare vicino", detta: "Detta da",
          piede: "Controllo deterministico sui dati ufficiali della Camera, senza modelli di AI.",
          sito: "Verifica una risposta su www.parliamentrag.it/verifica", ambito: "Camera · XIX legislatura" },
    en: { attesa: "Checking…", gruppi: "All groups", voci: "Authoritative voices", cit: "Exact quotes",
          presenti: "present", mancano: "Missing", tutti: "Every voice is there.", autorevoli: "authoritative",
          esatte: "exact", nessuna: "none", gov: "Government", rel: "rapporteur", nom: "named",
          su: " of ", senza: "not ranked", res: "Record", sbagliato: "written as",
          stati: { exact: "Exact", omissions: "Skips words", modified: "Does not match", not_found: "Not found" },
          vicino: "the speaker's name is not near the quote", detta: "Said by",
          piede: "Deterministic check on the Chamber's official data, with no AI model.",
          sito: "Check an answer at www.parliamentrag.it/verifica", ambito: "Chamber · 19th legislature" }
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
      var perche = v.role === "governo" ? t.gov : v.role === "relatore" ? t.rel : v.rank ? v.rank + t.su + v.group_size : t.senza;
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
h1 { font: 600 16px/1.3 var(--serif); margin: 0 0 2px; }
.sotto { font-size: 12px; color: var(--inchiostro-2); margin: 0 0 10px; }
.grafico { background: #fbfaf7; border: 1px solid var(--filetto); border-radius: 10px; overflow: hidden; }
.grafico img, .grafico svg { display: block; width: 100%; height: auto; }
.numeri { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 10px 0 4px; font: 13px var(--mono); }
.numeri b { font-weight: 700; }
.fav b { color: var(--si); } .con b { color: var(--no); } .ast b { color: var(--forse); }
.esito { font-weight: 600; }
.piede { margin-top: 8px; font-size: 12px; color: var(--inchiostro-3); }
.segreto { padding: 12px; background: var(--foglio); border: 1px solid var(--filetto); border-radius: 10px; }
</style></head><body>
<div class="testa"><span class="marchio">""" + _MARCHIO + r"""<span>ParliamentRAG</span></span><span class="etichetta" id="ambito"></span></div>
<div id="corpo"><p class="vuoto" id="attesa"></p></div>
<script>""" + _PONTE + r"""
(function () {
  var T = {
    it: { attesa: "Carico il voto…", fav: "favorevoli", con: "contrari", ast: "astenuti", pres: "presenti",
          esito: "Esito", grafico: "Immagine", segreto: "Voto segreto", ambito: "Camera · XIX legislatura",
          esiti: { approved: "approvata", rejected: "respinta" },
          spiega: "Nel voto segreto i voti dei singoli deputati non sono pubblici: non c'è un emiciclo da disegnare. Sono ufficiali solo i totali.",
          nodati: "Per questa votazione non ci sono i voti dei singoli deputati.",
          piede: "Un punto per deputato, raggruppati per gruppo: non è la posizione reale in Aula." },
    en: { attesa: "Loading the vote…", fav: "in favour", con: "against", ast: "abstained", pres: "present",
          esito: "Outcome", grafico: "Image", segreto: "Secret ballot", ambito: "Chamber · 19th legislature",
          esiti: { approved: "approved", rejected: "rejected" },
          spiega: "In a secret ballot individual votes are not public: there is no hemicycle to draw. Only the totals are official.",
          nodati: "There are no individual votes for this roll call.",
          piede: "One dot per deputy, grouped by group: not the real seat in the Chamber." }
  };
  var L = function () { return T[window.lingua()]; };
  document.getElementById("attesa").textContent = L().attesa;
  window.disegna = function (p) {
    var t = L(), esc = window.esc, d = window.datiDa(p) || {}, blocchi = p.content || [];
    document.getElementById("ambito").textContent = t.ambito;
    var tot = d.official_totals || {};
    var h = "<h1>" + esc(d.subject || d.description || "") + "</h1>";
    if (d.subject && d.description) h += '<p class="sotto">' + esc(d.description) + "</p>";
    var numeri = '<div class="numeri">' +
      (d.outcome ? '<span class="esito">' + t.esito + ": " + esc(t.esiti[d.outcome] || d.outcome) + "</span>" : "") +
      '<span class="fav"><b>' + esc(tot.in_favor) + "</b> " + t.fav + "</span>" +
      '<span class="con"><b>' + esc(tot.against) + "</b> " + t.con + "</span>" +
      '<span class="ast"><b>' + esc(tot.abstained) + "</b> " + t.ast + "</span>" +
      "<span><b>" + esc(tot.present) + "</b> " + t.pres + "</span></div>";
    if (d.available === false) {
      h += '<div class="segreto">' + (d.secret_vote ? "<b>" + t.segreto + "</b><p>" + t.spiega + "</p>" : "<p>" + t.nodati + "</p>") + "</div>" + numeri;
    } else {
      var grafico = "";
      blocchi.forEach(function (b) {
        if (b.type === "image" && b.data) grafico = '<img alt="" src="data:' + esc(b.mimeType || "image/png") + ";base64," + b.data + '">';
        else if (b.type === "text" && /^\s*<svg/.test(b.text || "")) grafico = b.text;
      });
      h += '<div class="grafico">' + grafico + "</div>" + numeri;
      h += '<p class="piede">' + t.piede + (d.image_png_url ? ' <a href="' + esc(d.image_png_url) + '">' + t.grafico + "</a>" : "") + "</p>";
    }
    document.getElementById("corpo").innerHTML = h;
  };
})();
</script></body></html>"""
