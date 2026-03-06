# Running Coach

An elite-level endurance running coach skill for Claude Code. Specializes in ultramarathon preparation, periodized training plan design, workout structure, and race execution strategy, grounded in David Roche's (SWAP Running) coaching methodology.

## What it does

- Coaches you through training plan design, workout prescription, and race preparation
- Pulls real training data from your Garmin Connect account (activities, HR zones, HRV, training readiness, sleep, stress)
- Gives advice grounded in your actual performance metrics, not generic numbers
- Handles setbacks (illness, injury, missed training) with evidence-based guidance
- Designs race execution strategies with segment-by-segment effort targets and nutrition plans

## Install

```bash
claude install github:tylerelias/running-coach
```

## Setup

### 1. Install Python dependencies

```bash
pip install garth requests
```

### 2. Set Garmin credentials

```bash
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="your-password"
```

Add these to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.) to persist them.

After the first successful connection, tokens are cached at `~/.garmin_tokens/` so credentials aren't needed again until they expire.

### 3. Start using it

Ask Claude anything about running training. The skill triggers automatically on questions about:

- Training plans, workout design, periodization
- Race preparation and execution strategy
- Pacing, tapering, recovery
- Injury/illness and returning to training
- Nutrition and fueling for endurance events
- Heart rate zone training
- Interpreting workout results
- Casual questions like "should I run today" or "my legs feel heavy"

## Garmin data commands

The skill uses a Python script to pull data from Garmin Connect. Claude runs these automatically when it needs your data, but you can also run them directly:

| Command | Description |
|---------|-------------|
| `activities --days 30` | Recent activities with pace, HR, elevation, training effect |
| `activity <id>` | Single activity detail with per-km splits |
| `zones` | HR zones, LTHR, LT pace, VO2max, resting HR |
| `health --days 7` | HRV, sleep score, stress, training readiness |
| `workouts --days 30` | Scheduled future workouts from Garmin calendar |
| `summary --days 7` | Training load summary with intensity distribution |

## Coaching philosophy

Built on David Roche's SWAP Running methodology:

- **Effort before pace** -- especially for mountain/ultra events
- **Joy is a training variable** -- consistency from enjoyment beats perfection from suffering
- **The weekend is the training** -- back-to-back long runs are the most race-specific stimulus
- **Recovery is training** -- defend rest days aggressively
- **Specificity increases over time** -- general to specific across the plan
- **Never chase missed volume** -- the plan moves forward from where you are
