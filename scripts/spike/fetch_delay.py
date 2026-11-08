import string, sys, zipfile
from pathlib import Path
import requests

URL = "https://www.transtats.bts.gov/OT_Delay/ot_delaycause1_DL.aspx"
ALPHA = string.ascii_uppercase + string.ascii_lowercase + string.digits
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"

def enc(t):
    return "".join(ALPHA[(ALPHA.index(c) + 13) % 62] if c in ALPHA else c for c in t)

y0, m0, y1, m1, dest = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), Path(sys.argv[5])
q = enc(f"where yearmonth between {y0*12+m0} AND {y1*12+m1}")
r = requests.get(URL, params={"8n4": q}, headers={"User-Agent": UA}, timeout=300)
print("status", r.status_code, "bytes", len(r.content), "ctype", r.headers.get("content-type"))
dest.write_bytes(r.content)
print("is_zip", zipfile.is_zipfile(dest))
