# Queen Nail — Google Maps Keyword Gap Finder

Two small Python tools to find the search keywords your salon **does not**
show up for on Google Maps — so you know what to target with Google Ads.

| File | What it does |
|------|--------------|
| `google_maps_search.py` | Searches Google Maps (no API key) and returns places with name, address, rating, reviews, phone, website, coordinates. |
| `nail_keyword_gap.py` | Runs a list of nail-salon keywords for your area, reports which ones a business is **MISSING** from, and ranks them by opportunity (weak competitors = easy wins). |

---

## ⚠️ Important: run it on your own computer

Google blocks searches from cloud/data-center servers (you'll get an
`HTTP 403`). These tools only return real results from a **normal home/office
internet connection**. Run them on your laptop, not on a server.

---

## Setup (one time)

1. Install [Python 3](https://www.python.org/downloads/) (3.9+).
2. Download `google_maps_search.py` and `nail_keyword_gap.py` into the same folder.
3. Open a terminal in that folder and install the one dependency:

   ```bash
   pip install requests
   ```

---

## Run it — Queen Nail, Toledo OH

**Toledo + all surrounding towns**, full keyword list, save to CSV:

```bash
python nail_keyword_gap.py "Queen Nail" "toledo-area" --csv queen_nail.csv
```

(`toledo-area` = Toledo, Sylvania, Maumee, Perrysburg, Oregon, Holland,
Rossford, Waterville.)

**Just Toledo:**

```bash
python nail_keyword_gap.py "Queen Nail" "Toledo OH" --csv queen_nail.csv
```

**Specific towns only:**

```bash
python nail_keyword_gap.py "Queen Nail" "Toledo OH,Sylvania OH,Maumee OH" --csv queen_nail.csv
```

**Your own keyword list:**

```bash
python nail_keyword_gap.py "Queen Nail" "Toledo OH" \
    --keywords "gel nails,dip powder,pedicure near me" --csv queen_nail.csv
```

---

## Reading the results

Open `queen_nail.csv` in Excel or Google Sheets. Columns:

| Column | Meaning |
|--------|---------|
| `status` | `MISSING` = Queen Nail not in results · `FOUND` = it ranks |
| `priority` | `HIGH` / `MEDIUM` / `LOW` — how good an Ads target this is |
| `competition` | `WEAK` / `MEDIUM` / `STRONG` — how entrenched the top rivals are |
| `top_competitor_reviews` | review count of the strongest rival (the bar to beat) |
| `top_competitors` | the top rivals with their rating & review counts |

**👉 Sort by `priority` and start with the `HIGH` rows** — those are keywords
where Queen Nail isn't showing up *and* the competition is weak.

### Quick CLI options

| Option | Default | Purpose |
|--------|---------|---------|
| `--csv FILE` | – | Save results to a spreadsheet file |
| `--keywords "a,b,c"` | built-in nail list (24 terms) | Check your own keywords |
| `--limit N` | 20 | How many Maps results count as "appearing" |
| `--delay SECONDS` | 2.0 | Pause between searches (be polite to Google) |
| `--json` | off | Print raw JSON instead of a report |

---

## How "priority" is decided

| Status | Competition (top rival reviews) | Priority |
|--------|--------------------------------|----------|
| MISSING | WEAK (< 50) | **HIGH** — best opportunity |
| MISSING | MEDIUM (50–200) | MEDIUM |
| MISSING | STRONG (200+) | LOW — costly to fight |
| FOUND | – | – (already visible) |

The 50 / 200 thresholds live at the top of `nail_keyword_gap.py`
(`WEAK_MAX_REVIEWS`, `MEDIUM_MAX_REVIEWS`) if you want to adjust them.

---

## Honest limitations

- **Maps ranking ≠ Google Ads keywords.** This is a great *starting point*,
  but for real ad spend, cross-check the HIGH keywords against Google's free
  **Keyword Planner** (inside Google Ads) for actual Toledo search volumes —
  some terms barely get searched.
- These tools read Google's public page layout, which Google can change at any
  time. If results suddenly come back empty, the parser may need a small update.
- Use at low volume; scraping Google heavily can get your IP temporarily blocked.
