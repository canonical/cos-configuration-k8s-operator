#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


from typing import Tuple


class FakeProcessVersionCheck:
    def __init__(self, args):
        pass

    def wait_output(self) -> Tuple[str, str]:
        return ("v0.1.0", "")
