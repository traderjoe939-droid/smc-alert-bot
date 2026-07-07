# SMC Liquidity Sweep Alert System — MVP Strategy Specification

Version: 0.3  
Mode: Alerts only  
Platform: MT5-compatible risk calculations  
Account currency: USD  
Fixed risk per trade: $400

## 1. Instruments

- EUR/USD
- GBP/USD
- USD/JPY
- AUD/USD
- USD/CAD
- GBP/JPY

## 2. Timeframes

- H4: primary market structure and dealing range
- H1: confirmation of higher-timeframe direction and area of interest
- M15: setup detection and signal generation
- M5: optional entry refinement and retest confirmation

The MVP will generate entries from M15 data. M5 is used only to improve timing, not to override an invalid M15 setup.

## 3. Six-Point Setup Score

Each valid condition contributes one point:

1. Higher-timeframe bias
2. Higher-timeframe key zone
3. Liquidity sweep
4. Displacement plus CHoCH/MSS
5. FVG / order-block retracement
6. Clean 3R path

Signal grades:

- A+ setup: 6/6
- A setup: 5/6
- Below 5/6: no alert

Core conditions are mandatory for both A and A+ alerts:

- Higher-timeframe bias
- Liquidity sweep
- Displacement plus CHoCH/MSS

A 5/6 setup is not allowed when one of these three core conditions is missing.

## 4. Higher-Timeframe Bias

### Swing definition

A confirmed swing high is a candle whose high is greater than the highs of the three candles immediately before and after it.

A confirmed swing low is a candle whose low is lower than the lows of the three candles immediately before and after it.

### Bullish bias

Both H4 and H1 must show:

- The latest confirmed swing high is above the previous confirmed swing high.
- The latest confirmed swing low is above the previous confirmed swing low.

### Bearish bias

Both H4 and H1 must show:

- The latest confirmed swing high is below the previous confirmed swing high.
- The latest confirmed swing low is below the previous confirmed swing low.

### Neutral bias

Bias is neutral when:

- H4 and H1 disagree.
- Structure is mixed.
- There are insufficient confirmed swings.

Neutral bias produces no alert.

## 5. Higher-Timeframe Key Zone

For the MVP, a key zone is objective and limited to premium/discount plus a higher-timeframe FVG or validated order block.

### Dealing range

Use the most recent confirmed H4 swing high and H4 swing low.

- Discount: price is below the 50% midpoint of the range.
- Premium: price is above the 50% midpoint of the range.

### Valid BUY zone

At least one must be true:

- Price is in the lower 50% of the H4 dealing range and within 0.25 H1 ATR of an H1 or H4 bullish FVG or bullish order block.
- Price is in the lowest 20% of the H4 dealing range.

### Valid SELL zone

At least one must be true:

- Price is in the upper 50% of the H4 dealing range and within 0.25 H1 ATR of an H1 or H4 bearish FVG or bearish order block.
- Price is in the highest 20% of the H4 dealing range.

A higher-timeframe order block must pass the objective rules in Section 10 on H1 or H4 data.

## 6. Liquidity Sweep

The sweep is detected on M15.

### Reference liquidity

Use the latest confirmed M15 swing high or swing low that:

- Is no more than 50 completed M15 candles old.
- Has not already been invalidated by a previous close beyond it.

### Bullish sweep

- Price trades below the reference swing low.
- The sweep exceeds the level by at least 0.05 M15 ATR.
- The same candle or the next completed candle closes back above the swept level.

### Bearish sweep

- Price trades above the reference swing high.
- The sweep exceeds the level by at least 0.05 M15 ATR.
- The same candle or the next completed candle closes back below the swept level.

## 7. Displacement

Displacement must occur within three completed M15 candles after the sweep.

A displacement candle must satisfy all of the following:

- Candle range is at least 1.25 times M15 ATR(14).
- Candle body is at least 1.5 times the median candle body of the previous 20 completed M15 candles.
- Bullish displacement closes in the top 25% of its range.
- Bearish displacement closes in the bottom 25% of its range.

## 8. CHoCH / MSS

### Bullish CHoCH/MSS

After a bullish liquidity sweep, a completed M15 candle must close above the most recent confirmed M15 swing high formed before the sweep.

### Bearish CHoCH/MSS

After a bearish liquidity sweep, a completed M15 candle must close below the most recent confirmed M15 swing low formed before the sweep.

A wick beyond structure is not sufficient. A completed candle close is required.

Displacement and CHoCH/MSS are scored as one combined condition.

## 9. Fair Value Gap

Use the standard three-candle definition.

### Bullish FVG

For candles A, B, and C:

- The low of candle C is above the high of candle A.
- The gap is created during or immediately after bullish displacement.

### Bearish FVG

- The high of candle C is below the low of candle A.
- The gap is created during or immediately after bearish displacement.

Minimum FVG size:

- At least 0.10 M15 ATR.

## 10. Order Block

Order-block detection is included in the MVP using one strict definition only.

### Bullish order block

After a bullish sweep, displacement, and bullish CHoCH/MSS, select the nearest bearish candle within the three completed candles immediately before the first qualifying bullish displacement candle.

The bullish order-block zone is:

- Upper boundary: the bearish candle open
- Lower boundary: the bearish candle low
- Midpoint: 50% of the zone

### Bearish order block

After a bearish sweep, displacement, and bearish CHoCH/MSS, select the nearest bullish candle within the three completed candles immediately before the first qualifying bearish displacement candle.

The bearish order-block zone is:

- Upper boundary: the bullish candle high
- Lower boundary: the bullish candle open
- Midpoint: 50% of the zone

### Validation and freshness

An order block is valid only when:

- The associated displacement satisfies Section 7.
- The associated move confirms CHoCH/MSS under Section 8.
- The order block has not previously received a qualifying midpoint retracement.
- No completed candle has closed beyond its distal boundary.
- An M15 entry order block is no more than 40 completed M15 candles old.
- An H1 key-zone order block is no more than 100 completed H1 candles old.
- An H4 key-zone order block is no more than 60 completed H4 candles old.

A bullish order block is invalidated by a completed close below its low. A bearish order block is invalidated by a completed close above its high.

## 11. Entry Rule

### Entry-zone priority

The planned entry zone is selected in this order:

1. FVG and order-block overlap from the same displacement leg
2. Qualifying FVG when no overlap exists
3. Qualifying order block when no FVG exists

When an FVG and order block overlap, use the overlap boundaries as the entry zone.

### Planned entry

The planned entry is the 50% midpoint of the selected entry zone.

### A+ entry confirmation

The FVG / order-block retracement condition passes when:

- Price trades into the selected entry zone.
- Price reaches or passes the zone midpoint.
- An M5 candle closes in the intended trade direction before price invalidates the setup.

### A setup

An A setup can be sent before the FVG / order-block retracement is complete, provided:

- All three core conditions pass.
- The setup scores exactly 5/6.
- A valid planned entry, stop, and targets can already be calculated.

The alert must clearly state which condition is missing and include `No trade yet.`

## 12. Stop-Loss Rule

### BUY

Stop is placed below the sweep low.

### SELL

Stop is placed above the sweep high.

### Buffer

Add a structural buffer equal to the greater of:

- 0.10 M15 ATR
- The configured minimum broker stop distance for the symbol

The stop is never moved closer merely to force a 3R target.

## 13. Targets

For the MVP, targets are fixed R multiples:

- TP1 = 1R
- TP2 = 2R
- TP3 = 3R

Where:

- BUY risk distance = Entry - Stop
- SELL risk distance = Stop - Entry

Future versions may replace fixed targets with internal and external liquidity targets.

## 14. Clean 3R Path

A clean 3R path passes when there is no confirmed opposing M15 or H1 swing level between entry and TP3.

### BUY obstacle

A confirmed M15 or H1 swing high below TP3 is treated as an obstacle.

### SELL obstacle

A confirmed M15 or H1 swing low above TP3 is treated as an obstacle.

For the MVP, any obstacle before TP3 causes this condition to fail. The setup can still qualify as an A signal if all core conditions remain valid and the total score is 5/6.

## 15. Invalidation

A setup is invalid before entry when:

- Price closes beyond the sweep extreme plus stop buffer.
- H4 or H1 bias becomes neutral or reverses.
- The selected FVG / order-block entry zone is fully crossed without the required M5 confirmation.
- The qualifying order block is invalidated by a completed close beyond its distal boundary.
- The setup remains untriggered for 24 completed M15 candles.

## 16. Alert Deduplication

Only one initial alert is allowed per unique setup.

A setup ID is created from:

- Symbol
- Direction
- Sweep candle timestamp
- Entry-zone timestamp

The same setup must not be alerted repeatedly on every monitoring cycle.

An A setup may later upgrade to A+ when the missing condition becomes valid. The A+ upgrade is sent once.

## 17. Alert Formats

### A+ alert

```text
🟢 A+ BUY

Pair: EUR/USD
Timeframe: M15

Entry: 1.08740
SL: 1.08580

TP1: 1.08900
TP2: 1.09060
TP3: 1.09220

Risk: $400
Lot Size: 2.50 lots

Score: 6/6 (100%)

✅ HTF Bias
✅ HTF Key Zone
✅ Liquidity Sweep
✅ Displacement + CHoCH
✅ FVG / OB Retracement
✅ Clean 3R Path
```

### A alert

```text
🟢 A Possible BUY

Pair: EUR/USD
Timeframe: M15

Entry: 1.08740
SL: 1.08580

TP1: 1.08900
TP2: 1.09060
TP3: 1.09220

Risk: $400
Lot Size: 2.50 lots

Score: 5/6 (83%)

✅ HTF Bias
✅ HTF Key Zone
✅ Liquidity Sweep
✅ Displacement + CHoCH
❌ FVG / OB Retracement
✅ Clean 3R Path

No trade yet.
```

BUY and SELL formats are mirrored.

## 18. Trade-Management Alerts

### MVP tracking behavior

- A+ signals are tracked automatically after the alert.
- A signals are not treated as active trades automatically because entry remains discretionary.
- An A signal is tracked only after the user confirms it with a Telegram command such as `/track SIGNAL_ID`.

Tracked signals generate one-time alerts for:

- Entry triggered
- Stop loss hit
- TP1 hit
- TP2 hit
- TP3 hit
- Setup invalidated before entry

## 19. Risk Rule

Every tracked trade uses a fixed maximum market-price loss of $400 from entry to stop loss. Commission and spread are excluded from this calculation.

Lot size is calculated from:

- Entry price
- Stop price
- Symbol contract size
- Tick size
- Tick value
- Account currency conversion when required
- Broker volume step, minimum volume, and maximum volume

The final lot size is rounded down to the broker's permitted volume step so calculated risk does not exceed $400.

## 20. Daily Safety Rule

The checklist specifies a daily cutoff after two full losses. The MVP will record the rule but will not block alerts automatically because the system does not yet know which discretionary alerts the user actually traded.

Once trade confirmation is added, the worker can stop issuing actionable alerts after two tracked full-stop losses in the same trading day.

## 21. MVP Boundaries

Included:

- Candle-close signal evaluation
- Objective FVG and order-block detection
- A and A+ alerts
- Fixed $400 risk calculation
- MT5-style volume rounding
- Telegram alerts
- Continuous multi-symbol monitoring
- SL and TP monitoring for tracked signals

Not included in the first version:

- Automatic MT5 order execution
- News filtering
- Multiple discretionary order-block models
- Partial-close execution
- Backtesting engine
- Machine learning
- Portfolio correlation limits

These can be added after the MVP runs reliably in forward testing.

## 22. Deferred Instrument

DAX / GER40 / DE40 is disabled in the MVP. It will be added only after a matching live data symbol and the broker-specific MT5 contract specification are confirmed.
