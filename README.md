# Outreach Automator (Streamlit)

## What it does
- Enter one or more niches and how many websites you need.
- Uses SerpAPI to find candidate sites (various query templates per niche).
- Analyzes each site for “publishability signals” (write for us, guest post, contribute, advertise, etc.).
- Crawls likely pages (home/contact/about) to extract emails; optionally enriches via Hunter.io.
- De‑dupes against your existing Excel/Google Sheet by root domain.
- Exports results to CSV, saves to Excel, or appends to a Google Sheet tab `Prospects`.

## Setup
1. Install python.
2. Windows: .venv\Scripts\activate
3. pip install -r requirements.txt
4. In Command Prompt:
   set SERPAPI_KEY=your-serpapi-key-here
   set HUNTER_API_KEY=your-hunter-key-here
   set OPENAI_API_KEY=your-openai-key-here
   streamlit run streamlit_app.py
And in the streamlit_app.py(OPTIONAL): 
  SERPAPI_KEY = os.getenv("SERPAPI_KEY") or st.secrets.get("SERPAPI_KEY", "")
  HUNTER_API_KEY = os.getenv("HUNTER_API_KEY") or st.secrets.get("HUNTER_API_KEY", "")
  OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", "")


## Run
streamlit run streamlit_app.py

## Google Sheets (optional)
`- Create a Service Account in Google Cloud, enable Sheets API.
`- Download JSON credentials and upload them in the app.
`- Share your target Sheet with the service account email.

## Notes & Extensibility
`- If you prefer Bing/Web Search API, swap serpapi_search with your provider.
`-Add more niche query templates in SEARCH_TEMPLATES_*.
`-Tweak score_publishability heuristic or plug a GPT call for better classification.
`-Respect robots/ToS in your jurisdiction; add rate limiting as needed
