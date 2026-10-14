"""Exact senato.it links: TOC parts matched to the speeches of the AKN file."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from senate_speech_links import (  # noqa: E402
    _TrackingParser,
    extract_interventions,
    letters,
    part_url,
    speaker_slug,
    speech_parts,
)

LONG = "Signor Presidente, colleghi, " + "intervengo sul provvedimento in esame con osservazioni puntuali. " * 3


def _speech(by, role, name, text):
    return (f'<an:speech by="{by}" as="{role}"><an:from>{name}</an:from>'
            f"<an:p>{text}</an:p></an:speech>")


AKN = f"""<?xml version="1.0" encoding="UTF-8"?>
<an:akomaNtoso xmlns:an="http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD03">
<an:debate name="resoconto">
<an:meta>
 <an:identification source="#senato"><an:FRBRWork>
  <an:FRBRthis value="x"/><an:FRBRuri value="x"/>
  <an:FRBRdate date="2026-10-01" name="seduta"/><an:FRBRauthor href="#senato"/>
  <an:FRBRnumber value="463"/>
 </an:FRBRWork></an:identification>
 <an:references source="#senato">
  <an:TLCPerson id="p1" href="/p1" showAs="PRESIDENTE"/>
  <an:TLCPerson id="p22918" href="/p22918" showAs="DE CRISTOFARO"/>
  <an:TLCPerson id="p1103" href="/p1103" showAs="GASPARRI"/>
  <an:TLCRole id="rolePres" href="/r" showAs="PRESIDENTE"/>
  <an:TLCRole id="senatore" href="/s" showAs="senatore"/>
 </an:references>
</an:meta>
<an:debateBody>
 <an:debateSection id="d1" name="Discussione del disegno di legge">
  <an:heading>Discussione del disegno di legge</an:heading>
  {_speech("#p1", "#rolePres", "PRESIDENTE", "Ha facoltà di parlare il senatore De Cristofaro.")}
  {_speech("#p22918", "#senatore", "DE CRISTOFARO", LONG)}
  {_speech("#p", "", "", "(Applausi). Continuo dopo l'interruzione.")}
  {_speech("#p1103", "#senatore", "*GASPARRI", "Domando di parlare.")}
  {_speech("#p1", "#rolePres", "PRESIDENTE", "Ne ha facoltà.")}
  {_speech("#p1103", "#senatore", "*GASPARRI", LONG)}
 </an:debateSection>
</an:debateBody>
</an:debate>
</an:akomaNtoso>"""

BASE = "doc_dc-ressten_rs-ddltit_ddddl"
TOC = [
    f"{BASE}-intervento_presidente",
    f"{BASE}-intervento_decristofaromistoavs",
    f"{BASE}-intervento_gasparrifibpppe",
    f"{BASE}-intervento_presidente:1",
    f"{BASE}-intervento_gasparrifibpppe:1",
]

PAGE = (
    '<div id="block-showdoc-toc">'
    + "".join(f'<a href="#" class="toc-link" data-part="{p}">x</a>'
              for p in ["doc_dc", "doc_dc-ressten_rs", f"{BASE}"] + TOC
              + ["doc_dc-allegatob_ab-intervento_rossi"])
    + "</div>"
)


def test_toc_keeps_only_record_interventions():
    assert extract_interventions(PAGE) == TOC
    assert extract_interventions("<html>no toc</html>") is None


def test_part_url_encodes_repeat_counter():
    url = part_url("https://www.senato.it/show-doc?leg=19&tipodoc=Resaula&id=1&idoggetto=0",
                   f"{BASE}-intervento_presidente:1")
    assert url.endswith("&part=doc_dc-ressten_rs-ddltit_ddddl-intervento_presidente%3A1")


def test_slug_and_letters():
    assert speaker_slug(f"{BASE}-intervento_gasparrifibpppe:1") == "gasparrifibpppe"
    assert letters("De Cristofaro") == "decristofaro"
    assert letters("Nicolò") == "nicolo"


def test_graph_speeches_map_to_their_toc_entry(tmp_path):
    path = tmp_path / "resaula_leg19_0463.akn"
    path.write_text(AKN, encoding="utf-8")
    parts, stats = speech_parts(str(path), TOC, _TrackingParser())
    assert stats == {"akn": 5, "toc": 5, "agree": 5, "aligned": True}
    # The short "Domando di parlare" is not in the graph; the interruption
    # block continues De Cristofaro's speech and has no TOC entry.
    assert {k: v[0].rsplit("-", 1)[1] for k, v in parts.items()} == {
        "sen_leg19_sed463_p22918_deb0_0": "intervento_decristofaromistoavs",
        "sen_leg19_sed463_p1103_deb0_1": "intervento_gasparrifibpppe:1",
    }


def test_count_mismatch_gives_no_links(tmp_path):
    path = tmp_path / "resaula_leg19_0463.akn"
    path.write_text(AKN, encoding="utf-8")
    parts, stats = speech_parts(str(path), TOC[:-1], _TrackingParser())
    assert parts == {} and not stats["aligned"]
