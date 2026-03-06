pebble-qibla-www
================

The server-side counterpart to [pebble-qibla](https://github.com/cpfair/pebble-qibla), the Qibla compass & prayer time app for Pebble.

## Deploying (e.g. Railway)

If you forked this and don’t have the original setup:

1. **MongoDB** (required)  
   Create a free cluster at [MongoDB Atlas](https://www.mongodb.com/cloud/atlas). Create a database user, get the connection string, and set it as **`MONGOLAB_URI`** in your host’s environment (Railway → Variables). The app uses the database name from the URI (e.g. `qibla`).

2. **GeoNames** (optional)  
   For geocoding, get a free username at [geonames.org](https://www.geonames.org/) and set **`GEONAMES_USERNAME`**. If unset, the app uses the public `demo` user (rate-limited).

3. **Sentry** (optional)  
   For error tracking, create a project at [sentry.io](https://sentry.io) and set **`SENTRY_DSN`**. If unset, the app runs without Sentry.

4. **Cron**  
   Prayer timeline pins are pushed by `cron.py`. Run it on a schedule (e.g. [cron-job.org](https://cron-job.org) calling an endpoint you add, or a separate worker/cron service) with the same `MONGOLAB_URI` (and any other env) set.
