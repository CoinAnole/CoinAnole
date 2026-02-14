"""Pet stat, mood, stage, and streak rules."""

from datetime import datetime, timedelta

from .constants import RECENT_ACTIVE_DAYS_LIMIT


def calculate_mood(pet: dict, github_stats: dict, repos_touched: list) -> str:
    """
    Calculate pet mood based on current stats.

    Mood affects the visual appearance of the pet.
    """
    stats = pet["stats"]

    if stats["satiety"] < 20:
        return "starving"
    elif stats["energy"] < 30:
        return "exhausted"
    elif stats["happiness"] > 80 and github_stats.get("current_streak", 0) > 3:
        return "ecstatic"
    elif len(repos_touched) > 5:
        return "scattered"
    else:
        return "content"


def calculate_stage(active_days: int) -> str:
    """
    Calculate evolution stage based on days of activity.

    Stages: baby -> teen -> adult -> elder
    Evolution is based on cumulative days with activity detected,
    not necessarily consecutive days.
    """
    if active_days < 10:
        return "baby"
    elif active_days < 50:
        return "teen"
    elif active_days < 200:
        return "adult"
    else:
        return "elder"


def apply_decay(pet: dict, hours_passed: float, activity: dict) -> dict:
    """
    Apply stat decay or recovery based on time passed and activity.

    Decay rates:
    - Satiety: -5 per 6 hours without commits (lower means hungrier)
    - Energy: +10 per 2 hours of rest (recovery during inactivity)
            -10 per 2 hours if still active (marathon mode)
    - Happiness: -2 per day
    """
    stats = pet["stats"]

    # Apply satiety decay (always decays)
    satiety_decay = 5 * hours_passed / 6
    stats["satiety"] = max(0, min(100, stats["satiety"] - satiety_decay))

    # Apply happiness decay (always decays slowly)
    happiness_decay = 2 * hours_passed / 24
    stats["happiness"] = max(0, min(100, stats["happiness"] - happiness_decay))

    # Energy: recover during rest, drain during marathons
    if activity["marathon_detected"]:
        # Marathon mode: drain energy faster
        energy_change = -(10 * hours_passed / 2)
        print(f"    Energy drain (marathon): {energy_change:.1f}")
    elif activity["commits_detected"] > 0:
        # Active but not marathon: slight energy drain
        energy_change = -(5 * hours_passed / 2)
        print(f"    Energy drain (active): {energy_change:.1f}")
    else:
        # Rest mode: recover energy
        energy_change = 10 * hours_passed / 2
        print(f"    Energy recovery (rest): +{energy_change:.1f}")

    stats["energy"] = max(0, min(100, stats["energy"] + energy_change))

    return pet


def apply_activity_bonuses(pet: dict, activity: dict) -> dict:
    """
    Apply stat bonuses from detected activity.

    Also applies energy penalties for marathon sessions.
    """
    stats = pet["stats"]
    commits = activity["commits_detected"]
    repos = activity["repos_touched"]

    if commits > 0:
        # Satiety increases (pet gets fed from activity)
        stats["satiety"] = min(100, stats["satiety"] + commits * 5)
        # Happiness increases from activity
        stats["happiness"] = min(100, stats["happiness"] + len(repos) * 2)

        # Marathon penalty: additional energy drain
        if activity["marathon_detected"]:
            marathon_penalty = 15  # Flat penalty for marathon sessions
            stats["energy"] = max(0, stats["energy"] - marathon_penalty)
            print(f"    Marathon penalty: -{marathon_penalty} energy")

    return pet


def trim_active_days(active_days: set[str] | list[str], limit: int = RECENT_ACTIVE_DAYS_LIMIT) -> list[str]:
    """
    Keep only the most recent active day entries for state size control.

    `active_days_total` stores the all-time count to preserve stage progression.
    """
    normalized = sorted({d for d in active_days if isinstance(d, str)})
    if len(normalized) <= limit:
        return normalized
    return normalized[-limit:]


def calculate_current_streak(active_days: set[str], today: str) -> int:
    """Calculate consecutive active days ending on today."""
    if today not in active_days:
        return 0

    try:
        cursor = datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        return 0

    streak = 0
    while cursor.isoformat() in active_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak
