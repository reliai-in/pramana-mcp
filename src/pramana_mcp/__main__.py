"""stdio entry point. `uvx pramana-mcp` lands here."""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    from pramana_mcp.server import run

    try:
        asyncio.run(run())
    except KeyboardInterrupt:  # a normal way for a host to stop us
        sys.exit(0)


if __name__ == "__main__":
    main()
