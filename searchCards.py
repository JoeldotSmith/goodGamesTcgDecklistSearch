import re
import urllib.request
import urllib.parse
import sys


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

    for match in matches:
        # Extract title
        title_match = re.search(r'title:"([^"]+)"', match)
        if not title_match:
            continue
        title = title_match.group(1).replace("\\/\\/", "//")

        # Skip if title doesn't loosely match our card name
        if card_name.lower().split(",")[0].strip() not in title.lower():
            continue

        # Skip art series cards
        if "art series" in title.lower():
            continue

        # Split into individual variant blocks by splitting on {id:
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

            if qty > 0:
                if best is None or price < best[3]:
                    best = (title, qty, condition, price)

    return best, None


def main():
    decklist_file = "decklist.txt"
    cards = get_cards(decklist_file)
    not_found = []
    results = []

    for card_name in cards:
        print(f"Searching: {card_name}...", end=" ", flush=True)
        result, error = fetch_cheapest(card_name)

        if error:
            print(f"ERROR — {error}")
            not_found.append(card_name)
        elif result is None:
            print("Not found / out of stock")
            not_found.append(card_name)
        else:
            title, qty, condition, price_cents = result
            print("✓")

            set_match = re.search(r"\[([^\]]+)\]$", title)
            set_name = set_match.group(1) if set_match else ""
            clean_title = title[: set_match.start()].strip() if set_match else title

            results.append(
                (
                    clean_title,
                    set_name,
                    condition,
                    str(qty),
                    f"${price_cents / 100:.2f}",
                )
            )

    # Column headers
    headers = ("Card Title", "Set", "Condition", "Qty", "Price")

    # Work out max width for each column
    col_widths = [len(h) for h in headers]
    for row in results:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Add padding
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
    title_str = " MTG Card Price Search — Good Games "
    title_padded = title_str.center(total_width - 2)

    print()
    print("┌" + title_padded + "┐")
    print(divider("├", "┬", "┤"))
    print(format_row(headers))
    print(divider("├", "┼", "┤"))
    for row in results:
        print(format_row(row))

    print(divider("├", "┼", "┤"))

    total_cents = sum(int(r[4].replace("$", "").replace(".", "")) for r in results)
    total_row = ("", "", "", "Total", f"${total_cents / 100:.2f}")
    print(format_row(total_row))

    print(divider("└", "┴", "┘"))
    print(divider("└", "┴", "┘"))

    if not_found:
        print("\n── Cards Not Found / Out of Stock ──")
        for card in not_found:
            print(f"  ✗ {card}")


if __name__ == "__main__":
    main()
