#!/usr/bin/env python3
"""Local CLI tool for the Mochi flashcard API.

This exposes the same operations as mcp.py without requiring an MCP client or a
running server. It is designed for local AI agents and automation tools that can
execute shell commands and consume JSON output.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
import importlib.util
import json
import os
import re
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


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


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

    review_stats = subparsers.add_parser("review-stats", help="Summarize recent review activity.")
    review_stats.add_argument("--days", type=positive_int, default=90)
    review_stats.add_argument("--deck-id")
    review_stats.add_argument("--split-by-deck", action="store_true")
    set_handler(review_stats, handle_review_stats)

    deck_stats = subparsers.add_parser("deck-stats", help="Summarize card and review counts by deck.")
    deck_stats.add_argument("--deck-id")
    set_handler(deck_stats, handle_deck_stats)

    search_cards = subparsers.add_parser("search-cards", help="Search card content, titles, tags, and fields.")
    search_cards.add_argument("--query", required=True)
    search_cards.add_argument("--deck-id")
    search_cards.add_argument("--limit", type=positive_int, default=50)
    set_handler(search_cards, handle_search_cards)

    recent_reviews = subparsers.add_parser("recent-reviews", help="List recently reviewed cards.")
    recent_reviews.add_argument("--days", type=positive_int, default=7)
    recent_reviews.add_argument("--limit", type=positive_int, default=50)
    recent_reviews.add_argument("--deck-id")
    set_handler(recent_reviews, handle_recent_reviews)

    create_simple = subparsers.add_parser("create-card-simple", help="Create a simple markdown Q/A card.")
    create_simple.add_argument("--deck-id", required=True)
    create_simple.add_argument("--front", required=True)
    create_simple.add_argument("--back", required=True)
    create_simple.add_argument("--tags", help="Comma-separated tags without leading # characters.")
    set_handler(create_simple, handle_create_card_simple)

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


def docs_from_page(page: Any, key: str = "docs") -> list[dict[str, Any]]:
    if not isinstance(page, dict):
        return []
    docs = page.get(key)
    if docs is None and key != "docs":
        docs = page.get("docs")
    if isinstance(docs, list):
        return [doc for doc in docs if isinstance(doc, dict)]
    return []


def fetch_all_cards(
    client: Any,
    *,
    deck_id: str | None = None,
    page_limit: int = 100,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    bookmark: str | None = None
    seen_bookmarks: set[str] = set()

    while True:
        page = client.list_cards(deck_id=deck_id, bookmark=bookmark, limit=page_limit)
        cards.extend(docs_from_page(page))
        next_bookmark = page.get("bookmark") if isinstance(page, dict) else None
        if not next_bookmark or next_bookmark in seen_bookmarks:
            break
        seen_bookmarks.add(next_bookmark)
        bookmark = next_bookmark

    return cards


def fetch_all_decks(client: Any) -> list[dict[str, Any]]:
    decks: list[dict[str, Any]] = []
    bookmark: str | None = None
    seen_bookmarks: set[str] = set()

    while True:
        page = client.list_decks(bookmark=bookmark)
        decks.extend(docs_from_page(page))
        next_bookmark = page.get("bookmark") if isinstance(page, dict) else None
        if not next_bookmark or next_bookmark in seen_bookmarks:
            break
        seen_bookmarks.add(next_bookmark)
        bookmark = next_bookmark

    return decks


def fetch_due_cards(
    client: Any,
    *,
    deck_id: str | None = None,
    date: str | None = None,
    page_limit: int = 100,
) -> list[dict[str, Any]]:
    due_cards: list[dict[str, Any]] = []
    bookmark: str | None = None
    seen_bookmarks: set[str] = set()

    while True:
        page = client.list_due_cards(
            deck_id=deck_id,
            bookmark=bookmark,
            limit=page_limit,
            date=date,
        )
        due_cards.extend(docs_from_page(page, key="cards"))
        next_bookmark = page.get("bookmark") if isinstance(page, dict) else None
        if not next_bookmark or next_bookmark in seen_bookmarks:
            break
        seen_bookmarks.add(next_bookmark)
        bookmark = next_bookmark

    return due_cards


def parse_mochi_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, dict):
        if "date" in value:
            return parse_mochi_datetime(value["date"])
        if "~#dt" in value:
            return datetime.fromtimestamp(value["~#dt"] / 1000, tz=timezone.utc)
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None
    if raw.startswith("~t") and raw[2:].isdigit():
        return datetime.fromtimestamp(int(raw[2:]) / 1000, tz=timezone.utc)
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone(timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def cutoff_for_days(days: int) -> datetime:
    return now_utc() - timedelta(days=days)


def calendar_cutoff_for_days(days: int) -> datetime:
    local_tz = datetime.now().astimezone().tzinfo
    # Mochi exposes review dates as midnight timestamps, not exact review times.
    # Include the previous date boundary so a same-day review logged as midnight
    # UTC on the prior date is still visible in `--days 1`.
    start_date = datetime.now(local_tz).date() - timedelta(days=days)
    local_start = datetime.combine(start_date, time.min, tzinfo=local_tz)
    return local_start.astimezone(timezone.utc)


def local_calendar_window(days: int) -> dict[str, Any]:
    local_tz = datetime.now().astimezone().tzinfo
    today = datetime.now(local_tz).date()
    start_date = today - timedelta(days=days - 1)
    local_start = datetime.combine(start_date, time.min, tzinfo=local_tz)
    local_end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=local_tz)
    api_cutoff = calendar_cutoff_for_days(days)
    return {
        "timezone": str(local_tz),
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
        "local_start": local_start.isoformat(),
        "local_end": local_end.isoformat(),
        "api_cutoff": api_cutoff.isoformat(),
        "note": "Mochi API review dates are date-level midnight timestamps; counts are grouped by local calendar day.",
    }


def review_local_date(review_date: datetime) -> str:
    local_tz = datetime.now().astimezone().tzinfo
    utc_date = review_date.astimezone(timezone.utc)
    utc_midnight = utc_date.hour == 0 and utc_date.minute == 0 and utc_date.second == 0
    local_offset = local_tz.utcoffset(review_date.astimezone(local_tz))
    if utc_midnight and local_offset is not None and local_offset > timedelta(0):
        return (utc_date.date() + timedelta(days=1)).isoformat()

    local_midnight = datetime.combine(
        review_date.astimezone(local_tz).date() + timedelta(days=1),
        time.min,
        tzinfo=local_tz,
    )
    if review_date == local_midnight.astimezone(timezone.utc):
        return local_midnight.date().isoformat()
    return review_date.astimezone(local_tz).date().isoformat()


def today_start_utc() -> datetime:
    local_tz = datetime.now().astimezone().tzinfo
    local_start = datetime.combine(datetime.now(local_tz).date(), time.min, tzinfo=local_tz)
    return local_start.astimezone(timezone.utc)


def get_tags(card: dict[str, Any]) -> list[str]:
    tags = card.get("tags") or card.get("manual-tags") or []
    if isinstance(tags, dict) and "~#set" in tags:
        tags = tags["~#set"]
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in tags]


def get_reviews(card: dict[str, Any]) -> list[dict[str, Any]]:
    reviews = card.get("reviews") or []
    if not isinstance(reviews, list):
        return []
    return [review for review in reviews if isinstance(review, dict)]


def get_fields_text(card: dict[str, Any]) -> str:
    fields = card.get("fields") or {}
    if not isinstance(fields, dict):
        return ""

    values: list[str] = []
    for field in fields.values():
        if isinstance(field, dict):
            value = field.get("value")
            if value is not None:
                values.append(str(value))
        elif field is not None:
            values.append(str(field))
    return " ".join(values)


def searchable_text(card: dict[str, Any]) -> str:
    parts = [
        str(card.get("name") or ""),
        str(card.get("content") or ""),
        " ".join(get_tags(card)),
        get_fields_text(card),
    ]
    return " ".join(part for part in parts if part)


def make_snippet(text: str, query: str | None = None, *, max_len: int = 180) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= max_len:
        return collapsed
    if query:
        match_at = collapsed.lower().find(query.lower())
        if match_at >= 0:
            start = max(0, match_at - max_len // 3)
            end = min(len(collapsed), start + max_len)
            prefix = "..." if start else ""
            suffix = "..." if end < len(collapsed) else ""
            return f"{prefix}{collapsed[start:end].strip()}{suffix}"
    return f"{collapsed[:max_len].strip()}..."


def brief_card(card: dict[str, Any], *, query: str | None = None) -> dict[str, Any]:
    reviews = sorted(
        (
            (review_date, review)
            for review in get_reviews(card)
            if (review_date := parse_mochi_datetime(review.get("date"))) is not None
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    latest_review = reviews[0][0].isoformat() if reviews else None
    latest_due = None
    if reviews:
        latest_due_dt = parse_mochi_datetime(reviews[0][1].get("due"))
        latest_due = latest_due_dt.isoformat() if latest_due_dt else None

    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "deck-id": card.get("deck-id"),
        "tags": get_tags(card),
        "last-reviewed": latest_review,
        "due": latest_due,
        "snippet": make_snippet(searchable_text(card), query),
    }


def count_review_events_since(card: dict[str, Any], cutoff: datetime) -> int:
    return sum(
        1
        for review in get_reviews(card)
        if (review_date := parse_mochi_datetime(review.get("date"))) is not None
        and review_date >= cutoff
    )


def review_events_for_cards(
    cards: list[dict[str, Any]],
    *,
    cutoff: datetime,
) -> list[tuple[datetime, dict[str, Any], dict[str, Any]]]:
    events: list[tuple[datetime, dict[str, Any], dict[str, Any]]] = []
    for card in cards:
        for review in get_reviews(card):
            review_date = parse_mochi_datetime(review.get("date"))
            if review_date is not None and review_date >= cutoff:
                events.append((review_date, card, review))
    return events


def parse_tags_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    tags = [tag.strip().lstrip("#") for tag in value.split(",")]
    return [tag for tag in tags if tag]


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


def handle_review_stats(args: argparse.Namespace) -> Any:
    client = get_client(args.timeout)
    cards = fetch_all_cards(client, deck_id=args.deck_id)
    cutoff = calendar_cutoff_for_days(args.days)
    events = review_events_for_cards(cards, cutoff=cutoff)
    unique_cards = {card.get("id") for _, card, _ in events if card.get("id")}
    by_local_date: dict[str, dict[str, Any]] = {}
    for review_date, card, _ in events:
        local_date = review_local_date(review_date)
        if local_date not in by_local_date:
            by_local_date[local_date] = {
                "date": local_date,
                "total_review_events": 0,
                "unique_cards_reviewed": 0,
                "_cards": set(),
            }
        by_local_date[local_date]["total_review_events"] += 1
        if card.get("id"):
            by_local_date[local_date]["_cards"].add(card["id"])

    for day_stats in by_local_date.values():
        day_stats["unique_cards_reviewed"] = len(day_stats.pop("_cards"))

    result: dict[str, Any] = {
        "days": args.days,
        "deck_id": args.deck_id,
        "calendar_window": local_calendar_window(args.days),
        "total_review_events": len(events),
        "unique_cards_reviewed": len(unique_cards),
        "reviews_per_day": round(len(events) / args.days, 2),
        "by_local_date": dict(sorted(by_local_date.items())),
    }

    if args.split_by_deck:
        by_deck: dict[str, dict[str, Any]] = {}
        for _, card, _ in events:
            deck_id = str(card.get("deck-id") or "")
            if deck_id not in by_deck:
                by_deck[deck_id] = {
                    "deck_id": deck_id,
                    "total_review_events": 0,
                    "unique_cards_reviewed": 0,
                    "_cards": set(),
                }
            by_deck[deck_id]["total_review_events"] += 1
            if card.get("id"):
                by_deck[deck_id]["_cards"].add(card["id"])

        for deck_stats in by_deck.values():
            deck_stats["unique_cards_reviewed"] = len(deck_stats.pop("_cards"))
            deck_stats["reviews_per_day"] = round(deck_stats["total_review_events"] / args.days, 2)
        result["by_deck"] = by_deck

    return result


def handle_deck_stats(args: argparse.Namespace) -> Any:
    client = get_client(args.timeout)
    all_decks = fetch_all_decks(client)
    deck_names = {deck.get("id"): deck.get("name") for deck in all_decks}
    cards = fetch_all_cards(client, deck_id=args.deck_id)

    if args.deck_id:
        target_decks = [args.deck_id]
    else:
        target_decks = sorted(
            {
                str(deck["id"])
                for deck in all_decks
                if deck.get("id")
            }
            | {str(card.get("deck-id")) for card in cards if card.get("deck-id")}
        )

    due_counts: dict[str, int] = defaultdict(int)
    due_cards = fetch_due_cards(client, deck_id=args.deck_id)
    for card in due_cards:
        deck_id = str(card.get("deck-id") or args.deck_id or "")
        due_counts[deck_id] += 1

    today_cutoff = today_start_utc()
    seven_day_cutoff = cutoff_for_days(7)
    thirty_day_cutoff = cutoff_for_days(30)
    cards_by_deck: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        if card.get("deck-id"):
            cards_by_deck[str(card["deck-id"])].append(card)

    stats = []
    for deck_id in target_decks:
        deck_cards = cards_by_deck.get(deck_id, [])
        stats.append(
            {
                "deck_id": deck_id,
                "deck_name": deck_names.get(deck_id),
                "total_cards": len(deck_cards),
                "new_cards": sum(1 for card in deck_cards if bool(card.get("new?"))),
                "due_cards": due_counts.get(deck_id, 0),
                "reviewed_today": sum(count_review_events_since(card, today_cutoff) for card in deck_cards),
                "reviewed_7d": sum(count_review_events_since(card, seven_day_cutoff) for card in deck_cards),
                "reviewed_30d": sum(count_review_events_since(card, thirty_day_cutoff) for card in deck_cards),
                "archived_cards": sum(1 for card in deck_cards if bool(card.get("archived?"))),
                "trashed_cards": sum(1 for card in deck_cards if bool(card.get("trashed?"))),
            }
        )

    return {
        "deck_id": args.deck_id,
        "decks": stats,
    }


def handle_search_cards(args: argparse.Namespace) -> Any:
    query = args.query.strip()
    if not query:
        raise argparse.ArgumentTypeError("--query must not be empty.")

    cards = fetch_all_cards(get_client(args.timeout), deck_id=args.deck_id)
    matches: list[dict[str, Any]] = []
    query_lower = query.lower()
    for card in cards:
        text = searchable_text(card)
        if query_lower in text.lower():
            matches.append(brief_card(card, query=query))
            if len(matches) >= args.limit:
                break

    return {
        "query": query,
        "deck_id": args.deck_id,
        "limit": args.limit,
        "count": len(matches),
        "cards": matches,
    }


def handle_recent_reviews(args: argparse.Namespace) -> Any:
    cards = fetch_all_cards(get_client(args.timeout), deck_id=args.deck_id)
    events = review_events_for_cards(cards, cutoff=calendar_cutoff_for_days(args.days))
    events.sort(key=lambda item: item[0], reverse=True)

    reviews = []
    for review_date, card, review in events[: args.limit]:
        due_date = parse_mochi_datetime(review.get("due"))
        reviews.append(
            {
                "card_id": card.get("id"),
                "name": card.get("name"),
                "deck-id": card.get("deck-id"),
                "reviewed_at": review_date.isoformat(),
                "reviewed_local_date": review_local_date(review_date),
                "remembered": review.get("remembered?"),
                "due": due_date.isoformat() if due_date else None,
                "snippet": make_snippet(searchable_text(card)),
            }
        )

    return {
        "days": args.days,
        "deck_id": args.deck_id,
        "calendar_window": local_calendar_window(args.days),
        "limit": args.limit,
        "count": len(reviews),
        "reviews": reviews,
    }


def handle_create_card_simple(args: argparse.Namespace) -> Any:
    content = f"# {args.front.strip()}\n---\n{args.back.strip()}"
    payload = compact_dict(
        {
            "deck-id": args.deck_id,
            "content": content,
            "manual-tags": parse_tags_csv(args.tags),
        }
    )
    return get_client(args.timeout).create_card(payload)


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
