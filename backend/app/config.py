"""
Configuration management for the Multi-View RAG system.

Loads configuration from:
1. config/default.yaml - all weights, thresholds, and settings
2. .env - secrets only (API keys, passwords)
"""
import logging
from datetime import date
from pathlib import Path
from typing import Dict, Any, List, Optional
from functools import lru_cache

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Maintenance switch: set to True to answer every API request with 503.
# Restart the backend after changing this value.
MAINTENANCE_MODE: bool = False

# Project root directory
# config.py is at: backend/app/config.py
# In Docker: /app/app/config.py → .parent.parent = /app/ (backend root)
# Locally: .parent.parent = backend/
# config/ is always at backend/config/
PROJECT_ROOT = Path(__file__).parent.parent  # backend/ or /app/
CONFIG_DIR = PROJECT_ROOT / "config"

# Locate .env file: prefer backend/.env, fallback to project root .env
_env_file = PROJECT_ROOT / ".env"
if not _env_file.exists():
    _env_file = PROJECT_ROOT.parent / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Only secrets live here; all other configuration is in YAML.
    """
    # Neo4j Connection
    neo4j_uri: str = Field(
        default="bolt://localhost:7689",
        description="Neo4j Bolt URI"
    )
    neo4j_user: str = Field(
        default="neo4j",
        description="Neo4j username"
    )
    neo4j_password: str = Field(
        description="Neo4j password (REQUIRED)"
    )

    openai_api_key: str = Field(
        description="OpenAI API key (required)"
    )

    # LangSmith observability (tracing is active only when the key is present)
    langsmith_api_key: str = Field(
        default="",
        description="LangSmith API key (empty = tracing disabled)"
    )
    langsmith_project: str = Field(
        default="parliamentrag",
        description="LangSmith project name"
    )

    # Brevo mailing list (newsletter opt-in is hidden when the key is empty)
    brevo_api_key: str = Field(default="", description="Brevo API key")
    # Strings, not ints: an empty value copied from .env.example must not crash startup
    brevo_list_id: str = Field(default="", description="Brevo list for confirmed subscribers")
    brevo_doi_template_id: str = Field(
        default="",
        description="Brevo double opt-in template (must contain the {{ doubleoptin }} link)"
    )
    public_site_url: str = Field(
        default="https://www.parliamentrag.it",
        description="Public site base URL, target of the confirmation redirect"
    )

    # The privacy notice promises deletion after this date (Europe/Rome)
    data_retention_until: date = Field(
        default=date(2027, 12, 31),
        description="Last day user data is kept; app.services.retention deletes it afterwards"
    )
    data_retention_max_days: Optional[int] = Field(
        default=None,
        description="Also delete user data older than this many days (unset = keep until the date)"
    )

    @field_validator("data_retention_max_days", mode="before")
    @classmethod
    def _blank_is_unset(cls, v):
        return None if v == "" else v

    # Debug settings
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    model_config = {
        "env_file": str(_env_file),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


class ConfigLoader:
    """Loads and manages YAML configuration."""

    def __init__(self, config_dir: Path = CONFIG_DIR):
        self.config_dir = config_dir
        self._config: Optional[Dict[str, Any]] = None

    def load_config(self) -> Dict[str, Any]:
        """Load the main configuration file."""
        if self._config is not None:
            return self._config

        config_path = self.config_dir / "default.yaml"
        if not config_path.exists():
            logger.warning(f"Config file not found at {config_path}, using defaults")
            self._config = self._get_default_config()
        else:
            with open(config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f)
            logger.info(f"Loaded configuration from {config_path}")

        return self._config

    def _get_default_config(self) -> Dict[str, Any]:
        """Return the fallback configuration used only when default.yaml is missing.

        Values must stay aligned with config/default.yaml (the source of truth,
        matching the technical paper).
        """
        return {
            "retrieval": {
                "dense_channel": {
                    "top_k": 200,
                    "similarity_threshold": 0.3
                },
                "graph_channel": {
                    "lexical_keywords_min_match": 1,
                    "semantic_similarity_threshold": 0.4,
                    "max_acts_per_query": 100
                },
                "merger": {
                    "diversity_weight": 0.15,
                    "coverage_weight": 0.20,
                    "authority_weight": 0.05,
                    "relevance_weight": 0.35,
                    "salience_weight": 0.25
                }
            },
            "authority": {
                "weights": {
                    "profession": 0.15,
                    "education": 0.10,
                    "committee": 0.25,
                    "acts": 0.20,
                    "interventions": 0.25,
                    "role": 0.05
                },
                "time_decay": {
                    "acts_half_life_days": 548,
                    "speeches_half_life_days": 548
                },
                "max_component_contribution": 0.8
            },
            "compass": {
                "purpose": "multi-view coverage",
                "anchors": {
                    "left": {
                        "groups": [
                            "Alleanza Verdi e Sinistra",
                            "Partito Democratico - Italia Democratica e Progressista"
                        ],
                        "confidence": 0.8
                    },
                    "center": {
                        "groups": [
                            "Azione - Popolari Europeisti Riformatori - Renew Europe",
                            "Italia Viva - Casa Riformista",
                            "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare"
                        ],
                        "confidence": 0.6
                    },
                    "right": {
                        "groups": [
                            "Fratelli d'Italia",
                            "Lega - Salvini Premier",
                            "Forza Italia - Berlusconi Presidente - PPE"
                        ],
                        "confidence": 0.8
                    }
                },
                "ambiguous": {
                    "Movimento 5 Stelle": {
                        "default_position": "left",
                        "confidence": 0.5
                    }
                },
                "unclassified": ["Misto"],
                "clustering": {
                    "min_fragments_for_kde": 3,
                    "kde_bandwidth": "scott"
                }
            },
            "generation": {
                "models": {
                    "analyst": "gpt-4.1-mini",
                    "writer": "gpt-4.1",
                    "integrator": "gpt-4.1"
                },
                "parameters": {
                    "max_tokens": 4000,
                    "temperature": 0.3,
                    "top_p": 1.0
                },
                "require_all_parties": True,
                "no_evidence_message": "Nel corpus analizzato non risultano interventi rilevanti su questo tema."
            },
            "coalitions": {
                "maggioranza": [
                    "Fratelli d'Italia",
                    "Lega - Salvini Premier",
                    "Forza Italia - Berlusconi Presidente - PPE",
                    "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare"
                ],
                "opposizione": [
                    "Partito Democratico - Italia Democratica e Progressista",
                    "Movimento 5 Stelle",
                    "Alleanza Verdi e Sinistra",
                    "Azione - Popolari Europeisti Riformatori - Renew Europe",
                    "Italia Viva - Casa Riformista",
                    "Misto"
                ]
            },
            "citation": {
                "method": "offset",
                "format": "«{quote}» [{speaker}, {party}, {date}, ID:{id}]",
                "verify_on_insert": True
            }
        }

    def save_config(self, data: Dict[str, Any]) -> None:
        """Apply configuration in-memory only (not persisted to disk).

        Changes take effect immediately for the current process but are
        lost on restart, preserving config/default.yaml as the source of truth.
        """
        self._config = data
        logger.info("Applied configuration in-memory (not persisted to disk)")

    @property
    def retrieval(self) -> Dict[str, Any]:
        return self.load_config().get("retrieval", {})

    @property
    def authority(self) -> Dict[str, Any]:
        return self.load_config().get("authority", {})

    @property
    def compass(self) -> Dict[str, Any]:
        return self.load_config().get("compass", {})

    @property
    def generation(self) -> Dict[str, Any]:
        return self.load_config().get("generation", {})

    @property
    def coalitions(self) -> Dict[str, List[str]]:
        return self.load_config().get("coalitions", {})

    @property
    def citation(self) -> Dict[str, Any]:
        return self.load_config().get("citation", {})

    def get_coalition(self, group_name: str) -> str:
        """
        Determine which coalition a group belongs to.

        Uses case-insensitive matching with normalized hyphens to handle
        DB names (UPPERCASE) vs config names (display case).

        Args:
            group_name: Parliamentary group name

        Returns:
            'maggioranza', 'opposizione' or 'misto' (the Gruppo Misto cannot be
            assigned to either side: it contains opposing components)
        """
        if not group_name:
            return "opposizione"

        def normalize(name: str) -> str:
            return name.upper().replace(" - ", "-").replace("- ", "-").replace(" -", "-")

        group_norm = normalize(group_name)
        coalitions = self.coalitions
        for coalition, groups in coalitions.items():
            for g in groups:
                if normalize(g) == group_norm:
                    return coalition
        return "opposizione"

    def get_all_parties(self) -> List[str]:
        """Get list of all parliamentary groups."""
        coalitions = self.coalitions
        all_parties = []
        for groups in coalitions.values():
            all_parties.extend(groups)
        return all_parties


@lru_cache()
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()


@lru_cache()
def get_config() -> ConfigLoader:
    """Get configuration loader (cached)."""
    return ConfigLoader()
