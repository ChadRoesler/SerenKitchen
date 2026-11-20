"""The kitchen's own door for a partner: an MCP endpoint on this same process.

Only there when the [mcp] extra is installed (`pip install seren-kitchen[mcp]`);
without it the mount is skipped with one log line and the kitchen is the page
and the HTTP API, as before.

WHY IT EXISTS. A partner reaches the kitchen through tools. A house that runs a
Workbench gets them there (it has the kitchen's tools built in, and talks to this
service over HTTP). A house that runs no Workbench had a board its partner could
not touch. This is the other path: point an MCP client at /mcp and the same eight
tools are there, with nothing else deployed.

The tools go to the Store in process (tools.py): mounted into the app that owns
it, there is no reason to call ourselves over HTTP. server.py is the mount, kept
parallel with the family's other in-process mounts on purpose.
"""
