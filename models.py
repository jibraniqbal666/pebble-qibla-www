import mongoengine as me
import os
import structlog

log = structlog.get_logger(__name__)


class User(me.Document):
    DEFAULT_CONFIG = {
        # These match up with keys in praytimes.py
        "method": "ISNA",
        "asr": "Standard",
        # These don't
        "prayer_names": "standard"
    }
    user_token = me.StringField()
    timeline_token = me.StringField()
    location = me.PointField()
    location_geoname = me.StringField()
    tz_offset = me.IntField()
    created_at = me.DateTimeField()
    subscribed_at = me.DateTimeField()
    # It melted down when I tried name the db field "config"
    # Not sure what was up
    _sparse_config = me.DictField(db_field="sparse_config")

    def geocode(self):
        import requests
        from otel_metrics import record_geocode

        loc = self.location
        if hasattr(loc, "keys"):
            loc = loc.get("coordinates")
        if not loc or len(loc) < 2:
            log.warning("geocode_skipped_no_location", user_token=self.user_token)
            record_geocode("skipped")
            return

        lon, lat = float(loc[0]), float(loc[1])
        username = os.environ.get("GEONAMES_USERNAME", "demo")
        try:
            res = requests.get(
                "https://secure.geonames.org/findNearbyPlaceNameJSON",
                params={
                    "lat": lat,
                    "lng": lon,
                    "cities": "cities1000",
                    "maxRows": 1,
                    "username": username,
                },
                timeout=5,
            )
        except requests.RequestException as exc:
            log.warning("geocode_request_failed", user_token=self.user_token, error=str(exc))
            if not self.location_geoname:
                self.location_geoname = "%.2f, %.2f" % (lat, lon)
            record_geocode("failure")
            return

        if not res.ok:
            log.warning("geocode_failed", user_token=self.user_token, status_code=res.status_code)
            if not self.location_geoname:
                self.location_geoname = "%.2f, %.2f" % (lat, lon)
            record_geocode("failure")
            return

        try:
            places = res.json().get("geonames") or []
        except ValueError as exc:
            log.warning("geocode_bad_json", user_token=self.user_token, error=str(exc))
            if not self.location_geoname:
                self.location_geoname = "%.2f, %.2f" % (lat, lon)
            record_geocode("failure")
            return

        if places:
            self.location_geoname = places[0]["name"]
            record_geocode("success")
        elif not self.location_geoname:
            self.location_geoname = "%.2f, %.2f" % (lat, lon)
            record_geocode("failure")
        else:
            record_geocode("failure")

    @property
    def config(self):
        if not hasattr(self, "_config_inst"):
            self._config_inst = dict(self.DEFAULT_CONFIG)
            self._config_inst.update(self._sparse_config)
        return self._config_inst

    def save(self):
        # Paste _config_inst back into _sparse_config if reqd.
        if hasattr(self, "_config_inst"):
            # Transfer updated keys if not default
            for k,v in self._config_inst.items():
                if self.DEFAULT_CONFIG[k] != v:
                    self._sparse_config[k] = v
                elif k in self._sparse_config:
                    del self._sparse_config[k]
            # Remove deleted keys
            for k,v in self.DEFAULT_CONFIG.items():
                if k not in self._config_inst and k in self._sparse_config:
                    del self._sparse_config[k]
        super(User, self).save()


class TimetableCachedTimes(me.Document):
    key = me.StringField()
    location_geoname = me.StringField()
    times = me.DictField()

    meta = {
        'indexes': [
            'key'
        ]
    }

MONGO_URI = os.environ.get('MONGOLAB_URI', None)
MONGODB_SETTINGS = {}
if not MONGO_URI:
    me.connect('qibla')
else:
    me.connect(MONGO_URI.split("/")[-1], host=MONGO_URI)
