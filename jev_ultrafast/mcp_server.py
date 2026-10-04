"""jevnav as an MCP tool, for Claude Desktop chat (no shell there). Each call runs the jevnav CLI once.

Run: uv run --directory <repo> --with 'mcp<2' --env-file .env python -m jev_ultrafast.mcp_server
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent.parent
server = FastMCP("jevnav", instructions=(
    "Use jevnav for every task in the user's own browser (Comet profile): opening pages, searching, filling forms, "
    "signing in. It is faster and cheaper than any other browser tool. Never put usernames, emails, passwords or codes "
    "in values: 1Password fills them while the user confirms with a fingerprint."
))


@server.tool()
async def jevnav(goal: str, url: str | None = None, values: dict[str, str] | None = None, target: str | None = None,
                 confirm: str | None = None) -> str:
    """Drive the user's Comet browser to a goal; returns one JSON result.

    goal: the whole task in plain words. url: start page (omit when resuming with target).
    values: non-secret field values you supply, e.g. {"from": "Zurich"}; Jev decides which field gets which.
    target: tab id from a previous result, to resume. confirm: allow one irreversible click whose label contains it.
    Statuses: done; need_value (add the value for `field`, resume with target); confirm (ask the user, then resume
    with confirm=<label>); login_timeout (tell the user to fill with 1Password and click the sign-in button, then
    resume); in_progress (resume with target); blocked or error (report)."""
    # Stay under the client's request timeout: nav stops itself at the deadline and still returns the target.
    cmd = [sys.executable, "-m", "jev_ultrafast.nav", "--goal", goal, "--budget", "35", "--login-wait", "30",
           "--deadline", "45"]
    for flag, value in (("--url", url), ("--target", target), ("--confirm", confirm)):
        if value:
            cmd += [flag, value]
    if values:
        cmd += ["--values", json.dumps(values)]
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=ROOT, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=55)
    except TimeoutError:
        proc.kill()
        return json.dumps({"status": "error", "error": "jevnav did not answer within 55 s"})
    return out.decode().strip() or json.dumps({"status": "error", "error": err.decode().strip()[-500:]})


if __name__ == "__main__":
    server.run()
