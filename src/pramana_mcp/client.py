"""Thin read-only HTTP client for the Pramana API.

Deliberately stdlib-only (`urllib`): this process is launched by an assistant
via `uvx`, so every dependency is a cold download on someone else's machine at
the moment they ask a question. `mcp` and `pramana-verify` earn their place;
an HTTP library does not.

Read paths only. v1 of this server exposes nothing that starts a replay or a
model diff, because a batch spends real money on model calls and an MCP tool
is a button any assistant can press.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_API_URL = "https://www.reliai.in/api"


class PramanaError(RuntimeError):
    """Raised with a message meant to be read by a person, via an assistant.

    Every message says what went wrong AND what to do about it — an assistant
    relaying "401" helps nobody, and the person reading it cannot see this
    process's environment.
    """


class PramanaClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout_s: float = 20.0):
        self.base_url = (base_url or os.environ.get("PRAMANA_API_URL") or DEFAULT_API_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("PRAMANA_API_KEY") or ""
        self.timeout_s = timeout_s
        if not self.api_key:
            raise PramanaError(
                "PRAMANA_API_KEY is not set, so this server cannot read anything. "
                "Create an engineer or admin key in Settings -> API keys at https://www.reliai.in/ "
                "and set it in the MCP server's env block."
            )

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code in (401, 403):
                raise PramanaError(
                    f"Pramana rejected the API key ({e.code}). Check PRAMANA_API_KEY is a current "
                    f"engineer or admin key — an auditor key cannot read recorded payloads. "
                    f"Server said: {body}"
                ) from None
            if e.code == 404:
                raise PramanaError(f"Not found at {path}. Server said: {body}") from None
            raise PramanaError(f"Pramana API returned {e.code} for {path}. Server said: {body}") from None
        except urllib.error.URLError as e:
            raise PramanaError(
                f"Could not reach the Pramana API at {self.base_url} ({e.reason}). "
                f"Check the machine is online, and PRAMANA_API_URL if you are self-hosting."
            ) from None
        except json.JSONDecodeError:
            raise PramanaError(f"Pramana API returned a non-JSON response for {path}.") from None

    # --- read paths -------------------------------------------------------
    #
    # `get` returns whatever the API sent, so each of these checks the shape it
    # promises rather than asserting it with a cast. An API that starts
    # returning something else should say so here, not three frames deeper
    # where the message would be an unexplained AttributeError.

    def _expect_list(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        data = self.get(path, params)
        if not isinstance(data, list):
            raise PramanaError(f"Expected a list from {path}, got {type(data).__name__}.")
        return [d for d in data if isinstance(d, dict)]

    def list_traces(self, limit: int = 20, before: str | None = None) -> list[dict[str, Any]]:
        return self._expect_list("/v1/traces", {"limit": limit, "before": before})

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        path = f"/v1/traces/{urllib.parse.quote(trace_id)}"
        data = self.get(path)
        if not isinstance(data, dict):
            raise PramanaError(f"Expected an object from {path}, got {type(data).__name__}.")
        return data

    def model_diffs_for_trace(self, trace_id: str) -> list[dict[str, Any]]:
        return self._expect_list(f"/v1/traces/{urllib.parse.quote(trace_id)}/model-diffs")
