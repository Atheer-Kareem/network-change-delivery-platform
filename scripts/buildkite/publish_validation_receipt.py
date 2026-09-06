#!/usr/bin/env python3
"""Called only after a complete engineering command succeeds; no status queries."""

import os

from profiled_delivery import publish_metadata

from network_change_delivery.profiled_promotion import (
    ProfiledBuildContext,
    validation_receipt,
)


def main():
    try:
        context = ProfiledBuildContext.from_environment(os.environ, main=False)
        publish_metadata(
            context,
            "profiled-validation-" + context.step,
            validation_receipt(context.build_id, context.commit, context.step),
        )
    except Exception:
        print("Validation success receipt was not published")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
