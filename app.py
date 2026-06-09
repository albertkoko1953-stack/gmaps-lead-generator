import asyncio
import csv
import io
import json
import re
import time
from urllib.parse import urljoin, urlparse

from flask import Flask, Response, jsonify, render_template, request
from playwright.async_api import async_playwright

app = Flask(__name__)

# ─── Helpers ────────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
SOCIAL_PATTERNS = {
    "facebook":  re.compile(r"https?://(?:www\.)?facebook\.com/[^\s\"'<>]+"),
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[^\s\"'<>]+"),
    "linkedin":  re.compile(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[^\s\"'<>]+"),
    "twitter":   re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/[^\s\"'<>]+"),
    "youtube":   re.compile(r"https?://(?:www\.)?youtube\.com/[^\s\"'<>]+"),
    "tiktok":    re.compile(r"https?://(?:www\.)?tiktok\.com/@[^\s\"'<>]+"),
}

def clean_url(url: str) -> str:
    """Normalise a URL: strip trailing slashes and fragments."""
    p = urlparse(url)
    return p._replace(fragment="", query="").geturl().rstrip("/")


async def enrich_website(page, url: str) -> dict:
    """Visit a business website and extract emails + social links."""
    result = {"email": "", "socials": {k: "" for k in SOCIAL_PATTERNS}}
    try:
        await page.goto(url, timeout=15000, wait_until="domcontentloaded")
        html = await page.content()

        # emails
        emails = EMAIL_RE.findall(html)
        filtered = [e for e in emails if not e.endswith((".png", ".jpg", ".gif", ".svg"))]
        if filtered:
            result["email"] = filtered[0]

        # social links
        for platform, pattern in SOCIAL_PATTERNS.items():
            matches = pattern.findall(html)
            if matches:
                result["socials"][platform] = clean_url(matches[0])

        # Also check contact page if homepage had nothing
        if not result["email"] and not any(result["socials"].values()):
            for path in ["/contact", "/contact-us", "/about"]:
                try:
                    contact_url = urljoin(url, path)
                    await page.goto(contact_url, timeout=10000, wait_until="domcontentloaded")
                    html2 = await page.content()
                    emails2 = EMAIL_RE.findall(html2)
                    filtered2 = [e for e in emails2 if not e.endswith((".png", ".jpg", ".gif", ".svg"))]
                    if filtered2:
                        result["email"] = filtered2[0]
                        break
                except Exception:
                    continue

    except Exception as e:
        pass
    return result


# ─── Scraper ────────────────────────────────────────────────────────────────

async def scrape_google_maps(keyword: str, location: str, max_results: int = 20) -> list[dict]:
    query = f"{keyword} in {location}"
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )

        # ── Step 1: collect listing URLs ────────────────────────────────────
        search_page = await context.new_page()
        maps_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
        await search_page.goto(maps_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Scroll the sidebar to load more listings
        sidebar_sel = '[role="feed"]'
        for _ in range(6):
            try:
                await search_page.evaluate(
                    f'document.querySelector(\'{sidebar_sel}\').scrollBy(0, 1200)'
                )
                await asyncio.sleep(1.2)
            except Exception:
                break

        # Grab all listing links
        links = await search_page.eval_on_selector_all(
            'a[href*="/maps/place/"]',
            'els => [...new Set(els.map(e => e.href))]',
        )
        links = [l for l in links if "/maps/place/" in l][:max_results]
        await search_page.close()

        # ── Step 2: open each listing ────────────────────────────────────────
        enrichment_page = await context.new_page()

        for link in links:
            detail_page = await context.new_page()
            try:
                await detail_page.goto(link, wait_until="networkidle", timeout=20000)
                await asyncio.sleep(1)

                async def safe_text(selector: str, page=detail_page) -> str:
                    try:
                        el = await page.query_selector(selector)
                        return (await el.inner_text()).strip() if el else ""
                    except Exception:
                        return ""

                # Name
                name = await safe_text("h1.DUwDvf, h1.fontHeadlineLarge")

                # Rating
                rating = await safe_text('span.MW4etd[aria-hidden="true"]')

                # Review count
                reviews = await safe_text('span.UY7F9')

                # Address – look for the copy-address button aria-label
                address = ""
                addr_btn = await detail_page.query_selector('button[data-item-id="address"]')
                if addr_btn:
                    address = (await addr_btn.get_attribute("aria-label") or "").replace("Address: ", "").strip()

                # Phone
                phone = ""
                phone_btn = await detail_page.query_selector('button[data-item-id^="phone"]')
                if phone_btn:
                    phone = (await phone_btn.get_attribute("aria-label") or "").replace("Phone: ", "").strip()

                # Website
                website = ""
                web_btn = await detail_page.query_selector('a[data-item-id="authority"]')
                if web_btn:
                    website = (await web_btn.get_attribute("href") or "").strip()

                # Category
                category = await safe_text('button.DkEaL')

                record = {
                    "name": name,
                    "category": category,
                    "rating": rating,
                    "reviews": reviews,
                    "phone": phone,
                    "address": address,
                    "website": website,
                    "email": "",
                    "socials": {k: "" for k in SOCIAL_PATTERNS},
                }

                # ── Step 3: Enrich from business website ─────────────────────
                if website:
                    enriched = await enrich_website(enrichment_page, website)
                    record["email"] = enriched["email"]
                    record["socials"] = enriched["socials"]

                results.append(record)

            except Exception as e:
                pass
            finally:
                await detail_page.close()

        await enrichment_page.close()
        await browser.close()

    return results


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.get_json()
    keyword  = (data.get("keyword", "") or "").strip()
    location = (data.get("location", "") or "").strip()
    limit    = min(int(data.get("limit", 20)), 40)

    if not keyword or not location:
        return jsonify({"error": "keyword and location are required"}), 400

    try:
        results = asyncio.run(scrape_google_maps(keyword, location, limit))
        return jsonify({"results": results, "count": len(results)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download", methods=["POST"])
def download():
    data    = request.get_json()
    records = data.get("results", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Name", "Category", "Rating", "Reviews", "Phone",
        "Address", "Website", "Email",
        "Facebook", "Instagram", "LinkedIn", "Twitter/X", "YouTube", "TikTok",
    ])
    for r in records:
        s = r.get("socials", {})
        writer.writerow([
            r.get("name", ""),
            r.get("category", ""),
            r.get("rating", ""),
            r.get("reviews", ""),
            r.get("phone", ""),
            r.get("address", ""),
            r.get("website", ""),
            r.get("email", ""),
            s.get("facebook", ""),
            s.get("instagram", ""),
            s.get("linkedin", ""),
            s.get("twitter", ""),
            s.get("youtube", ""),
            s.get("tiktok", ""),
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


if __name__ == "__main__":
    import os

if __name__ == '__main__':
    # রেন্ডার সার্ভারের পোর্ট অটোমেটিক ডিটেক্ট করার জন্য
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

