import json
import urllib.request
import urllib.parse
from models import CardResult

POSTAGE_USD = 10_50  # cents USD — flat international rate

EXCLUDE_STYLES = {"G"}  # Good = heavily played equivalent; keep NM, EX, VG

def _get_aud_rate() -> float:
    """Fetch live USD→AUD exchange rate."""
    try:
        req = urllib.request.Request(
            "https://open.er-api.com/v6/latest/USD",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rate = data["rates"]["AUD"]
        print(f"  [CardKingdom] USD→AUD rate: {rate:.4f}", end=" ")
        return rate
    except Exception as e:
        fallback = 1.58
        print(f"  [CardKingdom] Rate fetch failed ({e}), using fallback {fallback}", end=" ")
        return fallback


def fetch_all(cards: list[str]) -> dict[str, CardResult]:
    """
    Bulk fetch all cards from Card Kingdom.
    Returns dict of card_name_lower -> CardResult (cheapest non-foil, excl. G condition).
    Prices are converted to AUD cents.
    """
    print(f"  [CardKingdom] Fetching {len(cards)} cards (bulk)...", end=" ", flush=True)

    aud_rate = _get_aud_rate()

    html = _fetch(cards)
    if html is None:
        return {}

    results = _parse(html, aud_rate)
    print(f"✓  ({len(results)} found)")
    return results


def _fetch(cards: list[str]) -> dict | None:
    card_data = "\r\n".join(f"1 {name}" for name in cards)
    payload = json.dumps({
        "submit": 1,
        "cardData": card_data,
        "autofill_lp": "1",
        "NM": "1",
        "EX": "1",
        "VG": "1",
        "G": "1",
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://www.cardkingdom.com/api/builder",
        data=payload,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"\n  [CardKingdom] Request failed: {e}")
        return None


def _parse(data: dict, aud_rate: float) -> dict[str, CardResult]:
    results = {}

    for card_group in data.get("results", []):
        for printing in card_group:
            # Skip foils
            if printing.get("is_shiny") or printing.get("model") == "mtg_foil":
                continue

            card_name = printing.get("core_name", "").strip()
            if not card_name:
                continue

            card_key  = card_name.lower()
            set_name  = printing.get("edition", {}).get("name", "")
            clean_slug = printing.get("clean_slug", "")
            card_url  = f"https://www.cardkingdom.com/mtg/{printing['edition']['slug']}/{clean_slug}" if clean_slug else None

            for style in printing.get("style_qty", []):
                condition = style.get("style", "")
                if condition in EXCLUDE_STYLES:
                    continue

                qty = style.get("qty") or 0
                if qty == 0:
                    continue

                try:
                    price_usd_cents = int(round(float(style["price"]) * 100))
                except (KeyError, ValueError):
                    continue

                price_aud_cents = int(round(price_usd_cents * aud_rate))

                if card_key not in results or price_aud_cents < results[card_key].price_cents:
                    results[card_key] = CardResult(
                        card_name=card_name,
                        set_name=set_name,
                        condition=_style_to_condition(condition),
                        qty=qty,
                        price_cents=price_aud_cents,
                        url=card_url,
                    )

    return results


def _style_to_condition(style: str) -> str:
    return {
        "NM": "Near Mint",
        "EX": "Lightly Played",
        "VG": "Moderately Played",
        "G":  "Heavily Played",
    }.get(style, style)


def postage_cents(aud_rate: float) -> int:
    """Postage in AUD cents at the current exchange rate."""
    return int(round(POSTAGE_USD * aud_rate))
