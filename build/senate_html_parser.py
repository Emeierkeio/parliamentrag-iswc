"""
Parser for Senate stenographic records published only as web pages.

For a few sittings (XIX: 212, 213, 214, 216, 218, 221, 222) senato.it lists
the record but serves no AKN file (404). The full page
show-doc?tipodoc=Resaula&part=doc_dc carries the same content: section
headings are centred bold paragraphs, every speech opens with a link to the
speaker (loc/link.asp?...&id=<senatore id>, the same id as AKN "#p<id>"),
and paragraphs without a link continue the current speech.

The output has the same shape as SenateStenograficoParser.parse_xml_file,
so ingestion does not change.
"""

import html
import re
from typing import Optional

from senate_parser import SenateStenograficoParser, _slug, classify_phase_type

_TITLE_RE = re.compile(r"seduta n\.\s*(\d+)\s+del\s+(\d{2})/(\d{2})/(\d{4})", re.I)
_PARAGRAPH_RE = re.compile(r"<p([^>]*)>(.*?)</p>", re.S | re.I)
_SPEAKER_RE = re.compile(
    r"^\s*<a[^>]*href=\"[^\"]*tipodoc=sanasen&(?:amp;)?id=(\d+)\"[^>]*>([^<]+)</a>(.*)$", re.S | re.I
)
_TAG_RE = re.compile(r"<[^>]+>")
# After the speaker link: optional "(Group)", optional ", role", then ". ".
_LEAD_RE = re.compile(r"^\s*(?:\(([^)]*)\))?\s*(?:,\s*([^.]{1,120}))?\s*\.\s*")
_END_MARKERS = ("allegato a", "allegato b")
# The same speaker without a link, after the chair gave the floor:
# "BORGHI Enrico (IV-C-RE). Signora Presidente, ...".
_PLAIN_SPEAKER_RE = re.compile(
    r"^([A-ZÀ-Ý][A-ZÀ-Ý'\- ]+?(?: [A-ZÀ-Ý][a-zà-ÿ']+)*)\s*(\([^)]{1,40}\))?\s*(,\s*[^.]{1,120})?\.\s+(.*)$",
    re.S,
)
_EMPTY_ANCHOR_RE = re.compile(r"<a[^>]*>\s*</a>", re.I)
_BOLD_RE = re.compile(r"<b>(.*?)</b>", re.S | re.I)


def _is_bold_line(inner: str, text: str) -> bool:
    """A short paragraph set entirely in bold: an agenda heading."""
    bold = _text(" ".join(_BOLD_RE.findall(inner)))
    return 0 < len(text) < 400 and len(bold) >= 0.9 * len(text)


def _text(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub("", fragment)).replace("\xa0", " ").strip()


def parse_title(page: str) -> Optional[tuple[int, str]]:
    """(sitting number, ISO date) from the page title, or None."""
    m = _TITLE_RE.search(page)
    if not m:
        return None
    number, day, month, year = m.groups()
    return int(number), f"{year}-{month}-{day}"


class SenateHtmlParser(SenateStenograficoParser):
    def parse_html_file(self, filepath: str) -> dict:
        with open(filepath, encoding="utf-8") as f:
            page = f.read()
        title = parse_title(page)
        if title is None:
            raise ValueError(f"{filepath}: no sitting number/date in the page title")
        number, date = title
        year, month, day = (int(x) for x in date.split("-"))
        session_id = f"sen_leg{self.legislature}_sed{number}"
        session = {
            "id": session_id,
            "legislature": self.legislature,
            "number": number,
            "year": year,
            "month": month,
            "day": day,
            "chamber": "senato",
            "date": date,
        }

        start = page.find('class="bgt"')
        body = page[start:] if start != -1 else page

        sections: list[tuple[str, list[dict]]] = []
        heading = ""
        current: list[dict] = []
        speech: Optional[dict] = None
        chair_speaking = False

        def close_section():
            if current:
                sections.append((heading, list(current)))

        pending_heading = ""
        ids_by_name: dict[str, str] = {}
        for attrs, inner in _PARAGRAPH_RE.findall(body):
            inner = _EMPTY_ANCHOR_RE.sub("", inner)
            text = _text(inner)
            if not text:
                continue
            centred = "center" in attrs.lower()
            if centred and text.lower() in _END_MARKERS:
                break
            # The annexes follow the record with no heading of their own.
            if re.match(r"(?i)^\(?la seduta è tolta", text):
                break
            # A change of chair is printed like a heading but is not one.
            if text.lower().startswith("presidenza del"):
                continue
            if pending_heading or (_is_bold_line(inner, text) and not _SPEAKER_RE.match(inner.strip())):
                if centred or pending_heading or _is_bold_line(inner, text):
                    title = f"{pending_heading} {text}".strip() if pending_heading else text
                    if title.endswith(":") and not pending_heading:
                        pending_heading = title
                        continue
                    pending_heading = ""
                    close_section()
                    heading, current, speech, chair_speaking = title, [], None, False
                    continue
            if centred:
                continue

            m = _SPEAKER_RE.match(inner.strip())
            if m:
                person_id, name, rest = m.group(1), _text(m.group(2)), _text(m.group(3))
                ids_by_name[name.upper()] = person_id
                if name.upper() == "PRESIDENTE":
                    speech, chair_speaking = None, True
                    continue
                chair_speaking = False
                lead = _LEAD_RE.match(rest)
                role = lead.group(2).strip() if lead and lead.group(2) else None
                body_text = rest[lead.end():] if lead else rest
                if role and re.match(r"(?i)relat|senat", role):
                    role = None
                speech = {
                    "person_id": person_id,
                    "cognome_nome": name,
                    "speakingRole": role,
                    "parts": [body_text],
                }
                current.append(speech)
                continue

            if re.match(r"^PRESIDENTE\s*\.", text):
                speech, chair_speaking = None, True
                continue
            plain = _PLAIN_SPEAKER_RE.match(text)
            if plain and (plain.group(1).upper() in ids_by_name or plain.group(2)):
                name = plain.group(1).strip()
                role = plain.group(3).lstrip(", ").strip() if plain.group(3) else None
                if role and re.match(r"(?i)relat|senat", role):
                    role = None
                chair_speaking = False
                speech = {
                    "person_id": ids_by_name.get(name.upper()),
                    "cognome_nome": name,
                    "speakingRole": role,
                    "parts": [plain.group(4)],
                }
                current.append(speech)
                continue
            # Stage directions, e.g. "(La seduta, sospesa alle ore 10,09, ...)".
            if text.startswith("(") and text.rstrip(".").endswith(")"):
                continue
            if speech is not None and not chair_speaking:
                speech["parts"].append(text)

        close_section()

        debates: list[dict] = []
        phases: list[dict] = []
        speeches: list[dict] = []
        seen: set[str] = set()
        order = 0
        for heading_text, raw in sections:
            kept = []
            for s in raw:
                clean = self._camera_parser.preprocess_text(" ".join(p for p in s["parts"] if p))
                clean = re.sub(r"^[\s.,;:\-–]+", "", clean)
                if len(clean) >= self.config.min_speech_length:
                    kept.append((s, clean))
            if not kept:
                continue
            debate_id = f"{session_id}_{_slug(heading_text) or f'sec{order}'}"
            if debate_id in seen:
                debate_id = f"{debate_id}_{order}"
            seen.add(debate_id)
            phase_id = f"{debate_id}_phase0"
            debates.append({
                "id": debate_id,
                "originalId": heading_text,
                "title": heading_text,
                "order": order,
                "sessionId": session_id,
            })
            phases.append({
                "id": phase_id,
                "originalId": f"{heading_text}_phase0",
                "title": heading_text,
                "phaseType": classify_phase_type(heading_text),
                "order": 0,
                "debateId": debate_id,
            })
            for idx, (s, clean) in enumerate(kept):
                speeches.append({
                    "id": f"{session_id}_p{s['person_id'] or ''}_deb{order}_{idx}",
                    "text": clean,
                    "deputatoId": f"http://dati.senato.it/senatore/{s['person_id']}" if s["person_id"] else None,
                    "cognome_nome": s["cognome_nome"],
                    "speakingRole": s["speakingRole"],
                    "sessionId": session_id,
                    "debateId": debate_id,
                    "phaseId": phase_id,
                    "parentType": "phase",
                    "parentId": phase_id,
                    "order": idx,
                })
            order += 1

        return {
            "session": session,
            "debates": debates,
            "phases": phases,
            "speeches": speeches,
            "votes": [],
            "act_references": {},
        }
