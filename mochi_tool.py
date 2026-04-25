#!/usr/bin/env python3
"""Local CLI tool for the Mochi flashcard API.

This exposes the same operations as mcp.py without requiring an MCP client or a
running server. It is designed for local AI agents and automation tools that can
execute shell commands and consume JSON output.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
MCP_PATH = SCRIPT_DIR / "mcp.py"
ENV_API_KEY = "MOCHI_API_KEY"
ENV_NO_VENV = "MOCHI_TOOL_NO_VENV"


def maybe_reexec_with_local_venv() -> None:
    venv_python = SCRIPT_DIR / ".venv" / "bin" / "python"
    if os.environ.get(ENV_NO_VENV) or not venv_python.exists():
        return

    venv_dir = venv_python.parent.parent.resolve()
    if Path(sys.prefix).resolve() == venv_dir:
        return

    os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])


maybe_reexec_with_local_venv()


def load_mcp_module() -> Any:
    module_name = "_mcp_mochi_server"
    spec = importlib.util.spec_from_file_location(module_name, MCP_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {MCP_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


mcp = load_mcp_module()


def get_client(timeout: int | None = None) -> Any:
    config = mcp.load_config()
    api_key = os.environ.get(ENV_API_KEY)
    if not api_key:
        api_key = mcp.get_api_key()
    return mcp.MochiClient(api_key, timeout=timeout or config.timeout)


def load_json_arg(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"Invalid JSON: {exc}") from exc


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True))


def compact_dict(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout",
        type=int,
        help="Mochi API timeout in seconds. Defaults to saved MCP config.",
    )


def set_handler(parser: argparse.ArgumentParser, handler: Any) -> None:
    parser.set_defaults(handler=handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Local JSON CLI for Mochi. Uses MOCHI_API_KEY when set, otherwise "
            "the keyring configured by `python3 mcp.py --setup`."
        )
    )
    add_common_args(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_decks = subparsers.add_parser("list-decks", help="List Mochi decks.")
    list_decks.add_argument("--bookmark")
    set_handler(list_decks, handle_list_decks)

    get_deck = subparsers.add_parser("get-deck", help="Get a Mochi deck by ID.")
    get_deck.add_argument("deck_id")
    set_handler(get_deck, handle_get_deck)

    create_deck = subparsers.add_parser("create-deck", help="Create a Mochi deck.")
    create_deck.add_argument("name")
    create_deck.add_argument("--parent-id")
    create_deck.add_argument("--sort", type=int)
    create_deck.add_argument("--archived", action=argparse.BooleanOptionalAction)
    create_deck.add_argument("--trashed-at")
    set_handler(create_deck, handle_create_deck)

    update_deck = subparsers.add_parser("update-deck", help="Update a Mochi deck.")
    update_deck.add_argument("deck_id")
    update_deck.add_argument("--name")
    update_deck.add_argument("--parent-id")
    update_deck.add_argument("--sort", type=int)
    update_deck.add_argument("--archived", action=argparse.BooleanOptionalAction)
    update_deck.add_argument("--trashed-at")
    set_handler(update_deck, handle_update_deck)

    delete_deck = subparsers.add_parser("delete-deck", help="Delete a Mochi deck permanently.")
    delete_deck.add_argument("deck_id")
    set_handler(delete_deck, handle_delete_deck)

    list_cards = subparsers.add_parser("list-cards", help="List Mochi cards.")
    list_cards.add_argument("--deck-id")
    list_cards.add_argument("--bookmark")
    list_cards.add_argument("--limit", type=int)
    set_handler(list_cards, handle_list_cards)

    get_card = subparsers.add_parser("get-card", help="Get a Mochi card by ID.")
    get_card.add_argument("card_id")
    set_handler(get_card, handle_get_card)

    create_card = subparsers.add_parser("create-card", help="Create a Mochi card.")
    create_card.add_argument("deck_id")
    create_card.add_argument("--content")
    create_card.add_argument("--template-id")
    create_card.add_argument("--archived", action=argparse.BooleanOptionalAction)
    create_card.add_argument("--review-reverse", action=argparse.BooleanOptionalAction)
    create_card.add_argument("--pos")
    create_card.add_argument("--manual-tags-json", help='JSON list, for example ["tag-a","tag-b"].')
    create_card.add_argument(
        "--fields-json",
        help=(
            "JSON object of template fields. Values may be strings or "
            'objects like {"id":"field-id","value":"text"}.'
        ),
    )
    set_handler(create_card, handle_create_card)

    update_card = subparsers.add_parser("update-card", help="Update a Mochi card.")
    update_card.add_argument("card_id")
    update_card.add_argument("--content")
    update_card.add_argument("--deck-id")
    update_card.add_argument("--template-id")
    update_card.add_argument("--archived", action=argparse.BooleanOptionalAction)
    update_card.add_argument("--trashed-at")
    update_card.add_argument("--review-reverse", action=argparse.BooleanOptionalAction)
    update_card.add_argument("--pos")
    update_card.add_argument("--manual-tags-json", help='JSON list, for example ["tag-a","tag-b"].')
    update_card.add_argument("--fields-json", help="JSON object of template fields.")
    set_handler(update_card, handle_update_card)

    delete_card = subparsers.add_parser("delete-card", help="Delete a Mochi card permanently.")
    delete_card.add_argument("card_id")
    set_handler(delete_card, handle_delete_card)

    list_templates = subparsers.add_parser("list-templates", help="List Mochi templates.")
    list_templates.add_argument("--bookmark")
    set_handler(list_templates, handle_list_templates)

    get_template = subparsers.add_parser("get-template", help="Get a Mochi template by ID.")
    get_template.add_argument("template_id")
    set_handler(get_template, handle_get_template)

    list_due = subparsers.add_parser("list-due-cards", help="List due cards.")
    list_due.add_argument("--deck-id")
    list_due.add_argument("--bookmark")
    list_due.add_argument("--limit", type=int)
    list_due.add_argument("--date", help="Due date filter accepted by Mochi, such as YYYY-MM-DD.")
    set_handler(list_due, handle_list_due_cards)

    raw = subparsers.add_parser(
        "raw-request",
        help="Call an arbitrary Mochi API path for operations not yet covered.",
    )
    raw.add_argument("method", choices=["GET", "POST", "DELETE"])
    raw.add_argument("path", help="API path, for example /cards or /decks/{deck-id}.")
    raw.add_argument("--params-json", help="JSON object for query parameters.")
    raw.add_argument("--payload-json", help="JSON object for POST bodies.")
    set_handler(raw, handle_raw_request)

    return parser


def handle_list_decks(args: argparse.Namespace) -> Any:
    return get_client(args.timeout).list_decks(bookmark=args.bookmark)


def handle_get_deck(args: argparse.Namespace) -> Any:
    return get_client(args.timeout).get_deck(args.deck_id)


def handle_create_deck(args: argparse.Namespace) -> Any:
    payload = compact_dict(
        {
            "name": args.name,
            "parent-id": args.parent_id,
            "sort": args.sort,
            "archived?": args.archived,
            "trashed?": args.trashed_at,
        }
    )
    return get_client(args.timeout).create_deck(payload)


def handle_update_deck(args: argparse.Namespace) -> Any:
    payload = compact_dict(
        {
            "name": args.name,
            "parent-id": args.parent_id,
            "sort": args.sort,
            "archived?": args.archived,
            "trashed?": args.trashed_at,
        }
    )
    return get_client(args.timeout).update_deck(args.deck_id, payload)


def handle_delete_deck(args: argparse.Namespace) -> Any:
    return get_client(args.timeout).delete_deck(args.deck_id)


def handle_list_cards(args: argparse.Namespace) -> Any:
    return get_client(args.timeout).list_cards(
        deck_id=args.deck_id,
        bookmark=args.bookmark,
        limit=args.limit,
    )


def handle_get_card(args: argparse.Namespace) -> Any:
    return get_client(args.timeout).get_card(args.card_id)


def handle_create_card(args: argparse.Namespace) -> Any:
    manual_tags = load_json_arg(args.manual_tags_json, None)
    fields = load_json_arg(args.fields_json, None)
    payload = compact_dict(
        {
            "deck-id": args.deck_id,
            "content": args.content,
            "template-id": args.template_id,
            "archived?": args.archived,
            "review-reverse?": args.review_reverse,
            "pos": args.pos,
            "manual-tags": manual_tags,
            "fields": mcp.transform_fields(fields),
        }
    )
    return get_client(args.timeout).create_card(payload)


def handle_update_card(args: argparse.Namespace) -> Any:
    manual_tags = load_json_arg(args.manual_tags_json, None)
    fields = load_json_arg(args.fields_json, None)
    payload = compact_dict(
        {
            "content": args.content,
            "deck-id": args.deck_id,
            "template-id": args.template_id,
            "archived?": args.archived,
            "trashed?": args.trashed_at,
            "review-reverse?": args.review_reverse,
            "pos": args.pos,
            "manual-tags": manual_tags,
            "fields": mcp.transform_fields(fields),
        }
    )
    return get_client(args.timeout).update_card(args.card_id, payload)


def handle_delete_card(args: argparse.Namespace) -> Any:
    return get_client(args.timeout).delete_card(args.card_id)


def handle_list_templates(args: argparse.Namespace) -> Any:
    return get_client(args.timeout).list_templates(bookmark=args.bookmark)


def handle_get_template(args: argparse.Namespace) -> Any:
    return get_client(args.timeout).get_template(args.template_id)


def handle_list_due_cards(args: argparse.Namespace) -> Any:
    return get_client(args.timeout).list_due_cards(
        deck_id=args.deck_id,
        bookmark=args.bookmark,
        limit=args.limit,
        date=args.date,
    )


def handle_raw_request(args: argparse.Namespace) -> Any:
    params = load_json_arg(args.params_json, None)
    payload = load_json_arg(args.payload_json, None)
    if params is not None and not isinstance(params, dict):
        raise argparse.ArgumentTypeError("--params-json must decode to a JSON object.")
    if payload is not None and not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("--payload-json must decode to a JSON object.")

    path = args.path if args.path.startswith("/") else f"/{args.path}"
    return get_client(args.timeout)._request(args.method, path, params=params, payload=payload)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        print_json(args.handler(args))
    except (argparse.ArgumentTypeError, mcp.MochiError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
