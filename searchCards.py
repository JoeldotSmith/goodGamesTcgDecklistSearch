import re
import urllib.request
import urllib.parse
import sys
import argparse


def get_cards(decklist_file):
    cards = []
    with open(decklist_file, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                # Strip leading quantity number
                card_name = re.sub(r"^\d+\s+", "", line)
                cards.append(card_name)
    return cards


def fetch_cheapest(card_name):
    encoded = urllib.parse.quote(card_name.replace(",", ""))
    url = (
        f"https://tcg.goodgames.com.au/search?q={encoded}"
        "&f_Availability=Exclude%20Out%20Of%20Stock"
        "&f_Product%20Type=mtg%20single"
    )

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8")
    except Exception as e:
        return None, f"Request failed: {e}"

    # Extract all product snippet blocks
    pattern = re.compile(
        r"Spurit\.Preorder2\.snippet\.products\['[^']+'\]\s*=\s*(\{.*?\});", re.DOTALL
    )
    matches = pattern.findall(html)

    best = None  # (title, quantity, condition, price_cents)

    best_nm = None
    EXCLUDE_CONDITIONS = {
        "Heavily Played",
        "Damaged",
        "Heavily Played Foil",
        "Damaged Foil",
    }

    for match in matches:
        handle_match = re.search(r'handle:"([^"]+)"', match)
        handle = handle_match.group(1) if handle_match else None

        title_match = re.search(r'title:"([^"]+)"', match)
        if not title_match:
            continue
        title = title_match.group(1).replace("\\/\\/", "//")

        if card_name.lower().split(",")[0].strip() not in title.lower():
            continue
        if "art series" in title.lower():
            continue

        variant_blocks = re.split(r"(?=\{id:\d+,title:)", match)
        for block in variant_blocks:
            cond_match = re.search(r'title:"([^"]+)"', block)
            qty_match = re.search(r"inventory_quantity:(\d+)", block)
            price_match = re.search(r",price:(\d+),", block)

            if not (cond_match and qty_match and price_match):
                continue

            condition = cond_match.group(1)
            qty = int(qty_match.group(1))
            price = int(price_match.group(1))

            # Cheapest in-stock, excluding bad conditions
            if qty > 0 and condition not in EXCLUDE_CONDITIONS:
                if best is None or price < best[3]:
                    best = (title, qty, condition, price, handle)

            # Cheapest NM regardless of stock
            if condition == "Near Mint":
                if best_nm is None or price < best_nm:
                    best_nm = price

    return (best, best_nm), None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--filter-price",
        type=float,
        default=None,
        help="Only show cards cheaper than this price in the main table",
    )
    parser.add_argument(
        "--open", action="store_true", help="Open each result in the browser"
    )
    args = parser.parse_args()

    decklist_file = "decklist.txt"
    cards = get_cards(decklist_file)
    not_found = []
    results = []  # now stores (title, set, condition, qty, price, handle)

    print("Total cards:", len(cards))
    for card_name in cards:
        print(f"Searching: {card_name}...", end=" ", flush=True)
        result, error = fetch_cheapest(card_name)

        if error:
            print(f"ERROR — {error}")
            not_found.append(card_name)
        elif result[0] is None:
            print("Not found / out of stock")
            not_found.append(card_name)
        else:
            (title, qty, condition, price_cents, handle), best_nm = result
            print("✓")

            set_match = re.search(r"\[([^\]]+)\]$", title)
            set_name = set_match.group(1) if set_match else ""
            clean_title = title[: set_match.start()].strip() if set_match else title

            nm_str = f"${best_nm / 100:.2f}" if best_nm is not None else "N/A"

            results.append(
                (
                    clean_title,
                    set_name,
                    condition,
                    str(qty),
                    f"${price_cents / 100:.2f}",
                    nm_str,
                    f"+${(price_cents - best_nm if best_nm is not None else 0) / 100:.2f}",
                    handle,
                )
            )

    results.sort(key=lambda r: int(r[4].replace("$", "").replace(".", "")))

    if args.filter_price is not None:
        filter_cents = int(args.filter_price * 100)
        main_results = [
            r
            for r in results
            if int(r[4].replace("$", "").replace(".", "")) < filter_cents
        ]
        over_results = [
            r
            for r in results
            if int(r[4].replace("$", "").replace(".", "")) >= filter_cents
        ]
    else:
        main_results = results
        over_results = []

    # draw_table only uses first 5 cols, handle is index 5
    def draw_table(title_str, rows):
        display_rows = [r[:7] for r in rows]  # strip handle for display
        if not display_rows:
            return

        headers = (
            "Card Title",
            "Set",
            "Condition",
            "Qty",
            "Cheapest Available",
            "Cheapest Regardless",
            "Diff",
        )
        col_widths = [len(h) for h in headers]
        for row in display_rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(cell))
        col_widths = [w + 2 for w in col_widths]

        def format_row(row):
            return (
                "│ "
                + " │ ".join(
                    cell.ljust(col_widths[i])
                    if i < len(row) - 1
                    else cell.rjust(col_widths[i])
                    for i, cell in enumerate(row)
                )
                + " │"
            )

        def divider(left, mid, right):
            return left + mid.join("─" * (w + 2) for w in col_widths) + right

        total_width = sum(col_widths) + 3 * len(col_widths) + 1
        title_padded = f" {title_str + f' ({len(rows)}/{len(cards)} cards)'} ".center(
            total_width - 2
        )

        print()
        print("┌" + title_padded + "┐")
        print(divider("├", "┬", "┤"))
        print(format_row(headers))
        print(divider("├", "┼", "┤"))
        for row in display_rows:
            print(format_row(row))
        print(divider("├", "┼", "┤"))

        total_cents = sum(
            int(r[4].replace("$", "").replace(".", "")) for r in display_rows
        )
        total_cents_regardless = sum(
            int(r[5].replace("$", "").replace(".", "")) for r in display_rows
        )
        total_row = (
            "",
            "",
            "",
            "Total",
            f"${total_cents / 100:.2f}",
            f"${total_cents_regardless / 100:.2f}",
        )
        print(format_row(total_row))
        print(divider("└", "┴", "┘"))

    draw_table("MTG Card Price Search — Good Games", main_results)

    if over_results:
        draw_table(f"Filtered Out (≥ ${args.filter_price:.2f})", over_results)

    # Open URLs for main results only
    if args.open and main_results:
        print("\nOpening results in browser...")
        import subprocess, time

        for r in main_results:
            handle = r[7]
            if handle:
                url = f"https://tcg.goodgames.com.au/products/{handle}"
                subprocess.run(["open", url])  # macOS — use 'xdg-open' on Linux
                time.sleep(0.3)

    if not_found:
        print(
            "\n── Cards Not Found / Out of Stock ["
            + str(len(not_found))
            + "/"
            + str(len(cards))
            + "] ──"
        )
        for card in not_found:
            print(f"1 {card}")


if __name__ == "__main__":
    main()
