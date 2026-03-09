from __future__ import annotations

from pydantic import SecretStr

from ira.config import Neo4jConfig


def test_resolved_auth_prefers_explicit_password() -> None:
    cfg = Neo4jConfig(
        user="neo4j",
        password=SecretStr("from_password"),
        auth="neo4j/from_auth",
    )
    user, password = cfg.resolved_auth()
    assert user == "neo4j"
    assert password == "from_password"


def test_resolved_auth_falls_back_to_auth_field() -> None:
    cfg = Neo4jConfig(
        user="neo4j",
        password=SecretStr(""),
        auth="altuser/from_auth",
    )
    user, password = cfg.resolved_auth()
    assert user == "altuser"
    assert password == "from_auth"


def test_resolved_auth_uses_local_default_when_unset() -> None:
    cfg = Neo4jConfig(
        uri="bolt://localhost:7687",
        user="neo4j",
        password=SecretStr(""),
        auth="",
    )
    user, password = cfg.resolved_auth()
    assert user == "neo4j"
    assert password == "ira_knowledge_graph"

