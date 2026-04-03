import os
from dotenv import load_dotenv

load_dotenv()

from log_config import setup_logging

setup_logging()

import logging
import structlog
from flask import Flask, redirect, request, render_template, jsonify
from models import User
from timetable import TimetableResolver
from timeline import Timeline
from datetime import datetime, date, timedelta
import json

app = Flask(__name__)
log = structlog.get_logger(__name__)

if os.environ.get('SENTRY_DSN'):
    from raven.contrib.flask import Sentry
    Sentry(app, logging=True, level=logging.ERROR)

@app.route('/subscribe', methods=["POST"])
def subscribe():
    data = request.get_json()
    user_token = data["user_token"]
    user = User.objects(user_token=user_token) \
      .modify(upsert=True, new=True, set_on_insert__created_at=datetime.utcnow())
    if "timeline_token" in data:
        user.timeline_token = data["timeline_token"]
    user.location = [float(data["location_lon"]), float(data["location_lat"])]
    user.tz_offset = int(data["tz_offset"])
    user.subscribed_at = datetime.utcnow()
    user.geocode()
    user.save()
    Timeline.push_pins_for_user(user)

    result = {"location_geoname": user.location_geoname}
    return jsonify(result)


@app.route('/timeline/<user_token>', methods=["GET"])
def timeline_pins(user_token):
    """Return prayer-time pins for the user (adhoc fetch; no timeline-api push)."""
    try:
        user = User.objects.get(user_token=user_token)
    except User.DoesNotExist:
        return jsonify({"error": "user not found"}), 404
    start_date = request.args.get("start")
    end_date = request.args.get("end")
    if start_date:
        try:
            start_date = date.fromisoformat(start_date)
        except ValueError:
            return jsonify({"error": "invalid start date (use YYYY-MM-DD)"}), 400
    else:
        start_date = date.today() - timedelta(days=1)
    if end_date:
        try:
            end_date = date.fromisoformat(end_date)
        except ValueError:
            return jsonify({"error": "invalid end date (use YYYY-MM-DD)"}), 400
    else:
        end_date = date.today() + timedelta(days=3)
    if start_date > end_date:
        return jsonify({"error": "start must be before end"}), 400
    pins = Timeline.get_pins_for_user(user, start_date=start_date, end_date=end_date)
    return jsonify({"pins": pins})


@app.route('/settings/<user_token>',  methods=["GET", "POST"])
def settings(user_token):
    try:
        user = User.objects.get(user_token=user_token)
    except User.DoesNotExist:
        return render_template('registration_wait.html')

    # Wait until geocode completes
    if not user.location_geoname:
        return render_template('registration_wait.html')

    if not user.timeline_token:
        return render_template('no_timeline.html')

    if request.method == "POST":
        old_config = dict(user.config)
        user.config["method"] = request.form["method"]
        user.config["asr"] = request.form["asr"]
        user.config["prayer_names"] = request.form["prayer_names"]
        user.save()
        if old_config != user.config:
            Timeline.push_pins_for_user(user)
        return render_template('settings_confirmed.html')

    # Allow calculation method to override geocoded name, where applicable
    location = user.location
    if hasattr(location, "keys"):
        location = location['coordinates']
    location = location[::-1] # From the database, it's lon/lat
    location_geoname = TimetableResolver.ResolveLocationGeoname(user.config["method"], user.config, location)
    if location_geoname is None:
        location_geoname = user.location_geoname

    asr_options = ["Standard", "Hanafi"]

    method_options = sorted(list(TimetableResolver.Methods()))
    asr_setting_availability = json.dumps({x: TimetableResolver.AsrSettingAvailable(x) for x in method_options})
    prayer_name_options = {k: ", ".join([v[p] for p in ["fajr", "dhuhr", "asr", "maghrib", "isha"]]) for k,v in sorted(list(Timeline.PRAYER_NAMES.items()), key=lambda i: i[0] == "standard")}
    return render_template('settings.html', user=user, location_geoname=location_geoname, asr_options=asr_options, method_options=method_options, asr_setting_availability=asr_setting_availability, prayer_name_options=prayer_name_options)

@app.route('/')
def index():
    return "marhaba!"
    return redirect('https://apps.getpebble.com/applications/53ab84141d576ea3c30000d6')

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=8080)
