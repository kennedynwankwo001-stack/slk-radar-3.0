# SLK Radar

Scans 23 forex pairs after every H4 close and sends a Telegram message when a clean **Daily DRD** is confirmed by an **H4 body-close breakout**. It then waits for **H4 Reject H4** and tells you when it happens. It never gives entries.
SLK = **S**tructure (direction), **L**iquidity (target), **K**ey levels (decision zones). Rules: `docs/slk_radar_rules_v1.md`.

It runs free on GitHub Actions. No server needed.

## What you get on Telegram
- **SLK BIAS ALERT**: DRD confirmed by an H4 breakout (also an "EARLY" version when a clear rejection is still forming on the open Daily candle). At most 4 per Daily day, best first: PDH/PDL sweep, external breakout, most recent.
- **SLK H4 R H4**: H4 rejection within 6 H4 candles after the breakout. This is the stage you wait for before looking at the lower timeframe.
- **SLK CANCELLED** / **TARGET REACHED**: how the setup ended. Results are tracked automatically, with a weekly scorecard on Friday and `/results` any time.
- **Daily summary**: one message at each Daily close: setups still valid, the 3 best developing ones, and any that broke

The radar gives bias only, no entries. Send your bot `/radar EURAUD` (full read) or `/results` (how alerts ended). It answers at the next scan run, which can be up to a few hours later because GitHub's free plan only runs on a schedule. 

## Setup (about 15 minutes, no cost)
1. **Twelve Data key**: sign up at twelvedata.com (free Basic plan), copy your API key.
2. **Telegram bot**: in Telegram open **@BotFather**, send `/newbot`, copy the token. Then send any message to your new bot, and open `https://api.telegram.org/bot<TOKEN>/getUpdates` in your browser to find `"chat":{"id": ...}`. That number is your chat ID.
3. **GitHub**: create a new private repo, upload all these files (keep the `.github/workflows` folder).
4. In the repo: **Settings > Secrets and variables > Actions > New repository secret**. Add three secrets with exactly these names:
   `TWELVE_DATA_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
5. **Actions** tab > enable workflows > **SLK Radar scan** > **Run workflow**. Tick **dry run** first to read the output in the log, then run it again without dry run. The first real run saves a starting point and sends "SLK Radar is on". Alerts begin from the next H4 close.

Never paste keys or tokens in chat, issues or code. If one leaks, make a new one in Twelve Data / @BotFather and update the secret.

## Limits and notes
- Free Twelve Data: 800 credits/day and 8 requests/minute. One scan is 23 requests (about 3 minutes, paced automatically), about 140 credits/day.
- GitHub cron can run a few minutes late. A missed candle is picked up on the next run, and a breakout older than 3 H4 candles is not announced as new.
- Memory between runs uses the Actions cache. If GitHub clears it, the radar starts again silently (no flood of old alerts).
- The inducement (IDM) check is not automated yet.

## Try it on your own data
```
python -m slk_radar radar data/EURAUD_H1.csv --symbol EURAUD --as-of 2026-09-29T10:00
python -m slk_radar replay data/CADCHF_H1.csv --symbol CADCHF --from 2026-10-06 --to 2026-10-10
python -m unittest discover -s tests -t .
```
H1 files: time in UTC, columns `datetime;open;high;low;close` (Twelve Data CSV works as is). Python 3.10+, no packages to install.
