# MapLeads — Setup & Run Guide

## Prerequisites
- Python 3.10+
- pip

---

## 1. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows
```

## 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

## 3. Install Playwright browsers (one-time)

```bash
playwright install chromium
```

This downloads ~170 MB of Chromium — free, no API key needed.

## 4. Run the app

```bash
python app.py
```

Then open **http://localhost:5000** in your browser.

---

## Project Structure

```
leadgen/
├── app.py              ← Flask backend + Playwright scraper
├── requirements.txt
├── README.md
└── templates/
    └── index.html      ← Full frontend (Tailwind CSS)
```

---

## How it works

| Layer | What happens |
|-------|-------------|
| **Search** | Playwright opens Google Maps and scrolls the sidebar to collect listing URLs |
| **Detail scrape** | Opens each listing page, extracts Name / Phone / Address / Website / Rating |
| **Enrichment** | Visits each business website in a background tab to find Email and Social Media links |
| **CSV export** | Sends all data as a downloadable CSV with every column |

---

## Tips for best results

- Use specific keywords: "pediatric dentists" beats "dentists"
- City + State works better than just a city name (e.g. "Austin TX")
- 20 results takes ~2-3 minutes due to enrichment; 40 takes ~5 min
- If Google blocks you, add a `time.sleep(2)` between listing requests in `app.py`

---

## Legal note
This tool scrapes publicly visible data from Google Maps and business websites. Use responsibly and in accordance with Google's Terms of Service and applicable laws.
