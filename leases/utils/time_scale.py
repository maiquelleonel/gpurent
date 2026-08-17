from datetime import timedelta

from django.conf import settings


def get_simulated_duration(started_at, ended_at) -> timedelta:
    """
    Computes and returns the simulated duration (as a timedelta) between two datetimes,
    multiplying the real-world elapsed time by settings.TIME_SCALE_FACTOR.
    """
    if ended_at < started_at:
        return timedelta(0)

    real_seconds = (ended_at - started_at).total_seconds()
    time_scale_factor = getattr(settings, "TIME_SCALE_FACTOR", 120)
    simulated_seconds = real_seconds * time_scale_factor

    return timedelta(seconds=simulated_seconds)
