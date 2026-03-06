from timetable import TimetableResolver
from datetime import date, time, timedelta, datetime
from collections import defaultdict
import concurrent.futures
import threading
import requests
import pytz
import json


def _timeline_time(timestamp):
    """Format datetime for Rebble Timeline API: ISO 8601 with Z suffix and millisecond precision."""
    s = timestamp.isoformat()
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    elif "+00:00" in s:
        s = s.replace("+00:00", "Z")
    # API expects milliseconds; truncate microseconds to 3 digits
    if "." in s and len(s) > s.index(".") + 4:
        s = s[: s.index(".") + 4] + ("Z" if s.endswith("Z") else "")
    return s


class Timeline:
    PRAYER_NAMES =  {
        "standard": {
            "fajr": "Fajr",
            "sunrise": "Sunrise",
            "dhuhr": "Dhuhr",
            "asr": "Asr",
            "maghrib": "Maghrib",
            "isha": "Isha"
        },
        "arabic": {
            "fajr": "الفجر",
            "sunrise": "الشروق",
            "dhuhr": "الظهر",
            "asr": "العصر",
            "maghrib": "المغرب",
            "isha": "العشاء"
        },
        "turkish": {
            "fajr": "İmsak",
            "sunrise": "Güneş",
            "dhuhr": "Öğle",
            "asr": "İkindi",
            "maghrib": "Akşam",
            "isha": "Yatsı"
        }
    }
    TIMES_TO_PUSH = ["fajr", "dhuhr", "asr", "maghrib", "isha"]

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)
    # I'm not sure if the ThreadPoolExecutor ever shuts down threads, meaning we might need to trim this dict.
    executor_http_sessions = defaultdict(lambda: requests.Session())

    def push_pins_for_user(user, sync=False, clear=True):
        if not user.timeline_token:
            # They're not timeline-enabled
            return []
        pending_pins = []

        if clear:
            for x in range(-2, 3):
                pending_pins += Timeline._delete_pins_for_date(user, date.today() + timedelta(days=x))
        # Push pins for yesterday, today, tomorrow, and the day after
        # (20 total - just to avoid timezone worries)
        for x in range(-1, 3):
            pending_pins += Timeline._push_pins_for_date(user, date.today() + timedelta(days=x))

        if sync:
            # Wait until all our calls clear
            concurrent.futures.wait(pending_pins)
        else:
            return pending_pins

    def _push_pins_for_date(user, date):
        loc = user.location
        if hasattr(loc, "keys"):
            loc = loc['coordinates']
        loc = loc[::-1] # From the database, it's lon/lat
        geoname_option, times = TimetableResolver.Resolve(user.config["method"], user.config, loc, date)
        for key in Timeline.TIMES_TO_PUSH:
            yield Timeline.executor.submit(Timeline._push_time_pin, user, geoname_option, key, date, datetime.combine(date, time()).replace(tzinfo=pytz.utc) + timedelta(hours=times[key]))

    def _delete_pins_for_date(user, date):
        for key in Timeline.TIMES_TO_PUSH:
            yield Timeline.executor.submit(Timeline._delete_time_pin, user, key, date)

    def _delete_time_pin(user, prayer, date):
        session = Timeline.executor_http_sessions[threading.current_thread().ident]
        pin_id = "%s:%s:%s" % (user.user_token, date, prayer)
        res = session.delete("https://timeline-api.rebble.io/v1/user/pins/%s" % pin_id,
                           headers={"X-User-Token": user.timeline_token, "Content-Type": "application/json"})
        if res.status_code == 410:
            # They've uninstalled the app
            user.timeline_token = None
            user.save()
        assert res.status_code == 200, "Pin delete failed %s %s" % (res, res.text)
        return True

    def _push_time_pin(user, geoname_option, prayer, date, timestamp):
        session = Timeline.executor_http_sessions[threading.current_thread().ident]
        pin_data = Timeline._generate_pin(user, geoname_option, prayer, date, timestamp)
        res = session.put("https://timeline-api.rebble.io/v1/user/pins/%s" % pin_data["id"],
                           json=pin_data,
                           headers={"X-User-Token": user.timeline_token})
        if res.status_code == 410:
            # They've uninstalled the app
            user.timeline_token = None
            user.save()
        assert res.status_code == 200, "Pin push failed %s %s" % (res, res.text)
        return True

    def _generate_pin(user, geoname_option, prayer, date, timestamp):
        pin_id = "%s:%s:%s" % (user.user_token, date, prayer)
        prayer_name = Timeline.PRAYER_NAMES[user.config["prayer_names"]][prayer]
        geoname = (geoname_option if geoname_option else user.location_geoname)
        time_str = _timeline_time(timestamp)
        return {
            "id": pin_id,
            "time": time_str,
            "layout": {
                "type": "genericPin",
                "title": prayer_name,
                "subtitle": "in %s" % geoname,
                "tinyIcon": "system://images/NOTIFICATION_FLAG"
            },
            "actions": [
                {
                    "title": "Qibla Compass",
                    "type": "openWatchApp",
                    "launchCode": 20
                }
            ],
            "reminders": [
                {
                  "time": time_str,
                  "layout": {
                    "type": "genericReminder",
                    "title": prayer_name,
                    "locationName": "in %s" % geoname,
                    "tinyIcon": "system://images/NOTIFICATION_FLAG"
                  }
                }
            ]
        }
