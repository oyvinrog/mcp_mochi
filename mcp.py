#!/usr/bin/env python3
"""MCP server for the Mochi flashcard API."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if sys.path and Path(sys.path[0] or ".").resolve() == SCRIPT_DIR:
    sys.path.pop(0)

try:
    import keyring
    import requests
    from keyring.errors import KeyringError, NoKeyringError
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - dependency failure path
    missing = exc.name or "required dependency"
    print(
        f"Missing dependency: {missing}. Install dependencies with "
        "`python3 -m pip install -r requirements.txt`.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc
finally:
    sys.path.insert(0, str(SCRIPT_DIR))


MOCHI_BASE_URL = "https://app.mochi.cards/api"
CONFIG_DIR = Path.home() / ".config" / "mcp_mochi"
CONFIG_PATH = CONFIG_DIR / "config.json"
KEYRING_SERVICE = "mcp_mochi"
KEYRING_USERNAME = "api_key"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_PATH = "/"
DEFAULT_TIMEOUT = 30
LEGACY_PATH = "/mcp"


class MochiError(RuntimeError):
    """Raised when Mochi API interactions fail."""


@dataclass(slots=True)
class AppConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    path: str = DEFAULT_PATH
    timeout: int = DEFAULT_TIMEOUT


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def normalize_path(path: str) -> str:
    if not path:
        return DEFAULT_PATH
    if path == "/":
        return "/"
    return path if path.startswith("/") else f"/{path}"


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()

    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    raw_path = str(data.get("path", DEFAULT_PATH))
    path = normalize_path(raw_path)
    if path == LEGACY_PATH:
        path = DEFAULT_PATH

    return AppConfig(
        host=data.get("host", DEFAULT_HOST),
        port=int(data.get("port", DEFAULT_PORT)),
        path=path,
        timeout=int(data.get("timeout", DEFAULT_TIMEOUT)),
    )


def save_config(config: AppConfig) -> None:
    ensure_config_dir()
    payload = {
        "host": config.host,
        "port": config.port,
        "path": normalize_path(config.path),
        "timeout": config.timeout,
    }
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.chmod(CONFIG_PATH, 0o600)


def get_api_key() -> str:
    try:
        api_key = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except NoKeyringError as exc:
        raise MochiError(
            "No OS keyring backend is available. Install or configure a supported "
            "system keyring, then run `python3 mcp.py --setup`."
        ) from exc
    except KeyringError as exc:
        raise MochiError(f"Failed to read the Mochi API key from the OS keyring: {exc}") from exc

    if not api_key:
        raise MochiError(
            "No Mochi API key found in keyring. Run `python3 mcp.py --setup` first."
        )
    return api_key


def set_api_key(api_key: str) -> None:
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, api_key)
    except NoKeyringError as exc:
        raise MochiError(
            "No OS keyring backend is available. Install or configure a supported "
            "system keyring before running `python3 mcp.py --setup`."
        ) from exc
    except KeyringError as exc:
        raise MochiError(
            "Unable to store the Mochi API key in the OS keyring. "
            "Ensure a keyring backend is available and try again."
        ) from exc


def delete_api_key() -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except KeyringError:
        pass


class MochiClient:
    """Thin JSON client for the Mochi REST API."""

    def __init__(self, api_key: str, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.auth = (api_key, "")
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "mcp-mochi/1.0",
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{MOCHI_BASE_URL}{path}"
        with self._lock:
            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    params={k: v for k, v in (params or {}).items() if v is not None},
                    json=payload,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                raise MochiError(f"Request to Mochi failed: {exc}") from exc

        if response.status_code >= 400:
            detail = self._safe_json(response)
            raise MochiError(
                f"Mochi API error {response.status_code}: "
                f"{json.dumps(detail, ensure_ascii=True)}"
            )

        if response.status_code == 204 or not response.content:
            return {"ok": True}

        return self._safe_json(response)

    @staticmethod
    def _safe_json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    def list_decks(self, *, bookmark: str | None = None) -> Any:
        return self._request("GET", "/decks", params={"bookmark": bookmark})

    def get_deck(self, deck_id: str) -> Any:
        return self._request("GET", f"/decks/{deck_id}")

    def create_deck(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/decks", payload=payload)

    def update_deck(self, deck_id: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", f"/decks/{deck_id}", payload=payload)

    def delete_deck(self, deck_id: str) -> Any:
        return self._request("DELETE", f"/decks/{deck_id}")

    def list_cards(
        self,
        *,
        deck_id: str | None = None,
        bookmark: str | None = None,
        limit: int | None = None,
    ) -> Any:
        params = {"deck-id": deck_id, "bookmark": bookmark, "limit": limit}
        return self._request("GET", "/cards", params=params)

    def get_card(self, card_id: str) -> Any:
        return self._request("GET", f"/cards/{card_id}")

    def create_card(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/cards", payload=payload)

    def update_card(self, card_id: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", f"/cards/{card_id}", payload=payload)

    def delete_card(self, card_id: str) -> Any:
        return self._request("DELETE", f"/cards/{card_id}")

    def list_templates(
        self, *, bookmark: str | None = None
    ) -> Any:
        return self._request("GET", "/templates", params={"bookmark": bookmark})

    def get_template(self, template_id: str) -> Any:
        return self._request("GET", f"/templates/{template_id}")

    def list_due_cards(
        self,
        *,
        deck_id: str | None = None,
        bookmark: str | None = None,
        limit: int | None = None,
        date: str | None = None,
    ) -> Any:
        path = f"/due/{deck_id}" if deck_id else "/due"
        return self._request(
            "GET",
            path,
            params={"bookmark": bookmark, "limit": limit, "date": date},
        )

    def validate_key(self) -> None:
        self.list_decks()


def compact_dict(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def transform_fields(fields: dict[str, str] | dict[str, dict[str, Any]] | None) -> dict[str, Any] | None:
    if fields is None:
        return None

    transformed: dict[str, Any] = {}
    for field_id, value in fields.items():
        if isinstance(value, dict):
            field_value = value.get("value")
            transformed[field_id] = {"id": value.get("id", field_id), "value": field_value}
        else:
            transformed[field_id] = {"id": field_id, "value": value}
    return transformed


def create_server(config: AppConfig) -> FastMCP:
    client = MochiClient(get_api_key(), timeout=config.timeout)
    server = FastMCP(
        "Mochi",
        instructions="MCP server for Mochi flashcards and decks.",
        stateless_http=True,
        json_response=True,
        host=config.host,
        port=config.port,
        streamable_http_path=normalize_path(config.path),
    )

    @server.tool()
    def list_decks(bookmark: str | None = None) -> Any:
        """List Mochi decks."""
        return client.list_decks(bookmark=bookmark)

    @server.tool()
    def get_deck(deck_id: str) -> Any:
        """Get a Mochi deck by ID."""
        return client.get_deck(deck_id)

    @server.tool()
    def create_deck(
        name: str,
        parent_id: str | None = None,
        sort: int | None = None,
        archived: bool | None = None,
        trashed_at: str | None = None,
    ) -> Any:
        """Create a Mochi deck."""
        payload = compact_dict(
            {
                "name": name,
                "parent-id": parent_id,
                "sort": sort,
                "archived?": archived,
                "trashed?": trashed_at,
            }
        )
        return client.create_deck(payload)

    @server.tool()
    def update_deck(
        deck_id: str,
        name: str | None = None,
        parent_id: str | None = None,
        sort: int | None = None,
        archived: bool | None = None,
        trashed_at: str | None = None,
    ) -> Any:
        """Update a Mochi deck."""
        payload = compact_dict(
            {
                "name": name,
                "parent-id": parent_id,
                "sort": sort,
                "archived?": archived,
                "trashed?": trashed_at,
            }
        )
        return client.update_deck(deck_id, payload)

    @server.tool()
    def delete_deck(deck_id: str) -> Any:
        """Delete a Mochi deck permanently."""
        return client.delete_deck(deck_id)

    @server.tool()
    def list_cards(
        deck_id: str | None = None,
        bookmark: str | None = None,
        limit: int | None = None,
    ) -> Any:
        """List Mochi cards."""
        return client.list_cards(deck_id=deck_id, bookmark=bookmark, limit=limit)

    @server.tool()
    def get_card(card_id: str) -> Any:
        """Get a Mochi card by ID."""
        return client.get_card(card_id)

    @server.tool()
    def create_card(
        deck_id: str,
        content: str | None = None,
        template_id: str | None = None,
        archived: bool | None = None,
        review_reverse: bool | None = None,
        pos: str | None = None,
        manual_tags: list[str] | None = None,
        fields: dict[str, str] | dict[str, dict[str, Any]] | None = None,
    ) -> Any:
        """Create a Mochi card."""
        payload = compact_dict(
            {
                "deck-id": deck_id,
                "content": content,
                "template-id": template_id,
                "archived?": archived,
                "review-reverse?": review_reverse,
                "pos": pos,
                "manual-tags": manual_tags,
                "fields": transform_fields(fields),
            }
        )
        return client.create_card(payload)

    @server.tool()
    def update_card(
        card_id: str,
        content: str | None = None,
        deck_id: str | None = None,
        template_id: str | None = None,
        archived: bool | None = None,
        trashed_at: str | None = None,
        review_reverse: bool | None = None,
        pos: str | None = None,
        manual_tags: list[str] | None = None,
        fields: dict[str, str] | dict[str, dict[str, Any]] | None = None,
    ) -> Any:
        """Update a Mochi card."""
        payload = compact_dict(
            {
                "content": content,
                "deck-id": deck_id,
                "template-id": template_id,
                "archived?": archived,
                "trashed?": trashed_at,
                "review-reverse?": review_reverse,
                "pos": pos,
                "manual-tags": manual_tags,
                "fields": transform_fields(fields),
            }
        )
        return client.update_card(card_id, payload)

    @server.tool()
    def delete_card(card_id: str) -> Any:
        """Delete a Mochi card permanently."""
        return client.delete_card(card_id)

    @server.tool()
    def list_templates(bookmark: str | None = None) -> Any:
        """List Mochi templates."""
        return client.list_templates(bookmark=bookmark)

    @server.tool()
    def get_template(template_id: str) -> Any:
        """Get a Mochi template by ID."""
        return client.get_template(template_id)

    @server.tool()
    def list_due_cards(
        deck_id: str | None = None,
        bookmark: str | None = None,
        limit: int | None = None,
        date: str | None = None,
    ) -> Any:
        """List due cards."""
        return client.list_due_cards(
            deck_id=deck_id,
            bookmark=bookmark,
            limit=limit,
            date=date,
        )

    return server


def run_setup() -> int:
    print("Mochi API setup")
    api_key = getpass.getpass("Enter Mochi API key: ").strip()
    if not api_key:
        print("No API key provided.", file=sys.stderr)
        return 1

    set_api_key(api_key)

    config = load_config()
    save_config(config)

    try:
        MochiClient(api_key, timeout=config.timeout).validate_key()
    except MochiError as exc:
        delete_api_key()
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 1

    print("Stored Mochi API key in the OS keyring.")
    print(f"Server defaults saved to {CONFIG_PATH}.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mochi MCP server")
    parser.add_argument("--setup", action="store_true", help="Prompt for and store the Mochi API key.")
    parser.add_argument("--host", help=f"HTTP bind host. Default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, help=f"HTTP bind port. Default: {DEFAULT_PORT}")
    parser.add_argument("--path", help=f"HTTP MCP path. Default: {DEFAULT_PATH}")
    parser.add_argument(
        "--timeout",
        type=int,
        help=f"HTTP timeout for Mochi API requests in seconds. Default: {DEFAULT_TIMEOUT}",
    )
    return parser.parse_args()


def build_runtime_config(args: argparse.Namespace) -> AppConfig:
    config = load_config()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.path:
        config.path = normalize_path(args.path)
    if args.timeout:
        config.timeout = args.timeout
    return config


def main() -> int:
    args = parse_args()

    if args.setup:
        return run_setup()

    try:
        config = build_runtime_config(args)
        server = create_server(config)
    except MochiError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    server.run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
