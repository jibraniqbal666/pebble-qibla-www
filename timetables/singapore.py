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

# MUIS 2026+ PDFs use optional spaces in dates, e.g. "10/1/ 2026" and "1/10/ 2026".
_ROW_RE = re.compile(
    r"(?P<date>\d+\s*/\s*\d+\s*/\s*\d{4})\s+\w+\s+"
    r"(?P<fajr>\d{1,2}\s+\d\n?\d)\s+(?P<sunrise>\d{1,2}\s+\d\n?\d)\s+"
    r"(?P<dhuhr>\d{1,2}\s+\d\n?\d)\s+(?P<asr>\d{1,2}\s+\d\n?\d)\s+"
    r"(?P<magrib>\d{1,2}\s+\d\n?\d)\s+(?P<isha>\d{1,2}\s+\d\n?\d)"
)

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
        if len(raw) < 8 or not raw.startswith(b"%PDF"):
            raise RuntimeError(
                "Singapore timetable URL did not return a PDF (year=%s url=%s first_bytes=%r)"
                % (date.year, url, raw[:120])
            )
        try:
            time_table_pdf = PdfReader(io.BytesIO(raw), strict=False)
        except PdfReadError as e:
            raise RuntimeError(
                "Singapore timetable PDF could not be read (year=%s url=%s): %s"
                % (date.year, url, e)
            ) from e
        results = []
        for page in time_table_pdf.pages:
            text = page.extract_text() or ""
            for time_row in _ROW_RE.finditer(text):
                date_parts = [p.strip() for p in time_row.group("date").split("/")]
                row_date = datetime.date(
                    day=int(date_parts[0]),
                    month=int(date_parts[1]),
                    year=int(date_parts[2]),
                )
                results.append(("Singapore", row_date, {
                    "fajr":    cls._mangleTime(time_row.group("fajr"), row_date, False),
                    "sunrise": cls._mangleTime(time_row.group("sunrise"), row_date, False),
                    "dhuhr":   cls._mangleTime(time_row.group("dhuhr"), row_date, True),
                    "asr":     cls._mangleTime(time_row.group("asr"), row_date, True),
                    "maghrib": cls._mangleTime(time_row.group("magrib"), row_date, True),
                    "isha":    cls._mangleTime(time_row.group("isha"), row_date, True)
                }))

        results.sort(key=lambda x: x[1])
        last_date = None
        for result in results:
            row_date = result[1]
            if last_date is not None and row_date != last_date + datetime.timedelta(days=1) and row_date != last_date:
                raise RuntimeError(
                    "Singapore PDF parse gap: after %s next is %s (year=%s url=%s)"
                    % (last_date, row_date, date.year, url)
                )
            last_date = row_date
        n = len(results)
        if n not in (365, 366):
            raise RuntimeError(
                "Singapore PDF expected 365 or 366 days, got %s (year=%s url=%s)"
                % (n, date.year, url)
            )
        return results
