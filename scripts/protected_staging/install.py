#!/usr/bin/env python3
"""Development wrapper; standing root execution is rejected outside bootstrap."""

from __future__ import annotations

from network_change_delivery.protected_staging_installer_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
