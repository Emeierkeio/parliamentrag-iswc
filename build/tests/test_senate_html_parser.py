"""Senate records published only as web pages (no AKN file)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from senate_html_parser import SenateHtmlParser, parse_title  # noqa: E402

LINK = '<a href="https://www.senato.it/loc/link.asp?leg=19&amp;tipodoc=sanasen&amp;id={id}">{name}</a>'
LONG = "Signor Presidente, colleghi, " + "intervengo sul provvedimento in esame con alcune osservazioni puntuali. " * 3

PAGE = f"""<html><head><title>Legislatura 19ª - Aula - Resoconto stenografico della seduta n. 212 del 30/07/2024</title></head>
<body><div class="bgt">
<p style="text-align:center"><b>SENATO DELLA REPUBBLICA</b></p>
<p style="text-align:center">Presidenza del vice presidente CENTINAIO</p>
<p style="text-align:center"><b>Richieste di informative da parte del Governo</b></p>
<p style="text-align:justify">{LINK.format(id=29293, name="BORGHI Enrico")} <i>(IV-C-RE)</i>. Domando di parlare.</p>
<p style="text-align:justify">PRESIDENTE. Prego, senatore Borghi, ha facoltà di parlare.</p>
<p style="text-align:justify">BORGHI Enrico <i>(IV-C-RE)</i>. {LONG}</p>
<p style="text-align:justify">Seconda parte del discorso, che continua lo stesso intervento.</p>
<p style="text-align:justify"><i>(Applausi)</i>.</p>
<p style="text-align:justify"><b>Discussione del disegno di legge:</b></p>
<p style="text-align:justify"><a href="https://www.senato.it/loc/link.asp?leg=19&amp;tipodoc=sddliter&amp;id=1"><b>(1162)</b></a> <b>Conversione in legge del decreto-legge ricostruzione</b></p>
<p style="text-align:justify"><a href="x"></a>{LINK.format(id=29067, name="PRESIDENTE")}. Ha facoltà di parlare la relatrice.</p>
<p style="text-align:justify">{LINK.format(id=36397, name="FAROLFI")}, <i>relatrice</i>. {LONG}</p>
<p style="text-align:justify">La seduta è tolta alle ore 19.</p>
<p style="text-align:justify">{LINK.format(id=111, name="ROSSI")} <i>(PD)</i>. Interrogazione dell'allegato B. {LONG}</p>
</div></body></html>"""


def _parse(tmp_path):
    path = tmp_path / "resaula_leg19_0212.html"
    path.write_text(PAGE, encoding="utf-8")
    return SenateHtmlParser().parse_html_file(str(path))


def test_title_gives_number_and_date():
    assert parse_title(PAGE) == (212, "2024-07-30")


def test_sections_and_speakers(tmp_path):
    parsed = _parse(tmp_path)
    assert parsed["session"]["id"] == "sen_leg19_sed212"
    assert [d["title"] for d in parsed["debates"]] == [
        "Richieste di informative da parte del Governo",
        "Discussione del disegno di legge: (1162) Conversione in legge del decreto-legge ricostruzione",
    ]
    speakers = [(s["cognome_nome"], s["deputatoId"]) for s in parsed["speeches"]]
    assert speakers == [
        ("BORGHI Enrico", "http://dati.senato.it/senatore/29293"),
        ("FAROLFI", "http://dati.senato.it/senatore/36397"),
    ]


def test_continuation_joins_and_chair_and_annex_are_dropped(tmp_path):
    parsed = _parse(tmp_path)
    borghi = parsed["speeches"][0]
    assert borghi["text"].endswith("continua lo stesso intervento.")
    assert all("Prego, senatore" not in s["text"] for s in parsed["speeches"])
    assert all("allegato B" not in s["text"] for s in parsed["speeches"])
    assert parsed["speeches"][1]["speakingRole"] is None
