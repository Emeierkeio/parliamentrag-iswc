"""
senate_parser.py — Pure AKN XML data extraction for Senato della Repubblica stenografici.

SenateStenograficoParser parses an AKN (Akoma Ntoso 3.0) stenografico file and returns
a structured dict with the same keys as Camera parser: session, debates, phases, speeches,
votes, act_references.

CRITICAL: This module has zero Neo4j dependency. It is a pure data extraction module.

AKN namespace: http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD03
"""

import re
import xml.etree.ElementTree as ET
from typing import Optional

from build_config import BuildConfig
from xml_parser import StenograficoParser, classify_phase_type

# ---------------------------------------------------------------------------
# AKN namespace
# ---------------------------------------------------------------------------

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD03"
NS = {"an": AKN_NS}

# ---------------------------------------------------------------------------
# Sections to skip when iterating debateSections
# ---------------------------------------------------------------------------

_SKIP_SECTIONS = frozenset(
    ["InizioSeduta", "FineSeduta", "Presidenza", "Comunicazioni"]
)


def _slug(text: str) -> str:
    """Convert a section name to a safe ID segment (lowercase, hyphens for spaces)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", text).strip("_").lower()


class SenateStenograficoParser:
    """Pure AKN XML parser for Senato della Repubblica stenografici.

    Produces the same output dict contract as StenograficoParser (Camera):
        session, debates, phases, speeches, votes, act_references.

    No Neo4j dependency. All output is plain Python dicts.
    """

    def __init__(
        self, config: Optional[BuildConfig] = None, legislature: int = 19
    ) -> None:
        self.config = config or BuildConfig()
        self.legislature = legislature
        # Reuse Camera parser's preprocess_text — same text cleaning rules apply
        self._camera_parser = StenograficoParser(config)
        self._role_lookup: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_xml_file(self, filepath: str) -> dict:
        """Parse a Senate AKN stenografico file and return structured data.

        Returns:
            {
                "session": {...},
                "debates": [...],
                "phases": [...],
                "speeches": [...],
                "votes": [],           # always empty — Senate votes are separate documents
                "act_references": {},  # always empty — no inline argomenti in AKN
            }
        """
        tree = ET.parse(filepath)
        root = tree.getroot()

        debate_elem = root.find(f"{{{AKN_NS}}}debate")
        if debate_elem is None:
            # Try without namespace prefix (some files may use default ns)
            debate_elem = root.find("debate")
        if debate_elem is None:
            debate_elem = root  # root might be <an:debate> itself

        # --- Session metadata ---
        session = self._parse_session_metadata(debate_elem)
        session_id = session["id"]

        # --- Person and role lookups ---
        person_lookup, presidente_roles = self._build_lookups(debate_elem)

        # --- Debates, phases, speeches ---
        debates: list[dict] = []
        phases: list[dict] = []
        speeches: list[dict] = []

        debate_body = debate_elem.find(f"{{{AKN_NS}}}debateBody")
        if debate_body is None:
            return {
                "session": session,
                "debates": [],
                "phases": [],
                "speeches": [],
                "votes": [],
                "act_references": {},
            }

        debate_order = 0
        seen_debate_ids: set[str] = set()
        for section in debate_body.findall(f"{{{AKN_NS}}}debateSection"):
            section_name = section.get("name", "")

            # Skip administrative sections
            if section_name in _SKIP_SECTIONS:
                continue

            # Only include sections that contain at least one non-presidente speech
            section_speeches = self._parse_section_speeches(
                section,
                session_id,
                presidente_roles,
                person_lookup,
                debate_order,
            )

            # Skip sections with no usable speeches
            if not section_speeches:
                continue

            # Build debate node
            debate_slug = _slug(section_name) if section_name else f"sec{debate_order}"
            debate_id = f"{session_id}_{debate_slug}"
            # Section names repeat within a sitting (an agenda item resumed later).
            if debate_id in seen_debate_ids:
                debate_id = f"{debate_id}_{debate_order}"
            seen_debate_ids.add(debate_id)

            # Heading text may be whitespace-only or live in child elements
            # (e.g. <docTitle>) — join all descendant text, else fall back
            # to the section name attribute.
            heading_elem = section.find(f"{{{AKN_NS}}}heading")
            heading_text = (
                "".join(heading_elem.itertext()).strip()
                if heading_elem is not None
                else ""
            )
            title = heading_text or section_name

            debates.append({
                "id": debate_id,
                "originalId": section_name,
                "title": title,
                "order": debate_order,
                "sessionId": session_id,
            })

            # Build phase node (one per debate section — Senate has flat structure)
            phase_id = f"{debate_id}_phase0"
            phases.append({
                "id": phase_id,
                "originalId": f"{section_name}_phase0",
                "title": title,
                "phaseType": classify_phase_type(title),
                "order": 0,
                "debateId": debate_id,
            })

            # Assign debate/phase context to speeches
            for idx, speech in enumerate(section_speeches):
                # A senator often speaks several times in one debate.
                speech["id"] = f"{speech['id']}_{idx}"
                speech["debateId"] = debate_id
                speech["phaseId"] = phase_id
                speech["parentType"] = "phase"
                speech["parentId"] = phase_id
                speech["order"] = idx

            speeches.extend(section_speeches)
            debate_order += 1

        return {
            "session": session,
            "debates": debates,
            "phases": phases,
            "speeches": speeches,
            "votes": [],
            "act_references": {},
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_session_metadata(self, debate_elem) -> dict:
        """Extract session metadata from FRBRWork element."""
        meta = debate_elem.find(f"{{{AKN_NS}}}meta")
        if meta is None:
            raise ValueError("AKN file missing <an:meta> element")

        identification = meta.find(f"{{{AKN_NS}}}identification")
        if identification is None:
            raise ValueError("AKN file missing <an:identification> element")

        frbrwork = identification.find(f"{{{AKN_NS}}}FRBRWork")
        if frbrwork is None:
            raise ValueError("AKN file missing <an:FRBRWork> element")

        number_elem = frbrwork.find(f"{{{AKN_NS}}}FRBRnumber")
        date_elem = frbrwork.find(f"{{{AKN_NS}}}FRBRdate")

        if number_elem is None or date_elem is None:
            raise ValueError("AKN file missing FRBRnumber or FRBRdate in FRBRWork")

        number = int(number_elem.get("value", "0"))
        date_str = date_elem.get("date", "")  # e.g. "2022-11-15"

        # Parse date
        try:
            year, month, day = (int(x) for x in date_str.split("-"))
        except (ValueError, AttributeError):
            year, month, day = 0, 0, 0

        session_id = f"sen_leg{self.legislature}_sed{number}"

        return {
            "id": session_id,
            "legislature": self.legislature,
            "number": number,
            "year": year,
            "month": month,
            "day": day,
            "chamber": "senato",
            "date": date_str,
        }

    def _build_lookups(self, debate_elem) -> tuple[dict, set]:
        """Build person_lookup (id -> showAs) and presidente_roles set.

        Returns:
            person_lookup: {"p32600": "CASTELLONE", ...}
            presidente_roles: {"#rolePresidente", ...}
        """
        person_lookup: dict[str, str] = {}
        presidente_roles: set[str] = set()

        meta = debate_elem.find(f"{{{AKN_NS}}}meta")
        if meta is None:
            return person_lookup, presidente_roles

        references = meta.find(f"{{{AKN_NS}}}references")
        if references is None:
            return person_lookup, presidente_roles

        # TLCPerson entries
        for tlc_person in references.findall(f"{{{AKN_NS}}}TLCPerson"):
            pid = tlc_person.get("id", "")
            show_as = tlc_person.get("showAs", "")
            if pid:
                person_lookup[pid] = show_as

        # TLCRole entries. The chair is showAs="PRESIDENTE"; offices such as
        # "Presidente del Consiglio dei ministri" are speakers, not the chair.
        self._role_lookup = {}
        for tlc_role in references.findall(f"{{{AKN_NS}}}TLCRole"):
            role_id = tlc_role.get("id", "")
            show_as = tlc_role.get("showAs", "").strip()
            if not role_id:
                continue
            self._role_lookup[f"#{role_id}"] = show_as
            if show_as.upper() == "PRESIDENTE":
                presidente_roles.add(f"#{role_id}")
                presidente_roles.add(role_id)

        return person_lookup, presidente_roles

    def _parse_section_speeches(
        self,
        section,
        session_id: str,
        presidente_roles: set,
        person_lookup: dict,
        debate_order: int,
    ) -> list[dict]:
        """Parse all speech elements from a debateSection, excluding PRESIDENTE.

        The record splits a speech wherever it notes an interruption: the
        follow-up block has an empty speaker (by="#p", as=""). It continues
        whoever spoke last, so it is appended to that speech, or dropped
        when the last speaker was the chair.
        """
        result: list[dict] = []
        last_by = ""
        last_speech: Optional[dict] = None

        for speech_elem in section.findall(f"{{{AKN_NS}}}speech"):
            by_attr = speech_elem.get("by", "").lstrip("#")
            if by_attr in ("", "p"):
                if not last_by:
                    continue
                if last_speech is None or last_speech["_by"] != last_by:
                    continue
                extra = self._speech_text(speech_elem)
                if extra:
                    last_speech["text"] = f"{last_speech['text']} {extra}"
                continue

            last_by = by_attr
            speech = self._parse_speech(
                speech_elem,
                session_id,
                presidente_roles,
                person_lookup,
                debate_order,
            )
            if speech is not None:
                speech["_by"] = by_attr
                result.append(speech)
                last_speech = speech
            else:
                last_speech = None

        for speech in result:
            speech.pop("_by", None)
        return result

    def _speech_text(self, speech_elem) -> str:
        parts = [
            t for t in (self._extract_element_text(p) for p in speech_elem.findall(f"{{{AKN_NS}}}p")) if t
        ]
        text = self._camera_parser.preprocess_text(" ".join(parts))
        return re.sub(r"^[\s.,;:\-–]+", "", text)

    def _parse_speech(
        self,
        speech_elem,
        session_id: str,
        presidente_roles: set,
        person_lookup: dict,
        debate_order: int,
    ) -> Optional[dict]:
        """Parse a single <an:speech> element.

        Returns None if:
        - The speech's `as` attribute refers to a PRESIDENTE role
        - The cleaned text is below min_speech_length
        """
        # Check role — filter PRESIDENTE speeches
        as_attr = speech_elem.get("as", "")
        if as_attr in presidente_roles:
            return None

        # Extract speaker from `by` attribute: "#p32600" -> "p32600"
        by_attr = speech_elem.get("by", "")
        person_id = by_attr.lstrip("#")  # "p32600"

        # Numeric senator ID: "p32600" -> "32600".
        # deputatoId must match the Deputy node id loaded from senatori_xix.csv,
        # which is the full dati.senato.it URI.
        numeric_id = person_id.lstrip("p") if person_id.startswith("p") else person_id
        deputato_id = (
            f"http://dati.senato.it/senatore/{numeric_id}"
            if numeric_id and numeric_id.isdigit()
            else None
        )

        # Speaker display name from person_lookup or from <an:from> element
        cognome_nome = person_lookup.get(person_id, "")
        if not cognome_nome:
            from_elem = speech_elem.find(f"{{{AKN_NS}}}from")
            if from_elem is not None and from_elem.text:
                cognome_nome = from_elem.text.strip()

        # Also check the <an:from> text for PRESIDENTE filtering as fallback
        from_elem = speech_elem.find(f"{{{AKN_NS}}}from")
        if from_elem is not None and from_elem.text:
            from_text = from_elem.text.strip().upper()
            if from_text == "PRESIDENTE":
                return None

        # Collect text from all <an:p> elements
        text_parts: list[str] = []
        for p_elem in speech_elem.findall(f"{{{AKN_NS}}}p"):
            p_text = self._extract_element_text(p_elem)
            if p_text:
                text_parts.append(p_text)

        raw_text = " ".join(text_parts)
        clean_text = self._camera_parser.preprocess_text(raw_text)
        # The text opens with the group label, "(Misto-AVS). Signor Presidente";
        # preprocess_text drops the parenthetical and leaves the full stop.
        clean_text = re.sub(r"^[\s.,;:\-–]+", "", clean_text)

        # Filter speeches below minimum length
        if len(clean_text) < self.config.min_speech_length:
            return None

        # Completed with the position inside the debate by the caller.
        speech_id = f"{session_id}_{person_id}_deb{debate_order}"

        # Office held while speaking (TLCRole showAs, e.g. "Ministro della
        # difesa"); plain senators and deputies have no speaking role.
        speaking_role = self._role_lookup.get(as_attr)
        if speaking_role in ("", "senatore", "deputato"):
            speaking_role = None

        return {
            "id": speech_id,
            "text": clean_text,
            "deputatoId": deputato_id,
            "cognome_nome": cognome_nome,
            "speakingRole": speaking_role,
            "sessionId": session_id,
            "debateId": None,   # will be assigned by caller
            "phaseId": None,    # will be assigned by caller
            "parentType": None, # will be assigned by caller
            "parentId": None,   # will be assigned by caller
            "order": 0,         # will be assigned by caller
        }

    def _extract_element_text(self, element) -> str:
        """Extract all text from an XML element (text + tail of all descendants)."""
        if element is None:
            return ""
        parts: list[str] = []
        if element.text:
            parts.append(element.text.strip())
        for child in element:
            parts.append(self._extract_element_text(child))
            if child.tail:
                parts.append(child.tail.strip())
        return " ".join(filter(None, parts))
