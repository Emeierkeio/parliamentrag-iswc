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


class VoteActRef(BaseModel):
    """Act a roll call voted on (bill, ODG, motion), with its public page."""

    title: Optional[str] = None
    url: Optional[str] = None  # camera.it / aic.camera.it page (iter, dossier)
    text_url: Optional[str] = None  # direct PDF of the full text (stampato)


class VoteActTextResponse(BaseModel):
    """Testo integrale di ciò che una votazione ha deliberato (emendamento o
    articolo), estratto dall'Allegato A del resoconto di seduta."""

    paragraphs: list[str]
    source_url: str


class VoteDetailResponse(BaseModel):
    """Full roll-call detail for GET /api/timeline/votes/{vote_id}."""

    id: str
    number: int
    chamber: str = "camera"
    subject: Optional[str] = None
    description: Optional[str] = None
    acts: list[VoteActRef] = []
    # Allegato A del resoconto di seduta: testi integrali di emendamenti,
    # articoli e odg votati in quella seduta (documenti.camera.it).
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
    type: Optional[str] = None


class SpeakerInfo(BaseModel):
    """One speaker in a debate, listed chronologically."""

    id: str
    first_name: str
    last_name: str
    party: Optional[str] = None
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
    speaking_role: Optional[str] = None
    is_government_member: bool = False
    phase_title: Optional[str] = None


class DebateDetailResponse(BaseModel):
    """Full debate detail for GET /api/timeline/debates/{id}."""

    id: str
    title: str
    recap: Optional[str] = None
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
