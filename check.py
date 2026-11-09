"""ALiS永楽 自動予約チェッカー
ヘアセット 洋装 / りりさん / 平日 19:30〜19:45 スタートの枠が空いたら自動で予約し、LINE で知らせる。
1日1枠まで(お店のルールで同じ日に2枠は不可)。別の日は何件でも取る。
"""
import datetime as dt
import json
import os
import pathlib
import urllib.request
from zoneinfo import ZoneInfo

# ===== 設定(ここを変えれば条件を変えられる) =====
EARLIEST = (19, 30)        # この時刻以降に始まる枠
LATEST = (19, 45)          # この時刻までに始まる枠
WEEKDAYS_ONLY = True       # 平日(月〜金)だけ
DAYS_AHEAD = 14            # 何日先まで見るか(お店の受付は2週間先まで)
AUTO_BOOK = True           # False にすると通知だけ
# =================================================

BOOK_URL = "https://book.squareup.com/appointments/jjrlxic0iqozmk/location/LZ3BS3Y7KEAKD/services/3CIYMNCBEMMPYIQDLU267PIZ"
API = "https://app.squareup.com/appointments/api/buyer/availability"
LOCATION_ID = "LZ3BS3Y7KEAKD"
SERVICE_ID = "OVJQUJSMSBROOCAAM44OAIOE"   # ヘアセット > 洋装
STAFF_TOKEN = "TMlZNABHoCnIPfIk"          # りり
STAFF_ID = "qnrg2pynk9mmo2"

JST = ZoneInfo("Asia/Tokyo")
STATE = pathlib.Path("state.json")
YOUBI = "月火水木金土日"


# ---------- 空き枠を調べる ----------
def fetch_slots(now):
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = (start + dt.timedelta(days=DAYS_AHEAD + 1)) - dt.timedelta(milliseconds=1)
    body = {"search_availability_request": {"query": {"filter": {
        "start_at_range": {
            "start_at": start.isoformat(timespec="milliseconds"),
            "end_at": end.isoformat(timespec="milliseconds"),
        },
        "location_id": LOCATION_ID,
        "segment_filters": [{
            "service_variation_id": SERVICE_ID,
            "team_member_id_filter": {"any": [STAFF_TOKEN]},
        }],
    }}}}
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://book.squareup.com",
        "Referer": "https://book.squareup.com/",
        "User-Agent": "Mozilla/5.0",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    slots = set()
    for a in data.get("availability", []):
        if a.get("available") and a.get("staff_id") == STAFF_ID:
            slots.add(dt.datetime.fromtimestamp(a["start"], JST))
    return sorted(t for t in slots if t > now)


def wanted(t):
    if WEEKDAYS_ONLY and t.weekday() >= 5:
        return False
    return EARLIEST <= (t.hour, t.minute) <= LATEST


def label(t):
    return f"{t.month}/{t.day}({YOUBI[t.weekday()]}) {t:%H:%M}"


# ---------- 予約する ----------
SEL_JS = "() => [...document.querySelectorAll('[data-testid^=date-]')].map(e=>e.dataset.testid).filter(x=>x.endsWith('-selected'))"
TIMES_JS = "() => [...document.querySelectorAll('[data-testid=time-slot]')].map(e=>e.innerText.trim())"


def booking_info():
    info = {k: os.getenv(k, "").strip() for k in ("BOOK_LAST", "BOOK_FIRST", "BOOK_PHONE", "BOOK_EMAIL")}
    if not all(info.values()):
        return None
    phone = info["BOOK_PHONE"].replace("-", "").replace(" ", "")
    if phone.startswith("+81"):
        phone = phone[3:]
    info["BOOK_PHONE"] = phone.lstrip("0")
    return info


def prepare(pg):
    """メニューとりりさんを選んだ状態(「予約」ボタンを押す直前)まで進める。"""
    pg.goto(BOOK_URL, wait_until="load", timeout=60000)
    pg.locator("label", has_text="洋装").first.click()
    pg.locator("label", has_text="りり").first.click()
    pg.wait_for_timeout(500)


def go_calendar(pg, day):
    """「予約」を押してカレンダーを出し、day(日付)を選ぶ。押した時点の最新の空き枠が読み込まれる。"""
    pg.get_by_text("予約", exact=True).last.click()
    pg.get_by_test_id("time-slot").first.wait_for(timeout=30000)
    want = [f"date-{day.day}-selected"]
    for _ in range(8):
        if pg.evaluate(SEL_JS) == want:
            return True
        btn = pg.get_by_test_id(f"date-{day.day}")
        if btn.count():
            btn.click(timeout=3000)
            try:
                pg.wait_for_function(f"() => !!document.querySelector('[data-testid=\"date-{day.day}-selected\"]')", timeout=2500)
                pg.wait_for_timeout(300)
                return True
            except Exception:
                pass
        pg.get_by_test_id("next-week-button").click()
        pg.wait_for_timeout(700)
    return pg.evaluate(SEL_JS) == want


def open_calendar(pg, day):
    prepare(pg)
    return go_calendar(pg, day)


def checkout(pg, t, info, submit=True):
    """時間を押して、名前などを入れて予約する。"""
    slot = pg.get_by_test_id("time-slot").filter(has_text=f"{t:%H:%M}")
    if not slot.count():
        return "fail", "画面に行ったら枠がもう無かった(先に取られたかも)"
    slot.first.click()
    pg.wait_for_url("**/checkout", timeout=15000)
    pg.locator("market-field[name=phone] input").first.fill(info["BOOK_PHONE"])
    pg.locator("market-field[name=lastName] input").first.fill(info["BOOK_LAST"])
    pg.locator("market-field[name=firstName] input").first.fill(info["BOOK_FIRST"])
    pg.locator("market-field[name=email] input").first.fill(info["BOOK_EMAIL"])
    pg.wait_for_timeout(500)
    if not submit:
        return "held", "入力まで成功(テストやから送信はしてへん。枠は10分で自動解除)"
    btn = pg.get_by_test_id("book-appointment-button-mobile")
    if not btn.is_visible():
        btn = pg.get_by_test_id("book-appointment-button-desktop")
    btn.click()
    pg.wait_for_timeout(8000)
    body = pg.inner_text("body")
    if "checkout" not in pg.url or any(w in body for w in ("確定", "完了", "ありがとう", "予約済み")):
        return "ok", "予約できた"
    if any(w in body for w in ("コード", "認証", "確認番号")):
        return "fail", "確認コードの入力を求められて止まった。10分以内やったら予約ページから手動で続けてな"
    return "fail", "送信後に完了画面が出えへんかった。念のためメールを確認して"


def new_page(p):
    browser = p.chromium.launch(channel="chrome")
    pg = browser.new_page(locale="ja-JP", timezone_id="Asia/Tokyo", viewport={"width": 390, "height": 844})
    pg.set_default_timeout(20000)
    return browser, pg


def book(t, submit=True):
    """普段用:見つけた空き枠を予約する。結果を ("ok"|"held"|"fail", 説明) で返す。"""
    from playwright.sync_api import sync_playwright
    info = booking_info()
    if not info:
        return "fail", "予約用の Secrets(BOOK_LAST / BOOK_FIRST / BOOK_PHONE / BOOK_EMAIL)が足りへん"
    with sync_playwright() as p:
        browser, pg = new_page(p)
        step = "ページを開く"
        try:
            prepare(pg)
            step = "カレンダー表示"
            if not go_calendar(pg, t.date()):
                return "fail", "カレンダーで日付を選べへんかった"
            step = "時間を押して入力・送信"
            return checkout(pg, t, info, submit)
        except Exception as e:
            return "fail", f"「{step}」でエラー {type(e).__name__}"
        finally:
            browser.close()


def snipe(now, booked, log):
    """張り付きモード:2週間後の同じ日の19:30/19:45 は、今日の19:30/19:45 ぴったりに開く。
    開く少し前から画面を開いて待ち構えて、出た瞬間に予約する。"""
    import time
    from playwright.sync_api import sync_playwright

    day = now.date() + dt.timedelta(days=DAYS_AHEAD)
    targets = []
    h, m = EARLIEST
    while (h, m) <= LATEST:
        t = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=JST)
        if wanted(t) and t - dt.timedelta(days=DAYS_AHEAD) + dt.timedelta(minutes=20) > now:
            targets.append(t)
        m += 15
        h, m = h + m // 60, m % 60
    if not targets or day.isoformat() in booked:
        return
    info = booking_info()
    if not info:
        log.append("張り付きモード:予約用の Secrets が足りへんから中止")
        return

    log.append("張り付きモード:" + "、".join(label(t) for t in targets) + " を狙う")
    with sync_playwright() as p:
        browser, pg = new_page(p)
        try:
            for t in targets:
                open_at = t - dt.timedelta(days=DAYS_AHEAD)      # この時刻に枠が開く
                give_up = open_at + dt.timedelta(minutes=20)
                # 開く1分前まで待って、メニューとりりさんを選んだ状態で待ち構える
                wait = (open_at - dt.timedelta(seconds=60) - dt.datetime.now(JST)).total_seconds()
                if wait > 0:
                    time.sleep(wait)
                ready = False
                while dt.datetime.now(JST) < give_up:
                    if not ready:
                        try:
                            prepare(pg)
                            ready = True
                        except Exception:
                            time.sleep(1)
                            continue
                    try:
                        found = t in fetch_slots(dt.datetime.now(JST))
                    except Exception:
                        found = False
                    if not found:
                        time.sleep(1)
                        continue
                    ready = False
                    stamp = dt.datetime.now(JST).strftime("%H:%M:%S")
                    try:
                        if not go_calendar(pg, day):
                            log.append(f"張り付きモード {stamp}:カレンダーで日付を選べへんかった")
                            continue
                    except Exception as e:
                        log.append(f"張り付きモード {stamp}:カレンダー表示でエラー {type(e).__name__}(もう一回いく)")
                        continue
                    try:
                        result, msg = checkout(pg, t, info)
                    except Exception as e:
                        log.append(f"張り付きモード {stamp}:予約画面でエラー {type(e).__name__}(先に押さえられたかも。もう一回いく)")
                        continue
                    log.append(f"張り付きモード {stamp} {label(t)}: {msg}")
                    if result == "ok":
                        booked[day.isoformat()] = label(t)
                        send_line(f"🎉 予約取れたで！\nALiS永楽 ヘアセット(洋装) りりさん\n📅 {label(t)}\n\n行かれへん時は早めにキャンセルしてな。")
                        return
                log.append(f"張り付きモード {label(t)}: 取れへんかった")
        except Exception as e:
            log.append(f"張り付きモード:エラー {type(e).__name__}")
        finally:
            browser.close()


# ---------- LINE ----------
def send_line(text):
    token, uid = os.getenv("LINE_TOKEN"), os.getenv("LINE_USER_ID")
    if not token or not uid:
        print("LINE の設定(LINE_TOKEN / LINE_USER_ID)がまだやから通知は送らへん")
        return
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=json.dumps({"to": uid, "messages": [{"type": "text", "text": text[:4900]}]}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    urllib.request.urlopen(req, timeout=20)
    print("LINE 送信OK")


# ---------- メイン ----------
def main():
    now = dt.datetime.now(JST)
    today = now.date().isoformat()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state.setdefault("notified", [])
    booked = state.setdefault("booked_days", {})   # {"2026-11-12": "11/12(水) 19:30"}
    log = [f"## チェック結果 {now:%m/%d %H:%M}"]

    # 「予約済みを解除する日」(例: 11/12 、全部なら all)
    unbook = (os.getenv("UNBOOK_DAY") or "").strip()
    if unbook:
        for day in list(booked):
            d = dt.date.fromisoformat(day)
            if unbook.lower() == "all" or unbook in (f"{d.month}/{d.day}", f"{d.month:02d}/{d.day:02d}"):
                log.append(f"{booked.pop(day)} の予約済み記録を消した(その日もまた狙う)")

    # 過ぎた日の記録は消す
    for day in [d for d in booked if d < today]:
        booked.pop(day)

    if os.getenv("TEST_LINE") == "true":
        send_line("✅ テスト通知：空き枠チェッカーとLINEがつながったで")

    slots = fetch_slots(now)
    hits = [t for t in slots if wanted(t)]
    log.append(f"りりさんの空き枠(全時間帯): {len(slots)} 件 / 条件に合う枠: {len(hits)} 件")
    log += [f"- {label(t)}" for t in hits]
    if booked:
        log.append("予約済みの日: " + "、".join(booked[d] for d in sorted(booked)))

    # 予約テスト:一番先の枠で入力まで試す(送信はしない)
    if os.getenv("TEST_BOOKING") == "true" and slots:
        t = slots[-1]
        result, msg = book(t, submit=False)
        log.append(f"予約テスト {label(t)}: {msg}")
        send_line(f"🧪 予約テスト({label(t)}):{msg}")

    # 張り付きモード:17:40〜20:45 の間に動いた時だけ
    if AUTO_BOOK and (dt.time(17, 40) <= now.time() <= dt.time(LATEST[0] + 1, LATEST[1] % 60)):
        snipe(now, booked, log)
        now = dt.datetime.now(JST)
        slots = fetch_slots(now)
        hits = [t for t in slots if wanted(t)]

    done = set(state["notified"])
    for t in hits:
        day = t.date().isoformat()
        if day in booked or (not AUTO_BOOK and t.isoformat() in done):
            continue
        if AUTO_BOOK:
            result, msg = book(t)
            log.append(f"{label(t)} の予約: {msg}")
            if result == "ok":
                booked[day] = label(t)
                send_line(f"🎉 予約取れたで！\nALiS永楽 ヘアセット(洋装) りりさん\n📅 {label(t)}\n\n行かれへん時は早めにキャンセルしてな。")
            else:
                if t.isoformat() not in done:
                    send_line(f"⚠️ りりさんに空き({label(t)})が出たけど自動予約できへんかった。\n理由:{msg}\n\n急いで手動で👇\n{BOOK_URL}")
                done.add(t.isoformat())
        else:
            done.add(t.isoformat())
            send_line(f"🔔 りりさんに空きが出たで！\nALiS永楽 ヘアセット(洋装)\n・{label(t)}\n\n早めに予約してな👇\n{BOOK_URL}")
    state["notified"] = sorted(done & {t.isoformat() for t in hits})
    state.pop("booked", None)

    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    text = "\n".join(log)
    if len(log) > 2 or os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
        lf = pathlib.Path("log.md")
        old_lines = lf.read_text(encoding="utf-8").splitlines() if lf.exists() else []
        lf.write_text("\n".join((old_lines + [""] + log)[-400:]) + "\n", encoding="utf-8")
    print(text)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
