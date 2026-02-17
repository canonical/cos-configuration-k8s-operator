#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Scenario tests for SLO provider functionality."""

import dataclasses
import logging

import pytest
from scenario import Relation

from src.sloth import SlothSloProvider

logger = logging.getLogger(__name__)


@pytest.fixture
def slo_files(tmp_path):
    """Create sample SLO files for testing."""
    slo_dir = tmp_path / "slos"
    slo_dir.mkdir(parents=True)

    # Create first SLO file
    (slo_dir / "api-slo.yaml").write_text("""version: prometheus/v1
service: api-service
slos:
  - name: requests-availability
    objective: 99.9
    sli:
      events:
        error_query: 'sum(rate(http_requests_total{status=~"5.."}[{{.window}}]))'
        total_query: 'sum(rate(http_requests_total[{{.window}}]))'
""")

    # Create second SLO file
    (slo_dir / "db-slo.yaml").write_text("""version: prometheus/v1
service: db-service
slos:
  - name: query-availability
    objective: 99.95
    sli:
      events:
        error_query: 'sum(rate(db_queries_total{status="error"}[{{.window}}]))'
        total_query: 'sum(rate(db_queries_total[{{.window}}]))'
""")

    yield slo_dir


def test_sloth_relation_joined_with_charm(
    ctx,
    base_state,
    git_repo,
):
    """Test that joining the sloth relation works with the charm."""
    # GIVEN a sloth relation
    sloth_relation = Relation("sloth", remote_app_name="sloth-k8s")

    # AND git repo is configured
    in_state = dataclasses.replace(
        base_state,
        config=git_repo | {"slos_path": "slos"},
        relations=[sloth_relation, *base_state.relations],
    )

    # WHEN the sloth relation is joined
    with ctx(ctx.on.relation_joined(sloth_relation), in_state) as mgr:
        state_out = mgr.run()

    # THEN the charm completes successfully
    assert state_out is not None
    # AND the sloth relation is in the output state
    assert any(r.endpoint == "sloth" for r in state_out.relations)


def test_slo_files_read_correctly(slo_files, base_state):
    """Test that SLO files are read and combined correctly."""
    from unittest.mock import MagicMock

    # GIVEN an SLO provider pointing to test files
    mock_charm = MagicMock()
    provider = SlothSloProvider(mock_charm, "sloth", str(slo_files))

    # WHEN reading SLO files
    result = provider._read_slo_files()

    # THEN both files are read and combined with separator
    assert "api-service" in result
    assert "db-service" in result
    assert "---" in result
    assert result.count("---") == 1  # One separator for two files


def test_slo_provider_handles_missing_directory(base_state):
    """Test that SLO provider handles missing directory gracefully."""
    from unittest.mock import MagicMock

    # GIVEN an SLO provider pointing to non-existent directory
    mock_charm = MagicMock()
    provider = SlothSloProvider(mock_charm, "sloth", "/nonexistent/path")

    # WHEN reading SLO files
    result = provider._read_slo_files()

    # THEN empty string is returned
    assert result == ""


def test_slo_provider_handles_empty_directory(tmp_path, base_state):
    """Test that SLO provider handles empty directory gracefully."""
    from unittest.mock import MagicMock

    # GIVEN an empty SLO directory
    empty_dir = tmp_path / "empty_slos"
    empty_dir.mkdir()

    mock_charm = MagicMock()
    provider = SlothSloProvider(mock_charm, "sloth", str(empty_dir))

    # WHEN reading SLO files
    result = provider._read_slo_files()

    # THEN empty string is returned
    assert result == ""


def test_slo_provider_filters_yaml_files(tmp_path, base_state):
    """Test that SLO provider only reads YAML files."""
    from unittest.mock import MagicMock

    # GIVEN a directory with mixed file types
    slo_dir = tmp_path / "mixed_slos"
    slo_dir.mkdir()
    (slo_dir / "valid.yaml").write_text("version: prometheus/v1\nservice: test")
    (slo_dir / "valid.yml").write_text("version: prometheus/v1\nservice: test2")
    (slo_dir / "invalid.txt").write_text("should not be read")
    (slo_dir / "README.md").write_text("should not be read")

    mock_charm = MagicMock()
    provider = SlothSloProvider(mock_charm, "sloth", str(slo_dir))

    # WHEN reading SLO files
    result = provider._read_slo_files()

    # THEN only YAML files are included
    assert "test" in result or "test2" in result
    assert "should not be read" not in result
    assert "README" not in result

