#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import contextlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Tuple


class TempFolderSandbox:
    """A helper class for creating files in a temporary folder (sandbox)."""

    def __init__(self):
        self.root = tempfile.mkdtemp()

    def __del__(self):
        """Delete the sandbox."""
        # shutil.rmtree(self.root, ignore_errors=True)

    def _validated_path(self, rel_path) -> str:
        """Make sure this is a path within the root temp dir."""
        file_path = os.path.abspath(os.path.join(self.root, rel_path))

        if not file_path.startswith(self.root):
            raise ValueError(
                f"Path must be confined within temp dir's root {self.root}; got: {file_path}"
            )

        return file_path

    def put_file(self, rel_path: str, contents: str):
        """Write string to file.

        Args:
            rel_path: path to file, relative to the sandbox root.
            contents: the data to write to file.
        """
        file_path = self._validated_path(rel_path)

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wt") as f:
            f.write(contents)

    def put_files(self, *args: Tuple[str, str]):
        """Write strings to files. A vectorized version of `put_file`.

        Args:
            args: a tuple of path and contents.
        """
        for rel_path, contents in args:
            self.put_file(rel_path, contents)

    def remove_file(self, rel_path: str):
        file_path = self._validated_path(rel_path)
        with contextlib.suppress(FileNotFoundError):
            os.remove(file_path)

    def rmdir(self, rel_path):
        """Delete an empty dir.

        Args:
            rel_path: path to dir, relative to the sandbox root.
        """
        dir_path = self._validated_path(rel_path)
        os.rmdir(dir_path)

    def rmtree(self, rel_path):
        """Delete a dir tree.

        Args:
            rel_path: path to dir, relative to the sandbox root.
        """
        dir_path = self._validated_path(rel_path)
        shutil.rmtree(dir_path, ignore_errors=True)

    def clear(self):
        """Empty out the entire sandbox."""
        for path in Path(self.root).iterdir():
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
