"""
xml_parser.py — Pure XML data extraction for Camera dei Deputati stenografici.

StenograficoParser parses an XML stenografico file and returns a structured dict
with keys: session, debates, phases, speeches, votes, act_references.

CRITICAL: This module has zero Neo4j dependency. It is a pure data extraction module.
"""

import re
import xml.etree.ElementTree as ET
import regex
from typing import Optional

from build_config import BuildConfig


# ---------------------------------------------------------------------------
# Phase type patterns (module-level, compiled once)
# ---------------------------------------------------------------------------

_PHASE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'Dichiarazioni di voto', re.I), "vote_declaration"),
    (re.compile(r'Votazioni|Votazione', re.I), "vote"),
    (re.compile(r'Discussione sulle linee generali', re.I), "general_discussion"),
    (re.compile(r'Parere del Governo|parere del Governo', re.I), "government_opinion"),
    (re.compile(r'Annunzio di risoluzioni', re.I), "resolution_announcement"),
    (re.compile(r'Esame degli ordini del giorno', re.I), "order_of_business"),
    (re.compile(r'Esame', re.I), "article_examination"),
    (re.compile(r'Discussione', re.I), "discussion"),
    (re.compile(r'Interventi', re.I), "interventions"),
    (re.compile(r'scrutinio', re.I), "ballot"),
    (re.compile(r'Replica', re.I), "reply"),
]


def classify_phase_type(title: str) -> str:
    """Map an Italian phase title to an English enum value.

    Returns one of: vote_declaration, vote, general_discussion, government_opinion,
    resolution_announcement, order_of_business, article_examination, discussion,
    interventions, ballot, reply, other.
    """
    for pattern, phase_type in _PHASE_PATTERNS:
        if pattern.search(title):
            return phase_type
    return "other"


# ---------------------------------------------------------------------------
# Role prefixes for _extract_speaking_role
# ---------------------------------------------------------------------------

_ROLE_PREFIXES = (
    'Ministro', 'Ministra', 'Sottosegretario', 'Sottosegretaria',
    'Viceministro', 'Presidente del Consiglio', 'Relatore', 'Relatrice',
)


class StenograficoParser:
    """Pure XML parser for Camera dei Deputati stenografici.

    No Neo4j dependency. All output is plain Python dicts.
    """

    def __init__(self, config: Optional[BuildConfig] = None) -> None:
        self.config = config or BuildConfig()
        self.ns = {'xhtml': 'http://www.w3.org/1999/xhtml'}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_xml_file(self, filepath: str) -> dict:
        """Parse a stenografico XML file and return structured data.

        Returns:
            {
                "session": {...},
                "debates": [...],
                "phases": [...],
                "speeches": [...],
                "votes": [...],
                "act_references": {...},
            }
        """
        tree = ET.parse(filepath)
        root = tree.getroot()

        # --- Session ---
        leg = root.get('legislatura')
        num = root.get('numero')
        session_id = f"leg{leg}_sed{num}"
        session = {
            'id': session_id,
            'legislature': int(leg),
            'number': int(num),
            'year': int(root.get('anno')),
            'month': int(root.get('mese')),
            'day': int(root.get('giorno')),
            'chamber': root.get('ramo'),
            'date': f"{root.get('anno')}-{int(root.get('mese')):02d}-{int(root.get('giorno')):02d}",
        }

        debates: list[dict] = []
        phases: list[dict] = []
        speeches: list[dict] = []
        votes: list[dict] = []

        resoconto = root.find('resoconto')
        if resoconto is None:
            return {
                'session': session,
                'debates': [],
                'phases': [],
                'speeches': [],
                'votes': [],
                'act_references': {},
            }

        # --- Debates, phases, speeches ---
        debate_order = 0
        for dib_elem in resoconto.findall('dibattito'):
            dib_id = dib_elem.get('id')
            if not dib_id:
                continue
            full_dib_id = f"{session_id}_{dib_id}"

            titolo_elem = dib_elem.find('titolo')
            title = titolo_elem.text.strip() if titolo_elem is not None and titolo_elem.text else ""

            debates.append({
                'id': full_dib_id,
                'originalId': dib_id,
                'title': title,
                'order': debate_order,
                'sessionId': session_id,
            })
            debate_order += 1

            # Direct interventions inside dibattito (no fase)
            speech_order = 0
            for int_elem in dib_elem.findall('./intervento'):
                speech = self._parse_intervention(int_elem, session_id, full_dib_id, None)
                if speech:
                    speech['parentType'] = 'debate'
                    speech['parentId'] = full_dib_id
                    speech['order'] = speech_order
                    speeches.append(speech)
                    speech_order += 1

            # Phases inside dibattito
            phase_order = 0
            for fase_elem in dib_elem.findall('fase'):
                fase_id = fase_elem.get('id')
                if not fase_id:
                    continue
                full_fase_id = f"{session_id}_{fase_id}"

                fase_titolo_elem = fase_elem.find('titolo')
                fase_title = fase_titolo_elem.text.strip() if fase_titolo_elem is not None and fase_titolo_elem.text else ""

                phases.append({
                    'id': full_fase_id,
                    'originalId': fase_id,
                    'title': fase_title,
                    'phaseType': classify_phase_type(fase_title),
                    'order': phase_order,
                    'debateId': full_dib_id,
                })
                phase_order += 1

                # Interventions inside fase
                fase_speech_order = 0
                fase_speeches: list[dict] = []
                for int_elem in fase_elem.findall('intervento'):
                    speech = self._parse_intervention(int_elem, session_id, full_dib_id, full_fase_id)
                    if speech:
                        speech['parentType'] = 'phase'
                        speech['parentId'] = full_fase_id
                        speech['order'] = fase_speech_order
                        fase_speeches.append(speech)
                        fase_speech_order += 1

                # Merge ellipsis-continued speeches within phase
                fase_speeches = self.merge_continuation_interventions(fase_speeches)
                speeches.extend(fase_speeches)

        # --- Votes (session level — NOT inside dibattito) ---
        vot_index = 0
        for rv in resoconto.findall('raccoltaVotazioni'):
            for vs in rv.findall('votazioni'):
                for vot_elem in vs.findall('votazione'):
                    vote = self.parse_vote(vot_elem, session_id, vot_index)
                    votes.append(vote)
                    vot_index += 1

        # --- Act references ---
        act_references = self._parse_act_references(root)

        return {
            'session': session,
            'debates': debates,
            'phases': phases,
            'speeches': speeches,
            'votes': votes,
            'act_references': act_references,
        }

    def parse_vote(self, vot_elem, session_id: str, vot_index: int) -> dict:
        """Parse a single <votazione> element.

        Returns dict with keys matching the Vote node properties:
        id, number, type, subject, present, voters, abstained, majority,
        inFavor, against, onMission, outcome.
        """
        def get_text(tag: str) -> Optional[str]:
            elem = vot_elem.find(tag)
            return elem.text.strip() if elem is not None and elem.text else None

        def get_int(tag: str) -> Optional[int]:
            val = get_text(tag)
            try:
                return int(val) if val else None
            except (ValueError, TypeError):
                return None

        return {
            'id': f"{session_id}_vot_{vot_index}",
            'number': get_int('numero'),
            'type': get_text('tipo'),
            'subject': get_text('oggetto'),
            'present': get_int('presenti'),
            'voters': get_int('votanti'),
            'abstained': get_int('astenuti'),
            'majority': get_int('maggioranza'),
            'inFavor': get_int('favorevoli'),
            'against': get_int('contrari'),
            'onMission': get_int('missione'),
            'outcome': self._normalize_outcome(get_text('esito')),
        }

    @staticmethod
    def _normalize_outcome(esito: Optional[str]) -> Optional[str]:
        """Map raw XML esito to the normalized outcome vocabulary used by the
        SPARQL ingesters ('approved'/'rejected'), so all Vote nodes share one
        vocabulary regardless of source."""
        if not esito:
            return None
        mapping = {'Appr.': 'approved', 'Resp.': 'rejected'}
        return mapping.get(esito, esito)

    def _parse_act_references(self, root) -> dict[str, list[dict]]:
        """Parse <metadati><argomenti> to build debate-to-act map.

        Returns:
            {debate_original_id: [{"type": tipo, "code": codice}, ...]}
        """
        result: dict[str, list[dict]] = {}
        metadati = root.find('metadati')
        if metadati is None:
            return result
        for arg in metadati.findall('.//argomento'):
            dib_id = arg.get('idDibattito')
            if not dib_id:
                continue
            for atto in arg.findall('.//atto'):
                tipo = atto.get('tipologiaAtto')
                codice = atto.get('codiceArgomento')
                if tipo and codice:
                    result.setdefault(dib_id, []).append({"type": tipo, "code": codice})
        return result

    def _extract_speaking_role(self, testo_xhtml) -> Optional[str]:
        """Extract institutional role from <emphasis> tag after <nominativo>.

        Returns role text if it looks like an institutional role, else None.
        """
        if testo_xhtml is None:
            return None
        children = list(testo_xhtml)
        tags = [c.tag for c in children]
        if 'nominativo' not in tags:
            return None
        nom_idx = tags.index('nominativo')
        if nom_idx + 1 >= len(children):
            return None
        next_elem = children[nom_idx + 1]
        if next_elem.tag != 'emphasis' or not next_elem.text:
            return None
        text = next_elem.text.strip().rstrip('.')
        # Filter out stage directions (they start with '(')
        if text.startswith('('):
            return None
        # Only return if it looks like an institutional role
        if any(text.startswith(p) for p in _ROLE_PREFIXES):
            return text
        return None

    def _parse_intervention(
        self,
        intervento_elem,
        session_id: str,
        debate_id: Optional[str],
        phase_id: Optional[str],
    ) -> Optional[dict]:
        """Parse a single <intervento> element.

        Returns None if the speech is a PRESIDENTE speech or too short.
        """
        intervento_id = intervento_elem.get('id')
        if not intervento_id:
            return None

        full_id = f"{session_id}_{intervento_id}"

        testo_xhtml = intervento_elem.find('testoXHTML')

        # Check if speaker is PRESIDENTE
        dep_id, cognome_nome, is_presidente = self._get_nominativo_info(testo_xhtml)
        if is_presidente:
            return None

        # Extract speaking role from emphasis tag
        speaking_role = self._extract_speaking_role(testo_xhtml)

        # Collect all text
        text_parts: list[str] = []

        if testo_xhtml is not None:
            main_text = self.extract_text_from_element(testo_xhtml)
            # Remove speaker name from beginning if present
            if cognome_nome and main_text.startswith(cognome_nome):
                main_text = main_text[len(cognome_nome):].lstrip('. ')
            if main_text:
                text_parts.append(main_text)

        # Add interventoVirtuale sections
        for iv in intervento_elem.findall('interventoVirtuale'):
            iv_text = self.extract_text_from_element(iv)
            if iv_text:
                text_parts.append(iv_text)

        raw_text = ' '.join(text_parts)
        clean_text = self.preprocess_text(raw_text)

        # Filter speeches below minimum length
        if len(clean_text) < self.config.min_speech_length:
            return None

        return {
            'id': full_id,
            'originalId': intervento_id,
            'text': clean_text,
            'testo_raw': raw_text,
            'deputatoId': dep_id,
            'cognome_nome': cognome_nome,
            'speakingRole': speaking_role,
            'sessionId': session_id,
            'debateId': debate_id,
            'phaseId': phase_id,
        }

    def merge_continuation_interventions(self, interventions: list[dict]) -> list[dict]:
        """Merge consecutive speeches from same speaker when second starts with ellipsis.

        Handles chains of 3+ continuations.
        """
        if not interventions:
            return []

        merged_list: list[dict] = []
        skip_indices: set[int] = set()

        n = len(interventions)
        i = 0
        while i < n:
            if i in skip_indices:
                i += 1
                continue

            current = interventions[i]

            j = i + 1
            while j < n:
                if j in skip_indices:
                    j += 1
                    continue

                next_int = interventions[j]

                # Check same speaker
                same_speaker = False
                if current.get('deputatoId') and next_int.get('deputatoId'):
                    same_speaker = current['deputatoId'] == next_int['deputatoId']
                elif current.get('cognome_nome') and next_int.get('cognome_nome'):
                    nw1 = re.sub(r'\s+', ' ', current['cognome_nome']).strip().lower()
                    nw2 = re.sub(r'\s+', ' ', next_int['cognome_nome']).strip().lower()
                    same_speaker = nw1 == nw2

                if not same_speaker:
                    break

                # Check ellipsis continuation
                raw_next = next_int.get('testo_raw', '')
                ellipsis_match = re.match(r'^\s*(?:\.{3}|…|\.\s\.\s\.)', raw_next)
                if not ellipsis_match:
                    break

                # Merge texts
                sep = ' ' if not current['testo_raw'].endswith(' ') else ''
                current['testo_raw'] += sep + raw_next

                # Track merged IDs
                if 'mergedFromIds' not in current:
                    current['mergedFromIds'] = []
                current['mergedFromIds'].append(next_int.get('originalId', next_int.get('id')))

                skip_indices.add(j)
                j += 1

            # Recompute preprocessed text if merges happened
            if 'mergedFromIds' in current:
                current['text'] = self.preprocess_text(current['testo_raw'])

            merged_list.append(current)
            i = j

        return merged_list

    def preprocess_text(self, raw_text: str) -> str:
        """Clean raw speech text: remove parentheticals and speaker markers.

        Uses the `regex` library for recursive parenthesis removal.
        NO alignment_map returned — simplified from preprocess_text_with_alignment.
        """
        if not raw_text:
            return ""

        text = raw_text

        # 1. Remove balanced parentheticals (including nested) using recursive regex
        try:
            pattern_parens = r'\((?>[^()]+|(?R))*\)'
            text = regex.sub(pattern_parens, '', text)
        except Exception:
            pass

        # 2. Remove speaker markers in all-caps at start of sentences
        speaker_pattern = r"(?<=^|[\.\!\?]\s)([A-ZÀ-Ú][A-ZÀ-Ú\s'`]{2,})\."
        text = regex.sub(speaker_pattern, '', text)

        # 3. Remove the opening vocative only ("Signor Presidente,"). The
        # previous pattern ran to the first full stop and deleted the whole
        # first sentence of 12% of Camera XIX speeches (measured 2026-10-02).
        init_pattern = r'^\s*(Signor[a]?\s+)?(Presidente|Vicepresidente)\b[^,.;:!?]*[,.]'
        text = regex.sub(init_pattern, '', text)

        # 4. Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def extract_text_from_element(self, element) -> str:
        """Extract all text from an XML element, including sub-elements."""
        if element is None:
            return ""

        text_parts: list[str] = []
        if element.text:
            text_parts.append(element.text.strip())

        for child in element:
            if child.tag == 'nominativo':
                if child.text:
                    text_parts.append(child.text.strip())
            elif child.tag == 'emphasis':
                if child.text:
                    text_parts.append(child.text.strip())
            else:
                text_parts.append(self.extract_text_from_element(child))

            if child.tail:
                text_parts.append(child.tail.strip())

        return ' '.join(filter(None, text_parts))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_nominativo_info(self, testo_xhtml) -> tuple[Optional[str], Optional[str], bool]:
        """Extract deputato_id, cognomeNome, and whether speaker is PRESIDENTE."""
        nominativo = testo_xhtml.find('nominativo') if testo_xhtml is not None else None
        if nominativo is not None:
            dep_id = nominativo.get('id')
            cognome_nome = nominativo.get('cognomeNome')
            is_presidente = nominativo.text and nominativo.text.strip() == 'PRESIDENTE'
            return dep_id, cognome_nome, bool(is_presidente)
        return None, None, False
