# -*- coding: utf-8 -*-
"""Ngirim notifikasi push (FCM) sadurunge acara ing jadwal Al Mukarram.
Jadwal-e ing .github/workflows/kirim-notifikasi.yml ditulis "saben 5 menit"
(cron */5), NANGING GitHub Actions ora njamin iku -- diukur langsung saka
riwayat run tenanan (16 Ags 2026), jarak antar-run pancen 21-207 menit, ora
tau persis 5 menit (iki wewatesan/kebiasaan GitHub sing "best effort", dudu
salah setelan). Mula wewatesan jendhela notifikasi (di ngisor) kudu luwih
amba tinimbang jarak run paling adoh sing tau kedadeyan, supaya paling
during ana siji run sing kejegur jendhela sadurunge acara diwiwiti --
dedup liwat /notified aman sanajan jendhela amba (siji kunci per acara+jam
persis, ora bakal kirim bola-bali sanajan katut ing pirang-pirang run).

Logika "acara sabanjure" (next_occurrence) ing ngisor iki PORT LANGSUNG saka
D:\\Ngudi Susilo\\_Widget-Sholat\\jawa.py (widget Tkinter) -- iki salinan katelu
sawise JS port ing jadwal-almukarram.html; yen jawa.py diowahi maneh (mis. bug
fix), salinan iki kudu di-tempel manual maneh, ora otomatis sinkron.
"""
import datetime
import hashlib
import json
import os
import sys
import urllib.request
import urllib.error

import google.auth.transport.requests
from google.oauth2 import service_account

DATABASE_URL = "https://jadwalku-270ce-default-rtdb.asia-southeast1.firebasedatabase.app"
PROJECT_ID = "jadwalku-270ce"
NOTIF_WINDOW_MIN_LOW = -15
NOTIF_WINDOW_MIN_HIGH = 240

SCOPES = [
    "https://www.googleapis.com/auth/firebase.database",
    "https://www.googleapis.com/auth/firebase.messaging",
    "https://www.googleapis.com/auth/userinfo.email",
]

# ====== jawa.py (ported, see docstring ndhuwur) ======
PASARAN = ["Legi", "Pahing", "Pon", "Wage", "Kliwon"]
ANCHOR = datetime.date(1945, 8, 17)
WEEKDAY_JAWA = ["Senin", "Selasa", "Rebo", "Kemis", "Jemuah", "Setu", "Ahad"]
HIJRI_BULAN = ["", "Muharram", "Shafar", "Rabi'ul Awwal", "Rabi'ul Akhir",
               "Jumadil Ula", "Jumadil Akhir", "Rajab", "Sya'ban", "Ramadhan",
               "Syawal", "Dzulqa'dah", "Dzulhijjah"]
_HIJRI_EPOCH = 1948440


def pasaran_of(d):
    return PASARAN[(d - ANCHOR).days % 5]


def weekday_jawa_of(d):
    return WEEKDAY_JAWA[d.weekday()]


def dina_jawa_efektif(now, maghrib_hm):
    h, m = maghrib_hm
    maghrib_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now >= maghrib_dt:
        return now.date() + datetime.timedelta(days=1)
    return now.date()


def _gregorian_to_jdn(d):
    y, m, day = d.year, d.month, d.day
    a = (14 - m) // 12
    y2 = y + 4800 - a
    m2 = m + 12 * a - 3
    return (day + (153 * m2 + 2) // 5 + 365 * y2 + y2 // 4 - y2 // 100 + y2 // 400 - 32045)


def _islamic_to_jdn(year, month, day):
    return (day + -(-(29.5 * (month - 1)) // 1) + (year - 1) * 354
            + (3 + 11 * year) // 30 + _HIJRI_EPOCH - 1)


def gregorian_to_hijri(d):
    jdn = _gregorian_to_jdn(d)
    year = int((30 * (jdn - _HIJRI_EPOCH) + 10646) // 10631)
    month_start = _islamic_to_jdn(year, 1, 1)
    month = min(12, int(-(-(jdn - (29 + month_start)) // 29.5)) + 1)
    day = int(jdn - _islamic_to_jdn(year, month, 1) + 1)
    return year, month, day


def next_occurrence(event, now, maghrib_lookup, horizon_days=40):
    today_jawa = dina_jawa_efektif(now, maghrib_lookup(now.date()) or (18, 0))

    if event.get("date") or event.get("date_start"):
        ds = event.get("date_start") or event["date"]
        de = event.get("date_end") or event.get("date") or ds
        end_date = datetime.date.fromisoformat(de)
        start_date = datetime.date.fromisoformat(ds)
        if event.get("jam"):
            hh, mm = event["jam"].split(":")
            start_time = datetime.time(int(hh), int(mm))
            end_dt = datetime.datetime.combine(end_date, start_time)
        else:
            start_time = datetime.time(0, 0)
            end_dt = datetime.datetime.combine(end_date, datetime.time(23, 59))
        if end_dt >= now:
            return datetime.datetime.combine(start_date, start_time), start_date
        return None, None

    horizon = 370 if event.get("hijri_month") else horizon_days
    for i in range(horizon):
        cand = today_jawa + datetime.timedelta(days=i)
        if event.get("hijri_month"):
            _hy, hm_, hd = gregorian_to_hijri(cand)
            if hm_ != event["hijri_month"] or hd != event["hijri_day"]:
                continue
            if event.get("jam"):
                hh, mm = event["jam"].split(":")
                cand_dt = datetime.datetime.combine(cand, datetime.time(int(hh), int(mm)))
                check_dt = cand_dt
            else:
                cand_dt = datetime.datetime.combine(cand, datetime.time(0, 0))
                check_dt = datetime.datetime.combine(cand, datetime.time(23, 59, 59))
            if check_dt >= now:
                return cand_dt, cand
            continue
        if weekday_jawa_of(cand) != event["weekday"]:
            continue
        if event.get("pasaran") and pasaran_of(cand) != event["pasaran"]:
            continue
        civil_date = cand - datetime.timedelta(days=1) if event.get("malam") else cand
        if event.get("jam"):
            hh, mm = event["jam"].split(":")
            cand_dt = datetime.datetime.combine(civil_date, datetime.time(int(hh), int(mm)))
            check_dt = cand_dt
        else:
            if event.get("malam"):
                mg = maghrib_lookup(civil_date) or (18, 0)
                cand_dt = datetime.datetime.combine(civil_date, datetime.time(mg[0], mg[1]))
                check_dt = cand_dt
            else:
                cand_dt = datetime.datetime.combine(civil_date, datetime.time(0, 0))
                check_dt = datetime.datetime.combine(civil_date, datetime.time(23, 59, 59))
        if check_dt >= now:
            return cand_dt, cand
    return None, None


# ====== Firebase REST helpers (OAuth2 access token, bypasses RTDB rules) ======
def get_access_token():
    cred_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    creds = service_account.Credentials.from_service_account_file(cred_path, scopes=SCOPES)
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def db_get(path, token):
    url = DATABASE_URL.rstrip("/") + path + ".json"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data


def db_put(path, token, value):
    url = DATABASE_URL.rstrip("/") + path + ".json"
    body = json.dumps(value).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PUT",
                                  headers={"Authorization": "Bearer " + token,
                                           "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def db_delete(path, token):
    url = DATABASE_URL.rstrip("/") + path + ".json"
    req = urllib.request.Request(url, method="DELETE",
                                  headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def fcm_send(token, title, body, access_token):
    url = "https://fcm.googleapis.com/v1/projects/%s/messages:send" % PROJECT_ID
    payload = {"message": {"token": token, "notification": {"title": title, "body": body}}}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + access_token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        return True
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        print("  gagal token %s...: HTTP %s %s" % (token[:12], e.code, detail[:200]))
        return "UNREGISTERED" in detail or "NOT_FOUND" in detail or e.code in (400, 404)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "maghrib_map.json"), "r", encoding="utf-8") as f:
        maghrib_map = json.load(f)

    def maghrib_lookup(d):
        s = maghrib_map.get("%02d-%02d" % (d.month, d.day))
        if not s:
            return None
        hh, mm = s.split(":")
        return int(hh), int(mm)

    token = get_access_token()
    jadwal = db_get("/jadwal", token) or []
    tokens_map = db_get("/tokens", token) or {}
    notified_map = db_get("/notified", token) or {}

    now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)  # WIB
    fcm_tokens = list(tokens_map.keys())
    if not fcm_tokens:
        print("Boten wonten token FCM kadaftar, mandheg.")
        return

    due = []
    for ev in jadwal:
        dt, _ = next_occurrence(ev, now, maghrib_lookup)
        if dt is None:
            continue
        mins = (dt - now).total_seconds() / 60.0
        if NOTIF_WINDOW_MIN_LOW <= mins <= NOTIF_WINDOW_MIN_HIGH:
            due.append((ev, dt, mins))

    if not due:
        print("Boten wonten acara ing wewatesan %d menit kepengker nganti %d menit ngajeng." %
              (-NOTIF_WINDOW_MIN_LOW, NOTIF_WINDOW_MIN_HIGH))
        return

    dead_tokens = set()
    for ev, dt, mins in due:
        raw_key = "%s|%s" % (ev.get("label", ""), dt.isoformat())
        key = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()
        if key in notified_map:
            continue
        title = ev.get("label", "Jadwal Al Mukarram")
        if mins >= 0:
            body_txt = "Isih %d menit maneh (%02d:%02d WIB)" % (round(mins), dt.hour, dt.minute)
        else:
            body_txt = "Sampun wiwit %d menit kepengker (%02d:%02d WIB)" % (round(-mins), dt.hour, dt.minute)
        pend = ev.get("pendherek") or []
        if pend:
            body_txt += " · bersama " + ", ".join(pend)
        print("Ngirim: %s (H-%d menit) dhateng %d token" % (title, round(mins), len(fcm_tokens)))
        any_ok = False
        for tok in fcm_tokens:
            result = fcm_send(tok, title, body_txt, token)
            if result is True:
                any_ok = True
            elif result == "UNREGISTERED" or result is True and False:
                dead_tokens.add(tok)
        db_put("/notified/" + key, token, {"label": title, "ts": int(now.timestamp())})

    for tok in dead_tokens:
        print("Mbusak token mati:", tok[:12] + "...")
        db_delete("/tokens/" + tok, token)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)
