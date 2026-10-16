"""
Neo4j database client for the Multi-View RAG system.

Provides async-compatible database access with connection pooling.
"""
import logging
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import (
    AuthError,
    ConnectionPoolError,
    DatabaseUnavailable,
    ServiceUnavailable,
    SessionExpired,
)

logger = logging.getLogger(__name__)

# The database cannot be reached at all, as opposed to a bad query: the API
# answers 503 with Retry-After (handler in app/main.py).
NEO4J_UNAVAILABLE = (ServiceUnavailable, SessionExpired, DatabaseUnavailable, ConnectionPoolError)


class Neo4jClient:
    """Neo4j database client with connection pooling."""

    def __init__(self, uri: str, user: str, password: str):
        """
        Initialize the Neo4j client.

        Args:
            uri: Neo4j bolt URI (e.g., bolt://localhost:7689)
            user: Database username
            password: Database password
        """
        self.uri = uri
        self.user = user
        self._driver: Optional[Driver] = None

        try:
            self._driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                max_connection_lifetime=3600,
                max_connection_pool_size=50,
                connection_acquisition_timeout=60.0,
                connection_timeout=10.0,
                # Pooled connections die with the nightly Neo4j stop (backup at
                # 00:45 UTC): test idle ones before use, as Fascicoli does.
                liveness_check_timeout=30.0,
            )
            # Verify connectivity
            self._driver.verify_connectivity()
            logger.info(f"Connected to Neo4j at {uri}")
        except AuthError:
            logger.error(f"Authentication failed for Neo4j at {uri}")
            raise
        except ServiceUnavailable:
            logger.error(f"Neo4j service unavailable at {uri}")
            raise

    @contextmanager
    def session(self, database: str = "neo4j"):
        """
        Context manager for database sessions.

        Usage:
            with client.session() as session:
                result = session.run("MATCH (n) RETURN n LIMIT 10")
        """
        session = self._driver.session(database=database)
        try:
            yield session
        finally:
            session.close()

    def query(
        self,
        cypher: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: str = "neo4j"
    ) -> List[Dict[str, Any]]:
        """Execute a Cypher query and return results as a list of dicts."""
        with self.session(database) as session:
            result = session.run(cypher, parameters or {})
            return [record.data() for record in result]

    def query_single(
        self,
        cypher: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: str = "neo4j"
    ) -> Optional[Dict[str, Any]]:
        """Execute a query and return the single result record, or None."""
        with self.session(database) as session:
            result = session.run(cypher, parameters or {})
            record = result.single()
            return record.data() if record else None

    def verify_connectivity(self):
        """Verify database connectivity."""
        if self._driver:
            self._driver.verify_connectivity()

    def close(self):
        """Close the database connection."""
        if self._driver:
            self._driver.close()
            logger.info("Neo4j connection closed")


# Global client instance
_client: Optional[Neo4jClient] = None


def get_neo4j_client() -> Neo4jClient:
    """Get the global Neo4j client instance."""
    global _client
    if _client is None:
        raise RuntimeError(
            "Neo4j client not initialized. Call init_neo4j_client first."
        )
    return _client


def init_neo4j_client(uri: str, user: str, password: str) -> Neo4jClient:
    """Initialize the global Neo4j client."""
    global _client
    _client = Neo4jClient(uri, user, password)
    return _client
