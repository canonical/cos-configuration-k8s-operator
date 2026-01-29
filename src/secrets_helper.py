#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju secrets getter for sensitive data."""

import logging
from typing import Optional
from urllib.parse import urlparse

from ops.model import (
    ActiveStatus,
    BlockedStatus,
    Model,
    ModelError,
    SecretNotFoundError,
    StatusBase,
)

logger = logging.getLogger(__name__)


class SecretGetter:
    """A getter for Juju secrets and statuses related to secret operations."""

    def __init__(self, model: Model):
        self._model = model
        self._status: Optional[StatusBase] = None

    def get_value(self, secret_url: str) -> Optional[str]:
        """Retrieve the secret value from a secret URL.

        Args:
            secret_url: a URL of the form secret://<secret-id>/<key>

        Returns:
            The secret value, or None if not found or on errors.
        """
        if not secret_url:
            return None

        parsed_secret = urlparse(secret_url)
        secret_not_found_msg = "git SSH key secret not found."
        if not all([parsed_secret.scheme == "secret", parsed_secret.netloc, parsed_secret.path]):
            self._status = BlockedStatus(secret_not_found_msg)
            return None

        secret_id = parsed_secret.netloc
        if len(paths := parsed_secret.path.lstrip("/").split("/")) != 1:
            self._status = BlockedStatus(secret_not_found_msg)
            return None

        secret_key = paths[0]
        try:
            secret = self._model.get_secret(id=secret_id)
            content = secret.get_content(refresh=True)
            if not (value := content.get(secret_key)):
                self._status = BlockedStatus(secret_not_found_msg)
                return None
            self._status = ActiveStatus()
            return value
        except SecretNotFoundError:
            self._status = BlockedStatus(secret_not_found_msg)
            return None
        except ModelError as e:
            logger.error(
                f"missing charm permissions for the git SSH key secret. run 'juju grant-secret' to resolve: {e}"
            )
            self._status = BlockedStatus(
                "missing charm permissions for the secret, see debug-log."
            )
            return None
        except Exception as e:
            logger.error(f"unexpected error fetching secret: {e}")
            self._status = BlockedStatus("Unexpected error fetching secret, see debug-log.")
            return None

    def status(self) -> Optional[StatusBase]:
        """Retrieve the status."""
        return self._status
