"""Chamber motions and resolutions placed in the debate where they are voted."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from link_camera_motions import debates_for_vote, parse_sections  # noqa: E402

SITTING_492 = """<?xml version="1.0" encoding="UTF-8"?>
<seduta><resoconto>
<dibattito id="tit00030"><titolo>Sull'ordine dei lavori.</titolo>
  <intervento>Chiedo di parlare sulla risoluzione n. 6-00186.</intervento></dibattito>
<dibattito id="tit00040"><titolo>Comunicazioni del Ministro del Lavoro e delle politiche sociali
  sulla sicurezza sul lavoro.</titolo>
  <fase><titolo>(Annunzio di risoluzioni)</titolo>
  <intervento>Sono state presentate le risoluzioni Barzotti ed altri n. 6-00186.</intervento></fase>
</dibattito>
<dibattito id="tit00060"><titolo>Si riprende la discussione.</titolo></dibattito>
<dibattito id="tit00070"><titolo>Per un richiamo al Regolamento.</titolo>
  <intervento>Sulla risoluzione n. 6-00186 ...</intervento></dibattito>
<dibattito id="tit00080"><titolo>Si riprende la discussione.</titolo>
  <intervento>Indìco la votazione sulla risoluzione Barzotti ed altri n. 6-00186.
  La Camera respinge <emphasis>(Vedi votazione n. 2)</emphasis>.</intervento></dibattito>
</resoconto></seduta>
"""

SITTING_176 = """<?xml version="1.0" encoding="UTF-8"?>
<seduta><resoconto>
<dibattito id="tit00030"><titolo>Esame della Nota di aggiornamento del Documento di economia e
  finanza 2023.</titolo></dibattito>
<dibattito id="tit00040"><titolo>Preavviso di votazioni elettroniche.</titolo></dibattito>
<dibattito id="tit00070"><titolo>Si riprende la discussione.</titolo>
  <intervento>Votazione della risoluzione n. 6-00058 (Vedi votazione n. 1).</intervento></dibattito>
<dibattito id="tit00080"><titolo>Discussione della proposta di legge n. 85.</titolo></dibattito>
<dibattito id="tit00090"><titolo>Si riprende la discussione.</titolo>
  <intervento>Risoluzione n. 6-00059 (Vedi votazione n. 5).</intervento></dibattito>
</resoconto></seduta>
"""


def _sections(tmp_path, xml):
    path = tmp_path / "s.xml"
    path.write_text(xml, encoding="utf-8")
    return parse_sections(str(path))


def test_vote_section_and_the_debate_it_resumes(tmp_path):
    sections = _sections(tmp_path, SITTING_492)
    assert sections[1]["acts"] == {"6/00186"}
    assert debates_for_vote(sections, 2, "6/00186") == ["tit00080", "tit00040"]
    assert debates_for_vote(sections, 9, "6/00186") == []


def test_resolution_host_without_the_act_number(tmp_path):
    sections = _sections(tmp_path, SITTING_176)
    assert debates_for_vote(sections, 1, "6/00058") == ["tit00070", "tit00030"]
    # another agenda item came in between: no guess
    assert debates_for_vote(sections, 5, "6/00059") == ["tit00090"]
