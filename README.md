# Mochi MCP Server

Simple HTTP MCP server for the Mochi flashcard API.

## Requirements

- Python 3.13 or compatible
- A working OS keyring backend
- A Mochi API key

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Initial setup

Store your Mochi API key in the OS keyring:

```bash
.venv/bin/python3 mcp.py --setup
```

This also writes default server settings to `~/.config/mcp_mochi/config.json`.

## Run the server

Default run:

```bash
.venv/bin/python3 mcp.py
```

By default the server listens on:

```text
http://127.0.0.1:8000/
```

The MCP streamable HTTP endpoint is mounted at the root path `/`, which matches what Codex expects for a `url` entry.

Run with explicit host/port/path overrides:

```bash
.venv/bin/python3 mcp.py --host 127.0.0.1 --port 8000 --path /
```

## Codex example

Add this to `~/.codex/config.toml`:

```toml
[mcp_servers.mochi]
url = "http://127.0.0.1:8000"
```

Then start the server:

```bash
cd ~/scripts/mcp_mochi
.venv/bin/python3 mcp.py
```

## Notes

- Older saved configs that used `"/mcp"` are treated as `/` automatically.
- If startup fails with a keyring error, configure a supported system keyring backend and run `mcp.py --setup` again.
