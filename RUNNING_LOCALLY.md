# Running PortOpt Locally

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.10 or later | [python.org](https://www.python.org/downloads/) |
| pip | bundled with Python | — |
| Git | any | [git-scm.com](https://git-scm.com/) |

---

## 1. Clone the repo

```bash
git clone <your-repo-url>
cd PortOpt
```

---

## 2. Create a virtual environment

**Windows**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**Mac / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` in your terminal prompt.

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs Flask, yfinance, PyPortfolioOpt, cvxpy, pandas, numpy, scipy, and ReportLab.
First install takes 2–3 minutes — cvxpy and scipy are large.

---

## 4. Run the app

```bash
python app.py
```

Or, using the Flask CLI:
```bash
flask run
```

The server starts on **http://localhost:5000** by default.

---

## 5. Open in your browser

| Page | URL |
|------|-----|
| Portfolio Optimization | http://localhost:5000/ |
| Equity Valuation | http://localhost:5000/valuation |
| Health check | http://localhost:5000/health |

---

## Notes

- **Database**: SQLite file `portopt.db` is created automatically on first run in the project root. It stores saved portfolios and valuation lists.
- **Internet required**: yfinance fetches live market data from Yahoo Finance. Ticker lookups and financial data will fail without an internet connection.
- **Vercel Analytics / Speed Insights**: The `/_vercel/insights/script.js` and `/_vercel/speed-insights/script.js` scripts are served by Vercel's CDN and will 404 locally — this is expected and does not affect app functionality. They only activate when deployed to Vercel.
- **PDF export**: Requires ReportLab (included in requirements). No extra setup needed.

---

## Stopping the server

Press `Ctrl + C` in the terminal.

---

## Deactivate the virtual environment when done

```bash
deactivate
```
