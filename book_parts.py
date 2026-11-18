"""ALiS永楽 自動予約チェッカーの「画面操作」の部品(check.py から使う)"""
import os

BOOK_URL = "https://book.squareup.com/appointments/jjrlxic0iqozmk/location/LZ3BS3Y7KEAKD/services/3CIYMNCBEMMPYIQDLU267PIZ"


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
    # カレンダー(週の切り替えボタン)が出るまで待つ。今日の枠が無い日は時間の一覧が出えへんから、それは待たへん
    pg.get_by_test_id("next-week-button").wait_for(timeout=30000)
    pg.wait_for_timeout(500)
    want = [f"date-{day.day}-selected"]
    for _ in range(8):
        if pg.evaluate(SEL_JS) == want:
            try:
                pg.get_by_test_id("time-slot").first.wait_for(timeout=5000)
            except Exception:
                pass
            return True
        btn = pg.get_by_test_id(f"date-{day.day}")
        if btn.count():
            btn.click(timeout=3000)
            try:
                pg.wait_for_function(f"() => !!document.querySelector('[data-testid=\"date-{day.day}-selected\"]')", timeout=2500)
                try:
                    pg.get_by_test_id("time-slot").first.wait_for(timeout=5000)
                except Exception:
                    pass
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
    el = slot.first
    try:
        el.scroll_into_view_if_needed(timeout=3000)
        el.click(timeout=6000)
    except Exception:
        el.evaluate("e => e.click()")          # 何かに隠れて押せへん時は直接押す
    try:
        pg.wait_for_url("**/checkout", timeout=15000)
    except Exception:
        text = " ".join(pg.inner_text("body").split())[:150]
        raise RuntimeError(f"時間を押しても入力画面に進まへん(画面:{pg.url.rsplit('/', 1)[-1]} / {text})")
    pg.locator("market-field[name=phone] input").first.fill(info["BOOK_PHONE"])
    pg.locator("market-field[name=lastName] input").first.fill(info["BOOK_LAST"])
    pg.locator("market-field[name=firstName] input").first.fill(info["BOOK_FIRST"])
    pg.locator("market-field[name=email] input").first.fill(info["BOOK_EMAIL"])
    pg.wait_for_timeout(800)
    # 「以前、Square 予約で予約されたことがあるようです」のポップアップが出たら「ゲストとして続行する」を押す
    guest_ok = dismiss_login_popup(pg)
    btn = pg.get_by_test_id("book-appointment-button-mobile")
    if not btn.is_visible():
        btn = pg.get_by_test_id("book-appointment-button-desktop")
    # 押せる状態か確認(ここで押されへんなら、何かが邪魔してる)
    clickable = False
    for _ in range(3):
        try:
            btn.click(trial=True, timeout=3000)
            clickable = True
            break
        except Exception:
            guest_ok = dismiss_login_popup(pg) or guest_ok
    if not submit:
        note = "ポップアップをゲストで閉じた。" if guest_ok else ""
        state = "「予約する」も押せる状態" if clickable else "「予約する」が押されへん状態"
        return "held", f"入力まで成功、{note}{state}(テストやから送信はしてへん。枠は10分で自動解除)"
    if not clickable:
        return "fail", "「予約する」ボタンが押されへんかった(何かのポップアップが邪魔してるかも)"
    btn.click(timeout=5000)
    # 完了画面に切り替わるのを最大25秒待つ
    for _ in range(50):
        pg.wait_for_timeout(500)
        if dismiss_login_popup(pg):          # 送信後に出た時も、ゲストで続ける
            try:
                btn.click(timeout=5000)
            except Exception:
                pass
            continue
        body = pg.inner_text("body")
        if any(w in body for w in ("確認コードを入力", "認証コード", "確認番号")):
            return "fail", "確認コードの入力を求められて止まった。10分以内やったら予約ページから手動で続けてな"
        if "checkout" not in pg.url or any(w in body for w in ("確定", "完了", "ありがとう", "予約済み")):
            return "ok", f"予約できた(画面:{pg.url.rsplit('/', 1)[-1].split('?')[0]})"
    # 入力画面のまま → 何かエラーが出てる(個人情報は残さへんように、エラーっぽい行だけ拾う)
    errs = [l for l in body.splitlines() if any(w in l for w in ("エラー", "無効", "できません", "入力してください", "利用できません"))]
    return "fail", "送信しても完了画面にならへんかった。念のためメールを確認して" + (f"(画面の表示:{' / '.join(errs)[:120]})" if errs else "")


def dismiss_login_popup(pg):
    """ログインを勧めるポップアップが出てたら「ゲストとして続行する」を押す。押したら True。"""
    try:
        g = pg.locator("market-dialog").get_by_text("ゲストとして続行する")
        if g.count() and g.first.is_visible():
            g.first.click(timeout=3000)
            pg.wait_for_timeout(800)
            return True
    except Exception:
        pass
    return False


def new_page(p):
    browser = p.chromium.launch(channel="chrome")
    pg = browser.new_page(locale="ja-JP", timezone_id="Asia/Tokyo", viewport={"width": 390, "height": 844})
    pg.set_default_timeout(20000)
    return browser, pg
