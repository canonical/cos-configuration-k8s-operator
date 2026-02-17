#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Sloth SLO Provider wrapper for cos-configuration-k8s-operator.

This module provides a file-based interface for the Sloth charm library.
Unlike alert rules and dashboards (which are typically shipped with the charm),
SLO specifications are configuration files that should be managed separately
and read from disk. This wrapper class handles reading SLO YAML files from a
git-synced directory and forwarding them to the sloth-k8s-operator.
"""

import logging
import os
from typing import List

from charmlibs.interfaces.sloth import SlothProvider
from ops.charm import CharmBase

logger = logging.getLogger(__name__)


class SlothSloProvider:
    """Wrapper class for SlothProvider that reads SLO files from disk.

    This class is necessary because the Sloth charm library works differently
    from alert rules and dashboards flows. SLO specifications are not supposed
    to be shipped with the charm the way alerts are; instead, they are
    configuration files managed in a git repository. This wrapper provides a
    file-based interface similar to PrometheusRulesProvider and
    GrafanaDashboardProvider, reading YAML files from a directory and forwarding
    them to the Sloth charm.

    Args:
        charm: The charm instance.
        relation_name: Name of the sloth relation.
        slos_dir: Path to directory containing SLO YAML files.
    """

    def __init__(self, charm: CharmBase, relation_name: str, slos_dir: str):
        """Initialize the SlothSloProvider wrapper.

        Args:
            charm: The charm instance.
            relation_name: Name of the sloth relation.
            slos_dir: Path to directory containing SLO YAML files.
        """
        self._charm = charm
        self._relation_name = relation_name
        self._slos_dir = slos_dir
        # Initialize the underlying SlothProvider with inject_topology=False
        # because cos-configuration doesn't inject topology (see README about Juju Topology)
        self._provider = SlothProvider(charm, relation_name, inject_topology=False)

    def _collect_slo_file_paths(self) -> List[str]:
        """Collect paths to all SLO YAML files in the directory.

        Returns:
            List of file paths to YAML files, or empty list if none found.
        """
        slo_files = []
        for root, _, files in os.walk(self._slos_dir):
            for file in files:
                if file.endswith((".yaml", ".yml")):
                    file_path = os.path.join(root, file)
                    slo_files.append(file_path)
        return slo_files

    def _read_slo_files(self) -> str:
        """Read all SLO YAML files from the slos directory.

        Returns:
            Combined YAML string with all SLO specifications, separated by '---'.
            Returns empty string if directory doesn't exist or contains no files.
        """
        if not os.path.exists(self._slos_dir):
            logger.debug("SLO directory does not exist: %s", self._slos_dir)
            return ""

        if not os.path.isdir(self._slos_dir):
            logger.warning("SLO path is not a directory: %s", self._slos_dir)
            return ""

        slo_files = self._collect_slo_file_paths()
        if not slo_files:
            logger.debug("No SLO files found in %s", self._slos_dir)
            return ""

        # Read all files and combine them with YAML document separator
        slo_contents = []
        for file_path in sorted(slo_files):
            try:
                with open(file_path, "r") as f:
                    content = f.read().strip()
                    if content:
                        slo_contents.append(content)
                        logger.debug("Read SLO file: %s", file_path)
            except (IOError, OSError, PermissionError) as e:
                logger.warning("Failed to read SLO file %s: %s", file_path, e)

        if not slo_contents:
            return ""

        # Join with YAML document separator
        return "\n---\n".join(slo_contents)

    def _reinitialize_slo_specs(self):
        """Reinitialize SLO specifications from disk.

        This method is called when the git repository content changes.
        It reads all SLO files from the configured directory and sends them
        to the Sloth charm via the relation.
        """
        logger.info("Reinitializing SLO specs from %s", self._slos_dir)
        slo_config = self._read_slo_files()
        if slo_config:
            self._provider.provide_slos(slo_config)
            logger.info("Provided SLO config to sloth relation")
        else:
            logger.debug("No SLO config to provide")
