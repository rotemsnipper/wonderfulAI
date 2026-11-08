"""Spike: download the BTS T-100 Segment (All Carriers) for one year by replaying the TranStats download form.

Usage: python fetch_t100_segment.py YEAR OUT.zip
"""
import re
import sys
import zipfile
from pathlib import Path

import requests

URL = "https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4%20Pn44vr45"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"
FIELDS = ["YEAR", "MONTH", "UNIQUE_CARRIER", "UNIQUE_CARRIER_NAME", "ORIGIN_AIRPORT_ID", "ORIGIN",
          "ORIGIN_CITY_NAME", "ORIGIN_STATE_ABR", "ORIGIN_COUNTRY", "DEST_AIRPORT_ID", "DEST", "DEST_CITY_NAME",
          "DEST_STATE_ABR", "DEST_COUNTRY", "DEPARTURES_SCHEDULED", "DEPARTURES_PERFORMED", "SEATS",
          "PASSENGERS", "FREIGHT", "DISTANCE", "AIR_TIME", "AIRCRAFT_TYPE", "CLASS", "DATA_SOURCE"]

year, dest = sys.argv[1], Path(sys.argv[2])
s = requests.Session()
s.headers["User-Agent"] = UA
page = s.get(URL, timeout=120).text
form = {k: re.search(r'id="%s" value="([^"]*)"' % k, page).group(1)
        for k in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")}
form.update({"__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "", "cboGeography": "All",
             "cboPeriod": "All", "chkDownloadZip": "on", "btnDownload": "Download", "cboYear": year})
form.update({f: "on" for f in FIELDS})
r = s.post(URL, data=form, timeout=900, headers={"Referer": URL})
print("status", r.status_code, "bytes", len(r.content))
dest.write_bytes(r.content)
print("is_zip", zipfile.is_zipfile(dest))
