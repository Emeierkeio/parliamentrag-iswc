"""
Pydantic v2 models for the timeline API endpoints.

Provides response shapes for the three timeline endpoints:
  - GET /api/timeline            → TimelineResponse
  - GET /api/timeline/debates/{id} → DebateDetailResponse
  - GET /api/timeline/speakers/{debateId}/{speakerId} → SpeakerSummaryResponse
"""
from typing import Optional

from pydantic import BaseModel


class DebateSummary(BaseModel):
    """Lightweight debate entry nested inside a SessionCard."""

    id: str
    title: str
    speech_count: int
    # Senate outcome fragments ("È approvato.") that continue this debate,
    # merged into it; get_debate on this id includes their speeches.
    continuation_ids: list[str] = []


class SearchMatch(BaseModel):
    """Why a sitting matched a search: the vote, act, debate or speech that
    contains the words, so the list can show it next to the sitting."""

    kind: str                        # "vote" | "act" | "debate" | "speech" | "recap"
    text: str                        # vote subject, act title, debate title or speech excerpt
    vote_id: Optional[str] = None    # kind "vote" (and "act" when the act was voted)
    vote_number: Optional[int] = None
    speaker: Optional[str] = None    # kind "speech"


class SessionCard(BaseModel):
    """One parliamentary session shown in the timeline list."""

    id: str
    date: str                        # ISO date string "2026-04-07"
    chamber: str                     # "camera" or "senato"
    number: int
    recap: Optional[str] = None      # None if not yet generated
    debate_count: int
    vote_count: int
    speech_count: int
    debates: list[DebateSummary]
    matches: list[SearchMatch] = []  # only when searching


class TimelineResponse(BaseModel):
    """Paginated list of sessions for GET /api/timeline."""

    sessions: list[SessionCard]
    next_cursor: Optional[str] = None  # ISO date of the last session in this page
    has_more: bool


class PhaseInfo(BaseModel):
    """A single debate phase with speech count."""

    id: str
    title: str
    phase_type: Optional[str] = None
    speech_count: int


class VoteAmendment(BaseModel):
    """The amendment a floor vote is on, for a reader who does not know what «EM 1.151 NF» means."""

    numbers: list[str]                  # "1.151" (more when the vote groups several)
    first_signer: Optional[str] = None  # "Devis Dori"
    first_signer_id: Optional[str] = None  # "307634": the number of dati.camera.it / dati.senato.it
    signers: int = 0                    # every signatory, the first included
    excerpt: Optional[str] = None       # the start of the text, from the archive


class VoteInfo(BaseModel):
    """One roll-call vote attached to a session."""

    id: str
    number: int
    subject: Optional[str] = None
    description: Optional[str] = None
    final_vote: bool = False
    outcome: Optional[str] = None
    in_favor: Optional[int] = None
    against: Optional[int] = None
    abstained: Optional[int] = None
    # Readable subject of the motion or resolution voted on, from the debate
    # title (build/act_subjects.py); None for other votes.
    act_subject: Optional[str] = None
    # "quorum_check" for a Senate check of the quorum (Verifica del numero
    # legale): not a vote on anything, outcome is None. None otherwise.
    kind: Optional[str] = None
    # The main act voted on (the bill, not the joint ones absorbed into it)
    act_number: Optional[str] = None
    act_title: Optional[str] = None
    # The amendment voted on (ON_AMENDMENT), with the start of its text
    amendment: Optional[VoteAmendment] = None


class VoteParticipant(BaseModel):
    """One deputy's individual vote inside a roll call."""

    id: str
    first_name: str
    last_name: str
    party: Optional[str] = None
    outcome: str  # "favor" | "against" | "abstain" | "absent"
    # Ministers and former deputies keep another id (gov_*, Camera persona URI)
    senato_id: Optional[str] = None


class VotePartyBreakdown(BaseModel):
    """Aggregated favor/against/abstain/absent counts for one parliamentary group.

    secret counts members who took part in a secret ballot (how they voted is
    not public)."""

    party: str
    favor: int
    against: int
    abstain: int = 0
    absent: int
    secret: int = 0


class LawRef(BaseModel):
    """Law an act became, as published in the Gazzetta Ufficiale."""

    kind: str  # "legge" | "legge_costituzionale"
    number: int
    date: Optional[str] = None  # ISO date of the law
    label: str  # "Legge n. 180 del 9 ottobre 2026"
    eli: Optional[str] = None  # Normattiva ELI URL, original text
    normattiva_url: Optional[str] = None  # Normattiva URN resolver, text in force
    gu_number: Optional[int] = None
    gu_date: Optional[str] = None
    title: Optional[str] = None


class VoteActRef(BaseModel):
    """Act a roll call voted on (bill, ODG, motion), with its public page."""

    uri: Optional[str] = None  # graph and open-data URI (dati.camera.it / dati.senato.it)
    title: Optional[str] = None
    # Motions and resolutions: what the act is about, from official text
    # (build/act_subjects.py); the title is only their code.
    subject: Optional[str] = None
    number: Optional[str] = None  # "2822-B", "1903"
    status: Optional[str] = None  # Senate bills: "assorbito" for a joint bill absorbed by the main one
    url: Optional[str] = None  # camera.it / aic.camera.it / senato.it page (iter, dossier)
    text_url: Optional[str] = None  # full text: PDF of the printed bill, or the texts page
    law: Optional[LawRef] = None


class VoteActTextResponse(BaseModel):
    """Full text of what a roll call decided (amendment or article): from
    Allegato A of the Camera sitting, or from the amendment archive."""

    paragraphs: list[str]
    source_url: str


class VoteDetailResponse(BaseModel):
    """Full roll-call detail for GET /api/timeline/votes/{vote_id}."""

    id: str
    number: int
    chamber: str = "camera"
    subject: Optional[str] = None
    description: Optional[str] = None
    kind: Optional[str] = None  # see VoteInfo.kind
    acts: list[VoteActRef] = []
    # Camera: Allegato A of the sitting record (full texts of the amendments,
    # articles and agenda orders voted). Senate: the sitting record, which
    # carries its annexes.
    session_annex_url: Optional[str] = None
    # Scrutinio segreto: le espressioni individuali non sono pubbliche
    # (restano noti solo gli astenuti).
    secret_vote: bool = False
    outcome: Optional[str] = None
    vote_type: Optional[str] = None
    in_favor: Optional[int] = None
    against: Optional[int] = None
    abstained: Optional[int] = None
    present: Optional[int] = None
    voters: Optional[int] = None
    majority: Optional[int] = None
    on_mission: Optional[int] = None
    breakdown: list[VotePartyBreakdown]
    participants: list[VoteParticipant]


class ActInfo(BaseModel):
    """Parliamentary act discussed in a debate."""

    id: str
    title: Optional[str] = None
    subject: Optional[str] = None  # motions and resolutions, see VoteActRef
    type: Optional[str] = None
    number: Optional[str] = None
    status: Optional[str] = None  # see VoteActRef.status
    url: Optional[str] = None
    law: Optional[LawRef] = None


class SpeakerInfo(BaseModel):
    """One speaker in a debate, listed chronologically."""

    id: str
    first_name: str
    last_name: str
    party: Optional[str] = None
    # Set when party is a Mixed Group component: the group itself (Misto)
    parliamentary_group: Optional[str] = None
    speaking_role: Optional[str] = None
    is_government_member: bool = False
    speech_count: int
    phases: list[str]  # Phase titles where this speaker participated


class InterventionInfo(BaseModel):
    """One speech slot in a debate, in chronological order (a deputy who
    speaks twice appears twice, at each point where they took the floor)."""

    speech_id: str
    speaker_id: str
    first_name: str
    last_name: str
    party: Optional[str] = None
    parliamentary_group: Optional[str] = None  # see SpeakerInfo
    speaking_role: Optional[str] = None
    is_government_member: bool = False
    phase_title: Optional[str] = None


class DebateDetailResponse(BaseModel):
    """Full debate detail for GET /api/timeline/debates/{id}."""

    id: str
    title: str
    recap: Optional[str] = None
    # Outcome fragments merged into this debate (see DebateSummary)
    continuation_ids: list[str] = []
    phases: list[PhaseInfo]
    speakers: list[SpeakerInfo]
    interventions: list[InterventionInfo] = []
    votes: list[VoteInfo]
    acts: list[ActInfo]


class SpeechText(BaseModel):
    """Full text of a single speech in a debate."""

    id: str
    text: str
    phase_title: Optional[str] = None


class SpeakerSummaryResponse(BaseModel):
    """Speaker speeches and optional AI summary for GET /api/timeline/speakers/{debateId}/{speakerId}."""

    summary: Optional[str] = None
    speech_count: int
    phases: list[str]
    speeches: list[SpeechText] = []
