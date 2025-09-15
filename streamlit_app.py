# streamlit_app.py
import os
import re
import json
import time
import requests
import pandas as pd
import tldextract
from bs4 import BeautifulSoup
import streamlit as st

# Optional Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

# ---------- Constants & Config ----------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126 Safari/537.36"
    )
}

# Load keys from env or Streamlit secrets; can be overridden via UI expander
SERPAPI_KEY = os.getenv("SERPAPI_KEY") or st.secrets.get("SERPAPI_KEY", "")
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY") or st.secrets.get("HUNTER_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", "")

# ---------- UI ----------
st.set_page_config(page_title="Outreach Automator", layout="wide")
st.title("Outreach Automator")
st.caption("Find niche sites, assess publishability, scrape emails, de-dupe, and export to Excel/Sheets.")

cols = st.columns(4)
with cols[0]:
    niches_text = st.text_area(
        "Niche(s)",
        placeholder="e.g. camping, hiking gear, solar energy",
        height=100
    )
with cols[1]:
    per_niche = st.number_input("Websites per niche", min_value=1, max_value=200, value=30, step=5)
with cols[2]:
    search_depth = st.selectbox(
        "Search strategy",
        ["Balanced", "Aggressive (more variants)", "Lean (faster)"]
    )
with cols[3]:
    tld_choices = [".any", ".com", ".lv", ".lt", ".ee", ".gr", ".de", ".fr", ".co.uk", ".net", ".org"]
    allowed_tlds = st.multiselect(
        "Allowed domain TLDs (country/zone filter)",
        tld_choices,
        default=[".any"]
    )

with st.expander("API keys (optional fallback)"):
    serpapi_key_ui = st.text_input("SerpAPI API key", value=SERPAPI_KEY, type="password")
    hunter_key_ui = st.text_input("Hunter.io API key", value=HUNTER_API_KEY, type="password")
    open_ai_ui = st.text_input("Open AI key API key", value=OPENAI_API_KEY, type="password")
    if serpapi_key_ui:
        SERPAPI_KEY = serpapi_key_ui.strip()
    if hunter_key_ui:
        HUNTER_API_KEY = hunter_key_ui.strip()
    if open_ai_ui:
        OPENAI_API_KEY =  open_ai_ui.strip()

debug = st.checkbox("Show debug details", value=False)

st.markdown("---")
st.subheader("Data source for de-dupe & saving")
mode = st.radio("Choose storage", ["Excel (.xlsx)", "Google Sheet"], horizontal=True)

existing_df = pd.DataFrame(
    columns=["domain", "root_domain", "niche", "url_found", "email", "score", "signals", "notes", "timestamp"]
)
excel_file = None
sheet = None

if mode == "Excel (.xlsx)":
    excel_file = st.file_uploader(
        "Upload your existing Excel (optional) – will also be used for saving",
        type=["xlsx"]
    )
    if excel_file:
        try:
            existing_df = pd.read_excel(excel_file)
        except Exception:
            st.warning("Couldn't read the uploaded Excel. We'll create a new one on export.")
else:
    st.info("For Google Sheets, provide a Sheet URL and upload a Service Account JSON.")
    gsheet_url = st.text_input("Google Sheet URL (the tab will be 'Prospects' or created if missing)")
    gsa_file = st.file_uploader("Service Account JSON (upload)", type=["json"])
    if gsheet_url and gsa_file and gspread is not None:
        try:
            creds_info = json.load(gsa_file)
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
            gc = gspread.authorize(creds)
            sh = gc.open_by_url(gsheet_url)
            try:
                sheet = sh.worksheet("Prospects")
            except Exception:
                sheet = sh.add_worksheet(title="Prospects", rows=1000, cols=12)
            data = sheet.get_all_records()
            if data:
                existing_df = pd.DataFrame(data)
        except Exception as e:
            st.error(f"Google Sheets error: {e}")

# ---------- Utilities ----------
def root_domain(url_or_domain: str) -> str:
    ext = tldextract.extract(url_or_domain)
    if not ext.domain:
        return url_or_domain.lower().strip()
    root = f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain
    return root.lower()

SIGNAL_KEYWORDS = [
    "write for us",
    "guest post",
    "contribute",
    "submit article",
    "editorial guidelines",
    "sponsored post",
    "advertise",
    "press@",
    "editor@",
]

CONTACT_HINTS = [
    "contact", "contacts", "about", "team", "advertise",
    "write-for-us", "guest-post", "contributors"
]

SEARCH_TEMPLATES_BALANCED = [
    "{niche} blogs",
    "best {niche} websites",
    "{niche} magazine",
    "{niche} write for us",
    "{niche} guest post",
]

SEARCH_TEMPLATES_AGGR = SEARCH_TEMPLATES_BALANCED + [
    "{niche} submit article",
    "{niche} contribute",
    "top {niche} blogs",
    "{niche} site:medium.com",
]

SEARCH_TEMPLATES_LEAN = ["{niche} blogs", "{niche} magazine"]

def tld_matches(domain: str, allowed) -> bool:
    """Return True if domain's public suffix matches allowed list. '.any' accepts everything."""
    if not allowed or ".any" in allowed:
        return True
    ext = tldextract.extract(domain)
    suffix = (ext.suffix or "").lower()  # e.g., 'lv', 'co.uk'
    normalized_allowed = [t.strip(".").lower() for t in allowed]
    return suffix in normalized_allowed

def tld_to_serpapi_settings(tld: str):
    """Map a selected TLD to SerpAPI google_domain / gl / hl settings."""
    if not tld or tld == ".any":
        return {"google_domain": "google.com", "gl": None, "hl": None}
    t = tld.strip(".").lower()
    mapping = {
        "lv": ("google.lv", "lv", "lv"),
        "gr": ("google.gr", "gr", "el"),
        "lt": ("google.lt", "lt", "lt"),
        "ee": ("google.ee", "ee", "et"),
        "de": ("google.de", "de", "de"),
        "fr": ("google.fr", "fr", "fr"),
        "co.uk": ("google.co.uk", "gb", "en"),
        "com": ("google.com", "us", "en"),
        "net": ("google.com", "us", "en"),
        "org": ("google.com", "us", "en"),
    }
    gd, gl, hl = mapping.get(t, ("google.com", None, None))
    return {"google_domain": gd, "gl": gl, "hl": hl}

def serpapi_search(query, num=10, google_domain=None, gl=None, hl=None):
    if not SERPAPI_KEY:
        return []
    url = "https://serpapi.com/search.json"
    params = {"engine": "google", "q": query, "num": int(num), "api_key": SERPAPI_KEY}
    if google_domain:
        params["google_domain"] = google_domain
    if gl:
        params["gl"] = gl
    if hl:
        params["hl"] = hl
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            if debug:
                st.warning(f"SerpAPI error for '{query}': {data.get('error')}")
            return []
        results = []
        for item in data.get("organic_results", []) or []:
            link = item.get("link")
            if link:
                results.append(link)
        return results[:num]
    except Exception as e:
        if debug:
            st.warning(f"SerpAPI request failed for '{query}': {e}")
        return []

def fetch(url, timeout=25):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        return None
    return None

def discover_contact_pages(home_url):
    pages = set([home_url])
    html = fetch(home_url)
    if not html:
        return list(pages)
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = (a.get_text() or "").lower()
        candidates = CONTACT_HINTS + [k.replace(" ", "-") for k in CONTACT_HINTS]
        if any(hint in href.lower() or hint in text for hint in candidates):
            if href.startswith("http"):
                pages.add(href)
            else:
                base = home_url.rstrip("/")
                if href.startswith("/"):
                    pages.add(base + href)
    return list(pages)[:8]

def extract_emails(text: str):
    if not text:
        return []
    return list(set(EMAIL_RE.findall(text)))

def hunter_enrich(domain: str):
    if not HUNTER_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 10},
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            emails = [e.get("value") for e in data.get("data", {}).get("emails", []) if e.get("value")]
            return list(set(emails))
    except Exception:
        pass
    return []

def score_publishability(text: str):
    if not text:
        return 0.0, []
    lower = text.lower()
    signals_found = [kw for kw in SIGNAL_KEYWORDS if kw in lower]
    base = 0
    if "guest post" in lower or "write for us" in lower:
        base += 40
    if "submit" in lower or "contribute" in lower:
        base += 20
    if "sponsored" in lower or "advertise" in lower:
        base += 10
    base += min(30, 5 * len(signals_found))
    score = min(100, base)
    return float(score), signals_found

def analyze_site(url: str):
    rd = root_domain(url)
    home = f"https://{rd}/"
    pages = discover_contact_pages(home)

    all_text = ""
    for p in pages:
        html = fetch(p)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            txt = soup.get_text(" ", strip=True)
            all_text += "\n" + txt

    score, signals = score_publishability(all_text)
    emails = extract_emails(all_text) or hunter_enrich(rd)

    return {
        "domain": rd,
        "root_domain": rd,
        "url_found": home,
        "email": ", ".join(emails) if emails else "",
        "score": score,
        "signals": ", ".join(signals) if signals else "",
        "notes": "",
    }

def is_dup(df: pd.DataFrame, rd: str) -> bool:
    if df is None or df.empty:
        return False
    cols = [c.lower() for c in df.columns]
    if "root_domain" in cols:
        return rd in set(df[df.columns[cols.index("root_domain")]].astype(str).str.lower())
    if "domain" in cols:
        return rd in set(df[df.columns[cols.index("domain")]].astype(str).str.lower())
    return rd in set(df.astype(str).stack().str.lower().values)

# ---------- Main Action ----------
start = st.button("Run Prospecting")

if start:
    if not SERPAPI_KEY:
        st.error("Please set SERPAPI_KEY (env, secrets, or in the UI fallback).")
        st.stop()

    niches = (
        [n.strip() for n in niches_text.split(",") if n.strip()]
        if "," in niches_text else
        [n.strip() for n in niches_text.split("\n") if n.strip()]
    )
    if not niches:
        st.warning("Please enter at least one niche.")
        st.stop()

    strategy = SEARCH_TEMPLATES_BALANCED
    if search_depth.startswith("Aggressive"):
        strategy = SEARCH_TEMPLATES_AGGR
    elif search_depth.startswith("Lean"):
        strategy = SEARCH_TEMPLATES_LEAN

    candidates = []
    seen_roots = set()

    progress = st.progress(0)
    total_loops = max(1, len(niches))

    # choose which TLDs to actively search via SerpAPI
    tlds_to_use = [t for t in allowed_tlds if t != ".any"] or [".any"]

    for idx, niche in enumerate(niches, start=1):
        if debug:
            st.write(f"Searching niche: **{niche}** …")
        per_template = max(10, min(50, int(per_niche * 1.4 / max(1, len(strategy)))))
        urls = []
        for tmpl in strategy:
            base_q = tmpl.format(niche=niche)
            for tld in tlds_to_use:
                settings = tld_to_serpapi_settings(tld)
                found = serpapi_search(base_q, num=per_template, **settings)
                if debug:
                    st.write(f"Query: '{base_q}' [{settings}] → {len(found)} urls")
                urls += found
            time.sleep(0.8)

        # Normalize & de-dupe by root domain + TLD filter
        added = 0
        for u in urls:
            rd = root_domain(u)
            if not rd or rd in seen_roots:
                continue
            if not tld_matches(rd, allowed_tlds):
                continue
            seen_roots.add(rd)
            candidates.append({"niche": niche, "root_domain": rd, "source_url": u})
            added += 1
        if debug:
            st.write(f"Candidates added for '{niche}': {added}")
        progress.progress(idx / total_loops)

    st.success(f"Collected {len(candidates)} unique candidate domains across {len(niches)} niche(s).")

    # Analyze & build result table
    rows = []
    analyze_bar = st.progress(0)
    for i, c in enumerate(candidates, start=1):
        rd = c["root_domain"]
        if is_dup(existing_df, rd):
            continue
        info = analyze_site(c["source_url"])
        item = {"timestamp": pd.Timestamp.utcnow().isoformat(), "niche": c["niche"], **info}
        rows.append(item)
        analyze_bar.progress(i / max(1, len(candidates)))

    result_df = pd.DataFrame(rows)
    if result_df.empty:
        st.warning("No new sites found. Try Aggressive strategy, broaden TLDs, or enable debug to inspect queries.")
    else:
        st.dataframe(result_df, use_container_width=True)

        colx, coly, colz = st.columns(3)
        with colx:
            csv = result_df.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", csv, file_name="prospects.csv", mime="text/csv")
        with coly:
            if mode == "Excel (.xlsx)":
                out_name = st.text_input("Output Excel name", value="prospects.xlsx")
                if st.button("Save to Excel (.xlsx)"):
                    try:
                        if excel_file:
                            base = pd.read_excel(excel_file)
                            merged = pd.concat([base, result_df], ignore_index=True)
                        else:
                            merged = result_df.copy()
                        merged.to_excel(out_name, index=False)
                        st.success(f"Saved to {out_name}")
                    except Exception as e:
                        st.error(f"Excel saving error: {e}")
        with colz:
            if mode == "Google Sheet" and sheet is not None:
                if st.button("Append to Google Sheet"):
                    try:
                        header = ["timestamp","niche","domain","root_domain","url_found","email","score","signals","notes"]
                        exists = sheet.get_all_values()
                        if not exists:
                            sheet.append_row(header)
                        values = result_df[header].values.tolist()
                        sheet.append_rows(values)
                        st.success("Appended to Google Sheet (tab: Prospects)")
                    except Exception as e:
                        st.error(f"Google Sheet append error: {e}")

st.markdown("---")
st.caption(
    "Tips: set SERPAPI_KEY (env/secrets/UI). If results are empty, enable 'Show debug details' "
    "to see SerpAPI responses. The app avoids duplicates by root domain."
)
