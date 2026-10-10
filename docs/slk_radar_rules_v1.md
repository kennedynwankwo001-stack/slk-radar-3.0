# SLK Radar: Consolidated Testable Rules (v1)
Brainstorming only. Nothing is built. This merges your decisions, the earlier reviews and both Grok rounds into rules a computer can test using only time, open, high, low, close.

Tags: **[you]** = decided by you. **[default]** = my choice from Grok's suggestion or my own, change anytime. **[check]** = must be verified on real data.

## 1. Data and time
- Pairs (23 forex): EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD, AUDNZD, AUDCAD, NZDCAD, AUDCHF, CADCHF, GBPJPY, GBPCHF, GBPAUD, GBPNZD, GBPCAD, EURGBP, EURJPY, EURCHF, EURAUD, EURNZD, EURCAD. [you]
- Source: Twelve Data, Daily and H4. Weekly is built from Daily. [you]
- **Daily closes at 5pm New York** (21:00 UTC in summer, 22:00 UTC in winter). H4 bars are aligned to it, so in summer they close at 01, 05, 09, 13, 17, 21 UTC. Scan right after each H4 close. [default, changed from midnight UTC because the countdown timers on your EURAUD screenshots show a 21:00 UTC Daily close and a 05:00 UTC H4 close] [check]
- Build Daily and H4 from H1 candles aligned to 17:00 America/New_York, so the radar sees the same candles as your TradingView charts. [check]
- Sunday session: inspect real feed timestamps first, then decide whether to merge into Monday. Gaps are never breaks. Gaps over about 0.5 x Daily ATR are flagged. [check]
- Daily ATR = ATR(14) on Daily. Touch tolerance = 0.25 x Daily ATR. [you]

## 2. Two swing detectors
- **Structure swings:** candle highs/lows, 3 candles each side. [you]
- **A/V shape swings:** CLOSES only (line chart). A close is a peak (A) if it is higher than the 2 closes before and the 2 closes after it. Valley (V) is the inverse. [default]
- Major structure = the swing whose break printed the latest higher high / lower low. [you]

## 3. Breaks
- Break = candle BODY close beyond a swing. A wick only = sweep. [you]
- External break = body close through major structure (changes trend). Internal break = body close through a smaller swing inside the range. [you]
- Fake breakout = body closes through, then closes back inside within 2 candles. No bias change. [you, locked]
- CHoCH = first body close against the current leg. Unconfirmed until a second body close in the new direction. [you]
- Disrespected = body close through the zone and no close back inside for 3 candles. [you, locked]
- A close back inside on the 3rd candle (after the 2-candle fake window) is a "late reclaim": the level is not disrespected and stays valid, flagged as late reclaim. This closes the gap between the 2-candle and 3-candle rules. [default]

## 4. Key levels
- **A (sell zone):** high of the peak candle down to max(open, close) of that candle. **V (buy zone):** low of the valley candle up to min(open, close). [default]
- **OCL:** two consecutive same-colour candles. Zone = junction, from close of candle 1 to open of candle 2, with a minimum width of 0.1 x Daily ATR. Bullish OCL = buy, bearish OCL = sell. [you] width [default]
- **Reaction:** price touches the zone (within tolerance) and a candle closes back outside it, away from the level. Exact spacing between two reactions to be set while testing. [check]
- **History:** 2+ reactions. More reactions = higher priority in the list. [you]
- **Fresh:** a level never touched since it formed. A fresh level is just as valid as one with history. It is labelled "Fresh" in the alert, and history levels show their reaction count. [you]
- Only a disrespected level (closed through and held, not flipped) is not valid for a DRD. [default]
- **Flip:** after a level is disrespected, the same zone is marked Flip (old resistance now support, or the reverse). 1-2 retests are accepted before it weakens. Label only in v1. [default]
- **QM:** optional, secondary, not in v1. [default]
- Scan 120 Daily candles for history. Show the top 3 levels. [you]
- **Age filter:** a Daily key level can't be used for a new DRD if it is older than 60 Daily candles. Age is counted from its last reaction (or from when it formed, if never touched), so a level kept alive by recent reactions stays usable. [you, locked] reading [default]
- Touch tolerance stays 0.25 x Daily ATR. [you, locked]
- **Quality tie-breaker:** between levels with equal history, prefer the one that has liquidity beyond it or itself caused a structure break. Shown as an info note, not part of the score. [default]

## 5. Rejection and sweep
- Rejection = touch or entry into the zone, then close back outside it.
- Strong = close beyond the far side of the zone (engulf-style close counts). A wick of 50% or more of the range is a bonus. Weak = close still inside or within about 10% of the zone width. [you]
- Sweep = wick takes the pool, candle closes back. A body that closes and holds beyond = run, not a sweep. [you]
- **PDH/PDL sweep:** today's Daily wick takes the previous Daily high/low and closes back inside its range. Info line only. [you]

## 6. Liquidity (info and targets)
- Pools: PDH, PDL, PH4 (high/low of last closed H4 candle), equal highs/lows (within 0.1 x Daily ATR). [you]
- ERL = liquidity outside the current range in the DRD direction (the target). IRL = internal pullback liquidity (the fuel). [default]
- Premium/discount: info line only, 50% of the current Daily range (major high to major low). Range definition [check]. [default]

## 7. DRD (the storyline)
- DRD = a Daily candle rejects a Daily key level.
- **Multiple DRDs:** if two or more Strong/Medium DRDs exist on a pair, use the one with the higher score. If scores are equal, use the one whose key level is closer to the current price. [you, locked]
- Score (max 5): level quality (+2 for any valid level: fresh, with history, or flip; 0 if disrespected and not flipped), rejection (+2 strong, +1 weak), PDH/PDL sweep (+1). **Strong = 5, Medium = 3-4, Weak = 2 or less.** [you]
- Weak never sets bias and never alerts. [you]
- Full strength on the DRD day and the next trading day, then aging. [default]
- **Bias invalidation (the only three ways an active bias is cancelled):** [you, locked]
  1. The DRD key level is disrespected (body close through and holds 3 candles).
  2. A new opposing Strong/Medium DRD appears.
  3. An H4 candle body closes against the bias through the H4 swing that confirmed it.
- After a cancellation, the radar re-evaluates and uses the highest-scoring valid DRD. The earlier "5 Daily candles then context only" expiry is removed, so only these three rules cancel a bias.

## 8. H4 confirmation
- **H4 breakout (BO):** for a bearish DRD, an H4 candle body closes below an H4 swing LOW. For a bullish DRD, above an H4 swing HIGH. (Internal is enough.) [you, locked]
- **H4 swings are read on the close line** (n=1: a close higher/lower than the closes either side), which matches how you read the H4 line chart. Daily structure still uses candle swings with 3 candles each side. [you, tested on EURAUD]
- **"Most recent confirmed H4 swing"** = the latest swing already broken by a body close in the DRD direction, or the latest unbroken swing if none has been broken yet. [you, locked]
- The break must happen after the DRD candle has closed. A break that happened before the DRD doesn't count as confirmation. [default]
- **H4 sweep (info line, before the BO):** an H4 wick takes the extreme of the Daily key level or an H4 pool, and the candle closes back. Your own sequence label is "H4 sweep and breakout, then H4 reject H4". [you] (from your EURAUD annotation)
- An H4 body close back through the confirming swing, against the bias, cancels the setup (bias invalidation rule 3). It does not create the opposite bias by itself. [you, locked]
- **H4 rejection after the BO:** an H4 candle closes rejecting an H4 key level in the same direction. Counts only within 6 H4 candles (one day) after the BO. Retest is not required for the main alert. [you, locked]

## 8b. Added after the first two replays
- **Tiebreak between DRDs of equal score:** candle colour first (bullish candle for a buy DRD, bearish for a sell DRD), then the closest level. Replaces the old "closest only". [you had no preference; tested]
- **Flips count:** a disrespected level seen from the other side is valid for a DRD (+2 level quality). [you]
- **Early alert:** a Strong DRD forming on the still-open Daily candle plus an H4 breakout sends an "EARLY, Daily not closed" alert. A Medium or Weak forming DRD never alerts early. [default]
- **Entry plan:** includes one line saying inducement (IDM) is not checked by the radar. [default]
- **Data:** Twelve Data sends hourly candles for Saturday/Sunday too. The radar drops Friday 5pm to Sunday 5pm New York.

## 9. Weekly chain (optional booster)
- WRW = a Weekly candle rejects a Weekly key level (same A/V/OCL types).
- Chain: WRW, Daily BO/BOS, DRD, H4 BO/BOS. Counts Monday and Tuesday. Weekly never overrides a fresh Daily rejection. Full chain = top grade. [you]/[default]

## 10. Bias
- A Strong or Medium DRD sets the working bias. Structure is shown beside it. No DRD: follow the last external break. Neither: Neutral. No session bias. [you]

## 11. Messages
- **Alert 1:** Strong or Medium DRD plus a closed H4 BO in the same direction. [you]
- **Message 2 (once):** "retest confirmed" when the H4 rejection closes. [you]
- **Reminder next day:** one message saying whether the setup is still valid or broken. [you]
- **Daily watchlist (one message per day):** you asked for at least 3 alerts a day. Real setups can't be forced, so after the Daily close the radar sends the 3 best developing setups (Strong or Medium DRD whose H4 breakout has not closed yet), labelled "watching, not confirmed". Fewer than 3 if fewer qualify. Weak DRDs are never added to fill the list. [default]
- **News alerts:** dropped from version 1 (you said to forget the calendar source). Can be added later. [you]
- **No quiet hours:** alerts are sent whenever a candle completes. Times in messages are shown in Lagos time. [you]
- Alert shows: pair, bias, level (type, reactions, respected), DRD grade, H4 confirmation, PDH/PDL sweep line, next target (ERL). Short format. [you]

## 12. Entry (only on request: `/radar PAIR entry`)
- Entry zone = nearest H4/H1/H2 key level aligned with bias. Stop = beyond the extreme of that level or the swing that would cancel the DRD. Target = next ERL. [default]
- No 1-10 score in v1. Log every alert and outcome so a score can be earned later. [default]

## 13. Known gaps (settle with real data)
- Reaction spacing, "most recent confirmed H4 swing" edge cases, range definition for premium/discount, news calendar source.
- Sunday handling is no longer a problem: with a 5pm New York Daily close, the week opens at the Sunday 5pm New York candle, which is Monday's Daily candle. No merge needed.

## 14. Worked example 1: EURAUD, 29-30 Sep 2026 (your screenshots, my reading)
- **Daily key level:** bullish OCL, two bullish candles in a row with the junction near 1.6175 (your label: "Daily rejection from OCL KL"). The junction is almost a single line, so the radar needs a minimum zone width.
- **DRD:** a later Daily candle wicked a little below the level (to about 1.6165) and closed far above it. Strong rejection by the close. Bullish DRD.
- **H4:** price swept just below the level (wick about 1.6165) and closed back up, then an H4 candle closed through the most recent H4 swing high (your label: "4h sweep and breakout"). Then an H4 candle wicked down to the broken level near 1.6213 and closed up (your label: "4h reject 4h"). This is the rejection at a retest of the broken level.
- **1h entry:** entry about 1.62201, stop 1.62076, target 1.62728 (the previous high, ERL). Risk about 12.5 pips for about 52.7 pips, roughly 4 to 1.
- **Radar test:** the radar should alert at the H4 breakout close, then send "retest confirmed" at the H4 rejection close, and `/radar EURAUD entry` should suggest a zone near 1.6220 with a stop below it and the target at the prior high.

## 15. Worked example 2: CADCHF, 7-9 Oct 2026 (radar replay)
- **Daily key level:** a sell level at 0.58618-0.58648 that earlier price had broken and then came back to (a flip, 1 reaction).
- **DRD:** Wed 7 Oct. Daily wicked above the previous day's high (PDH swept) and closed back below the level. Strong, 5/5, bearish. Early picture was already visible on the open candle at 13:00 UTC.
- **H4:** an H4 candle swept the swing high 0.58589 and closed back below; then an H4 candle closed below the swing low 0.58409. The radar alerts at that close: Thu 8 Oct 02:00 Lagos. Target 0.58363 (PDL).
- **Retest:** H4 rejection of 0.58409 at 06:00 Lagos on 8 Oct, so "retest confirmed" is sent.
- **Cancel:** an H4 body close back above 0.58409 at 10:00 Lagos on 8 Oct cancels the setup (rule 3). Check against your own trade: if you stayed in the idea after this, tell the radar why.
- **Still to learn:** what makes an H4 breakout "low probability" in your practice (you wait for another one).
