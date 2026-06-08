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
                card_name = re.sub(r"^\d+\s+", "", line)
                cards.append(card_name)
    return cards


# ─── Good Games ───────────────────────────────────────────────────────────────

def fetch_goodgames(card_name):
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

    pattern = re.compile(
        r"Spurit\.Preorder2\.snippet\.products\['[^']+'\]\s*=\s*(\{.*?\});", re.DOTALL
    )
    matches = pattern.findall(html)

    best = None
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

            if qty > 0 and condition not in EXCLUDE_CONDITIONS:
                if best is None or price < best[3]:
                    best = (title, qty, condition, price, handle)

            if condition == "Near Mint":
                if best_nm is None or price < best_nm:
                    best_nm = price

    return (best, best_nm), None


# ─── MTGMate ──────────────────────────────────────────────────────────────────

def fetch_mtgmate(cards):
    """
    Fetch all cards in one bulk GET request to MTGMate.
    Returns:
      results   : dict  card_name_lower -> {"price": int cents, "qty": int, "set": str, "condition": str}
      not_found : set   of card_name_lower that MTGMate couldn't fill
    """
    decklist = "\n".join(f"1 {name}" for name in cards)
    params = urllib.parse.urlencode({
        "utf8": "✓",
        "decklist": decklist,
        "commit": "Build Deck"
    })
    url = f"https://www.mtgmate.com.au/cards/decklist_results?{params}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-AU,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8")
    except Exception as e:
        print(f"\n  [MTGMate] Request failed: {e}")
        return {}, set()

    results = {}
    not_found = set()

    # ── Not-found cards ────────────────────────────────────────────────────────
    # Appears under: "completely out of stock, or didn't match anything in our system"
    # Each card is a <li>CARD NAME</li> beneath that heading
# ── Not-found cards ────────────────────────────────────────────────────────
    for li in re.finditer(r'<li class="partially-in-stock">(?:\d+x\s+)?([^<]+)</li>', html):
        not_found.add(li.group(1).strip().lower())

    # ── Available cards ────────────────────────────────────────────────────────
    # Split on <th class="card-name ..."> header rows
    chunks = re.split(r'<th[^>]*class="card-name[^"]*"[^>]*>\s*([^<]+?)\s*</th>', html)
    # chunks = [preamble, card1_name, card1_html, card2_name, card2_html, ...]

    EXCLUDE = {"heavily played", "damaged", "heavily played foil", "damaged foil"}

    i = 1
    while i + 1 < len(chunks):
        card_key = chunks[i].strip().lower()
        block = chunks[i + 1]
        i += 2

        # Each printing is a <tr class="magic-card ...">...</tr>
        for row in re.finditer(r'<tr class="magic-card[^"]*">(.*?)</tr>', block, re.DOTALL):
            row_html = row.group(1)

            href_match = re.search(r'href="/cards/([^"]+)"', row_html)
            if not href_match:
                continue

            # Condition from URL slug: last colon-separated segment e.g. :lightly-played
            slug_match = re.search(r':([a-z-]+)"', row_html)
            condition = slug_match.group(1).replace("-", " ").title() if slug_match else "Unknown"

            if condition.lower() in EXCLUDE:
                continue

            set_match = re.search(r'href="/cards/[^"]+">([^<]+)</a>', row_html)
            set_name = set_match.group(1).strip() if set_match else ""

            qty_match = re.search(r'Available:\s*(\d+)', row_html)
            price_match = re.search(r'\$([0-9]+\.[0-9]+)', row_html)

            if not (qty_match and price_match):
                continue

            qty = int(qty_match.group(1))
            price_cents = int(round(float(price_match.group(1)) * 100))

            if qty == 0:
                continue

            if card_key not in results or price_cents < results[card_key]["price"]:
                results[card_key] = {
                    "price": price_cents,
                    "qty": qty,
                    "set": set_name,
                    "condition": condition,
                }

    return results, not_found


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter-price", type=float, default=None)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--filter-diff", type=float, default=None)
    args = parser.parse_args()

    decklist_file = "decklist.txt"
    cards = get_cards(decklist_file)
    not_found = []
    results = []

    # ── MTGMate bulk fetch ─────────────────────────────────────────────────────
    print(f"Fetching {len(cards)} cards from MTGMate (bulk)...", end=" ", flush=True)
    mm_results, mm_not_found = fetch_mtgmate(cards)
    print("✓")

    # ── Good Games per-card fetch + merge ─────────────────────────────────────
    print(f"Total cards: {len(cards)}")
    for card_name in cards:
        print(f"Searching GoodGames: {card_name}...", end=" ", flush=True)
        gg_result, error = fetch_goodgames(card_name)

        gg_best = gg_result[0] if gg_result else None
        if error:
            print(f"ERROR — {error}")
            gg_best = None

        mm_data = mm_results.get(card_name.lower())

        # ── Determine cheapest source ──────────────────────────────────────────
        gg_price = gg_best[3] if gg_best else None          # cents
        mm_price = mm_data["price"] if mm_data else None    # cents

        if gg_price is None and mm_price is None:
            print("Not found / out of stock")
            not_found.append(card_name)
            continue

        print("✓")

        # Pick cheapest
        if gg_price is not None and (mm_price is None or gg_price <= mm_price):
            price_cents = gg_price
            condition = gg_best[2]
            set_name_raw = gg_best[0]
            set_match = re.search(r"\[([^\]]+)\]$", set_name_raw)
            set_name = set_match.group(1) if set_match else ""
            clean_title = set_name_raw[: set_match.start()].strip() if set_match else set_name_raw
            qty = str(gg_best[1])
            handle = gg_best[4]
            source = "GG+MM" if mm_price is not None else "GG"
            gg_url = f"https://tcg.goodgames.com.au/products/{handle}" if handle else None
            best_url = gg_url
        else:
            price_cents = mm_price
            condition = mm_data["condition"]
            set_name = mm_data["set"]
            clean_title = card_name
            qty = str(mm_data["qty"])
            handle = None
            source = "GG+MM" if gg_price is not None else "MM"
            mm_slug = urllib.parse.quote(card_name.replace(" ", "_"))
            best_url = f"https://www.mtgmate.com.au/cards/{mm_slug}"

        # NM price: best across both sites (GoodGames tracks this separately)
        best_nm = gg_result[1] if gg_result else None
        nm_str = f"${best_nm / 100:.2f}" if best_nm is not None else "N/A"
        diff = (price_cents - best_nm if best_nm is not None else 0) / 100
        sign = "+" if diff >= 0 else "-"

        results.append((
            clean_title,
            set_name,
            condition,
            qty,
            f"${price_cents / 100:.2f}",
            nm_str,
            f"{sign}${abs(diff):.2f}",
            source,
            best_url,
        ))

    results.sort(key=lambda r: int(r[4].replace("$", "").replace(".", "")))

    # ── Filtering ──────────────────────────────────────────────────────────────
    main_results = results
    over_results = []

    if args.filter_price is not None:
        filter_cents = int(args.filter_price * 100)
        over_results += [r for r in main_results if int(r[4].replace("$", "").replace(".", "")) >= filter_cents]
        main_results  = [r for r in main_results if int(r[4].replace("$", "").replace(".", "")) <  filter_cents]

    if args.filter_diff is not None:
        filter_cents = int(args.filter_diff * 100)
        over_results += [r for r in main_results if int(r[6].replace("$", "").replace("+", "").replace("-", "").replace(".", "")) >= filter_cents]
        main_results  = [r for r in main_results if int(r[6].replace("$", "").replace("+", "").replace("-", "").replace(".", "")) <  filter_cents]

    # ── Table drawing ──────────────────────────────────────────────────────────
    def draw_table(title_str, rows):
        display_rows = [r[:8] for r in rows]  # strip URL
        if not display_rows:
            return

        headers = (
            "Card Title",
            "Set",
            "Condition",
            "Qty",
            "Cheapest Available",
            "Cheapest NM",
            "Diff",
            "Source",
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
        title_padded = f" {title_str + f' ({len(rows)}/{len(cards)} cards)'} ".center(total_width - 2)

        print()
        print("┌" + title_padded + "┐")
        print(divider("├", "┬", "┤"))
        print(format_row(headers))
        print(divider("├", "┼", "┤"))
        for row in display_rows:
            print(format_row(row))
        print(divider("├", "┼", "┤"))

        total_cents = sum(int(r[4].replace("$", "").replace(".", "")) for r in display_rows)
        total_nm    = sum(int(r[5].replace("$", "").replace(".", "")) for r in display_rows if r[5] != "N/A")
        total_row   = ("", "", "", "Total", f"${total_cents / 100:.2f}", f"${total_nm / 100:.2f}", "", "")
        print(format_row(total_row))
        print(divider("└", "┴", "┘"))

    draw_table("MTG Card Price Search — GoodGames + MTGMate", main_results)
    if over_results:
        draw_table("Filtered Out", over_results)

    # ── Open URLs ──────────────────────────────────────────────────────────────
    if args.open and main_results:
        print("\nOpening results in browser...")
        import subprocess, time
        for r in main_results:
            url = r[8]
            if url:
                subprocess.run(["open", url])
                time.sleep(0.3)

    # ── Not found ─────────────────────────────────────────────────────────────
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
