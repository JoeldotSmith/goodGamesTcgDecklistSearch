import re
import argparse
import urllib.parse
import subprocess
import time
from itertools import combinations

from models import CardResult
import cardkingdom
import goodgames
import mtgmate
   # cents
POSTAGE = {
    "goodgames": 6_50,
    "mtgmate":   6_00,
    "cardkingdom": 15_00,
}

def optimise_order(
    cards: list[str],
    vendor_results: dict[str, dict[str, CardResult]],
    excluded_cards: set[str],
) -> None:
    vendor_names = list(vendor_results.keys())
    active_cards = [c for c in cards if c.lower() not in excluded_cards]
    sourceable = {
        c for c in active_cards
        if any(c.lower() in vendor_results[v] for v in vendor_names)
    }

    best_solution = None  # tuple: (coverage, total_cost, config)

    for r in range(1, len(vendor_names) + 1):
        for vendor_subset in combinations(vendor_names, r):
            config = {}
            for card in sourceable:
                key = card.lower()
                cheapest_vendor = None
                cheapest_price  = None
                for v in vendor_subset:
                    result = vendor_results[v].get(key)
                    if result is not None:
                        if cheapest_price is None or result.price_cents < cheapest_price:
                            cheapest_price  = result.price_cents
                            cheapest_vendor = v
                if cheapest_vendor:
                    config[key] = cheapest_vendor

            vendors_used  = set(config.values())
            card_total    = sum(vendor_results[v][k].price_cents for k, v in config.items())
            postage_total = sum(POSTAGE[v] for v in vendors_used)
            total         = card_total + postage_total
            coverage      = len(config)

            # Prefer more cards first, then lower cost
            if best_solution is None or (coverage, -total) > (best_solution[0], -best_solution[1]):
                best_solution = (coverage, total, config)

    if not best_solution:
        print("\nNo cards could be sourced from any vendor.")
        return

    _, best_cost, best_config = best_solution

    # --- rest of your printing logic unchanged ---
    vendor_cards: dict[str, list[str]] = {v: [] for v in vendor_names}
    for card_lower, vendor in best_config.items():
        vendor_cards[vendor].append(card_lower)

    unsourceable = [c for c in active_cards if c.lower() not in best_config]

    print("\n" + "═" * 60)
    print(f"  OPTIMAL ORDER  —  total incl. postage: ${best_cost / 100:.2f}")
    print("═" * 60)
    for vendor in vendor_names:
        card_list = vendor_cards[vendor]
        if not card_list:
            continue
        results     = vendor_results[vendor]
        postage     = POSTAGE[vendor]
        cards_cost  = sum(results[k].price_cents for k in card_list)
        order_total = cards_cost + postage
        rows = []
        for card_lower in sorted(card_list, key=lambda k: results[k].price_cents):
            r = results[card_lower]
            rows.append((r.card_name, r.set_name, r.condition, str(r.qty), f"${r.price_cents / 100:.2f}"))
        _draw_order_table(
            title=f"Order from {vendor.title()}",
            rows=rows,
            postage=postage,
            cards_total=cards_cost,
            order_total=order_total,
        )
    if unsourceable:
        print(f"\n── Still unavailable ({len(unsourceable)}/{len(cards)}) ──")
        for c in unsourceable:
            print(f"  1 {c}")


def _draw_order_table(
    title: str,
    rows: list[tuple],
    postage: int,
    cards_total: int,
    order_total: int,
) -> None:
    headers = ("Card Title", "Set", "Condition", "Qty", "Price")
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))
    col_widths = [w + 2 for w in col_widths]

    def format_row(row):
        return (
            "│ "
            + " │ ".join(
                cell.ljust(col_widths[i]) if i < len(row) - 1 else cell.rjust(col_widths[i])
                for i, cell in enumerate(row)
            )
            + " │"
        )

    def divider(left, mid, right):
        return left + mid.join("─" * (w + 2) for w in col_widths) + right

    total_width = sum(col_widths) + 3 * len(col_widths) + 1
    title_padded = f" {title} ({len(rows)} cards) ".center(total_width - 2)

    print()
    print("┌" + title_padded + "┐")
    print(divider("├", "┬", "┤"))
    print(format_row(headers))
    print(divider("├", "┼", "┤"))
    for row in rows:
        print(format_row(row))
    print(divider("├", "┼", "┤"))
    print(format_row(("", "", "", "Cards",   f"${cards_total / 100:.2f}")))
    print(format_row(("", "", "", "Post", f"${postage / 100:.2f}")))
    print(divider("├", "┼", "┤"))
    print(format_row(("", "", "", "Total",   f"${order_total / 100:.2f}")))
    print(divider("└", "┴", "┘"))

def get_cards(decklist_file: str) -> list[str]:
    cards = []
    with open(decklist_file, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                card_name = re.sub(r"^\d+\s+", "", line)
                cards.append(card_name)
    return cards


def merge(
    cards: list[str],
    vendor_results: dict[str, dict[str, CardResult]],
    gg_nm: dict[str, int],
) -> tuple[list[dict], list[str]]:
    """
    For each card pick the cheapest source across all vendors.
    vendor_results: dict of vendor_name -> {card_key -> CardResult}
    """
    rows = []
    not_found = []

    for card_name in cards:
        key = card_name.lower()

        # Find cheapest vendor for this card
        best_result = None
        best_vendor = None
        available_vendors = []

        for vendor_name, results in vendor_results.items():
            r = results.get(key)
            if r is not None:
                available_vendors.append(vendor_name)
                if best_result is None or r.price_cents < best_result.price_cents:
                    best_result = r
                    best_vendor = vendor_name

        if best_result is None:
            not_found.append(card_name)
            continue

        # Source label — show all vendors that have it, highlight the chosen one
        others = [v for v in available_vendors if v != best_vendor]
        source = best_vendor + (f" (+{len(others)})" if others else "")

        nm_cents = gg_nm.get(key)
        nm_str = f"${nm_cents / 100:.2f}" if nm_cents is not None else "N/A"
        diff = (best_result.price_cents - nm_cents) / 100 if nm_cents is not None else 0
        sign = "+" if diff >= 0 else "-"

        rows.append({
            "title":     best_result.card_name,
            "set":       best_result.set_name,
            "condition": best_result.condition,
            "qty":       str(best_result.qty),
            "price":     best_result.price_cents,
            "price_str": f"${best_result.price_cents / 100:.2f}",
            "nm_str":    nm_str,
            "diff_str":  f"{sign}${abs(diff):.2f}",
            "source":    source,
            "url":       best_result.url,
        })

    rows.sort(key=lambda r: r["price"])
    return rows, not_found


def apply_filters(
    rows: list[dict],
    filter_price: float | None,
    filter_diff: float | None,
) -> tuple[list[dict], list[dict]]:
    main_rows = rows
    over_rows = []

    if filter_price is not None:
        threshold = int(filter_price * 100)
        over_rows  += [r for r in main_rows if r["price"] >= threshold]
        main_rows   = [r for r in main_rows if r["price"] <  threshold]

    if filter_diff is not None:
        threshold = int(filter_diff * 100)
        over_rows  += [r for r in main_rows if _diff_cents(r["diff_str"]) >= threshold]
        main_rows   = [r for r in main_rows if _diff_cents(r["diff_str"]) <  threshold]

    return main_rows, over_rows


def _diff_cents(diff_str: str) -> int:
    return int(diff_str.replace("+", "").replace("-", "").replace("$", "").replace(".", ""))


def draw_table(title_str: str, rows: list[dict], total_cards: int) -> None:
    if not rows:
        return

    headers = ("Card Title", "Set", "Condition", "Qty", "Cheapest Available", "Cheapest NM", "Diff", "Source")
    display = [
        (r["title"], r["set"], r["condition"], r["qty"], r["price_str"], r["nm_str"], r["diff_str"], r["source"])
        for r in rows
    ]

    col_widths = [len(h) for h in headers]
    for row in display:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))
    col_widths = [w + 2 for w in col_widths]

    def format_row(row):
        return (
            "│ "
            + " │ ".join(
                cell.ljust(col_widths[i]) if i < len(row) - 1 else cell.rjust(col_widths[i])
                for i, cell in enumerate(row)
            )
            + " │"
        )

    def divider(left, mid, right):
        return left + mid.join("─" * (w + 2) for w in col_widths) + right

    total_width = sum(col_widths) + 3 * len(col_widths) + 1
    title_padded = f" {title_str} ({len(rows)}/{total_cards} cards) ".center(total_width - 2)

    print()
    print("┌" + title_padded + "┐")
    print(divider("├", "┬", "┤"))
    print(format_row(headers))
    print(divider("├", "┼", "┤"))
    for row in display:
        print(format_row(row))
    print(divider("├", "┼", "┤"))

    total_price = sum(r["price"] for r in rows)
    total_nm = sum(
        int(r["nm_str"].replace("$", "").replace(".", ""))
        for r in rows if r["nm_str"] != "N/A"
    )
    total_row = ("", "", "", "Total", f"${total_price / 100:.2f}", f"${total_nm / 100:.2f}", "", "")
    print(format_row(total_row))
    print(divider("└", "┴", "┘"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter-price", type=float, default=None)
    parser.add_argument("--filter-diff",  type=float, default=None)
    parser.add_argument("--open", action="store_true")
    parser.add_argument(
        "--ignore-vendor",
        nargs="+",
        choices=["ck", "gg", "mm"],
        default=[],
        metavar="VENDOR",
        help="Vendors to ignore: ck, gg, mm",
    )
    args = parser.parse_args()

    cards = get_cards("decklist.txt")
    print(f"Total cards: {len(cards)}\n")

    ck_results = cardkingdom.fetch_all(cards) if "ck" not in args.ignore_vendor else {}
    print()
    gg_results, gg_nm = goodgames.fetch_all(cards) if "gg" not in args.ignore_vendor else ({}, {})
    print()
    mm_results = mtgmate.fetch_all(cards) if "mm" not in args.ignore_vendor else {}

    VENDOR_ALIASES = {"gg": "goodgames", "mm": "mtgmate", "ck": "cardkingdom"}

    ignored = {VENDOR_ALIASES[v] for v in args.ignore_vendor}

    vendor_results = {
        "goodgames":   gg_results,
        "mtgmate":     mm_results,
        "cardkingdom": ck_results,
    }
    vendor_results = {k: v for k, v in vendor_results.items() if k not in ignored}

    rows, not_found = merge(cards, vendor_results, gg_nm)
    main_rows, over_rows = apply_filters(rows, args.filter_price, args.filter_diff)

    draw_table("MTG Card Price Search — GoodGames + MTGMate", main_rows, len(cards))
    if over_rows:
        draw_table("Filtered Out", over_rows, len(cards))

    if args.open and main_rows:
        print("\nOpening results in browser...")
        for r in main_rows:
            if r["url"]:
                subprocess.run(["open", r["url"]])
                time.sleep(0.3)

    if not_found:
        print(f"\n── Not Found / Out of Stock [{len(not_found)}/{len(cards)}] ──")
        for card in not_found:
            print(f"  1 {card}")

    excluded = set(r.lower() for r in not_found)
    if args.filter_price is not None or args.filter_diff is not None:
        excluded |= {r["title"].lower() for r in over_rows}

    optimise_order(cards, vendor_results, excluded)


if __name__ == "__main__":
    main()
