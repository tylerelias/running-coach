#!/usr/bin/env python3
"""
Garmin Connect data fetcher for the running-coach skill.

Pulls training data, health metrics, and scheduled workouts from Garmin Connect
using the garth library. Outputs JSON to stdout for Claude to consume.

Usage:
    python garmin_fetch.py activities [--days N] [--type running|trail_running|all]
    python garmin_fetch.py activity <activity_id>
    python garmin_fetch.py zones
    python garmin_fetch.py health [--days N]
    python garmin_fetch.py workouts [--days N]
    python garmin_fetch.py summary [--days N]

Environment variables:
    GARMIN_EMAIL    - Garmin Connect email
    GARMIN_PASSWORD - Garmin Connect password

Token cache is stored at ~/.garmin_tokens/ and reused automatically.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

TOKEN_DIR = Path.home() / ".garmin_tokens"


def get_client():
    """Authenticate and return a garth client."""
    try:
        import garth
    except ImportError:
        print(json.dumps({
            "error": "garth not installed",
            "fix": "pip install garth requests"
        }))
        sys.exit(1)

    # Try loading cached tokens first
    if TOKEN_DIR.exists():
        try:
            garth.resume(str(TOKEN_DIR))
            # Test if tokens are still valid
            garth.client.username
            return garth
        except Exception:
            pass

    # Fall back to credentials
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        print(json.dumps({
            "error": "No cached tokens and no credentials provided",
            "fix": "Set GARMIN_EMAIL and GARMIN_PASSWORD environment variables"
        }))
        sys.exit(1)

    try:
        garth.login(email, password)
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        garth.save(str(TOKEN_DIR))
        return garth
    except Exception as e:
        print(json.dumps({"error": f"Login failed: {str(e)}"}))
        sys.exit(1)


def format_pace(speed_mps):
    """Convert m/s to min:sec/km string."""
    if not speed_mps or speed_mps <= 0:
        return None
    secs_per_km = 1000 / speed_mps
    minutes = int(secs_per_km // 60)
    seconds = int(secs_per_km % 60)
    return f"{minutes}:{seconds:02d}/km"


def format_duration(seconds):
    """Convert seconds to H:MM:SS or M:SS string."""
    if not seconds:
        return "0:00"
    seconds = int(seconds)
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h}:{m:02d}:{s:02d}"
    else:
        m = seconds // 60
        s = seconds % 60
        return f"{m}:{s:02d}"


def cmd_activities(garth, args):
    """Fetch recent activities."""
    end = datetime.now()
    start = end - timedelta(days=args.days)

    activities = garth.connectapi(
        f"/activitylist-service/activities/search/activities",
        params={
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
            "start": 0,
            "limit": 100,
        }
    )

    if not isinstance(activities, list):
        activities = activities.get("activities", [])

    # Filter by type if requested
    if args.type != "all":
        type_map = {
            "running": ["running", "treadmill_running"],
            "trail_running": ["trail_running"],
        }
        allowed = type_map.get(args.type, [args.type])
        activities = [
            a for a in activities
            if (a.get("activityType", {}).get("typeKey", "") in allowed)
        ]

    results = []
    for a in activities:
        avg_speed = a.get("averageSpeed", 0)
        activity = {
            "id": a.get("activityId"),
            "name": a.get("activityName", "Unnamed"),
            "type": a.get("activityType", {}).get("typeKey", "unknown"),
            "date": (a.get("startTimeLocal") or a.get("startTimeGMT", ""))[:10],
            "distance_km": round((a.get("distance", 0) or 0) / 1000, 2),
            "duration": format_duration(a.get("duration", 0)),
            "duration_seconds": int(a.get("duration", 0) or 0),
            "avg_pace": format_pace(avg_speed),
            "avg_hr": a.get("averageHR"),
            "max_hr": a.get("maxHR"),
            "elevation_gain_m": round(a.get("elevationGain", 0) or 0),
            "elevation_loss_m": round(a.get("elevationLoss", 0) or 0),
            "calories": a.get("calories"),
            "training_effect_aerobic": a.get("aerobicTrainingEffect"),
            "training_effect_anaerobic": a.get("anaerobicTrainingEffect"),
        }
        results.append(activity)

    print(json.dumps({
        "period": f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}",
        "count": len(results),
        "activities": results,
    }, indent=2))


def cmd_activity(garth, args):
    """Fetch detailed single activity with splits."""
    activity_id = args.activity_id

    # Main activity data
    data = garth.connectapi(f"/activity-service/activity/{activity_id}")
    summary = data.get("summaryDTO", {})

    # Splits
    splits = []
    try:
        split_data = garth.connectapi(
            f"/activity-service/activity/{activity_id}/split_summaries",
            params={"splitType": 0}
        )
        if isinstance(split_data, list):
            split_list = split_data
        else:
            split_list = split_data.get("splitSummaries", split_data.get("splits", []))

        for i, s in enumerate(split_list):
            duration = s.get("duration") or s.get("elapsedDuration") or s.get("timerDuration", 0)
            distance = s.get("distance", 0)
            split = {
                "km": i + 1,
                "duration": format_duration(duration),
                "pace": format_pace(distance / duration if duration > 0 else 0),
                "avg_hr": s.get("averageHR") or s.get("averageHeartRate"),
                "elevation_gain": round(s.get("elevationGain", 0) or 0),
                "elevation_loss": round(s.get("elevationLoss", 0) or 0),
            }
            # GAP if available
            gap = s.get("gradeAdjustedSpeed") or s.get("avgGradeAdjustedSpeed")
            if gap:
                split["gap"] = format_pace(gap)
            splits.append(split)
    except Exception:
        pass

    avg_speed = summary.get("averageSpeed", 0)
    gap_speed = (
        summary.get("avgGradeAdjustedSpeed")
        or summary.get("averageGradeAdjustedSpeed")
        or data.get("avgGradeAdjustedSpeed")
    )

    result = {
        "id": data.get("activityId", activity_id),
        "name": data.get("activityName", "Unnamed"),
        "type": (
            data.get("activityType", {}).get("typeKey")
            or data.get("activityTypeDTO", {}).get("typeKey", "unknown")
        ),
        "date": (data.get("startTimeLocal") or data.get("startTimeGMT", ""))[:10],
        "start_time": data.get("startTimeLocal") or data.get("startTimeGMT"),
        "distance_km": round((summary.get("distance", 0) or 0) / 1000, 2),
        "duration": format_duration(summary.get("elapsedDuration") or summary.get("duration", 0)),
        "moving_duration": format_duration(summary.get("movingDuration", 0)),
        "avg_pace": format_pace(avg_speed),
        "gap": format_pace(gap_speed) if gap_speed else None,
        "avg_hr": summary.get("averageHR") or summary.get("averageHeartRate"),
        "max_hr": summary.get("maxHR") or summary.get("maxHeartRate"),
        "elevation_gain_m": round(summary.get("elevationGain", 0) or 0),
        "elevation_loss_m": round(summary.get("elevationLoss", 0) or 0),
        "calories": summary.get("calories", 0),
        "avg_cadence": summary.get("averageRunningCadenceInStepsPerMinute"),
        "splits": splits if splits else None,
    }

    print(json.dumps(result, indent=2))


def cmd_zones(garth, args):
    """Fetch HR zones, LTHR, LT pace, VO2max."""
    # User settings
    settings = garth.connectapi("/userprofile-service/userprofile/user-settings")
    user_data = settings.get("userData", {})

    result = {}

    # VO2max
    vo2 = user_data.get("vo2MaxRunning")
    if vo2 and vo2 > 0:
        result["vo2max"] = vo2

    # LTHR
    lthr = user_data.get("lactateThresholdHeartRate")
    if lthr and lthr > 0:
        result["lthr"] = lthr

    # LT pace
    lt_speed = user_data.get("lactateThresholdSpeed")
    if lt_speed and lt_speed > 0:
        lt_pace_secs = round(1000 / lt_speed)
        if 150 <= lt_pace_secs <= 600:
            result["lt_pace"] = format_pace(lt_speed)
            result["lt_pace_seconds_per_km"] = lt_pace_secs

    # Max HR
    for field in ["userMaxHr", "runningMaxHr", "maxHeartRate"]:
        val = user_data.get(field)
        if val and isinstance(val, (int, float)) and val > 0:
            result["max_hr"] = int(val)
            break

    if "max_hr" not in result and "lthr" in result:
        result["max_hr"] = round(result["lthr"] / 0.91)
        result["max_hr_source"] = "estimated from LTHR"

    # Resting HR
    for field in ["restingHeartRate", "currentRestingHeartRate"]:
        val = user_data.get(field)
        if val and isinstance(val, (int, float)) and val > 0:
            result["resting_hr"] = int(val)
            break

    # HR Zones
    for field in ["heartRateZones", "zones"]:
        zones = user_data.get(field)
        if zones and isinstance(zones, list) and len(zones) > 0:
            result["hr_zones"] = [
                {
                    "zone": i + 1,
                    "min": z.get("zoneLowerBoundary") or z.get("startValue") or z.get("min", 0),
                    "max": z.get("zoneUpperBoundary") or z.get("endValue") or z.get("max", 0),
                }
                for i, z in enumerate(zones[:5])
            ]
            break

    # Also try lactate threshold endpoint
    try:
        lt_data = garth.connectapi("/biometric-service/latestLactateThreshold")
        if lt_data:
            if lt_data.get("lactateThresholdHeartRate") and "lthr" not in result:
                result["lthr"] = lt_data["lactateThresholdHeartRate"]
            if lt_data.get("lactateThresholdSpeed") and "lt_pace" not in result:
                result["lt_pace"] = format_pace(lt_data["lactateThresholdSpeed"])
            if lt_data.get("startTimeGMT") or lt_data.get("calendarDate"):
                result["lt_test_date"] = lt_data.get("startTimeGMT") or lt_data.get("calendarDate")
    except Exception:
        pass

    # Resting HR from wellness
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        hr_data = garth.connectapi(f"/wellness-service/wellness/dailyHeartRate/{today}")
        if hr_data and hr_data.get("restingHeartRate"):
            result["resting_hr_today"] = hr_data["restingHeartRate"]
    except Exception:
        pass

    print(json.dumps(result, indent=2))


def cmd_health(garth, args):
    """Fetch health/wellness metrics using garth's built-in stats API."""
    from garth.stats import DailySleep, DailyHRV, DailyStress, DailyTrainingStatus
    from datetime import date as date_type

    end_date = date_type.today()
    start_date = end_date - timedelta(days=args.days)

    result = {
        "period": f"{start_date} to {end_date}",
        "daily": [],
    }

    # Fetch all stat types via garth's built-in list() (handles API paths correctly)
    sleep_data = {}
    hrv_data = {}
    stress_data = {}
    training_data = {}
    readiness_data = {}

    try:
        for item in DailySleep.list(end_date):
            sleep_data[str(item.calendar_date)] = item
    except Exception:
        pass

    try:
        for item in DailyHRV.list(end_date):
            hrv_data[str(item.calendar_date)] = item
    except Exception:
        pass

    try:
        for item in DailyStress.list(end_date):
            stress_data[str(item.calendar_date)] = item
    except Exception:
        pass

    try:
        for item in DailyTrainingStatus.list(end_date):
            training_data[str(item.calendar_date)] = item
    except Exception:
        pass

    # Training readiness via direct API (not in garth.stats)
    current = start_date
    while current <= end_date:
        date_str = str(current)
        try:
            raw = garth.connectapi(f"/metrics-service/metrics/trainingreadiness/{date_str}")
            if isinstance(raw, list) and raw:
                readiness_data[date_str] = raw[0]
            elif isinstance(raw, dict):
                readiness_data[date_str] = raw
        except Exception:
            pass
        current += timedelta(days=1)

    # Assemble daily records
    current = start_date
    while current <= end_date:
        date_str = str(current)
        day = {"date": date_str}

        # Sleep score
        if date_str in sleep_data:
            s = sleep_data[date_str]
            day["sleep_score"] = s.value

        # HRV
        if date_str in hrv_data:
            h = hrv_data[date_str]
            day["hrv_weekly_avg"] = h.weekly_avg
            day["hrv_last_night"] = h.last_night_avg
            day["hrv_status"] = h.status

        # Stress
        if date_str in stress_data:
            st = stress_data[date_str]
            day["overall_stress"] = st.overall_stress_level
            # Convert stress durations to minutes
            day["high_stress_min"] = round((st.high_stress_duration or 0) / 60)
            day["rest_duration_min"] = round((st.rest_stress_duration or 0) / 60)

        # Training status
        if date_str in training_data:
            t = training_data[date_str]
            day["training_status_feedback"] = t.training_status_feedback_phrase
            day["acwr_status"] = t.acwr_status
            day["acwr_percent"] = t.acwr_percent

        # Training readiness
        if date_str in readiness_data:
            r = readiness_data[date_str]
            day["training_readiness_score"] = r.get("score")
            day["training_readiness_level"] = r.get("level")
            day["recovery_time_hours"] = round(r.get("recoveryTime", 0) / 60, 1) if r.get("recoveryTime") else None
            day["sleep_score_from_readiness"] = r.get("sleepScore")

        # Only include days with data beyond just the date
        if len(day) > 1:
            result["daily"].append(day)

        current += timedelta(days=1)

    print(json.dumps(result, indent=2))


def cmd_workouts(garth, args):
    """Fetch scheduled workouts from calendar."""
    end = datetime.now() + timedelta(days=args.days)
    start = datetime.now()

    # Fetch calendar items month by month
    all_workouts = []
    current_month = start.replace(day=1)
    end_month = end.replace(day=1)

    while current_month <= end_month:
        year = current_month.year
        month = current_month.month - 1  # Garmin uses 0-indexed months

        try:
            cal = garth.connectapi(f"/calendar-service/year/{year}/month/{month}")
            items = cal.get("calendarItems", [])
            for item in items:
                if item.get("itemType") == "workout":
                    item_date = str(item.get("date", ""))[:10]
                    # Only include if in our date range
                    if start.strftime("%Y-%m-%d") <= item_date <= end.strftime("%Y-%m-%d"):
                        workout = {
                            "date": item_date,
                            "name": item.get("title", "Untitled"),
                            "workout_id": item.get("workoutId"),
                            "sport": item.get("sportTypeKey", "running"),
                            "estimated_duration": format_duration(
                                item.get("duration") or item.get("estimatedDurationInSecs", 0)
                            ),
                            "estimated_distance_km": round(
                                (item.get("distance") or item.get("estimatedDistanceInMeters", 0)) / 1000, 2
                            ),
                        }
                        all_workouts.append(workout)
        except Exception:
            pass

        # Next month
        if current_month.month == 12:
            current_month = current_month.replace(year=current_month.year + 1, month=1)
        else:
            current_month = current_month.replace(month=current_month.month + 1)

    all_workouts.sort(key=lambda w: w["date"])

    print(json.dumps({
        "period": f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}",
        "count": len(all_workouts),
        "workouts": all_workouts,
    }, indent=2))


def cmd_summary(garth, args):
    """Generate a training summary for the period."""
    end = datetime.now()
    start = end - timedelta(days=args.days)

    activities = garth.connectapi(
        "/activitylist-service/activities/search/activities",
        params={
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
            "start": 0,
            "limit": 200,
        }
    )

    if not isinstance(activities, list):
        activities = activities.get("activities", [])

    # Filter to running activities
    running_types = {"running", "trail_running", "treadmill_running"}
    runs = [
        a for a in activities
        if a.get("activityType", {}).get("typeKey", "") in running_types
    ]

    total_distance = sum((a.get("distance", 0) or 0) for a in runs)
    total_duration = sum((a.get("duration", 0) or 0) for a in runs)
    total_elevation = sum((a.get("elevationGain", 0) or 0) for a in runs)
    avg_hr_values = [a.get("averageHR") for a in runs if a.get("averageHR")]

    # Intensity distribution based on Garmin aerobic training effect:
    # 0-1.9 = minor/recovery, 2.0-2.9 = maintaining, 3.0-3.9 = improving, 4.0+ = highly improving
    easy_runs = 0
    moderate_runs = 0
    hard_runs = 0
    for a in runs:
        te = a.get("aerobicTrainingEffect", 0) or 0
        if te < 3.0:
            easy_runs += 1
        elif te < 4.0:
            moderate_runs += 1
        else:
            hard_runs += 1

    summary = {
        "period": f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}",
        "days": args.days,
        "total_runs": len(runs),
        "total_distance_km": round(total_distance / 1000, 1),
        "total_duration": format_duration(total_duration),
        "total_duration_hours": round(total_duration / 3600, 1),
        "total_elevation_gain_m": round(total_elevation),
        "avg_distance_km": round(total_distance / 1000 / max(len(runs), 1), 1),
        "avg_duration": format_duration(total_duration / max(len(runs), 1)),
        "avg_hr": round(sum(avg_hr_values) / max(len(avg_hr_values), 1)) if avg_hr_values else None,
        "intensity_distribution": {
            "easy": easy_runs,
            "moderate": moderate_runs,
            "hard": hard_runs,
        },
        "longest_run_km": round(max((a.get("distance", 0) or 0) for a in runs) / 1000, 1) if runs else 0,
        "most_elevation_m": round(max((a.get("elevationGain", 0) or 0) for a in runs)) if runs else 0,
    }

    # Get current fitness markers
    try:
        settings = garth.connectapi("/userprofile-service/userprofile/user-settings")
        ud = settings.get("userData", {})
        if ud.get("vo2MaxRunning"):
            summary["current_vo2max"] = ud["vo2MaxRunning"]
        if ud.get("lactateThresholdHeartRate"):
            summary["current_lthr"] = ud["lactateThresholdHeartRate"]
        lt_speed = ud.get("lactateThresholdSpeed")
        if lt_speed and lt_speed > 0:
            lt_pace_secs = round(1000 / lt_speed)
            if 150 <= lt_pace_secs <= 600:
                summary["current_lt_pace"] = format_pace(lt_speed)
    except Exception:
        pass

    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Garmin Connect data fetcher")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # activities
    p_act = subparsers.add_parser("activities", help="List recent activities")
    p_act.add_argument("--days", type=int, default=30, help="Number of days to look back")
    p_act.add_argument("--type", default="all", help="Activity type filter (running, trail_running, all)")

    # activity detail
    p_det = subparsers.add_parser("activity", help="Get detailed activity")
    p_det.add_argument("activity_id", help="Garmin activity ID")

    # zones
    subparsers.add_parser("zones", help="Get HR zones, LTHR, VO2max")

    # health
    p_health = subparsers.add_parser("health", help="Get health/wellness metrics")
    p_health.add_argument("--days", type=int, default=7, help="Number of days to look back")

    # workouts
    p_work = subparsers.add_parser("workouts", help="Get scheduled workouts")
    p_work.add_argument("--days", type=int, default=30, help="Number of days to look ahead")

    # summary
    p_sum = subparsers.add_parser("summary", help="Training summary")
    p_sum.add_argument("--days", type=int, default=7, help="Number of days to summarize")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    garth_client = get_client()

    commands = {
        "activities": cmd_activities,
        "activity": cmd_activity,
        "zones": cmd_zones,
        "health": cmd_health,
        "workouts": cmd_workouts,
        "summary": cmd_summary,
    }

    commands[args.command](garth_client, args)


if __name__ == "__main__":
    main()
