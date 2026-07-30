# India/USA Earnings Dashboard

Fetches upcoming earnings (India + USA) via Yahoo Finance, builds an
interactive HTML dashboard, sends a Telegram alert for tomorrow's
earnings, and runs automatically every day on GitHub Actions.

## Files in this repo

| File | Purpose |
|---|---|
| `india_earnings_dashboard.py` | Main script |
| `requirements.txt` | Python dependencies |
| `docs/index.html` | Generated dashboard (created by the script, published via GitHub Pages) |
| `telegram_config.py` | LOCAL-ONLY fallback for Telegram credentials (gitignored — see below) |
| `.github/workflows/earnings.yml` | GitHub Actions workflow — runs daily at 4:00 PM CST |
| `.gitignore` | Keeps `telegram_config.py` out of git |

## Step-by-step setup

### 1. Create the GitHub repository
1. Go to github.com → New repository (e.g. `earnings-dashboard`).
2. Choose **Public** or **Private** (Private repos need GitHub Pro/Team/Enterprise, or a free-tier GitHub Actions/Pages plan — public repos get GitHub Pages free either way).
3. Don't initialize with a README (we already have the files).

### 2. Push these files to the repo
From the folder containing all the files above:
```bash
git init
git add .
git commit -m "Initial commit: earnings dashboard"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

### 3. Add your Telegram credentials as GitHub Secrets
1. In your repo, go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Add:
   - Name: `TELEGRAM_BOT_TOKEN` → Value: your bot token from @BotFather
   - Name: `TELEGRAM_CHAT_ID` → Value: your chat ID
4. Save both. They're encrypted and never shown again in the UI — only
   injected into the workflow at run time.

(Getting a bot token / chat ID: see the instructions inside
`telegram_config.py` if you want a refresher — same steps apply.)

### 4. Enable GitHub Pages so you can view the dashboard via a link
1. Go to **Settings → Pages**.
2. Under **Build and deployment → Source**, choose **Deploy from a branch**.
3. Branch: `main`, Folder: `/docs`. Click **Save**.
4. GitHub will give you a URL like:
   `https://<your-username>.github.io/<your-repo>/`
   That's your live dashboard link — it updates automatically every time
   the workflow runs and commits a new `docs/index.html`.
   (First deploy can take a minute or two after the first successful workflow run.)

### 5. Test it manually before waiting for the schedule
1. Go to the **Actions** tab → **Daily earnings dashboard** workflow.
2. Click **Run workflow** → **Run workflow** (this is the `workflow_dispatch`
   trigger already included in the workflow file).
3. Watch it run. If it succeeds, check:
   - Your Telegram chat for the alert message.
   - `https://<your-username>.github.io/<your-repo>/` for the dashboard.

### 6. The daily schedule
Already configured in `.github/workflows/earnings.yml`:
```yaml
schedule:
  - cron: "0 22 * * *"   # 22:00 UTC = 4:00 PM CST (UTC-6)
```
**Important caveat:** GitHub Actions cron always runs in UTC and does not
auto-adjust for US daylight saving. This line is pinned to 4:00 PM CST
(UTC-6, "winter" Central Time). During Central Daylight Time (CDT,
UTC-5 — roughly mid-March to early November), the same UTC time will
actually land at 5:00 PM local instead of 4:00 PM. If you want it exactly
at 4:00 PM local clock time year-round, you have two options:
- Manually flip the cron line between `0 22 * * *` (CST months) and
  `0 21 * * *` (CDT months) twice a year, or
- Keep both cron lines active and add a tiny date check at the top of the
  workflow that exits early on the "wrong" one for the current time of
  year.
GitHub also documents that scheduled workflows can be delayed by a few
minutes during periods of high load — this is normal and not a bug in
this setup.

## Running locally (optional)
```bash
pip install -r requirements.txt
cp telegram_config.py telegram_config.py   # already there — just fill in your token/chat ID
python india_earnings_dashboard.py
```
Open `docs/index.html` in a browser.
