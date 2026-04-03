from .base import Timetable
import datetime
from pytz import timezone, utc
import requests
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError
import re
import io

# Many CDNs (e.g. CloudFront in front of isomer) return 403 HTML for the default python-requests UA.
_PDF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PebbleQibla/1.0;"
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
}

timetable_pdfs = {
    2016: "http://www.muis.gov.sg/documents/Resource_Centre/Prayer_Timetable_2016.pdf",
    2017: "http://www.muis.gov.sg/documents/Resource_Centre/Prayer%20Timetable%202017.pdf",
    2018: "https://www.muis.gov.sg/-/media/Files/Corporate-Site/Prayer-Timetable-2018.pdf",
    2026: "https://isomer-user-content.by.gov.sg/48/f989baef-c5eb-440e-b3bb-874626a0664e/Prayer%20timetable%202026.pdf"
}

class Singapore(Timetable):
    @classmethod
    def CacheKey(cls, location, date):
        return ""

    @classmethod
    def _mangleTime(cls, time_str, date, aft):
        time = datetime.datetime.strptime(time_str.replace("\n", ""), "%H %M").time()
        if aft:
            if time.hour < 12:
                time = time.replace(hour=time.hour + 12)
        dt = timezone("Asia/Singapore").localize(datetime.datetime.combine(date, time))
        utc_dt = dt.astimezone(utc).replace(tzinfo=None)
        since_midnight = utc_dt - datetime.datetime.combine(date, datetime.datetime.min.time())
        return since_midnight.total_seconds() / 3600

    @classmethod
    def Times(cls, location, date):
        url = timetable_pdfs[date.year]
        time_table_pdf_req = requests.get(url, headers=_PDF_HEADERS, timeout=90)
        time_table_pdf_req.raise_for_status()
        raw = time_table_pdf_req.content
        try:
            time_table_pdf = PdfReader(io.BytesIO(raw), strict=False)
        except PdfReadError as e:
            raise RuntimeError(
                "Singapore timetable PDF could not be read (year=%s url=%s): %s"
                % (date.year, url, e)
            ) from e
        results = []
        for page in time_table_pdf.pages:
            text = page.extract_text()
            for time_row in re.finditer(r"(?P<date>\d+\n?/\n?\d+\n?/\n?\d{4})\s+\w+\s+(?P<fajr>\d{1,2}\s+\d\n?\d)\s+(?P<sunrise>\d{1,2}\s+\d\n?\d)\s+(?P<dhuhr>\d{1,2}\s+\d\n?\d)\s+(?P<asr>\d{1,2}\s+\d\n?\d)\s+(?P<magrib>\d{1,2}\s+\d\n?\d)\s+(?P<isha>\d{1,2}\s+\d\n?\d)", text):
                date_parts = list(int(x.strip()) for x in time_row.group("date").split("/"))
                date = datetime.date(day=date_parts[0], month=date_parts[1], year=date_parts[2])
                results.append(("Singapore", date, {
                    "fajr":    cls._mangleTime(time_row.group("fajr"), date, False),
                    "sunrise": cls._mangleTime(time_row.group("sunrise"), date, False),
                    "dhuhr":   cls._mangleTime(time_row.group("dhuhr"), date, True),
                    "asr":     cls._mangleTime(time_row.group("asr"), date, True),
                    "maghrib": cls._mangleTime(time_row.group("magrib"), date, True),
                    "isha":    cls._mangleTime(time_row.group("isha"), date, True)
                }))

        # Check nothing is missing for the year...
        missing_data = False
        last_date = None
        for result in sorted(results, key=lambda x: x[1]):
            if last_date:
                if result[1] != last_date + datetime.timedelta(days=1):
                    missing_data = True
                    print("Skip %s -> %s" % (last_date, result[1]))
            last_date = result[1]
        assert not missing_data
        assert len(results) in (365, 366)
        return results
