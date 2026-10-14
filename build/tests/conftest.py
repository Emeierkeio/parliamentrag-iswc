"""
Shared pytest fixtures for build pipeline tests.
"""

import pytest


def pytest_configure(config):
    """Register custom markers so pytest does not warn about unknown marks."""
    config.addinivalue_line(
        "markers",
        "integration: requires a running Neo4j instance (run with: pytest -m integration)",
    )
    config.addinivalue_line(
        "markers",
        "slow: requires external models/resources (run with: pytest -m slow)",
    )


# ---------------------------------------------------------------------------
# Minimal valid XML for a full stenografico session
# ---------------------------------------------------------------------------

SAMPLE_SESSION_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<atto legislatura="19" numero="250" anno="2024" mese="3" giorno="15" ramo="Camera">
  <metadati>
    <argomenti>
      <argomento idDibattito="tit00050">
        <atti>
          <atto tipologiaAtto="pdl" codiceArgomento="5-A"/>
        </atti>
      </argomento>
    </argomenti>
  </metadati>
  <resoconto>
    <dibattito id="tit00050">
      <titolo>Discussione del disegno di legge n. 5-A</titolo>
      <fase id="fas00001">
        <titolo>Discussione sulle linee generali</titolo>
        <intervento id="int00001">
          <testoXHTML>
            <nominativo id="300001" cognomeNome="ROSSI Mario">ROSSI Mario</nominativo>
            <emphasis type="italic">Ministro dell\'Interno</emphasis>
            Testo dell\'intervento del ministro. Questo è un testo di prova abbastanza lungo
            per superare la soglia minima di caratteri richiesta dalla configurazione.
            Stiamo aggiungendo ulteriore contenuto per garantire che la lunghezza sia sufficiente.
          </testoXHTML>
        </intervento>
        <intervento id="int00002">
          <testoXHTML>
            <nominativo id="300002" cognomeNome="BIANCHI Anna">BIANCHI Anna</nominativo>
            Testo del secondo intervento. Anche questo deve essere abbastanza lungo da
            superare la soglia minima. Aggiungiamo contenuto qui per assicurarci che
            l\'intervento non venga scartato dal filtro di lunghezza minima.
          </testoXHTML>
        </intervento>
      </fase>
    </dibattito>
    <raccoltaVotazioni id="tit00100">
      <votazioni>
        <votazione>
          <numero>1</numero>
          <tipo>Nominale</tipo>
          <oggetto>Emendamento 1.1</oggetto>
          <presenti>400</presenti>
          <votanti>380</votanti>
          <astenuti>20</astenuti>
          <maggioranza>191</maggioranza>
          <favorevoli>200</favorevoli>
          <contrari>180</contrari>
          <missione>50</missione>
          <esito>Appr.</esito>
        </votazione>
      </votazioni>
    </raccoltaVotazioni>
  </resoconto>
</atto>
"""

SAMPLE_VOTE_XML = """\
<votazione>
  <numero>42</numero>
  <tipo>Nominale</tipo>
  <oggetto>Articolo 3 del disegno di legge</oggetto>
  <presenti>450</presenti>
  <votanti>420</votanti>
  <astenuti>30</astenuti>
  <maggioranza>211</maggioranza>
  <favorevoli>250</favorevoli>
  <contrari>170</contrari>
  <missione>45</missione>
  <esito>Appr.</esito>
</votazione>
"""

SAMPLE_SPEECH_WITH_ROLE_XML = """\
<testoXHTML>
  <nominativo id="300001" cognomeNome="MELONI Giorgia">MELONI Giorgia</nominativo>
  <emphasis type="italic">Ministro dell\'Interno</emphasis>
  Testo del discorso istituzionale.
</testoXHTML>
"""

SAMPLE_SPEECH_NO_ROLE_XML = """\
<testoXHTML>
  <nominativo id="300002" cognomeNome="BIANCHI Anna">BIANCHI Anna</nominativo>
  Testo del discorso senza ruolo istituzionale.
</testoXHTML>
"""


@pytest.fixture
def sample_session_xml() -> str:
    """Return minimal valid XML string for a full stenografico session."""
    return SAMPLE_SESSION_XML


@pytest.fixture
def sample_vote_xml() -> str:
    """Return a standalone <votazione> XML string with all required fields."""
    return SAMPLE_VOTE_XML


@pytest.fixture
def sample_speech_with_role_xml() -> str:
    """Return a <testoXHTML> with nominativo followed by emphasis role tag."""
    return SAMPLE_SPEECH_WITH_ROLE_XML


@pytest.fixture
def sample_speech_no_role_xml() -> str:
    """Return a <testoXHTML> with nominativo but no emphasis tag."""
    return SAMPLE_SPEECH_NO_ROLE_XML


@pytest.fixture
def tmp_xml_file(sample_session_xml, tmp_path):
    """Write sample_session_xml to a temp file and yield the path."""
    xml_file = tmp_path / "test_session.xml"
    xml_file.write_text(sample_session_xml, encoding='utf-8')
    yield str(xml_file)
