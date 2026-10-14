"""
Minimal Neo4j client for scripts. Reads config from environment variables.
"""
import os
from typing import Any, Dict, List, Optional
from neo4j import GraphDatabase


class Neo4jClient:
    """Minimal Neo4j client."""

    def __init__(self, uri: str, user: str, password: str):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def query(self, cypher: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(cypher, parameters or {})
            return [dict(record) for record in result]

    def query_single(self, cypher: str, parameters: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        results = self.query(cypher, parameters)
        return results[0] if results else None


def get_neo4j_client(uri: Optional[str] = None, user: Optional[str] = None, password: Optional[str] = None) -> Neo4jClient:
    """Create a Neo4j client from args or environment variables."""
    uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = user or os.environ.get("NEO4J_USER", "neo4j")
    password = password or os.environ.get("NEO4J_PASSWORD", "parliament")
    return Neo4jClient(uri, user, password)
