#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import re
import sqlite3
import datetime
import os
import sys
import random
import subprocess

try:
    from PIL import Image, ImageDraw
    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False


def app_dir():
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
            base = os.path.join(base, "Dokon Daftari")
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support/Dokon Daftari")
        else:
            base = os.path.expanduser("~/.local/share/Dokon Daftari")
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            pass
        return base
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            base = meipass
        else:
            base = os.path.normpath(os.path.join(os.path.dirname(sys.executable), "..", "Resources"))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


DB_PATH = os.path.join(app_dir(), "dokon.db")
ICON_PATH = resource_path("icon.ico")
RECEIPTS_DIR = os.path.join(app_dir(), "cheklar")
BARCODE_LABELS_DIR = os.path.join(app_dir(), "shtrix kodlar")
# MUHIM (foydalanuvchi so'rovi bilan): har bir mahsulot uchun rasm
# qo'shish imkoniyati -- rasmlar shu papkada saqlanadi, "products.
# image_path" ustunida esa FAQAT fayl nomi (masalan "42.jpg") saqlanadi.
PRODUCT_IMAGES_DIR = os.path.join(app_dir(), "mahsulot rasmlari")
SETTINGS_PATH = os.path.join(app_dir(), "sozlamalar.json")
UNITS = ["dona", "kg", "litr", "metr"]
REPORT_DAYS = 30
UZ_MONTHS = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
             "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]

if sys.platform == "win32":
    FONT_SANS_NAME = "Segoe UI"
    FONT_MONO_NAME = "Consolas"
elif sys.platform == "darwin":
    FONT_SANS_NAME = "Helvetica Neue"
    FONT_MONO_NAME = "Menlo"
else:
    FONT_SANS_NAME = "DejaVu Sans"
    FONT_MONO_NAME = "DejaVu Sans Mono"


# ---------------------------------------------------------------------------
# BUG TUZATISH (sozlamalar yo'qolib qolishi -- Telegram token/admin/ruxsat
# berilganlar va printer sozlamalari 2-3 kundan keyin "uchib ketishi"):
#
# Sabab -- "lost update" musobaqasi (race condition). Dastur ichida bir
# nechta oqim (Telegram botining fon jarayoni -- doim ishlab turadi va
# har necha soniyada sozlamalarni o'qib-yozadi, GUI oqimi -- printer
# tanlaganda, Telegram sozlamalarini saqlaganda va h.k.) bir xil
# sozlamalar.json faylini HECH QANDAY UMUMIY QULFSIZ (lock) o'qib va
# qayta yozib turishardi:
#
#   settings = load_settings()      # A oqimi o'qiydi
#   settings = load_settings()      #   ...B oqimi ham ARALASHIB o'qiydi
#   settings["x"] = 1
#   save_settings(settings)         # B birinchi yozadi
#   settings["y"] = 2
#   save_settings(settings)         # A ESKI nusxa asosida yozadi -> B ning
#                                    # "x" o'zgarishi BUTUNLAY yo'qolib ketadi
#
# Bundan tashqari, `save_settings` faylni to'g'ridan-to'g'ri ("w" rejimida)
# yozar edi -- ya'ni avval faylni 0 baytga qisqartirib, keyin yozib
# chiqarardi. Agar aynan shu payt boshqa oqim ham faylni yozayotgan bo'lsa
# yoki dastur/kompyuter kutilmaganda o'chib qolsa, fayl YARIM YOZILGAN,
# BUZILGAN JSON holida qolib ketadi. `load_settings` esa har qanday
# xatolikni jimgina yutib, {} (bo'sh lug'at) qaytarardi -- shundan keyin
# birinchi bo'lib sozlamalarni saqlagan oqim BUTUN faylni shu bo'sh holat
# ustiga yozib, hamma narsani (Telegram token, admin ID, ruxsat
# berilganlar, printer nomi va h.k.) DOIMIY ravishda yo'qotardi.
#
# Tuzatish:
#   1) BUTUN dastur uchun BITTA umumiy qulf (_SETTINGS_LOCK, RLock --
#      qayta kirishga ruxsat beradi, shuning uchun bir xil oqim ichida
#      load/save/update ichma-ich chaqirilsa ham "deadlock" bo'lmaydi).
#   2) `save_settings` endi ATOM tarzda yozadi: avval vaqtinchalik faylga
#      to'liq yozib bo'lingach, `os.replace()` bilan asosiy faylga
#      almashtiradi -- shuning uchun yarim yozilgan/buzilgan holat
#      umuman yuzaga kelmaydi.
#   3) Har safar saqlashdan oldin oldingi holat .bak faylga zaxiralanadi;
#      agar asosiy fayl biror sababdan o'qib bo'lmasa, `load_settings`
#      uni jimgina {} qaytarish o'rniga avtomatik zaxiradan tiklaydi.
#   4) `update_settings(mutator)` -- o'qish+o'zgartirish+yozishni BITTA
#      qulf ostida, bo'linmas (atomik) tarzda bajaradigan yordamchi
#      funksiya. Yangi kod shuni ishlatishi kerak; eski
#      "load_settings()...save_settings()" juftliklari esa shu qulf bilan
#      o'ralgan (pastda `_telegram_lock()` shu umumiy qulfning o'ziga
#      ishora qiladi).
# ---------------------------------------------------------------------------
import threading as _threading_for_settings
_SETTINGS_LOCK = _threading_for_settings.RLock()
_SETTINGS_BACKUP_PATH = SETTINGS_PATH + ".bak"


def _read_settings_file(path):
    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_settings_file(path, data):
    import json
    import tempfile
    dir_name = os.path.dirname(path) or "."
    try:
        os.makedirs(dir_name, exist_ok=True)
    except Exception:
        pass
    fd, tmp_path = tempfile.mkstemp(prefix=".sozlamalar_", suffix=".tmp", dir=dir_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def load_settings():
    with _SETTINGS_LOCK:
        try:
            return _read_settings_file(SETTINGS_PATH)
        except Exception:
            pass
        # Asosiy fayl o'qilmadi (buzilgan/yo'q) -- zaxiradan tiklashga
        # urinamiz, shu bilan sozlamalar butunlay yo'qolib qolmaydi.
        try:
            data = _read_settings_file(_SETTINGS_BACKUP_PATH)
        except Exception:
            return {}
        try:
            _write_settings_file(SETTINGS_PATH, data)
        except Exception:
            pass
        return data


def save_settings(data):
    with _SETTINGS_LOCK:
        try:
            if os.path.exists(SETTINGS_PATH):
                try:
                    current = _read_settings_file(SETTINGS_PATH)
                    _write_settings_file(_SETTINGS_BACKUP_PATH, current)
                except Exception:
                    pass
            _write_settings_file(SETTINGS_PATH, data)
        except Exception:
            pass


def settings_lock():
    """GUI qatlami (dokon_gui.py) uchun ochiq nom -- sozlamalarni o'qib
    o'zgartirib qayta yozadigan har qanday kod shu qulf ostida
    bajarilishi kerak (Telegram fon oqimi bilan bir xil qulf)."""
    return _SETTINGS_LOCK


def update_settings(mutator):
    """Sozlamalarni bo'linmas (atomik) tarzda o'qib, `mutator(settings)`
    orqali o'zgartirib, qayta saqlaydi. `mutator` lug'atni joyida
    o'zgartirishi mumkin, yoki yangi lug'at qaytarishi mumkin (qaytgan
    qiymat None bo'lmasa, o'sha saqlanadi). BUTUN jarayon bitta qulf
    ostida bajarilgani uchun boshqa oqimning orada "aralashib" sozlama
    o'zgarishini yo'qotib qo'yishi mumkin emas."""
    with _SETTINGS_LOCK:
        s = load_settings()
        result = mutator(s)
        if result is not None:
            s = result
        save_settings(s)
        return s

# ---------------------------------------------------------------------------
# Ma'lumotlar bazasi
# ---------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_column_if_missing(conn, table, col_def):
    col_name = col_def.split()[0]
    existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if col_name not in existing:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            cost_price REAL NOT NULL DEFAULT 0,
            price REAL NOT NULL,
            qty REAL NOT NULL,
            unit TEXT NOT NULL DEFAULT 'dona',
            barcode TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            product_name TEXT NOT NULL,
            qty REAL NOT NULL,
            unit TEXT NOT NULL DEFAULT 'dona',
            cost_price REAL NOT NULL DEFAULT 0,
            price REAL NOT NULL,
            list_price REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL,
            profit REAL NOT NULL DEFAULT 0,
            payment_type TEXT NOT NULL DEFAULT 'naqd',
            date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT,
            amount REAL NOT NULL,
            note TEXT,
            date TEXT NOT NULL,
            paid INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS debt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debt_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            qty REAL NOT NULL,
            unit TEXT NOT NULL DEFAULT 'dona',
            FOREIGN KEY (debt_id) REFERENCES debts(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS day_closures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            closed_at TEXT NOT NULL,
            sales_naqd REAL NOT NULL DEFAULT 0,
            profit_naqd REAL NOT NULL DEFAULT 0,
            sales_nasiya REAL NOT NULL DEFAULT 0,
            profit_nasiya REAL NOT NULL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS telegram_sale_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_batch TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            message_id INTEGER NOT NULL
        )
    """)
    # MUHIM (foydalanuvchi so'rovi bilan -- "to'langani naqdga qo'shilsinmi?"):
    # nasiyaga savdo qilinganda, xaridor hozir bir qismini (paid_now) darhol
    # to'lasa, o'sha summa "Bugungi savdo (naqd)" ko'rsatkichiga qo'shilishi,
    # qolgan qismi esa "nasiya" ko'rsatkichida qolishi kerak. Buning uchun
    # har bir savdo partiyasi (sale_batch) uchun hozir to'langan summa shu
    # yerda saqlanadi -- keyinchalik hisobot so'rovlarida ANIQ shu qiymat
    # bo'yicha (taxminiy emas) naqd/nasiya orasida taqsimlash uchun.
    c.execute("""
        CREATE TABLE IF NOT EXISTS sale_batch_meta (
            sale_batch TEXT PRIMARY KEY,
            paid_now REAL NOT NULL DEFAULT 0
        )
    """)
    # Qarz bo'yicha keyinroq olingan to'lovlar (qisman yoki oxirgi). Bu
    # summalar to'lov olingan KUNNING naqd savdosiga qo'shiladi (foyda esa
    # faqat qarz TO'LIQ to'langanda hisoblanadi -- o'zgarmagan).
    c.execute("""
        CREATE TABLE IF NOT EXISTS debt_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debt_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            closure_id INTEGER,
            is_final INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()

    _add_column_if_missing(conn, "products", "unit TEXT NOT NULL DEFAULT 'dona'")
    _add_column_if_missing(conn, "products", "cost_price REAL NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "products", "barcode TEXT")
    # MUHIM (foydalanuvchi so'rovi bilan): mahsulot rasmi -- faqat fayl
    # nomi saqlanadi (masalan "42.jpg"), haqiqiy fayl PRODUCT_IMAGES_DIR
    # papkasida turadi.
    _add_column_if_missing(conn, "products", "image_path TEXT")
    _add_column_if_missing(conn, "sales", "product_id INTEGER")
    _add_column_if_missing(conn, "sales", "unit TEXT NOT NULL DEFAULT 'dona'")
    _add_column_if_missing(conn, "sales", "payment_type TEXT NOT NULL DEFAULT 'naqd'")
    _add_column_if_missing(conn, "sales", "created_at TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "sales", "cost_price REAL NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "sales", "profit REAL NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "sales", "closure_id INTEGER")
    _add_column_if_missing(conn, "sales", "list_price REAL NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "sales", "payment_method TEXT")
    _add_column_if_missing(conn, "sales", "sale_batch TEXT")
    _add_column_if_missing(conn, "debts", "phone TEXT")
    # MUHIM: quyidagi ikkitasi -- qarz (nasiya) to'langanda uning foydasini
    # "Bugungi foyda"ga (naqd foyda hisobiga) qo'shib qo'yish uchun kerak.
    # sale_batch -- shu qarzni yaratgan asl sotuv partiyasi (shu orqali,
    # to'langanda o'sha partiyaning haqiqiy profit'ini sales jadvalidan olib
    # hisoblaymiz -- taxminiy emas, aniq qiymat). paid_date -- qachon
    # to'langani (naqd foydaga faqat TO'LANGAN KUNI qo'shiladi).
    _add_column_if_missing(conn, "debts", "sale_batch TEXT")
    _add_column_if_missing(conn, "debts", "paid_date TEXT")
    conn.commit()
    conn.close()

    # MUHIM: "sale_batch" ustuni ENDI qo'shildi -- lekin bundan OLDIN
    # yaratilgan (eski) nasiya qarzlarda bu maydon bo'sh (NULL) qoladi,
    # shuning uchun ular hech qachon "to'landi" deb belgilansa ham foydasi
    # "Foyda"ga o'tmay qolaverardi (aynan shu muammo foydalanuvchi
    # tomonidan skrinshotda ko'rsatildi: Qarzdorlik=0 bo'lsa ham, "Nasiya
    # foydasi" hamon "kutilayotgan" bo'lib turardi). Shu sababli, dastur har
    # safar ochilganda, sale_batch'i yo'q eski qarzlarni ularning
    # debt_items (mahsulot nomi/miqdori) ro'yxati bilan, o'sha kungi nasiya
    # sotuvlar orasidan MOS partiyani (sale_batch) topib, BIR MARTALIK
    # avtomatik "bog'lab qo'yish" (backfill) amalga oshiriladi.
    _backfill_debt_sale_batches()

    os.makedirs(RECEIPTS_DIR, exist_ok=True)
    os.makedirs(BARCODE_LABELS_DIR, exist_ok=True)


def _backfill_debt_sale_batches():
    """Sale_batch'i yo'q (eski) nasiya qarzlarni, ularning debt_items
    (mahsulot nomi/miqdori/birligi) ro'yxatini o'sha KUNGI nasiya
    sotuvlarning har bir partiyasi (sale_batch) bilan solishtirib, ANIQ MOS
    keladigan (va hali boshqa qarzga bog'lanmagan) partiyani topib
    bog'laydi. Faqat BIR MARTA, mos partiya topilganda ishlaydi -- mos
    kelmasa yoki bir nechta partiya bir xil bo'lsa (noaniqlik bo'lsa),
    hech narsaga tegilmaydi (xato bog'lanishdan ko'ra, bog'lanmay qolishi
    afzal)."""
    try:
        conn = get_conn()
        debts_without_batch = conn.execute(
            "SELECT id, date FROM debts WHERE sale_batch IS NULL OR sale_batch=''").fetchall()
        if not debts_without_batch:
            conn.close()
            return
        for did, ddate in debts_without_batch:
            items = conn.execute(
                "SELECT product_name, qty, unit FROM debt_items WHERE debt_id=?", (did,)).fetchall()
            if not items:
                continue
            item_set = sorted((n, round(float(q), 6), u) for n, q, u in items)
            batches = conn.execute(
                "SELECT DISTINCT sale_batch FROM sales WHERE date=? AND payment_type='nasiya' "
                "AND sale_batch IS NOT NULL", (ddate,)).fetchall()
            matches = []
            for (batch,) in batches:
                already = conn.execute(
                    "SELECT COUNT(*) FROM debts WHERE sale_batch=?", (batch,)).fetchone()[0]
                if already:
                    continue
                rows = conn.execute(
                    "SELECT product_name, qty, unit FROM sales WHERE sale_batch=?", (batch,)).fetchall()
                batch_set = sorted((n, round(float(q), 6), u) for n, q, u in rows)
                if batch_set == item_set:
                    matches.append(batch)
            if len(matches) == 1:
                conn.execute("UPDATE debts SET sale_batch=? WHERE id=?", (matches[0], did))
        conn.commit()
        conn.close()
    except Exception:
        # MUHIM: bu -- ixtiyoriy, "iloji bo'lsa yordam beradigan" tuzatish,
        # shuning uchun xatolik bo'lsa ham dastur ishga tushishiga
        # to'sqinlik qilmasligi kerak.
        pass


def today_str():
    return datetime.date.today().isoformat()


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def fmt_money(n):
    return f"{n:,.0f}".replace(",", " ")


def fmt_qty(qty, unit):
    q = float(qty)
    if abs(q - round(q)) < 1e-9:
        s = str(int(round(q)))
    else:
        s = f"{q:.3f}".rstrip("0").rstrip(".")
    return f"{s} {unit}"


def fmt_signed_money(n):
    sign = "+" if n >= 0 else "-"
    return f"{sign}{fmt_money(abs(n))}"


def close_day_for_date(date_str, allow_empty=False):
    """Berilgan sana uchun kunni yopadi: shu sanaga oid, hali biror
    closure'ga bog'lanmagan (closure_id IS NULL) barcha sotuvlarning umumiy
    summasi/foydasini day_closures jadvaliga yozadi va ANA SHU sotuv
    qatorlariga yangi closure_id'ni belgilaydi.

    MUHIM: shundan keyin bu qatorlar "bugungi ochiq savdo" hisobidan
    chiqadi -- shuning uchun kunni yopgandan so'ng Bosh sahifadagi
    "Bugungi savdo/foyda" ko'rsatkichlari darhol 0 ga tushadi (agar o'sha
    kundan keyin yangi sotuv qilinsa, faqat o'shalar hisoblanadi).

    Agar shu kun uchun allaqachon yopilgan bo'lsa -- None qaytaradi.
    Agar allow_empty=False bo'lib, hali sotuv umuman bo'lmagan bo'lsa --
    shuningdek None qaytaradi (hech narsa yaratilmaydi)."""
    conn = get_conn()
    already = conn.execute("SELECT id FROM day_closures WHERE date=?", (date_str,)).fetchone()
    conn.close()
    # MUHIM (foydalanuvchi so'rovi bilan -- "to'langani naqdga qo'shilsinmi?"):
    # nasiyaga savdo qilinib xaridor hozir bir qismini (paid_now) darhol
    # to'lagan bo'lsa, o'sha qism NAQD tomonga, qolgani NASIYA tomonga
    # hisoblanadi. Qarz bo'yicha keyin olingan to'lovlar ham naqdga qo'shiladi.
    sales_naqd, profit_naqd, sales_nasiya, profit_nasiya = get_naqd_nasiya_totals(
        date_str, closure_open_only=True)
    nothing = (sales_naqd == 0 and profit_naqd == 0 and sales_nasiya == 0 and profit_nasiya == 0)
    if nothing and (already or not allow_empty):
        return None
    conn = get_conn()
    try:
        if already:
            # Kun allaqachon yopilgan, lekin shundan keyin yangi savdo/to'lov
            # bo'lgan: yangilarini MAVJUD yopilishga qo'shamiz (aks holda ular
            # hech qachon yopilmay, yopilish tarixida yo'qolib qolardi).
            closure_id = already[0]
            conn.execute(
                "UPDATE day_closures SET closed_at=?, sales_naqd=sales_naqd+?, profit_naqd=profit_naqd+?, "
                "sales_nasiya=sales_nasiya+?, profit_nasiya=profit_nasiya+? WHERE id=?",
                (now_str(), sales_naqd, profit_naqd, sales_nasiya, profit_nasiya, closure_id))
        else:
            cur = conn.execute(
                "INSERT INTO day_closures (date, closed_at, sales_naqd, profit_naqd, sales_nasiya, profit_nasiya) "
                "VALUES (?,?,?,?,?,?)",
                (date_str, now_str(), sales_naqd, profit_naqd, sales_nasiya, profit_nasiya))
            closure_id = cur.lastrowid
        conn.execute("UPDATE sales SET closure_id=? WHERE date=? AND closure_id IS NULL", (closure_id, date_str))
        conn.execute("UPDATE debt_payments SET closure_id=? WHERE date=? AND closure_id IS NULL",
                     (closure_id, date_str))
        conn.commit()
    finally:
        conn.close()
    return closure_id


def mark_debt_paid(debt_id):
    """Qarzni 'to'landi' deb belgilaydi. MUHIM: bu funksiya ENDI qarzning
    to'langan sanasini ham (paid_date) yozadi -- shu orqali Bosh sahifadagi
    "Foyda" (avvalgi "Foyda (naqd)") ko'rsatkichiga, aynan SHU KUNI to'langan
    nasiya qarzlarning haqiqiy foydasi ham qo'shilib boradi (agar qarz
    yaratilgan sotuv partiyasi -- sale_batch -- topilsa). Bu orqali alohida
    "Bugungi foyda (nasiya)" oynasi endi kerak emas: qarz to'langan zahoti
    uning foydasi "Foyda" ichida ko'rinadi.

    Qaytaradi: (ok: bool, error: str|None)."""
    conn = get_conn()
    row = conn.execute("SELECT paid, sale_batch, amount FROM debts WHERE id=?", (debt_id,)).fetchone()
    if not row:
        conn.close()
        return False, "Qarz topilmadi."
    paid, sale_batch, amount = row
    if paid:
        conn.close()
        return False, "Bu qarz allaqachon to'langan."
    conn.execute("UPDATE debts SET paid=1, paid_date=? WHERE id=?", (today_str(), debt_id))
    # Oxirgi (qolgan) summa ham bugungi naqd savdoga qo'shiladi.
    if amount and amount > 0:
        conn.execute(
            "INSERT INTO debt_payments (debt_id, amount, date, created_at, is_final) VALUES (?,?,?,?,1)",
            (debt_id, amount, today_str(), now_str()))
    conn.commit()
    conn.close()
    return True, None


_DEBT_NOTE_PAT = re.compile(r"^([\d\s]+)\s*to'landi,\s*([\d\s]+)\s*qoldi$")


def pay_debt_partial(debt_id, pay_amount):
    """Qarzdor qarzining FAQAT bir qismini to'lasa, shu summani qarzdan
    ayiradi: debts.amount kamayadi (qolgan qarz), izoh esa "X to'landi,
    Y qoldi" ko'rinishida yangilanadi (X -- shu qarz bo'yicha JAMI
    to'langan summa, oldingi to'lovlar bilan birga). Agar kiritilgan
    summa qarzning to'liq qoldig'iga teng bo'lsa -- qarz odatdagidek
    "to'landi" deb belgilanadi (mark_debt_paid orqali, foyda hisobi
    ham shunda to'g'ri ishlaydi).

    Qaytaradi: (ok: bool, error: str|None, remaining: float|None)."""
    try:
        pay_amount = float(pay_amount)
    except (TypeError, ValueError):
        return False, "To'lanadigan summa noto'g'ri.", None
    if not math.isfinite(pay_amount) or pay_amount <= 0:
        return False, "To'lanadigan summa 0 dan katta bo'lishi kerak.", None
    conn = get_conn()
    try:
        row = conn.execute("SELECT amount, note, paid FROM debts WHERE id=?", (debt_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return False, "Qarz topilmadi.", None
    amount, note, paid = row
    if paid:
        return False, "Bu qarz allaqachon to'langan.", None
    if pay_amount > amount + 1e-9:
        return False, f"To'lanadigan summa qarzdan ({fmt_money(amount)}) katta bo'lishi mumkin emas.", None
    if pay_amount >= amount - 1e-9:
        ok, err = mark_debt_paid(debt_id)
        return ok, err, 0.0 if ok else None
    prev_paid = 0.0
    m = _DEBT_NOTE_PAT.match(note or "")
    if m:
        try:
            prev_paid = float(m.group(1).replace(" ", ""))
        except ValueError:
            prev_paid = 0.0
    new_amount = amount - pay_amount
    new_note = f"{fmt_money(prev_paid + pay_amount)} to'landi, {fmt_money(new_amount)} qoldi"
    conn = get_conn()
    try:
        conn.execute("UPDATE debts SET amount=?, note=? WHERE id=? AND paid=0",
                     (new_amount, new_note, debt_id))
        conn.execute(
            "INSERT INTO debt_payments (debt_id, amount, date, created_at, is_final) VALUES (?,?,?,?,0)",
            (debt_id, pay_amount, today_str(), now_str()))
        conn.commit()
    finally:
        conn.close()
    return True, None, new_amount


def record_sale_batch_paid_now(sale_batch, paid_now):
    """Bitta savdo partiyasi (sale_batch) uchun xaridor HOZIR to'lagan
    summani (paid_now) saqlaydi -- nasiyaga savdo qilinganda chaqiriladi
    (to'lov 0 bo'lsa ham, kelajakda so'ralganda aniq javob bo'lishi
    uchun). get_naqd_nasiya_totals() shu jadvaldan foydalanib, "Bugungi
    savdo (naqd)"/"(nasiya)" ko'rsatkichlarini TO'G'RI taqsimlaydi."""
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO sale_batch_meta (sale_batch, paid_now) VALUES (?, ?)",
        (sale_batch, paid_now or 0))
    conn.commit()
    conn.close()


def get_naqd_nasiya_totals_where(where_sql, params):
    """UMUMIY versiya -- istalgan WHERE sharti (bitta sana, davr oralig'i
    va h.k.) bo'yicha naqd/nasiya savdo va foyda yig'indilarini, "hozir
    to'langan" (paid_now) summani NAQD tomonga qo'shib/NASIYA tomonidan
    ayirib, TO'G'RI taqsimlab qaytaradi.

    where_sql -- "sales" jadvaliga tegishli WHERE qismi (masalan
    "WHERE date=?" yoki "WHERE date BETWEEN ? AND ?"), ICHIDA
    "payment_type" sharti BO'LMASLIGI kerak (bu funksiya o'zi qo'shadi).

    Qaytaradi: (sales_naqd, profit_naqd, sales_nasiya, profit_nasiya)."""
    conn = get_conn()
    naqd_raw = conn.execute(
        f"SELECT COALESCE(SUM(total),0), COALESCE(SUM(profit),0) FROM sales "
        f"{where_sql} AND payment_type='naqd'", params).fetchone()
    nasiya_raw = conn.execute(
        f"SELECT COALESCE(SUM(total),0), COALESCE(SUM(profit),0) FROM sales "
        f"{where_sql} AND payment_type='nasiya'", params).fetchone()
    paid_now_sum = conn.execute(
        f"SELECT COALESCE(SUM(sbm.paid_now),0) FROM sale_batch_meta sbm WHERE sbm.sale_batch IN ("
        f"  SELECT DISTINCT sale_batch FROM sales "
        f"  {where_sql} AND payment_type='nasiya' AND sale_batch IS NOT NULL)",
        params).fetchone()[0]
    # Qarz bo'yicha keyinroq olingan to'lovlar (debt_payments) shu davrning
    # NAQD savdosiga qo'shiladi (jadvalda ham "date"/"closure_id" ustunlari
    # bor, shuning uchun bir xil WHERE ishlaydi).
    debt_pay_sum = conn.execute(
        f"SELECT COALESCE(SUM(amount),0) FROM debt_payments {where_sql}", params).fetchone()[0]
    conn.close()
    sales_naqd = naqd_raw[0] + paid_now_sum + debt_pay_sum
    profit_naqd = naqd_raw[1]
    sales_nasiya = max(0.0, nasiya_raw[0] - paid_now_sum)
    profit_nasiya = nasiya_raw[1]
    return sales_naqd, profit_naqd, sales_nasiya, profit_nasiya


def get_naqd_nasiya_totals(date_str, closure_open_only=True):
    """Bitta SANA uchun naqd/nasiya savdo (summasi) va foyda
    yig'indilarini qaytaradi -- MUHIM (foydalanuvchi so'rovi bilan):
    nasiyaga savdo qilinganda xaridor hozir bir qismini (paid_now) darhol
    to'lagan bo'lsa, o'sha qism NAQD tomonga, qolgani esa NASIYA tomonga
    hisoblanadi (haqiqiy kassadagi pul bilan mos kelishi uchun). Foyda
    (profit) esa bu bilan bog'liq emas -- u sotuv vaqtida to'liq summa
    bo'yicha hisoblanadi va faqat qarz TO'LIQ to'langanda (mark_debt_paid)
    "Foyda" kartochkasiga o'tadi (get_todays_rolled_over_nasiya_profit
    orqali) -- shuning uchun bu yerda ikki marta hisoblanib qolmaydi.

    get_naqd_nasiya_totals_where()ning bitta-sana uchun qulay o'ramasi.

    Qaytaradi: (sales_naqd, profit_naqd, sales_nasiya, profit_nasiya)."""
    extra = " AND closure_id IS NULL" if closure_open_only else ""
    return get_naqd_nasiya_totals_where(f"WHERE date=?{extra}", (date_str,))


def get_pending_nasiya_profit_for_date(date_str):
    """Berilgan sana uchun, HALI TO'LANMAGAN nasiya sotuvlarning kutilayotgan
    foydasini qaytaradi -- Bosh sahifadagi "Bugungi nasiya (qarzga)"
    kartochkasining "kutilayotgan foyda" ko'rsatkichi uchun. MUHIM: agar bu
    yerda oddiy SUM(profit) ishlatilsa, va o'sha kuni qarz allaqachon
    to'langan bo'lsa, uning foydasi HAM shu yerda ("kutilayotgan" sifatida),
    HAM "Foyda" kartochkasida (haqiqiy sifatida) ko'rinib, IKKI MARTA
    hisoblanib qolar edi -- shuning uchun bu yerda FAQAT hali paid=0 bo'lgan
    (yoki hali debts'ga bog'lanmagan) nasiya sotuvlar profiti hisoblanadi."""
    conn = get_conn()
    total = conn.execute(
        "SELECT COALESCE(SUM(profit),0) FROM sales "
        "WHERE date=? AND payment_type='nasiya' AND closure_id IS NULL",
        (date_str,)).fetchone()[0]
    paid = conn.execute(
        "SELECT COALESCE(SUM(s.profit),0) FROM sales s JOIN debts d ON d.sale_batch = s.sale_batch "
        "WHERE s.date=? AND s.payment_type='nasiya' AND s.closure_id IS NULL AND d.paid=1",
        (date_str,)).fetchone()[0]
    conn.close()
    return total - paid


def get_rolled_over_nasiya_profit_for_date(paid_date_str):
    """get_todays_rolled_over_nasiya_profit()'ning UMUMIY (istalgan sana
    uchun ishlaydigan, closure_id bilan cheklanmagan) versiyasi -- "Hisobot"
    sahifasidagi kunlik foyda grafigi uchun ishlatiladi (u yerdagi kunlar
    odatda ALLAQACHON yopilgan bo'ladi, shuning uchun closure_id IS NULL
    sharti bu yerga to'g'ri kelmaydi)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT sale_batch FROM debts WHERE paid=1 AND paid_date=? AND sale_batch IS NOT NULL",
        (paid_date_str,)).fetchall()
    batches = [r[0] for r in rows if r[0]]
    if not batches:
        conn.close()
        return 0.0
    total = 0.0
    for b in batches:
        p = conn.execute("SELECT COALESCE(SUM(profit),0) FROM sales WHERE sale_batch=?", (b,)).fetchone()[0]
        total += p
    conn.close()
    return total


def get_pending_nasiya_profit_for_sales_date(sale_date_str):
    """get_pending_nasiya_profit_for_date()'ning UMUMIY (closure_id bilan
    cheklanmagan) versiyasi -- "Hisobot" sahifasidagi grafik/kartochkalar
    uchun: berilgan SOTUV sanasidagi nasiya foydadan, HALI TO'LANMAGAN
    (kutilayotgan) qismini qaytaradi."""
    conn = get_conn()
    total = conn.execute(
        "SELECT COALESCE(SUM(profit),0) FROM sales WHERE date=? AND payment_type='nasiya'",
        (sale_date_str,)).fetchone()[0]
    paid = conn.execute(
        "SELECT COALESCE(SUM(s.profit),0) FROM sales s JOIN debts d ON d.sale_batch = s.sale_batch "
        "WHERE s.date=? AND s.payment_type='nasiya' AND d.paid=1",
        (sale_date_str,)).fetchone()[0]
    conn.close()
    return total - paid


def get_realized_and_pending_nasiya_profit(date_from=None, date_to=None):
    """"Hisobot" sahifasidagi davr bo'yicha kartochkalar uchun: berilgan
    (yoki cheksiz, agar ikkalasi ham None bo'lsa) davrdagi nasiya
    sotuvlarning TO'LANGAN (realizatsiya qilingan) va HALI TO'LANMAGAN
    (kutilayotgan) foydasini alohida-alohida qaytaradi.

    Qaytaradi: (paid_nasiya_profit, pending_nasiya_profit)."""
    conn = get_conn()
    if date_from and date_to:
        where = "WHERE payment_type='nasiya' AND date BETWEEN ? AND ?"
        params = (date_from, date_to)
        join_where = "WHERE s.payment_type='nasiya' AND s.date BETWEEN ? AND ?"
    else:
        where = "WHERE payment_type='nasiya'"
        params = ()
        join_where = "WHERE s.payment_type='nasiya'"
    nasiya_total_profit = conn.execute(
        f"SELECT COALESCE(SUM(profit),0) FROM sales {where}", params).fetchone()[0]
    paid_nasiya_profit = conn.execute(
        f"SELECT COALESCE(SUM(s.profit),0) FROM sales s JOIN debts d ON d.sale_batch = s.sale_batch "
        f"{join_where} AND d.paid=1", params).fetchone()[0]
    conn.close()
    pending_nasiya_profit = nasiya_total_profit - paid_nasiya_profit
    return paid_nasiya_profit, pending_nasiya_profit


def get_todays_rolled_over_nasiya_profit():
    """Bugun to'langan nasiya qarzlarning (agar ular qaysi sotuv
    partiyasidan yaratilgani ma'lum bo'lsa -- sale_batch orqali) haqiqiy
    foydasini qaytaradi. Bosh sahifadagi "Foyda" kartasi shu qiymatni
    bugungi naqd foydaga qo'shib ko'rsatadi."""
    conn = get_conn()
    row = conn.execute(
        "SELECT d.sale_batch FROM debts d WHERE d.paid=1 AND d.paid_date=? AND d.sale_batch IS NOT NULL",
        (today_str(),)).fetchall()
    conn.close()
    batches = [r[0] for r in row if r[0]]
    if not batches:
        return 0.0
    conn = get_conn()
    total = 0.0
    for b in batches:
        p = conn.execute("SELECT COALESCE(SUM(profit),0) FROM sales WHERE sale_batch=?", (b,)).fetchone()[0]
        total += p
    conn.close()
    return total


def auto_close_missed_days():
    """Dastur ochilmagan paytda yarim tun (00:00) o'tib ketgan bo'lsa ham,
    dastur ochilgach avvalgi kunlar uchun avtomatik ravishda kunni yopish
    imkonini beradi. Bugungi kundan OLDINGI barcha sanalar orasidan, hali
    yopilmagan (closure_id IS NULL bo'lgan sotuvlari bor) kunlarni topib,
    har birini navbat bilan yopadi. Shu tufayli, dastur bir necha kun
    ochilmasa ham, orqada qolgan kunlar keyingi safar ochilganda to'g'ri
    yopiladi."""
    today = today_str()
    conn = get_conn()
    dates = [r[0] for r in conn.execute(
        "SELECT date FROM sales WHERE closure_id IS NULL AND date < ? "
        "UNION SELECT date FROM debt_payments WHERE closure_id IS NULL AND date < ? ORDER BY date",
        (today, today)).fetchall()]
    conn.close()
    closed = []
    for d in dates:
        cid = close_day_for_date(d, allow_empty=False)
        if cid is not None:
            closed.append(d)
    return closed


def find_product_by_name(name, exclude_id=None):
    """Nomi (katta-kichik harf va bo'sh joylarga qaramasdan) bir xil bo'lgan
    mahsulotni qidiradi -- yangi mahsulot qo'shishda tasodifiy dublikat
    yaratib qo'ymaslik uchun ishlatiladi. Topilsa, (id, name, cost_price,
    price, qty, unit, barcode) qatorini, topilmasa None qaytaradi."""
    target = (name or "").strip().lower()
    if not target:
        return None
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, cost_price, price, qty, unit, barcode FROM products").fetchall()
    conn.close()
    for row in rows:
        if exclude_id is not None and row[0] == exclude_id:
            continue
        if row[1].strip().lower() == target:
            return row
    return None


# Chek (receipt) yaratish va chop etish
# ---------------------------------------------------------------------------

RECEIPT_WIDTH = 38
RECEIPT_PAPER_OPTIONS = [
    ("58 mm qog'oz (tor, 32 belgi)", 32, 58),
    ("Standart (38 belgi)", 38, 58),
    ("80 mm qog'oz (keng, 48 belgi)", 48, 80),
    ("Ixtiyoriy (mm kiriting)", None, None),
]
RECEIPT_DEFAULT_WIDTH_CHARS = 27
RECEIPT_DEFAULT_MM = 50

BARCODE_LABEL_SIZE_OPTIONS = [
    ("58 x 38 mm", (58, 38)),
    ("40 x 30 mm", (40, 30)),
    ("50 x 30 mm", (50, 30)),
    ("50 x 40 mm", (50, 40)),
    ("60 x 40 mm", (60, 40)),
    ("Ixtiyoriy (mm kiriting)", None),
]


def _center(text, width=RECEIPT_WIDTH):
    return text.center(width)


def _line(ch="-", width=RECEIPT_WIDTH):
    return ch * width


def build_receipt_text(items, total, payment_type, customer_name=None, phone=None, width=None, method_label=None,
                        paid_now=0):
    width = width or RECEIPT_WIDTH
    now = datetime.datetime.now()
    receipt_no = now.strftime("%y%m%d-%H%M%S")

    lines = []
    lines.append(_center("TREYDCHI", width))
    lines.append(_line("=", width))
    lines.append(f"Chek No: {receipt_no}")
    lines.append(f"Sana:   {now.strftime('%d.%m.%Y  %H:%M')}")
    lines.append(_line(width=width))

    for i in items:
        name = i["name"]
        if len(name) > width:
            name = name[:width - 1] + "…"
        lines.append(name)
        qty_str = fmt_qty(i["qty"], i["unit"])
        price_str = f"{fmt_money(i['price'])}"
        total_str = f"{fmt_money(i['total'])}"
        mid = f"  {qty_str} x {price_str}"
        row = mid + " " * max(1, width - len(mid) - len(total_str)) + total_str
        lines.append(row)

    lines.append(_line(width=width))
    total_label = "JAMI:"
    total_val = f"{fmt_money(total)}"
    lines.append(total_label + " " * max(1, width - len(total_label) - len(total_val)) + total_val)
    lines.append(_line(width=width))

    if payment_type == "naqd":
        lines.append(_center(f"TO'LOV: {(method_label or 'Naqd').upper()}", width))
    else:
        # MUHIM (foydalanuvchi so'rovi bilan): "qisman to'lov" alohida
        # to'lov turi EMAS -- bu hamon oddiy "NASIYA" hisoblanadi. Agar
        # xaridor bir qismini DARHOL to'lagan bo'lsa (paid_now > 0), buni
        # faqat pastdagi "Hozir to'landi / Qarz (qoldiq)" qatorlari orqali
        # ko'rsatamiz -- "TO'LOV:" yorlig'i esa doim "NASIYA (QARZGA)".
        lines.append(_center("TO'LOV: NASIYA (QARZGA)", width))
        if customer_name:
            lines.append(f"Xaridor: {customer_name}")
        if phone:
            lines.append(f"Telefon: {phone}")
        if paid_now and paid_now > 0:
            remaining = max(total - paid_now, 0)
            lines.append(f"Hozir to'landi: {fmt_money(paid_now)} so'm")
            lines.append(f"Qarz (qoldiq): {fmt_money(remaining)} so'm")

    lines.append(_line("=", width))
    lines.append(_center("Xaridingiz uchun rahmat!", width))
    lines.append("")
    return "\n".join(lines)


_LAST_PRINTER_ERROR = None


def list_printers():
    global _LAST_PRINTER_ERROR
    if sys.platform == "win32":
        try:
            import win32print
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            printers = [p[2] for p in win32print.EnumPrinters(flags)]
            _LAST_PRINTER_ERROR = None
            return printers
        except ImportError as e:
            _LAST_PRINTER_ERROR = f"'pywin32' kutubxonasi topilmadi ({e})"
            return []
        except Exception as e:
            _LAST_PRINTER_ERROR = f"{type(e).__name__}: {e}"
            return []
    else:
        try:
            result = subprocess.run(["lpstat", "-p"], capture_output=True,
                                     text=True, timeout=5)
            printers = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("printer "):
                    printers.append(line.split()[1])
            _LAST_PRINTER_ERROR = None
            return printers
        except FileNotFoundError:
            _LAST_PRINTER_ERROR = "CUPS ('lpstat') topilmadi — printer tizimi o'rnatilmagan"
            return []
        except Exception as e:
            _LAST_PRINTER_ERROR = f"{type(e).__name__}: {e}"
            return []


def get_default_printer():
    if sys.platform == "win32":
        try:
            import win32print
            return win32print.GetDefaultPrinter()
        except Exception:
            return None
    else:
        try:
            result = subprocess.run(["lpstat", "-d"], capture_output=True,
                                     text=True, timeout=5)
            line = result.stdout.strip()
            if ":" in line:
                name = line.split(":", 1)[1].strip()
                return name or None
            return None
        except Exception:
            return None


def set_default_printer(name):
    if sys.platform == "win32":
        try:
            import win32print
            win32print.SetDefaultPrinter(name)
            return True
        except Exception:
            return False
    else:
        try:
            subprocess.run(["lpoptions", "-d", name], check=True,
                            capture_output=True, timeout=5)
            return True
        except Exception:
            return False


def save_receipt_file(text):
    os.makedirs(RECEIPTS_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RECEIPTS_DIR, f"chek_{stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _print_raw_text(text, printer_name=None):
    try:
        import win32print
    except ImportError:
        return False, "pywin32 kutubxonasi yo'q"

    name = printer_name or win32print.GetDefaultPrinter()
    if not name:
        return False, "Standart printer topilmadi"
    try:
        hprinter = win32print.OpenPrinter(name)
    except Exception as e:
        return False, str(e)
    try:
        win32print.StartDocPrinter(hprinter, 1, ("Treydchi - Chek", None, "RAW"))
        try:
            win32print.StartPagePrinter(hprinter)
            init_cmds = b"\x1b\x40" + b"\x1b\x21\x00" + b"\x1d\x21\x00"
            data = init_cmds + (text + "\n\n\n").encode("utf-8", errors="replace")
            win32print.WritePrinter(hprinter, data)
            win32print.EndPagePrinter(hprinter)
        finally:
            win32print.EndDocPrinter(hprinter)
    except Exception as e:
        return False, str(e)
    finally:
        win32print.ClosePrinter(hprinter)
    return True, None


def _open_custom_paper_dc(printer_name, width_mm, length_mm=None):
    try:
        import win32print
        import win32ui
        import win32con
        import win32gui
    except ImportError:
        return None
    try:
        hprinter = win32print.OpenPrinter(printer_name)
        try:
            devmode = win32print.DocumentProperties(0, hprinter, printer_name, None, None, 0)
            devmode.PaperWidth = max(1, int(width_mm * 10))
            fields = win32con.DM_PAPERWIDTH
            if length_mm is not None:
                devmode.PaperLength = max(1, int(length_mm * 10))
                fields |= win32con.DM_PAPERLENGTH
            devmode.Fields |= fields
            win32print.DocumentProperties(0, hprinter, printer_name, devmode, devmode,
                                            win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER)
        finally:
            win32print.ClosePrinter(hprinter)
        hdc_handle = win32gui.CreateDC("WINSPOOL", printer_name, None, devmode)
        return win32ui.CreateDCFromHandle(hdc_handle)
    except Exception:
        return None


def _wrap_line_to_fit(hdc, line, max_width_px):
    """Berilgan qatorni, HOZIRGI (o'zgarmagan) shrift bilan, qog'oz
    kengligiga (max_width_px) sig'dirish uchun, FAQAT ZARUR bo'lganda,
    ANIQ BIR joyda ikkiga bo'ladi.

    MUHIM: bu funksiya juda TORAYTIRILGAN maqsadga ega -- faqat "JAMI:"
    kabi, oxirida katta bo'shliqdan keyin summa keladigan qatorlarni
    to'g'rilaydi (label + bo'shliq + "12345 so'm"). Sarlavha ("ELMANS
    MATERIALS"), markazlashtirilgan matnlar (str.center() bilan, oxiri
    bo'shliqqa tugaydi) va "====...====" ajratuvchi chiziqlar (bo'shliqsiz)
    bu funksiya tomonidan HECH QACHON o'zgartirilmaydi -- ular avvalgidek,
    o'zgarishsiz chop etiladi."""
    if not line.strip() or hdc.GetTextExtent(line)[0] <= max_width_px:
        return [line]

    # Qatordagi barcha "kamida 2 ta ketma-ket bo'shliq" joylarini topamiz
    # va ENG OXIRGISINI tanlaymiz -- lekin FAQAT o'sha joydan keyin
    # HAQIQIY matn (masalan "397 000 so'm" -- ichida bitta bo'shliqlar
    # bo'lishi mumkin, shuning uchun oldingi versiyada moslik topilmagan
    # edi) qolgan bo'lsagina. Markazlashtirilgan matnlar (str.center())da
    # oxirgi shunday bo'shliq DOIM qatorning eng OXIRIGACHA davom etadi
    # (undan keyin hech narsa qolmaydi) -- shu sababli ular avtomatik
    # ravishda o'tkazib yuboriladi va o'zgarishsiz qoladi.
    best = None
    for m in re.finditer(r"\s{2,}", line):
        if line[m.end():].strip():
            best = m
    if best:
        part1 = line[:best.start()].rstrip()
        part2 = line[best.end():]
        if part1 and hdc.GetTextExtent(part1)[0] <= max_width_px:
            return [part1, part2]

    # Mos joy topilmasa (masalan ajratuvchi chiziq yoki sarlavha), qatorni
    # O'ZGARISHSIZ qoldiramiz -- bu boshqa hech narsaga tegmasligimiz
    # kerakligi haqidagi aniq ko'rsatmaga mos.
    return [line]


def _print_gdi_text(text, printer_name=None, paper_width_mm=58):
    # ESKI (dokon_desktop.py'dan ko'chirilgan) versiya -- foydalanuvchi aniq
    # so'ragan holda tiklandi. Shuni yodda tutish kerak: bu yerda shrift
    # o'lchami real o'lchov (GetTextExtent kalibrlash) bilan EMAS, oddiy
    # "0.60" nisbat taxmini bilan hisoblanadi va qatorlarni ehtiyot
    # bo'lib bo'lib-bo'lib chop etadigan _wrap_line_to_fit() ISHLATILMAYDI.
    try:
        import win32print
        import win32ui
        import win32con
    except ImportError:
        return False, "pywin32 kutubxonasi yo'q"

    name = printer_name or win32print.GetDefaultPrinter()
    if not name:
        return False, "Standart printer topilmadi"

    lines = text.split("\n")
    chars_per_line = max((len(l) for l in lines if l), default=32)

    FIXED_DPI = 203
    printable_width_px = int(paper_width_mm / 25.4 * FIXED_DPI * 0.90)

    font_height = int(printable_width_px / max(1, chars_per_line) / 0.60)
    font_height = max(20, min(font_height, 40))
    line_height = int(font_height * 1.2) or 1
    needed_height_px = line_height * (len(lines) + 2)

    length_mm = max(30, (needed_height_px / FIXED_DPI) * 25.4 + 8)

    hdc = _open_custom_paper_dc(name, paper_width_mm, length_mm)
    if hdc is None:
        try:
            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(name)
        except Exception as e:
            return False, str(e)

    try:
        font = win32ui.CreateFont({
            "name": FONT_MONO_NAME,
            "height": -font_height,
            "weight": 400,
        })
        hdc.SelectObject(font)

        # MUHIM TUZATISH: faqat "JAMI:" qatorida, agar u chop etish
        # kengligiga sig'masa (masalan katta summa tufayli), oxiridagi
        # 0 lar kesilib qolmasligi uchun shu QATORNI ikkiga bo'lamiz.
        # Boshqa qatorlarga (sarlavha, mahsulot nomlari va h.k.) tegilmaydi.
        final_lines = []
        for line in lines:
            if line.startswith("JAMI:"):
                final_lines.extend(_wrap_line_to_fit(hdc, line, printable_width_px))
            else:
                final_lines.append(line)

        needed_height_px = line_height * (len(final_lines) + 2)
        printable_height = hdc.GetDeviceCaps(win32con.VERTRES) or (needed_height_px + 1000)

        hdc.StartDoc("Treydchi - Chek")
        hdc.StartPage()
        hdc.SelectObject(font)

        y = 0
        for line in final_lines:
            if y > printable_height - line_height:
                hdc.EndPage()
                hdc.StartPage()
                hdc.SelectObject(font)
                y = 0
            hdc.TextOut(0, y, line)
            y += line_height

        hdc.EndPage()
        hdc.EndDoc()
        return True, None
    except Exception as e:
        try:
            hdc.AbortDoc()
        except Exception:
            pass
        return False, str(e)


def _print_raw_mac(data_bytes, printer_name=None):
    try:
        cmd = ["lp"]
        if printer_name:
            cmd += ["-d", printer_name]
        cmd += ["-o", "raw"]
        proc = subprocess.run(cmd, input=data_bytes, capture_output=True, timeout=15)
        if proc.returncode == 0:
            return True, None
        return False, proc.stderr.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return False, "CUPS ('lp') topilmadi"
    except Exception as e:
        return False, str(e)


def _print_plain_mac(path, printer_name=None):
    try:
        cmd = ["lp"]
        if printer_name:
            cmd += ["-d", printer_name]
        cmd += [path]
        proc = subprocess.run(cmd, capture_output=True, timeout=15)
        if proc.returncode == 0:
            return True, None
        return False, proc.stderr.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return False, "CUPS ('lp') topilmadi"
    except Exception as e:
        return False, str(e)


def print_receipt_file(path, printer_name=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        return False, str(e)

    paper_width_mm = load_settings().get("receipt_paper_mm", 50)

    if sys.platform == "win32":
        ok, _err = _print_gdi_text(text, printer_name, paper_width_mm)
        if ok:
            return True, None

        ok, _err = _print_raw_text(text, printer_name)
        if ok:
            return True, None
    else:
        init_cmds = b"\x1b\x40" + b"\x1b\x21\x00" + b"\x1d\x21\x00"
        data = init_cmds + (text + "\n\n\n").encode("utf-8", errors="replace")
        ok, _err = _print_raw_mac(data, printer_name)
        if ok:
            return True, None

        ok, _err = _print_plain_mac(path, printer_name)
        if ok:
            return True, None

    prev_default = None
    try:
        if printer_name:
            prev_default = get_default_printer()
            if prev_default and prev_default != printer_name:
                set_default_printer(printer_name)
        if hasattr(os, "startfile"):
            os.startfile(path, "print")
            return True, None
        else:
            return False, "Bu operatsion tizimda avtomatik chop etish qo'llab-quvvatlanmaydi."
    except Exception as e:
        return False, str(e)
    finally:
        if printer_name and prev_default and prev_default != printer_name:
            set_default_printer(prev_default)


# ---------------------------------------------------------------------------
# Shtrix kod (barcode) avtomatik yaratish, rasmga chizish, saqlash va chop etish
# ---------------------------------------------------------------------------

def generate_random_barcode(existing_codes):
    from barcode import EAN13

    for _ in range(200):
        first_digit = str(random.randint(1, 9))
        middle_digits = "".join(str(random.randint(0, 9)) for _ in range(10))
        last_digit = str(random.randint(1, 9))
        digits12 = first_digit + middle_digits + last_digit
        code = EAN13(digits12).get_fullcode()
        if code not in existing_codes:
            return code
    return code


def _load_label_font(bold=False, size=16):
    from PIL import ImageFont
    candidates = [
        "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf" if bold else "C:\\Windows\\Fonts\\segoeui.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Neue Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Helvetica Neue.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/SFNSText.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, size, index=0)
            from PIL import Image, ImageDraw
            _test = ImageDraw.Draw(Image.new("RGB", (10, 10)))
            bbox = _test.textbbox((0, 0), "Aa0", font=font)
            if (bbox[2] - bbox[0]) > 0 and (bbox[3] - bbox[1]) > 0:
                return font
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _fit_label_font(draw, text, max_width, start_size=23, min_size=11):
    """Berilgan matn (mahsulot nomi) `max_width` piksel ichiga sig'guncha
    shrift o'lchamini asta-sekin kichraytiradi. Agar eng kichik o'lchamda
    ham sig'masa, matnning o'zi "..." bilan qirqiladi (bu ORQAGA QOLDIRILGAN
    so'nggi chora, odatda amalda kamdan-kam kerak bo'ladi)."""
    size = start_size
    font = _load_label_font(bold=True, size=size)
    while size > min_size:
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
        size -= 1
        font = _load_label_font(bold=True, size=size)
    return font


def build_barcode_label_image(code, product_name, price, name_font_size=None,
                               price_font_size=25, barcode_scale=1.0):
    """Shtrix kod yorlig'i rasmini yaratadi.

    MUHIM (foydalanuvchi so'ragan moslashuvchanlik): endi mahsulot nomi,
    narxi va shtrix kodning o'zi (chiziqlar balandligi + pastidagi raqam
    shrifti) ALOHIDA-ALOHIDA kattalashtirilishi/kichraytirilishi mumkin:
      - name_font_size: mahsulot nomi shrifti (None bo'lsa, eskidek --
        avtomatik moslashadi, sig'masa kichrayadi).
      - price_font_size: narx shrifti (standart 25, avvalgidek).
      - barcode_scale: shtrix kodning o'zi qanchalik katta/kichik bo'lishi
        (1.0 = standart o'lcham; masalan 1.3 -- 30% kattaroq chiziqlar
        va raqam shrifti).
    Yorliqning o'lchami (label_w/label_h) endi HAQIQIY o'lchangan matn
    balandliklariga qarab DINAMIK hisoblanadi -- shunda katta shrift
    tanlansa ham, matn yorliqning tashqarisiga chiqib ketmaydi yoki
    ustma-ust tushib qolmaydi."""
    from io import BytesIO
    from barcode import EAN13
    from barcode.writer import ImageWriter
    from PIL import Image, ImageDraw

    barcode_scale = max(0.5, min(float(barcode_scale or 1.0), 2.5))
    barcode_module_height = 10.0 * barcode_scale
    barcode_font_size = max(6, int(round(8 * barcode_scale)))

    buffer = BytesIO()
    writer = ImageWriter()
    for _font_candidate in (
        "C:\\Windows\\Fonts\\arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(_font_candidate):
            writer.font_path = _font_candidate
            break
    ean = EAN13(code, writer=writer)
    ean.write(buffer, options={
        "write_text": True,
        "module_height": barcode_module_height,
        "font_size": barcode_font_size,
        "quiet_zone": 2,
        "text_distance": 3,
    })
    buffer.seek(0)
    barcode_img = Image.open(buffer).convert("RGB")

    side_margin = 24
    top_margin = 18
    bottom_margin = 18
    gap_after_text = 10
    gap_name_price = 8

    label_w = max(barcode_img.width, 360) + side_margin * 2

    # --- Shriftlarni tayyorlaymiz (o'lchash uchun vaqtinchalik draw) ---
    _measure_img = Image.new("RGB", (10, 10))
    _measure_draw = ImageDraw.Draw(_measure_img)

    font_price = _load_label_font(bold=True, size=int(price_font_size or 25))
    price_text = f"{fmt_money(price)} so'm"

    name_text = product_name
    max_name_width = label_w - side_margin * 2
    if name_font_size:
        # Foydalanuvchi ANIQ o'lcham tanlagan -- avtomatik kichraytirish
        # QILINMAYDI, faqat haqiqatan ham sig'masa oxiri "..." bilan
        # qirqiladi (yorliqdan tashqariga chiqib ketmasligi uchun).
        font_name = _load_label_font(bold=True, size=int(name_font_size))
    else:
        font_name = _fit_label_font(_measure_draw, name_text, max_name_width, start_size=23, min_size=11)
    try:
        bbox_check = _measure_draw.textbbox((0, 0), name_text, font=font_name)
        while (bbox_check[2] - bbox_check[0]) > max_name_width and len(name_text) > 1:
            name_text = name_text[:-1]
            bbox_check = _measure_draw.textbbox((0, 0), name_text + "…", font=font_name)
        if name_text != product_name:
            name_text = name_text.rstrip() + "…"
    except Exception:
        pass

    name_h = 22
    price_h = 30
    try:
        nb = _measure_draw.textbbox((0, 0), name_text, font=font_name)
        name_h = (nb[3] - nb[1]) or name_h
    except Exception:
        pass
    try:
        pb = _measure_draw.textbbox((0, 0), price_text, font=font_price)
        price_h = (pb[3] - pb[1]) or price_h
    except Exception:
        pass

    text_block_height = top_margin + name_h + gap_name_price + price_h
    label_h = text_block_height + gap_after_text + barcode_img.height + bottom_margin
    label = Image.new("RGB", (label_w, label_h), "white")
    draw = ImageDraw.Draw(label)

    name_y = top_margin
    price_y = name_y + name_h + gap_name_price
    try:
        bbox = draw.textbbox((0, 0), name_text, font=font_name)
        name_x = (label_w - (bbox[2] - bbox[0])) / 2
        draw.text((name_x, name_y), name_text, font=font_name, fill="black")
    except Exception:
        draw.text((side_margin, name_y), name_text, fill="black")
    try:
        bbox2 = draw.textbbox((0, 0), price_text, font=font_price)
        price_x = (label_w - (bbox2[2] - bbox2[0])) / 2
        draw.text((price_x, price_y), price_text, font=font_price, fill="black")
    except Exception:
        draw.text((side_margin, price_y), price_text, fill="black")

    bx = (label_w - barcode_img.width) // 2
    by = text_block_height + gap_after_text
    label.paste(barcode_img, (bx, by))
    return label


def save_barcode_label(image, code):
    os.makedirs(BARCODE_LABELS_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BARCODE_LABELS_DIR, f"barcode_{code}_{stamp}.png")
    image.save(path)
    return path


def _print_gdi_image(image_path, printer_name=None, label_width_mm=58, label_height_mm=38, copies=1):
    """Shtrix kod rasmini Windows GDI orqali printerga chop etadi.

    MUHIM TUZATISH: ilgari har bir nusxa (copy) uchun ALOHIDA StartDoc/EndDoc
    (ya'ni alohida chop etish topshirig'i) ochilar edi -- bu ko'pchilik
    shtrix kod (label) printerlarida har nusxadan keyin printer/spooler bilan
    qaytadan "muzokara" qilinishiga sabab bo'lib, bir nechta nusxa chop
    etilganda printer "to'xtab-to'xtab" (sekin, notekis) ishlar edi. Endi
    BITTA StartDoc ichida har bir nusxa uchun alohida StartPage/EndPage
    chaqiriladi -- shunda butun chop etish bitta uzluksiz topshiriq bo'lib,
    printer nusxalarni tez va tekis chiqaradi."""
    try:
        import win32print
        import win32ui
        import win32con
        from PIL import Image, ImageWin
    except ImportError:
        return False, "pywin32 yoki Pillow kutubxonasi yo'q"

    name = printer_name or win32print.GetDefaultPrinter()
    if not name:
        return False, "Standart printer topilmadi"

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        return False, str(e)

    try:
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(name)
    except Exception as e:
        return False, str(e)

    copies = max(1, int(copies or 1))
    try:
        printable_width = hdc.GetDeviceCaps(win32con.HORZRES)
        printable_height = hdc.GetDeviceCaps(win32con.VERTRES)
        if not printable_width or not printable_height:
            FIXED_DPI = 203
            printable_width = int(label_width_mm / 25.4 * FIXED_DPI)
            printable_height = int(label_height_mm / 25.4 * FIXED_DPI)

        target_w = printable_width * 0.96
        target_h = printable_height * 0.96

        scale = min(target_w / img.width, target_h / img.height)
        out_w = max(1, int(img.width * scale))
        out_h = max(1, int(img.height * scale))
        x0 = max(0, (printable_width - out_w) // 2)
        y0 = max(0, (printable_height - out_h) // 2)

        dib = ImageWin.Dib(img)
        hdc.StartDoc("Treydchi - Shtrix kod")
        try:
            for _ in range(copies):
                hdc.StartPage()
                dib.draw(hdc.GetHandleOutput(), (x0, y0, x0 + out_w, y0 + out_h))
                hdc.EndPage()
        finally:
            hdc.EndDoc()
        return True, None
    except Exception as e:
        try:
            hdc.AbortDoc()
        except Exception:
            pass
        return False, str(e)
    finally:
        try:
            hdc.DeleteDC()
        except Exception:
            pass


def _print_image_mac(image_path, printer_name=None, label_width_mm=58, label_height_mm=38, copies=1):
    try:
        copies = max(1, int(copies or 1))
        cmd = ["lp", "-n", str(copies)]
        if printer_name:
            cmd += ["-d", printer_name]
        media = f"Custom.{int(label_width_mm)}x{int(label_height_mm)}mm"
        cmd += ["-o", f"media={media}", "-o", "fit-to-page", image_path]
        proc = subprocess.run(cmd, capture_output=True, timeout=15)
        if proc.returncode == 0:
            return True, None
        return False, proc.stderr.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return False, "CUPS ('lp') topilmadi"
    except Exception as e:
        return False, str(e)


def _print_raster_barcode_mac(image_path, printer_name=None, label_width_mm=58, dots_per_mm=8, copies=1):
    try:
        copies = max(1, int(copies or 1))
        paper_mm = load_settings().get("receipt_paper_mm", 50)
        if paper_mm >= 70:
            max_dots = 576
        else:
            max_dots = 384

        img = Image.open(image_path).convert("L")
        desired_w = max(8, int(label_width_mm * dots_per_mm))
        target_w = min(desired_w, max_dots)
        target_w = max(8, (target_w // 8) * 8)
        scale = target_w / img.width
        target_h = max(1, int(img.height * scale))
        img = img.resize((target_w, target_h), Image.LANCZOS)
        img = img.point(lambda p: 0 if p < 160 else 255, mode="L").convert("1")

        width_px, height_px = img.size
        width_bytes = (width_px + 7) // 8
        raw = bytearray()
        pixels = img.load()
        for y in range(height_px):
            byte = 0
            bit_count = 0
            for x in range(width_px):
                bit = 1 if pixels[x, y] == 0 else 0
                byte = (byte << 1) | bit
                bit_count += 1
                if bit_count == 8:
                    raw.append(byte)
                    byte = 0
                    bit_count = 0
            if bit_count:
                byte <<= (8 - bit_count)
                raw.append(byte)

        xL, xH = width_bytes & 0xFF, (width_bytes >> 8) & 0xFF
        yL, yH = height_px & 0xFF, (height_px >> 8) & 0xFF
        header = bytes([0x1D, 0x76, 0x30, 0x00, xL, xH, yL, yH])
        init_cmds = b"\x1b\x40"
        # MUHIM: bir nechta nusxa so'ralsa, hammasi BITTA raw ma'lumot bloki
        # (bitta ulanish/topshiriq) ichida ketma-ket yuboriladi -- shunda
        # printer ular orasida to'xtab qolmaydi.
        one_label = header + bytes(raw) + b"\n\n\n"
        data = init_cmds + (one_label * copies)
        return _print_raw_mac(data, printer_name)
    except Exception as e:
        return False, str(e)


def print_barcode_label_file(path, printer_name=None, label_size_mm=None, copies=1):
    """Shtrix kod rasmini chop etadi. `copies` -- nechta nusxa chiqarish
    kerakligi. MUHIM TUZATISH: avval GUI tomonida har nusxa uchun bu funksiya
    ALOHIDA chaqirilar edi (har safar yangi print-job ochib) -- bu esa
    printerni har nusxadan keyin to'xtatib qo'yardi. Endi barcha nusxalar
    BITTA chaqiruvda, bitta uzluksiz print-job ichida chiqariladi."""
    width_mm, height_mm = label_size_mm or (58, 38)
    copies = max(1, int(copies or 1))

    if sys.platform == "win32":
        ok, _err = _print_gdi_image(path, printer_name, width_mm, height_mm, copies=copies)
        if ok:
            return True, None
    else:
        ok, _err = _print_raster_barcode_mac(path, printer_name, width_mm, copies=copies)
        if ok:
            return True, None
        ok, _err = _print_image_mac(path, printer_name, width_mm, height_mm, copies=copies)
        if ok:
            return True, None

    prev_default = None
    try:
        if printer_name:
            prev_default = get_default_printer()
            if prev_default and prev_default != printer_name:
                set_default_printer(printer_name)
        if hasattr(os, "startfile"):
            for _ in range(copies):
                os.startfile(path, "print")
            return True, None
        else:
            return False, "Bu operatsion tizimda avtomatik chop etish qo'llab-quvvatlanmaydi."
    except Exception as e:
        return False, str(e)
    finally:
        if printer_name and prev_default and prev_default != printer_name:
            set_default_printer(prev_default)


# ---------------------------------------------------------------------------
# Telegram bot — sotuv xabarnomalari va foydalanuvchilarni tasdiqlash tizimi
# ---------------------------------------------------------------------------

_TELEGRAM_SETTINGS_LOCK = None
_LAST_TELEGRAM_ERROR = None
_SSL_CONTEXT = None


def _get_ssl_context():
    global _SSL_CONTEXT
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT
    import ssl
    ctx = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            ctx = ssl.create_default_context()
        except Exception:
            ctx = None
    _SSL_CONTEXT = ctx
    return ctx


def _telegram_lock():
    # BUG TUZATISH: ilgari bu yerda ALOHIDA, faqat Telegram kodi
    # ishlatadigan qulf yaratilar edi -- printer sozlamalarini yoki
    # boshqa oddiy `load_settings()/save_settings()` chaqiruvlarini
    # umuman "ko'rmasdi". Natijada Telegram fon oqimi bilan GUI/printer
    # oqimlari bir vaqtning o'zida sozlamalar.json faylini yozib,
    # bir-birining o'zgarishini yo'qotib qo'yishardi. Endi bu funksiya
    # `load_settings`/`save_settings`/`update_settings` ham ishlatadigan
    # BITTA umumiy `_SETTINGS_LOCK`ni qaytaradi (u RLock bo'lgani uchun
    # shu oqim ichida qayta-qayta qulflash xavfsiz).
    return _SETTINGS_LOCK


def _telegram_api_call(token, method, params=None, timeout=15):
    global _LAST_TELEGRAM_ERROR
    import urllib.request
    import urllib.parse
    import urllib.error
    import json as _json
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    ctx = _get_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
            _LAST_TELEGRAM_ERROR = None
            if isinstance(result, dict) and not result.get("ok", True):
                _desc = result.get("description") or "noma'lum xato"
                _LAST_TELEGRAM_ERROR = f"Telegram: {_desc}"
            return result
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            parsed = _json.loads(body)
            desc = parsed.get("description", body)
        except Exception:
            desc = str(e)
        _LAST_TELEGRAM_ERROR = f"HTTP {e.code}: {desc}"
        return None
    except Exception as e:
        import ssl as _ssl_mod
        if isinstance(e, _ssl_mod.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(e):
            _LAST_TELEGRAM_ERROR = (
                "SSL sertifikat xatosi — Python'ning ishonchli sertifikatlar "
                "ro'yxati o'rnatilmagan. Terminalda shuni ishga tushiring: "
                "pip install certifi --break-system-packages (yoki oddiy: pip install certifi), "
                "so'ng dasturni qayta ishga tushiring."
            )
        else:
            _LAST_TELEGRAM_ERROR = f"{type(e).__name__}: {e}"
        return None


def _telegram_send(token, chat_id, text):
    return _telegram_api_call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    })


def _telegram_send_ok(token, chat_id, text):
    result = _telegram_send(token, chat_id, text)
    return bool(result and result.get("ok"))


def _telegram_send_get_message_id(token, chat_id, text):
    result = _telegram_send(token, chat_id, text)
    if result and result.get("ok"):
        return result.get("result", {}).get("message_id")
    return None


def _telegram_delete_message(token, chat_id, message_id):
    result = _telegram_api_call(token, "deleteMessage", {
        "chat_id": chat_id,
        "message_id": message_id,
    })
    return bool(result and result.get("ok"))


def _telegram_send_with_buttons(token, chat_id, text, buttons):
    import json as _json
    keyboard = {"inline_keyboard": [[{"text": label, "callback_data": data}] for label, data in buttons]}
    return _telegram_api_call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": _json.dumps(keyboard),
    })


def _telegram_answer_callback(token, callback_query_id, text=None):
    params = {"callback_query_id": callback_query_id}
    if text:
        params["text"] = text
    _telegram_api_call(token, "answerCallbackQuery", params)


def _telegram_edit_message_text(token, chat_id, message_id, text, clear_buttons=True):
    import json as _json
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if clear_buttons:
        params["reply_markup"] = _json.dumps({"inline_keyboard": []})
    _telegram_api_call(token, "editMessageText", params)


def _telegram_edit_message_text_with_buttons(token, chat_id, message_id, text, buttons):
    """_telegram_edit_message_text()'dan farqli -- tugmalarni TOZALAMAYDI,
    ULARNI YANGISI BILAN ALMASHTIRADI (masalan ruxsatlar panelida, tugma
    bosilgandan keyin joriy holatni ko'rsatib qayta chizish uchun)."""
    import json as _json
    keyboard = {"inline_keyboard": [[{"text": label, "callback_data": data}] for label, data in buttons]}
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": _json.dumps(keyboard),
    }
    _telegram_api_call(token, "editMessageText", params)


def approve_telegram_user(cid):
    with _telegram_lock():
        settings = load_settings()
        pending = settings.get("telegram_pending_requests") or []
        approved = settings.get("telegram_approved_users") or []
        user = next((p for p in pending if str(p.get("chat_id")) == str(cid)), None)
        pending = [p for p in pending if str(p.get("chat_id")) != str(cid)]
        if user is not None and not any(str(a.get("chat_id")) == str(cid) for a in approved):
            user = dict(user)
            user["approved_at"] = now_str()
            approved.append(user)
        settings["telegram_pending_requests"] = pending
        settings["telegram_approved_users"] = approved
        save_settings(settings)
    # MUHIM TUZATISH (foydalanuvchi so'rovi -- "oddiy foydalanuvchiga ham
    # tuzatildimi?"): ruxsat berilgan zahoti menyu tugmasini o'rnatish
    # (quyida, finalize_approved_menu_button) Telegram serveriga TARMOQ
    # so'rovi yuboradi. Bu funksiya (approve_telegram_user) GUI oqimidan
    # ham ("Ruxsat berish" tugmasi) chaqirilishi mumkin -- avval bu tarmoq
    # so'rovi shu yerning O'ZIDA, sozlamalarni saqlash bilan bir vaqtda
    # bajarilardi, bu esa GUI'dan chaqirilganda dasturni bir necha
    # soniyaga muzlatib qo'yishi mumkin edi (xuddi Saqlash/Ulanishni
    # tekshirish tugmalaridagi kabi). Endi tarmoq qismi ALOHIDA funksiyaga
    # ajratildi -- chaqiruvchi buni o'zi mos joyda (GUI uchun fon oqimida,
    # bot polling oqimi uchun -- u allaqachon fon oqimi bo'lgani uchun
    # to'g'ridan-to'g'ri) chaqiradi.
    return user


def finalize_approved_menu_button(user):
    """approve_telegram_user() muvaffaqiyatli bo'lgach chaqiriladi: YANGI
    ruxsat berilgan foydalanuvchi uchun ko'k "Narxlar"/"Prices"/"Цены"
    tugmasini DARHOL, uning tanlagan tilida o'rnatadi -- bot qayta ishga
    tushishini kutish shart emas. MUHIM: bu TARMOQ so'rovi -- chaqiruvchi
    buni UI (yoki bot polling) oqimini bloklamaydigan joyda chaqirishi
    kerak."""
    if user is None:
        return
    try:
        settings = load_settings()
        miniapp_url = _MINIAPP_STATE.get("url")
        token = (settings.get("telegram_bot_token") or "").strip()
        if miniapp_url and token:
            _set_menu_button_for_chat(
                token, miniapp_url, chat_id=user.get("chat_id"), lang=user.get("language") or "uz")
    except Exception:
        pass


def reject_telegram_user(cid):
    with _telegram_lock():
        settings = load_settings()
        pending = settings.get("telegram_pending_requests") or []
        user = next((p for p in pending if str(p.get("chat_id")) == str(cid)), None)
        pending = [p for p in pending if str(p.get("chat_id")) != str(cid)]
        settings["telegram_pending_requests"] = pending
        save_settings(settings)
    return user


def remove_telegram_user(cid):
    with _telegram_lock():
        settings = load_settings()
        approved = settings.get("telegram_approved_users") or []
        user = next((a for a in approved if str(a.get("chat_id")) == str(cid)), None)
        approved = [a for a in approved if str(a.get("chat_id")) != str(cid)]
        settings["telegram_approved_users"] = approved
        save_settings(settings)
    return user


def _notify_telegram_removal(token, user):
    if not token or not user:
        return
    cid = user.get("chat_id")
    if not cid:
        return
    lang = user.get("language") or "uz"
    _telegram_send(token, cid, _tg_str(lang, "access_removed"))


def _notify_telegram_decision(token, admin_chat_id, user, approved, via_app=False):
    if not token or not user:
        return
    target_cid = user.get("chat_id")
    admin_msg_id = user.get("admin_msg_id")
    # MUHIM (yo'qolgan funksiya qaytarildi): adminga yuboriladigan xabar
    # ("Ruxsat berildi"/"Rad etildi") endi ADMIN o'zi tanlagan tilda
    # yoziladi -- so'rovchiga yuboriladigan xabar esa (user_text) o'sha
    # so'rovchining O'Z tilida qoladi (ikkisi mustaqil, chunki har biri
    # o'z tilini o'zi tanlaydi).
    admin_lang = _admin_lang(load_settings())
    label = _telegram_user_label(user, admin_lang)
    suffix = _tg_str(admin_lang, "admin_via_app_suffix") if via_app else ""
    lang = user.get("language") or "uz"

    if approved:
        admin_text = f"{_tg_str(admin_lang, 'admin_decision_approved_title', suffix=suffix)}\n{label}"
        user_text = _tg_str(lang, "access_granted")
    else:
        admin_text = f"{_tg_str(admin_lang, 'admin_decision_rejected_title', suffix=suffix)}\n{label}"
        user_text = _tg_str(lang, "access_rejected")

    if admin_chat_id and admin_msg_id:
        _telegram_edit_message_text(token, admin_chat_id, admin_msg_id, admin_text)
    elif admin_chat_id:
        _telegram_send(token, admin_chat_id, admin_text)

    if target_cid:
        _telegram_send(token, target_cid, user_text)


def _sale_message_already_sent(sale_batch, chat_id):
    """MUHIM TUZATISH: internet o'chib-yonganda (sotuv OFFLINE qilinib,
    keyin internet qaytganda) bitta sotuv xabari ba'zan IKKI MARTA
    yuborilib qolar edi. Sababi: xabar navbatga qo'yilib (chunki birinchi
    urinish "muvaffaqiyatsiz" deb belgilangan), keyin esa Telegram'ga
    so'rov aslida YETIB BORGAN, ammo javob mijozga internet uzilishi
    tufayli qaytmagan bo'lishi mumkin -- shu sababli xabar qayta
    yuborilganda ikkinchi nusxa paydo bo'ladi. Bu funksiya har bir
    yuborish urinishidan OLDIN, shu sotuv partiyasi uchun shu chat_id'ga
    xabar ALLAQACHON yuborilganmi (telegram_sale_messages jadvalida
    yozuvi bormi) tekshiradi -- agar bor bo'lsa, qayta yuborilmaydi."""
    if not sale_batch:
        return False
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT 1 FROM telegram_sale_messages WHERE sale_batch=? AND chat_id=? LIMIT 1",
            (sale_batch, str(chat_id))).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def _store_sale_telegram_message(sale_batch, chat_id, message_id):
    if not sale_batch:
        return
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO telegram_sale_messages (sale_batch, chat_id, message_id) VALUES (?,?,?)",
            (sale_batch, str(chat_id), message_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def delete_telegram_messages_for_sale_batch(sale_batch):
    """Berilgan sotuv "partiyasi"ga tegishli, avval yuborilgan Telegram
    xabarlarini o'chiradi.

    MUHIM TUZATISH: agar sotuv OFFLINE (internetsiz) qilingan bo'lsa, unga
    tegishli xabar hali yuborilmagan, faqat "telegram_pending_messages"
    navbatida kutib turgan bo'lishi mumkin. Avval bu funksiya FAQAT
    ALLAQACHON YUBORILGAN xabarlarni (telegram_sale_messages jadvali)
    o'chirar edi -- navbatdagi (hali yuborilmagan) xabar esa o'chirilmasdan
    qolib, internet qaytgach baribir yuborilib ketardi (garchi sotuv
    allaqachon o'chirilgan/omborga qaytarilgan bo'lsa ham). Endi shu
    sotuv partiyasiga tegishli navbatdagi xabarlar ham DARHOL (sinxron
    ravishda) navbatdan olib tashlanadi -- ular endi hech qachon
    yuborilmaydi.
    """
    if not sale_batch:
        return

    with _telegram_lock():
        settings = load_settings()
        pending_msgs = settings.get("telegram_pending_messages") or []
        still_pending = [item for item in pending_msgs if item.get("sale_batch") != sale_batch]
        if len(still_pending) != len(pending_msgs):
            settings["telegram_pending_messages"] = still_pending
            save_settings(settings)

    settings = load_settings()
    token = (settings.get("telegram_bot_token") or "").strip()
    if not token:
        return

    def _delete_all():
        try:
            conn = get_conn()
            rows = conn.execute(
                "SELECT id, chat_id, message_id FROM telegram_sale_messages WHERE sale_batch=?",
                (sale_batch,)).fetchall()
            for row_id, chat_id, message_id in rows:
                _telegram_delete_message(token, chat_id, message_id)
                conn.execute("DELETE FROM telegram_sale_messages WHERE id=?", (row_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    import threading
    threading.Thread(target=_delete_all, daemon=True).start()


def send_telegram_to_all_approved(text, sale_batch=None):
    settings = load_settings()
    token = (settings.get("telegram_bot_token") or "").strip()
    approved = settings.get("telegram_approved_users") or []
    admin_chat_id = (settings.get("telegram_admin_chat_id") or "").strip()

    recipient_ids = []
    seen = set()
    for user in approved:
        cid = user.get("chat_id")
        if cid is None:
            continue
        key = str(cid)
        if key in seen:
            continue
        seen.add(key)
        recipient_ids.append(cid)
    if admin_chat_id and admin_chat_id not in seen:
        recipient_ids.append(admin_chat_id)

    if not token or not recipient_ids:
        return

    def _send_all():
        to_queue = []
        for cid in recipient_ids:
            message_id = _telegram_send_get_message_id(token, cid, text)
            if message_id is not None:
                if sale_batch:
                    _store_sale_telegram_message(sale_batch, cid, message_id)
            else:
                to_queue.append({"chat_id": cid, "text": text, "queued_at": now_str(),
                                  "sale_batch": sale_batch})
        if to_queue:
            with _telegram_lock():
                s = load_settings()
                q = s.get("telegram_pending_messages") or []
                q.extend(to_queue)
                s["telegram_pending_messages"] = q
                save_settings(s)

    import threading
    threading.Thread(target=_send_all, daemon=True).start()


# ---------------------------------------------------------------------------
# Telegram bot uchun ko'p tillilik (uz/en/ru) -- MUHIM: bu dastur
# interfeysining o'zi uchun ishlatiladigan TRANSLATIONS/tr() lug'atidan
# ATAYLAB alohida, chunki har bir Telegram foydalanuvchisi (do'kon egasi
# emas, botga yozgan boshqa odam) o'zining shaxsiy tilini bot orqali
# mustaqil tanlaydi -- bu dasturning o'zi qaysi tilda ishlab turganiga
# umuman bog'liq emas.
# ---------------------------------------------------------------------------

_TG_LANGUAGES = [
    ("uz", "🇺🇿 O'zbekcha"),
    ("en", "🇬🇧 English"),
    ("ru", "🇷🇺 Русский"),
]

_TG_STRINGS = {
    "uz": {
        "new_sale": "Yangi sotuv", "total": "Jami", "profit": "Foyda",
        "payment": "To'lov", "cash": "Naqd", "credit": "Nasiya (qarzga)",
        "customer": "Xaridor", "currency": "so'm",
        "choose_lang": "Assalomu alaykum! Iltimos, tilni tanlang:",
        "lang_saved": "✅ Til o'zbekcha qilib saqlandi. Endi admin sizga ruxsat berishini kuting.",
        "access_granted": "✅ Sizga botdan foydalanishga ruxsat berildi.\nEndi har bir sotuv haqida xabar olib turasiz.",
        "access_rejected": "🚫 Sizning so'rovingiz rad etildi.",
        "access_removed": "🚫 Sizga botdan foydalanish huquqi bekor qilindi.\nEndi sizga sotuv/bildirishnoma xabarlari kelmaydi.",
        "no_permission": "🚫 Sizda mahsulot narxini so'rash huquqi yo'q. Do'kon egasidan so'rang.",
        "not_found": "❌ \"{q}\" bo'yicha mahsulot topilmadi.",
        "results_header": "🔎 Qidiruv natijalari — \"{q}\":",
        "price": "Narxi", "qty": "Qoldiq",
        "choose_lang_change": "Tilni tanlang:",
        "lang_changed": "✅ Til o'zbekcha qilib o'zgartirildi.",
        # MUHIM (yo'qolgan funksiya qaytarildi): admin-ga botdan keladigan
        # BARCHA xabarlar ("Yangi so'rov" bildirishnomasi, /pending va
        # /approved ro'yxatlari, qaror natijasi, adminlik berilgan/olib
        # qo'yilgan xabarlari va h.k.) endi admin O'ZI tanlagan tilda
        # ("telegram_admin_language") keladi -- ilgari bularning barchasi
        # tilga qaramasdan doim o'zbekcha yozilardi.
        "admin_new_request_title": "🔔 <b>Yangi so'rov</b>",
        "admin_new_request_body": "Botdan foydalanishga ruxsat so'rayapti.\nPastdagi tugma orqali shu yerdan tasdiqlashingiz yoki rad etishingiz mumkin (yoki dasturdagi 'Telegram sozlamalari' oynasidan ham).",
        "admin_btn_approve": "✅ Ruxsat berish",
        "admin_btn_reject": "🚫 Rad etish",
        "admin_btn_remove": "🚫 Chiqarib tashlash",
        "admin_decision_approved_title": "✅ <b>Ruxsat berildi{suffix}</b>",
        "admin_decision_rejected_title": "🚫 <b>Rad etildi{suffix}</b>",
        "admin_decision_removed_title": "🚫 <b>Chiqarib tashlandi</b>",
        "admin_via_app_suffix": " (dastur orqali)",
        "admin_answer_approved": "Ruxsat berildi ✅",
        "admin_answer_rejected": "Rad etildi 🚫",
        "admin_answer_removed": "Chiqarib tashlandi 🚫",
        "admin_no_permission_callback": "Sizda bu amalni bajarish huquqi yo'q.",
        "admin_no_pending": "Hozircha kutilayotgan so'rov yo'q.",
        "admin_no_approved": "Hozircha hech kimga ruxsat berilmagan.",
        "admin_pending_title": "🔔 <b>Kutilayotgan so'rov</b>",
        "admin_approved_title": "✅ <b>Ruxsat berilgan</b>",
        "admin_help": "🛠 <b>Admin buyruqlari</b>\n\n/pending — kutilayotgan so'rovlarni ko'rish\n/approved — ruxsat berilganlar ro'yxati (chiqarib tashlash imkoni bilan)\n\nIstalgan mahsulot nomini yozsangiz, uning narxi va qoldig'ini ko'rsataman (bazangizni to'g'ridan-to'g'ri o'qiyman, alohida ruxsat kerak emas).",
        "admin_granted": "👑 <b>Siz botning administratori etib belgilandingiz.</b>\n\nEndi dasturdan alohida ruxsat so'ramasdan, botdan turib:\n— botga yozgan odamlarning so'rovlarini tasdiqlashingiz yoki rad etishingiz (✅/🚫),\n— ruxsat berilganlar ro'yxatini boshqarishingiz,\n— istalgan mahsulot nomini yozib, narxi/qoldig'ini bilishingiz\nmumkin.",
        "admin_revoked": "🚫 <b>Sizning administrator huquqingiz olib qo'yildi.</b>\nEndi botdan turib so'rovlarni tasdiqlash/rad etish yoki ruxsat berilganlarni boshqarish imkoniga ega emassiz.",
        # MUHIM (yangi funksiya): admin endi har bir ruxsat berilgan
        # foydalanuvchining Mini App huquqlarini (narx so'rash/savdo/
        # mahsulot qo'shish/hisobotlar) BEVOSITA BOTDAN turib, kompyuterni
        # ochmasdan ham yoqib-o'chirib turishi mumkin.
        "admin_btn_permissions": "⚙️ Ruxsatlar",
        "admin_btn_back": "⬅️ Orqaga",
        "admin_perm_menu_title": "⚙️ <b>Ruxsatlarni boshqarish</b>",
        "admin_perm_toggled": "✅ Yangilandi",
        "admin_user_not_found": "❌ Bu foydalanuvchi topilmadi (chiqarib tashlangan bo'lishi mumkin).",
    },
    "en": {
        "new_sale": "New sale", "total": "Total", "profit": "Profit",
        "payment": "Payment", "cash": "Cash", "credit": "Credit (on debt)",
        "customer": "Customer", "currency": "so'm",
        "choose_lang": "Hello! Please choose your language:",
        "lang_saved": "✅ Language set to English. Please wait for the admin to approve you.",
        "access_granted": "✅ You have been granted access to the bot.\nYou will now receive a notification for every sale.",
        "access_rejected": "🚫 Your request has been rejected.",
        "access_removed": "🚫 Your access to the bot has been revoked.\nYou will no longer receive sale/notification messages.",
        "no_permission": "🚫 You don't have permission to check product prices. Ask the shop owner.",
        "not_found": "❌ No product found matching \"{q}\".",
        "results_header": "🔎 Search results — \"{q}\":",
        "price": "Price", "qty": "In stock",
        "choose_lang_change": "Choose your language:",
        "lang_changed": "✅ Language changed to English.",
        "admin_new_request_title": "🔔 <b>New request</b>",
        "admin_new_request_body": "Is requesting access to the bot.\nUse the button below to approve or reject right here (or from the 'Telegram settings' window in the app).",
        "admin_btn_approve": "✅ Approve",
        "admin_btn_reject": "🚫 Reject",
        "admin_btn_remove": "🚫 Remove",
        "admin_decision_approved_title": "✅ <b>Approved{suffix}</b>",
        "admin_decision_rejected_title": "🚫 <b>Rejected{suffix}</b>",
        "admin_decision_removed_title": "🚫 <b>Removed</b>",
        "admin_via_app_suffix": " (via the app)",
        "admin_answer_approved": "Approved ✅",
        "admin_answer_rejected": "Rejected 🚫",
        "admin_answer_removed": "Removed 🚫",
        "admin_no_permission_callback": "You don't have permission to do this.",
        "admin_no_pending": "No pending requests right now.",
        "admin_no_approved": "No one has been approved yet.",
        "admin_pending_title": "🔔 <b>Pending request</b>",
        "admin_approved_title": "✅ <b>Approved</b>",
        "admin_help": "🛠 <b>Admin commands</b>\n\n/pending — view pending requests\n/approved — list of approved users (with an option to remove)\n\nType any product name and I'll show its price and stock (I read your database directly, no separate permission needed).",
        "admin_granted": "👑 <b>You have been set as the bot's administrator.</b>\n\nWithout needing separate permission from the app, you can now, right from the bot:\n— approve or reject people's requests (✅/🚫),\n— manage the list of approved users,\n— type any product name to check its price/stock.",
        "admin_revoked": "🚫 <b>Your administrator rights have been removed.</b>\nYou can no longer approve/reject requests or manage approved users from the bot.",
        "admin_btn_permissions": "⚙️ Permissions",
        "admin_btn_back": "⬅️ Back",
        "admin_perm_menu_title": "⚙️ <b>Manage permissions</b>",
        "admin_perm_toggled": "✅ Updated",
        "admin_user_not_found": "❌ This user was not found (may have been removed).",
    },
    "ru": {
        "new_sale": "Новая продажа", "total": "Итого", "profit": "Прибыль",
        "payment": "Оплата", "cash": "Наличные", "credit": "В долг",
        "customer": "Покупатель", "currency": "сум",
        "choose_lang": "Здравствуйте! Пожалуйста, выберите язык:",
        "lang_saved": "✅ Язык сохранён: русский. Дождитесь подтверждения администратора.",
        "access_granted": "✅ Вам предоставлен доступ к боту.\nТеперь вы будете получать уведомление о каждой продаже.",
        "access_rejected": "🚫 Ваш запрос отклонён.",
        "access_removed": "🚫 Ваш доступ к боту отозван.\nВы больше не будете получать уведомления о продажах.",
        "no_permission": "🚫 У вас нет разрешения проверять цены товаров. Спросите владельца магазина.",
        "not_found": "❌ Товар по запросу \"{q}\" не найден.",
        "results_header": "🔎 Результаты поиска — \"{q}\":",
        "price": "Цена", "qty": "В наличии",
        "choose_lang_change": "Выберите язык:",
        "lang_changed": "✅ Язык изменён на русский.",
        "admin_new_request_title": "🔔 <b>Новый запрос</b>",
        "admin_new_request_body": "Просит доступ к боту.\nКнопкой ниже вы можете подтвердить или отклонить прямо здесь (или из окна 'Настройки Telegram' в программе).",
        "admin_btn_approve": "✅ Разрешить",
        "admin_btn_reject": "🚫 Отклонить",
        "admin_btn_remove": "🚫 Убрать",
        "admin_decision_approved_title": "✅ <b>Разрешено{suffix}</b>",
        "admin_decision_rejected_title": "🚫 <b>Отклонено{suffix}</b>",
        "admin_decision_removed_title": "🚫 <b>Убрано</b>",
        "admin_via_app_suffix": " (через программу)",
        "admin_answer_approved": "Разрешено ✅",
        "admin_answer_rejected": "Отклонено 🚫",
        "admin_answer_removed": "Убрано 🚫",
        "admin_no_permission_callback": "У вас нет прав для этого действия.",
        "admin_no_pending": "Пока нет ожидающих запросов.",
        "admin_no_approved": "Пока никому не предоставлен доступ.",
        "admin_pending_title": "🔔 <b>Ожидающий запрос</b>",
        "admin_approved_title": "✅ <b>Разрешён</b>",
        "admin_help": "🛠 <b>Команды администратора</b>\n\n/pending — просмотреть ожидающие запросы\n/approved — список разрешённых пользователей (с возможностью удаления)\n\nНапишите название любого товара — покажу его цену и остаток (читаю вашу базу напрямую, отдельное разрешение не нужно).",
        "admin_granted": "👑 <b>Вы назначены администратором бота.</b>\n\nТеперь, не спрашивая отдельного разрешения в программе, вы можете прямо из бота:\n— подтверждать или отклонять запросы (✅/🚫),\n— управлять списком разрешённых пользователей,\n— написать название товара, чтобы узнать его цену/остаток.",
        "admin_revoked": "🚫 <b>Ваши права администратора отозваны.</b>\nВы больше не можете подтверждать/отклонять запросы или управлять пользователями из бота.",
        "admin_btn_permissions": "⚙️ Разрешения",
        "admin_btn_back": "⬅️ Назад",
        "admin_perm_menu_title": "⚙️ <b>Управление разрешениями</b>",
        "admin_perm_toggled": "✅ Обновлено",
        "admin_user_not_found": "❌ Пользователь не найден (возможно, был удалён).",
    },
}


def _tg_str(lang, key, **kwargs):
    d = _TG_STRINGS.get(lang) or _TG_STRINGS["uz"]
    text = d.get(key) or _TG_STRINGS["uz"].get(key, key)
    return text.format(**kwargs) if kwargs else text


def _admin_lang(settings):
    """Admin botdan turib olgan BARCHA xabarlarni (yangi so'rov, /pending,
    /approved, qaror natijasi, adminlik berilgan/olib qo'yilgan xabarlari
    va h.k.) o'zi /til orqali tanlagan tilda olishi uchun -- hali hech
    qanday til tanlamagan bo'lsa (masalan endigina admin etib
    belgilangan), "uz"ga tushadi."""
    lang = settings.get("telegram_admin_language")
    return lang if lang in _TG_STRINGS else "uz"


def build_telegram_sale_message(items, total, total_profit, payment_type, method_label=None,
                                  customer_name=None, lang="uz"):
    """Sotuv haqidagi Telegram xabarini beriladigan TILGA (uz/en/ru) mos
    qilib quradi -- MUHIM: bu funksiya dastur interfeysi tiliga (be.LANG)
    bog'liq EMAS, chunki har bir Telegram foydalanuvchisi o'z tilini bot
    orqali mustaqil tanlaydi (qarang: _send_language_picker). Shu sababli
    alohida _TG_STRINGS lug'atidan foydalaniladi."""
    lang = lang if lang in _TG_STRINGS else "uz"
    s = _TG_STRINGS[lang]
    lines = [f"🧾 <b>{s['new_sale']}</b>"]
    for i in items:
        unit_label = _tg_unit_label(i['unit'], lang)
        lines.append(f"• {i['name']} — {fmt_qty(i['qty'], unit_label)} x {fmt_money(i['price'])} {s['currency']}")
    lines.append(f"<b>{s['total']}:</b> {fmt_money(total)} {s['currency']}")
    lines.append(f"<b>{s['profit']}:</b> {fmt_money(total_profit)} {s['currency']}")
    if payment_type == "naqd":
        lines.append(f"{s['payment']}: {method_label or s['cash']}")
    else:
        lines.append(f"{s['payment']}: {s['credit']}")
        if customer_name:
            lines.append(f"{s['customer']}: {customer_name}")
    lines.append(datetime.datetime.now().strftime("%d.%m.%Y %H:%M"))
    return "\n".join(lines)


def _tg_unit_label(unit, lang):
    """fmt_qty() birlik nomini (dona/kg/litr/metr) botga yuboriladigan
    tilga mos ravishda tarjima qiladi -- kichik, mustaqil lug'at."""
    table = {
        "dona": {"en": "pcs", "ru": "шт"},
        "kg": {"en": "kg", "ru": "кг"},
        "litr": {"en": "L", "ru": "л"},
        "metr": {"en": "m", "ru": "м"},
    }
    return table.get(unit, {}).get(lang, unit)


def send_sale_notifications(items, total, total_profit, payment_type, method_label=None,
                              customer_name=None, sale_batch=None):
    """send_telegram_to_all_approved()'ning O'RNINI bosuvchi, TILGA MOS
    xabar yuboradigan funksiya.

    MUHIM: avval BARCHA ruxsat berilgan foydalanuvchilarga BITTA (doim
    o'zbekcha) xabar matni yuborilar edi. Endi har bir foydalanuvchining
    o'zi bot orqali tanlagan tiliga (user["language"]) qarab, xabar
    ALOHIDA-ALOHIDA, o'sha tilda tarjima qilinib yuboriladi."""
    settings = load_settings()
    token = (settings.get("telegram_bot_token") or "").strip()
    approved = settings.get("telegram_approved_users") or []
    admin_chat_id = (settings.get("telegram_admin_chat_id") or "").strip()

    recipients = []
    seen = set()
    for user in approved:
        cid = user.get("chat_id")
        if cid is None:
            continue
        key = str(cid)
        if key in seen:
            continue
        seen.add(key)
        recipients.append((cid, user.get("language") or "uz"))
    if admin_chat_id and admin_chat_id not in seen:
        # MUHIM (yo'qolgan funksiya qaytarildi): adminga ham sotuv
        # xabarlari O'ZI tanlagan tilda ("telegram_admin_language")
        # yuborilishi kerak, doim o'zbekcha emas.
        recipients.append((admin_chat_id, _admin_lang(settings)))

    if not token or not recipients:
        return

    def _send_all():
        to_queue = []
        for cid, lang in recipients:
            # MUHIM TUZATISH: qayta yuborishdan oldin, shu sotuvga oid
            # xabar shu chat_id'ga ALLAQACHON yuborilganmi tekshiriladi --
            # ikki karra yuborish (masalan internet uzilib-ulanganda)ning
            # oldini olish uchun.
            if sale_batch and _sale_message_already_sent(sale_batch, cid):
                continue
            text = build_telegram_sale_message(items, total, total_profit, payment_type,
                                                 method_label=method_label, customer_name=customer_name,
                                                 lang=lang)
            message_id = _telegram_send_get_message_id(token, cid, text)
            if message_id is not None:
                if sale_batch:
                    _store_sale_telegram_message(sale_batch, cid, message_id)
            else:
                to_queue.append({"chat_id": cid, "text": text, "queued_at": now_str(),
                                  "sale_batch": sale_batch})
        if to_queue:
            with _telegram_lock():
                s = load_settings()
                q = s.get("telegram_pending_messages") or []
                q.extend(to_queue)
                s["telegram_pending_messages"] = q
                save_settings(s)

    import threading
    threading.Thread(target=_send_all, daemon=True).start()


_TG_LANG_FLAGS = {"uz": "🇺🇿", "en": "🇬🇧", "ru": "🇷🇺"}

# MUHIM (yo'qolgan funksiya qaytarildi): bu yorliqlar FAQAT admin-ga
# yuboriladigan xabarlarda (/pending, /approved, qaror natijalari) ko'rinadi
# -- shuning uchun admin o'zi tanlagan tilga ("telegram_admin_language")
# mos tarjima qilinishi kerak.
_TG_PERM_LABELS = {
    "uz": {"query": "🔎 narx so'rash", "sale": "🛒 savdo qilish",
           "manage": "📦 mahsulot qo'shish", "reports": "📊 hisobotlar"},
    "en": {"query": "🔎 price lookup", "sale": "🛒 make sales",
           "manage": "📦 add products", "reports": "📊 reports"},
    "ru": {"query": "🔎 узнавать цену", "sale": "🛒 продажи",
           "manage": "📦 добавление товаров", "reports": "📊 отчёты"},
}


def _telegram_user_label(user, lang="uz"):
    lang = lang if lang in _TG_PERM_LABELS else "uz"
    labels = _TG_PERM_LABELS[lang]
    parts = []
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
    if name:
        parts.append(name)
    if user.get("username"):
        parts.append(f"@{user['username']}")
    parts.append(f"ID: {user.get('chat_id')}")
    ulang = user.get("language")
    if ulang:
        parts.append(_TG_LANG_FLAGS.get(ulang, ulang))
    if user.get("can_query_products"):
        parts.append(f"{labels['query']}: ✅")
    if user.get("can_make_sales"):
        parts.append(f"{labels['sale']}: ✅")
    if user.get("can_manage_products"):
        parts.append(f"{labels['manage']}: ✅")
    if user.get("can_view_reports"):
        parts.append(f"{labels['reports']}: ✅")
    return " — ".join(parts)


def _find_approved_user(cid):
    settings = load_settings()
    approved = settings.get("telegram_approved_users") or []
    return next((u for u in approved if str(u.get("chat_id")) == str(cid)), None)


def _build_permission_buttons(user, lang):
    """YANGI FUNKSIYA (foydalanuvchi so'rovi bilan): admin endi ruxsat
    berilgan har bir odamning Mini App huquqlarini (narx so'rash/savdo
    qilish/mahsulot qo'shish/hisobotlar) BEVOSITA BOTDAN turib, kompyuterni
    ochmasdan ham yoqib-o'chirib turishi mumkin -- har bir tugma joriy
    holatni (✅/❌) ko'rsatadi va bosilganda darhol teskarisiga o'giradi."""
    lang = lang if lang in _TG_PERM_LABELS else "uz"
    labels = _TG_PERM_LABELS[lang]
    cid = user.get("chat_id")

    def _mark(flag):
        return "✅" if flag else "❌"

    return [
        (f"{labels['query']}: {_mark(user.get('can_query_products'))}", f"tgperm:query:{cid}"),
        (f"{labels['sale']}: {_mark(user.get('can_make_sales'))}", f"tgperm:sale:{cid}"),
        (f"{labels['manage']}: {_mark(user.get('can_manage_products'))}", f"tgperm:manage:{cid}"),
        (f"{labels['reports']}: {_mark(user.get('can_view_reports'))}", f"tgperm:reports:{cid}"),
        (_tg_str(lang, "admin_btn_back"), f"tgpermback:{cid}"),
    ]


def set_telegram_product_query_permission(cid, allowed):
    """Admin dastur ichidan (Telegram sozlamalari oynasidan) ruxsat
    berilgan foydalanuvchiga MAHSULOT NARXI/QOLDIG'INI botdan so'rash
    huquqini yoqadi/o'chiradi. MUHIM: bu ruxsat FAQAT allaqachon
    "ruxsat berilgan" (approved) foydalanuvchilarga beriladi -- oddiy
    (hali tasdiqlanmagan) so'rovchilar bu imkoniyatdan foydalana olmaydi."""
    with _telegram_lock():
        settings = load_settings()
        approved = settings.get("telegram_approved_users") or []
        changed = False
        for u in approved:
            if str(u.get("chat_id")) == str(cid):
                u["can_query_products"] = bool(allowed)
                changed = True
        if changed:
            settings["telegram_approved_users"] = approved
            save_settings(settings)
        return changed


def search_products_for_bot(query, limit=8):
    """Telegram bot orqali mahsulot nomi yoki shtrix kod bo'yicha qidiradi
    -- MUHIM: bu funksiya FAQAT admin ruxsat bergan (can_query_products)
    foydalanuvchilar uchun ishlatiladi, quyida _telegram_poll_loop() da
    tekshiriladi."""
    query = (query or "").strip()
    if not query:
        return []
    conn = get_conn()
    like = f"%{query}%"
    rows = conn.execute(
        "SELECT name, price, qty, unit FROM products "
        "WHERE barcode=? OR name LIKE ? ORDER BY name LIMIT ?",
        (query, like, limit)).fetchall()
    conn.close()
    return rows


def build_product_query_reply(query, rows, lang="uz"):
    lang = lang if lang in _TG_STRINGS else "uz"
    if not rows:
        return _tg_str(lang, "not_found", q=query)
    lines = [_tg_str(lang, "results_header", q=query)]
    for name, price, qty, unit in rows:
        unit_label = _tg_unit_label(unit, lang)
        s = _TG_STRINGS[lang]
        lines.append(f"• <b>{name}</b>\n  {s['price']}: {fmt_money(price)} {s['currency']}   "
                     f"{s['qty']}: {fmt_qty(qty, unit_label)}")
    return "\n".join(lines)


def _send_language_picker(token, chat_id):
    buttons = [(label, f"tglang:{code}:{chat_id}") for code, label in _TG_LANGUAGES]
    _telegram_send_with_buttons(token, chat_id, _tg_str("uz", "choose_lang"), buttons)


def _send_language_change_picker(token, chat_id):
    """/til buyrug'i orqali -- ALLAQACHON ruxsat berilgan (yoki so'rovi
    kutilayotgan) foydalanuvchi tilini istalgan vaqtda o'zgartirishi uchun.
    MUHIM: bu yangi so'rov emas, shuning uchun boshqa callback prefiksi
    ("tglangchg:") ishlatiladi -- shu orqali "yangi foydalanuvchi" oqimi
    (tglang:) bilan aralashib ketmaydi."""
    buttons = [(label, f"tglangchg:{code}:{chat_id}") for code, label in _TG_LANGUAGES]
    _telegram_send_with_buttons(token, chat_id, "🌐 Til / Language / Язык:", buttons)


_TELEGRAM_COMMANDS_REGISTERED_FOR = None
_TELEGRAM_DEFAULT_COMMANDS_REGISTERED_FOR = None

_ADMIN_TELEGRAM_COMMANDS = [
    {"command": "pending", "description": "Kutilayotgan so'rovlar"},
    {"command": "approved", "description": "Ruxsat berilganlar ro'yxati"},
    {"command": "help", "description": "Yordam / buyruqlar ro'yxati"},
    {"command": "til", "description": "Tilni almashtirish"},
]

# MUHIM: oddiy foydalanuvchilar uchun buyruqlar ro'yxati -- ATAYLAB faqat
# "/til" bor, /pending, /approved, /help YO'Q. Bu ro'yxat "default" scope
# (barcha foydalanuvchilar uchun umumiy) sifatida yuboriladi -- shu orqali
# admin-ga tegishli buyruqlar oddiy foydalanuvchilarning bot menyusida
# UMUMAN ko'rinmaydi (avval bu buyruqlar ehtimol @BotFather orqali yoki
# eski kod bilan "default" scope'ga o'rnatilib qolgan bo'lishi mumkin edi).
_USER_TELEGRAM_COMMANDS = [
    {"command": "til", "description": "Tilni almashtirish / Change language / Сменить язык"},
]


def notify_new_telegram_admin(token, chat_id):
    """BUG TUZATISH (yo'qolgan funksiya qaytarildi): "Telegram sozlamalari"
    oynasida admin chat_id YANGI kiritilganda (yoki o'zgartirilganda), o'sha
    odamga botdan "Siz administrator etib belgilandingiz" xabari va til
    tanlash tugmalari yuborilishi kerak edi -- MUHIM: bu odam pending/
    approved ro'yxatlariga UMUMAN qo'shilmaydi va undan hech qanday alohida
    ruxsat (dasturdagi "Ruxsat berish" tugmasi) so'ralmaydi -- u chat_id
    orqali admin sifatida tanilgani uchun avtomatik to'liq huquqqa ega
    (pending/approved odamlarni bot ichidan boshqarish, istalgan mahsulotni
    so'rash va h.k.). Ilgari bu xabar umuman yuborilmasdi, shu sababli
    admin o'zi ID kiritgandan keyin ham botdan hech qanday tasdiqlovchi
    javob olmasdi."""
    if not token or not chat_id:
        return
    lang = _admin_lang(load_settings())
    _telegram_send(token, chat_id, _tg_str(lang, "admin_granted"))
    try:
        _send_language_change_picker(token, chat_id)
    except Exception:
        pass


def notify_admin_removed(token, chat_id, lang="uz"):
    """BUG TUZATISH (yo'qolgan funksiya qaytarildi): admin chat_id
    "Telegram sozlamalari" oynasidan o'chirilganda (yoki boshqa odamga
    almashtirilganda), ESKI admin o'zi oldin tanlagan tilda "administrator
    huquqingiz olib qo'yildi" xabarini olishi kerak -- shuning uchun bu
    funksiya `lang` parametrini chaqiruvchi (GUI) tomonidan, sozlamalar
    ALMASHTIRILISHDAN OLDIN o'qib olingan "telegram_admin_language"
    qiymati bilan chaqiriladi."""
    if not token or not chat_id:
        return
    lang = lang if lang in _TG_STRINGS else "uz"
    _telegram_send(token, chat_id, _tg_str(lang, "admin_revoked"))


def _telegram_register_default_commands(token, force=False):
    """Botning HAMMA foydalanuvchilar uchun umumiy ("default" scope)
    buyruqlar ro'yxatini o'rnatadi/qayta yozadi -- FAQAT "/til". Bu chaqiruv
    admin-ga tegishli chat-scoped ro'yxatdan (yuqorida) MUSTAQIL ishlaydi va
    uni almashtirmaydi -- Telegram botlarida "default" va "chat" scope'lar
    alohida-alohida saqlanadi, shuning uchun ikkalasini ham aniq
    o'rnatish kerak."""
    global _TELEGRAM_DEFAULT_COMMANDS_REGISTERED_FOR
    if not token:
        return
    if not force and _TELEGRAM_DEFAULT_COMMANDS_REGISTERED_FOR == token:
        return
    import json as _json
    result = _telegram_api_call(token, "setMyCommands", {
        "commands": _json.dumps(_USER_TELEGRAM_COMMANDS),
    })
    if result and result.get("ok"):
        _TELEGRAM_DEFAULT_COMMANDS_REGISTERED_FOR = token


def _telegram_register_admin_commands(token, admin_chat_id, force=False):
    global _TELEGRAM_COMMANDS_REGISTERED_FOR
    if not token or not admin_chat_id:
        return
    key = (token, str(admin_chat_id))
    if not force and _TELEGRAM_COMMANDS_REGISTERED_FOR == key:
        return
    import json as _json
    scope = {"type": "chat", "chat_id": admin_chat_id}
    result = _telegram_api_call(token, "setMyCommands", {
        "commands": _json.dumps(_ADMIN_TELEGRAM_COMMANDS),
        "scope": _json.dumps(scope),
    })
    if result and result.get("ok"):
        _TELEGRAM_COMMANDS_REGISTERED_FOR = key


def _handle_admin_command(token, admin_chat_id, text):
    text = (text or "").strip()
    cmd = text.split("@")[0].split()[0].lower() if text else ""
    # MUHIM (yo'qolgan funksiya qaytarildi): pastdagi HAMMA javoblar endi
    # admin o'zi /til orqali tanlagan tilda ("telegram_admin_language")
    # yuboriladi -- ilgari bularning barchasi tilga qaramasdan doim
    # o'zbekcha yozilardi.
    lang = _admin_lang(load_settings())
    if cmd == "/til":
        try:
            _send_language_change_picker(token, admin_chat_id)
        except Exception:
            pass
        return True
    if cmd not in ("/pending", "/approved", "/help", "/start"):
        # MUHIM: admin (do'kon egasi) hech kimdan ruxsat so'ramaydi -- u
        # o'zi barcha mahsulotlarni istalgan vaqtda so'rashi mumkin. Agar
        # yozilgan matn tanilgan buyruq bo'lmasa va bo'sh bo'lmasa, uni
        # mahsulot qidiruvi deb hisoblab, bazadan javob qaytaramiz.
        if text and not text.startswith("/"):
            rows = search_products_for_bot(text)
            reply = build_product_query_reply(text, rows, lang=lang)
            _telegram_send(token, admin_chat_id, reply)
            return True
        return False

    if cmd in ("/help", "/start"):
        _telegram_send(token, admin_chat_id, _tg_str(lang, "admin_help"))
        return True

    if cmd == "/pending":
        settings = load_settings()
        pending = settings.get("telegram_pending_requests") or []
        if not pending:
            _telegram_send(token, admin_chat_id, _tg_str(lang, "admin_no_pending"))
            return True
        for user in pending:
            cid = user.get("chat_id")
            pending_text = f"{_tg_str(lang, 'admin_pending_title')}\n{_telegram_user_label(user, lang)}"
            send_result = _telegram_send_with_buttons(
                token, admin_chat_id, pending_text,
                buttons=[(_tg_str(lang, "admin_btn_approve"), f"tgapprove:{cid}"),
                         (_tg_str(lang, "admin_btn_reject"), f"tgreject:{cid}")])
            try:
                if send_result and send_result.get("ok") and not user.get("admin_msg_id"):
                    with _telegram_lock():
                        s = load_settings()
                        p = s.get("telegram_pending_requests") or []
                        for u in p:
                            if str(u.get("chat_id")) == str(cid):
                                u["admin_msg_id"] = send_result["result"]["message_id"]
                        s["telegram_pending_requests"] = p
                        save_settings(s)
            except Exception:
                pass
        return True

    if cmd == "/approved":
        settings = load_settings()
        approved = settings.get("telegram_approved_users") or []
        if not approved:
            _telegram_send(token, admin_chat_id, _tg_str(lang, "admin_no_approved"))
            return True
        for user in approved:
            cid = user.get("chat_id")
            approved_text = f"{_tg_str(lang, 'admin_approved_title')}\n{_telegram_user_label(user, lang)}"
            # YANGI FUNKSIYA: "⚙️ Ruxsatlar" tugmasi -- admin shu yerdan,
            # kompyuterni ochmasdan, ushbu odamning Mini App huquqlarini
            # (narx so'rash/savdo/mahsulot qo'shish/hisobotlar) boshqarishi
            # uchun.
            _telegram_send_with_buttons(
                token, admin_chat_id, approved_text,
                buttons=[(_tg_str(lang, "admin_btn_permissions"), f"tgpermmenu:{cid}"),
                         (_tg_str(lang, "admin_btn_remove"), f"tgremove:{cid}")])
        return True

    return False


def _telegram_poll_loop(stop_flag):
    import time
    last_update_id = None
    while not stop_flag["stop"]:
        try:
            settings = load_settings()
            token = (settings.get("telegram_bot_token") or "").strip()
            admin_chat_id = (settings.get("telegram_admin_chat_id") or "").strip()
            # MUHIM (yo'qolgan funksiya qaytarildi): admin-ga botdan turib
            # yuboriladigan BARCHA xabarlar shu tsikl davomida admin o'zi
            # tanlagan tilda ("telegram_admin_language") yozilishi uchun.
            admin_lang = _admin_lang(settings)
            if not token:
                time.sleep(5)
                continue

            _telegram_register_default_commands(token)
            if admin_chat_id:
                _telegram_register_admin_commands(token, admin_chat_id)

            pending_msgs = settings.get("telegram_pending_messages") or []
            if pending_msgs:
                still_pending = []
                for item in pending_msgs:
                    # MUHIM TUZATISH: qayta urinishdan oldin ham xuddi
                    # shunday tekshiriladi -- agar bu xabar biror sabab
                    # bilan (masalan boshqa oqim orqali) ALLAQACHON
                    # yuborilgan bo'lsa, navbatdan shunchaki olib
                    # tashlanadi, qayta yuborilmaydi.
                    if item.get("sale_batch") and _sale_message_already_sent(
                            item["sale_batch"], item["chat_id"]):
                        continue
                    message_id = _telegram_send_get_message_id(token, item["chat_id"], item["text"])
                    if message_id is not None:
                        if item.get("sale_batch"):
                            _store_sale_telegram_message(item["sale_batch"], item["chat_id"], message_id)
                        continue
                    still_pending.append(item)
                with _telegram_lock():
                    s = load_settings()
                    s["telegram_pending_messages"] = still_pending
                    save_settings(s)

            if last_update_id is None:
                last_update_id = settings.get("telegram_last_update_id", 0)

            params = {"timeout": 20, "offset": last_update_id + 1} if last_update_id else {"timeout": 20}
            result = _telegram_api_call(token, "getUpdates", params, timeout=25)
            if not result or not result.get("ok"):
                time.sleep(5)
                continue

            updates = result.get("result", [])
            if not updates:
                time.sleep(1)
                continue

            # MUHIM TUZATISH: agar quyidagi qayta ishlash (xabar yuborish,
            # baza so'rovi va h.k.) davomida kutilmagan xatolik yuz bersa,
            # avvalgi kod "offset"ni HECH QACHON saqlamas edi -- natijada
            # Telegram O'SHA XABAR(LAR)NI CHEKSIZ QAYTA-QAYTA yuborar edi,
            # bot esa har safar qayta javob yozar edi ("to'xtovsiz" javob
            # muammosi shundan kelib chiqqan). Endi eng yuqori update_id
            # QAYTA ISHLASHDAN OLDIN, DARHOL saqlanadi -- shu bilan Telegram
            # bu xabarlarni "o'qilgan" deb belgilaydi va qayta yubormaydi,
            # qayta ishlashda xatolik bo'lsa ham xabar takrorlanmaydi.
            new_last_update_id = last_update_id or 0
            for upd in updates:
                new_last_update_id = max(new_last_update_id, upd.get("update_id", 0))
            if new_last_update_id != (last_update_id or 0):
                last_update_id = new_last_update_id
                try:
                    with _telegram_lock():
                        s = load_settings()
                        s["telegram_last_update_id"] = last_update_id
                        save_settings(s)
                except Exception:
                    pass

            callback_updates = [u for u in updates if u.get("callback_query")]
            message_updates = [u for u in updates if not u.get("callback_query")]

            for upd in callback_updates:
                cq = upd["callback_query"]
                cq_id = cq.get("id")
                data = cq.get("data") or ""
                from_id = (cq.get("from") or {}).get("id")
                message = cq.get("message") or {}
                msg_chat_id = (message.get("chat") or {}).get("id")
                msg_id = message.get("message_id")

                # "tglang:" -- so'rovchi o'zi uchun til tanlaydi, shuning uchun
                # bu amal FAQAT admin bajaradigan amallar tekshiruvidan
                # (quyidagi guard) chetlab o'tishi kerak.
                if data.startswith("tglang:"):
                    parts = data.split(":")
                    if len(parts) == 3:
                        _, lang_code, lang_cid = parts
                        if str(from_id) == str(lang_cid) and lang_code in _TG_STRINGS:
                            # MUHIM TUZATISH (foydalanuvchi so'rovi -- "til
                            # tanlash sekin ishlayapti, ba'zida dastur ham
                            # javob bermay qolyapti"): sozlamalarni
                            # o'zgartirish (tez, tarmoqsiz) va Telegramga
                            # javob berish (sekin bo'lishi mumkin bo'lgan
                            # TARMOQ so'rovlari) endi ALOHIDA bosqichlarga
                            # ajratildi. Ilgari xabar yuborish (admin-ga
                            # bildirishnoma) umumiy qulf (_telegram_lock --
                            # bu xuddi shu qulf GUI oqimida sozlamalarni
                            # o'qish/yozish uchun ham ishlatiladi) ICHIDA
                            # bajarilardi -- internet sekin bo'lsa, shu
                            # so'rov tugaguncha QULF band bo'lib qolar, va
                            # shu payt dastur oynasi sozlamalarni o'qishga
                            # urinsa (masalan Telegram sozlamalari oynasi
                            # har 4 soniyada avtomatik yangilanadi), u ham
                            # javob bermay "muzlab" qolardi. Endi qulf FAQAT
                            # faylga yozish paytida ushlanadi, tarmoq
                            # so'rovlari esa qulf BO'SHATILGANDAN KEYIN
                            # bajariladi.
                            with _telegram_lock():
                                s = load_settings()
                                lang_pending = s.get("telegram_lang_pending") or []
                                entry = None
                                for p in lang_pending:
                                    if str(p.get("chat_id")) == str(lang_cid):
                                        entry = p
                                        break
                                if entry:
                                    lang_pending = [p for p in lang_pending if str(p.get("chat_id")) != str(lang_cid)]
                                    s["telegram_lang_pending"] = lang_pending
                                    new_user = dict(entry)
                                    new_user["language"] = lang_code
                                    pending = s.get("telegram_pending_requests") or []
                                    pending.append(new_user)
                                    s["telegram_pending_requests"] = pending
                                    save_settings(s)
                                else:
                                    new_user = None
                            if entry:
                                _telegram_answer_callback(token, cq_id, "✅")
                                if msg_chat_id and msg_id:
                                    try:
                                        _telegram_edit_message_text(
                                            token, msg_chat_id, msg_id,
                                            _tg_str(lang_code, "lang_saved"))
                                    except Exception:
                                        pass
                                if admin_chat_id:
                                    send_result = _telegram_send_with_buttons(
                                        token, admin_chat_id,
                                        f"{_tg_str(admin_lang, 'admin_new_request_title')}\n"
                                        f"{_telegram_user_label(new_user, admin_lang)}\n\n"
                                        f"{_tg_str(admin_lang, 'admin_new_request_body')}",
                                        buttons=[(_tg_str(admin_lang, "admin_btn_approve"), f"tgapprove:{lang_cid}"),
                                                 (_tg_str(admin_lang, "admin_btn_reject"), f"tgreject:{lang_cid}")])
                                    try:
                                        if send_result and send_result.get("ok"):
                                            with _telegram_lock():
                                                s2 = load_settings()
                                                pending2 = s2.get("telegram_pending_requests") or []
                                                for p in pending2:
                                                    if str(p.get("chat_id")) == str(lang_cid):
                                                        p["admin_msg_id"] = send_result["result"]["message_id"]
                                                s2["telegram_pending_requests"] = pending2
                                                save_settings(s2)
                                    except Exception:
                                        pass
                            else:
                                _telegram_answer_callback(token, cq_id)
                        else:
                            _telegram_answer_callback(token, cq_id)
                    else:
                        _telegram_answer_callback(token, cq_id)
                    continue

                # "tglangchg:" -- /til buyrug'i orqali, ALLAQACHON ruxsat
                # berilgan (yoki so'rovi kutilayotgan) foydalanuvchi o'z
                # tilini istalgan vaqtda o'zgartiradi. Bu ham admin bo'lmagan
                # amal, shuning uchun quyidagi admin-guard'dan oldin, alohida
                # tekshiriladi.
                if data.startswith("tglangchg:"):
                    parts = data.split(":")
                    if len(parts) == 3:
                        _, lang_code, chg_cid = parts
                        if str(from_id) == str(chg_cid) and lang_code in _TG_STRINGS:
                            with _telegram_lock():
                                s = load_settings()
                                changed = False
                                # MUHIM TUZATISH: ADMIN telegram_approved_users
                                # ro'yxatida UMUMAN yo'q (u ruxsat so'ramasdan
                                # avtomatik to'liq huquqqa ega) -- shuning
                                # uchun /til orqali tanlagan tili avval hech
                                # qayerga saqlanmay, "muvaffaqiyatli" degan
                                # xabar ko'rsatilsa ham HAQIQATDA hech narsa
                                # o'zgarmas, va Mini App hamon Telegram'ning
                                # o'z tiliga (yoki "uz"ga) tushib qolar edi.
                                # Endi admin uchun alohida sozlama kaliti
                                # ("telegram_admin_language") ishlatiladi.
                                admin_chat_id_chk = (s.get("telegram_admin_chat_id") or "").strip()
                                if admin_chat_id_chk and str(chg_cid) == str(admin_chat_id_chk):
                                    s["telegram_admin_language"] = lang_code
                                    changed = True
                                approved_list = s.get("telegram_approved_users") or []
                                for u in approved_list:
                                    if str(u.get("chat_id")) == str(chg_cid):
                                        u["language"] = lang_code
                                        changed = True
                                        break
                                if changed:
                                    s["telegram_approved_users"] = approved_list
                                pending_list = s.get("telegram_pending_requests") or []
                                for p in pending_list:
                                    if str(p.get("chat_id")) == str(chg_cid):
                                        p["language"] = lang_code
                                        changed = True
                                        break
                                if changed:
                                    s["telegram_pending_requests"] = pending_list
                                save_settings(s)
                            # MUHIM TUZATISH (foydalanuvchi so'rovi -- "admin
                            # til tanlasa birdan tanlamayapti, sekin
                            # tanlayapti, ba'zida dastur ham javob bermay
                            # o'tib ketyapti"): ilgari "Narxlar" tugmasini
                            # qayta sozlash (_set_menu_button_for_chat --
                            # Telegram serveriga TARMOQ so'rovi, sekin
                            # internetda bir necha soniya cho'zilishi mumkin)
                            # HAM javob berishdan (_telegram_answer_callback)
                            # OLDIN, HAM umumiy qulf (_telegram_lock, u xuddi
                            # shu qulf GUI oqimida sozlamalarni o'qish/yozish
                            # uchun ham ishlatiladi) ICHIDA bajarilardi.
                            # Natijada: (1) Telegram tugmadagi "yuklanmoqda"
                            # aylanuvchisi shu so'rov tugaguncha ko'rinib
                            # turar, tanlov "sekin"/"javob bermayotgandek"
                            # ko'rinardi; (2) shu vaqt davomida qulf band
                            # bo'lganidan, dastur oynasi sozlamalarni o'qishga
                            # urinsa (masalan Telegram sozlamalari oynasi har
                            # 4 soniyada avtomatik yangilanadi), UNING ham
                            # javob bermay "muzlab" qolish ehtimoli bor edi;
                            # (3) admin shu orada qayta-qayta bossa, bosishlar
                            # navbatga to'planib, keyinroq ketma-ket bajarilib,
                            # "biror joyni o'tkazib yuborgandek" ko'rinardi.
                            # Endi: qulf FAQAT faylga yozish paytida ushlanadi;
                            # Telegramga tezkor javob (✅ va xabar matni) ENG
                            # OLDIN, qulf bo'shatilgandan keyin yuboriladi;
                            # "Narxlar" tugmasini qayta sozlash (eng sekin
                            # qism) esa ENG OXIRIDA, alohida bajariladi.
                            _telegram_answer_callback(token, cq_id, "✅")
                            if msg_chat_id and msg_id:
                                try:
                                    _telegram_edit_message_text(
                                        token, msg_chat_id, msg_id,
                                        _tg_str(lang_code, "lang_changed"))
                                except Exception:
                                    pass
                            try:
                                miniapp_url = _MINIAPP_STATE.get("url")
                                if miniapp_url:
                                    _set_menu_button_for_chat(
                                        token, miniapp_url, chat_id=chg_cid, lang=lang_code)
                            except Exception:
                                pass
                        else:
                            _telegram_answer_callback(token, cq_id)
                    else:
                        _telegram_answer_callback(token, cq_id)
                    continue

                if admin_chat_id and str(from_id) != str(admin_chat_id):
                    _telegram_answer_callback(token, cq_id, _tg_str(admin_lang, "admin_no_permission_callback"))
                    continue

                # YANGI FUNKSIYA (foydalanuvchi so'rovi bilan): admin endi
                # ruxsat berilgan har bir odamning Mini App huquqlarini
                # BEVOSITA BOTDAN turib boshqarishi mumkin -- kompyuterdagi
                # dasturni ochish shart emas. "tgpermmenu:" -- ruxsatlar
                # panelini ochadi, "tgperm:<key>:<cid>" -- bitta huquqni
                # yoqadi/o'chiradi va panelni joriy holat bilan qayta
                # chizadi, "tgpermback:" -- oldingi (asosiy) kartochkaga
                # qaytaradi.
                if data.startswith("tgpermmenu:") or data.startswith("tgpermback:"):
                    _, _, perm_cid = data.partition(":")
                    user = _find_approved_user(perm_cid)
                    if not user:
                        _telegram_answer_callback(token, cq_id, _tg_str(admin_lang, "admin_user_not_found"))
                        continue
                    if data.startswith("tgpermmenu:"):
                        panel_text = f"{_tg_str(admin_lang, 'admin_perm_menu_title')}\n{_telegram_user_label(user, admin_lang)}"
                        panel_buttons = _build_permission_buttons(user, admin_lang)
                    else:
                        panel_text = f"{_tg_str(admin_lang, 'admin_approved_title')}\n{_telegram_user_label(user, admin_lang)}"
                        panel_buttons = [(_tg_str(admin_lang, "admin_btn_permissions"), f"tgpermmenu:{perm_cid}"),
                                         (_tg_str(admin_lang, "admin_btn_remove"), f"tgremove:{perm_cid}")]
                    _telegram_answer_callback(token, cq_id)
                    if msg_chat_id and msg_id:
                        _telegram_edit_message_text_with_buttons(token, msg_chat_id, msg_id, panel_text, panel_buttons)
                    continue

                if data.startswith("tgperm:"):
                    parts = data.split(":")
                    if len(parts) == 3:
                        _, perm_key, perm_cid = parts
                        setters = {
                            "query": set_telegram_product_query_permission,
                            "sale": set_telegram_sale_permission,
                            "manage": set_telegram_manage_products_permission,
                            "reports": set_telegram_reports_permission,
                        }
                        setter = setters.get(perm_key)
                        user = _find_approved_user(perm_cid)
                        current_map = {
                            "query": bool(user and user.get("can_query_products")),
                            "sale": bool(user and user.get("can_make_sales")),
                            "manage": bool(user and user.get("can_manage_products")),
                            "reports": bool(user and user.get("can_view_reports")),
                        }
                        if setter and user:
                            setter(perm_cid, not current_map.get(perm_key))
                            user = _find_approved_user(perm_cid)
                            _telegram_answer_callback(token, cq_id, _tg_str(admin_lang, "admin_perm_toggled"))
                            if user and msg_chat_id and msg_id:
                                panel_text = f"{_tg_str(admin_lang, 'admin_perm_menu_title')}\n{_telegram_user_label(user, admin_lang)}"
                                panel_buttons = _build_permission_buttons(user, admin_lang)
                                _telegram_edit_message_text_with_buttons(
                                    token, msg_chat_id, msg_id, panel_text, panel_buttons)
                        else:
                            _telegram_answer_callback(token, cq_id, _tg_str(admin_lang, "admin_user_not_found"))
                    else:
                        _telegram_answer_callback(token, cq_id)
                    continue

                action, _, target_cid = data.partition(":")

                if action == "tgapprove" and target_cid:
                    user = approve_telegram_user(target_cid)
                    _telegram_answer_callback(token, cq_id, _tg_str(admin_lang, "admin_answer_approved"))
                    if msg_chat_id and msg_id:
                        cur_label = _telegram_user_label(user, admin_lang) if user else str(target_cid)
                        _telegram_edit_message_text(
                            token, msg_chat_id, msg_id,
                            f"{_tg_str(admin_lang, 'admin_decision_approved_title', suffix='')}\n{cur_label}")
                    if user and not user.get("admin_msg_id") and msg_chat_id and msg_id:
                        user = dict(user)
                        user["admin_msg_id"] = msg_id
                    _notify_telegram_decision(token, admin_chat_id, user, approved=True, via_app=False)
                    finalize_approved_menu_button(user)
                elif action == "tgreject" and target_cid:
                    user = reject_telegram_user(target_cid)
                    _telegram_answer_callback(token, cq_id, _tg_str(admin_lang, "admin_answer_rejected"))
                    if msg_chat_id and msg_id:
                        cur_label = _telegram_user_label(user, admin_lang) if user else str(target_cid)
                        _telegram_edit_message_text(
                            token, msg_chat_id, msg_id,
                            f"{_tg_str(admin_lang, 'admin_decision_rejected_title', suffix='')}\n{cur_label}")
                    if user and not user.get("admin_msg_id") and msg_chat_id and msg_id:
                        user = dict(user)
                        user["admin_msg_id"] = msg_id
                    _notify_telegram_decision(token, admin_chat_id, user, approved=False, via_app=False)
                elif action == "tgremove" and target_cid:
                    removed_user = remove_telegram_user(target_cid)
                    _telegram_answer_callback(token, cq_id, _tg_str(admin_lang, "admin_answer_removed"))
                    _notify_telegram_removal(token, removed_user)
                    if removed_user and msg_chat_id and msg_id:
                        removed_text = f"{_tg_str(admin_lang, 'admin_decision_removed_title')}\n{_telegram_user_label(removed_user, admin_lang)}"
                        _telegram_edit_message_text(token, msg_chat_id, msg_id, removed_text)
                else:
                    _telegram_answer_callback(token, cq_id)

            if admin_chat_id:
                for upd in message_updates:
                    msg = upd.get("message") or upd.get("edited_message")
                    if not msg:
                        continue
                    chat = msg.get("chat", {})
                    if str(chat.get("id")) == str(admin_chat_id):
                        _handle_admin_command(token, admin_chat_id, msg.get("text"))

            with _telegram_lock():
                settings = load_settings()
                pending = settings.get("telegram_pending_requests") or []
                approved = settings.get("telegram_approved_users") or []
                lang_pending = settings.get("telegram_lang_pending") or []
                pending_ids = {p["chat_id"] for p in pending}
                approved_ids = {a["chat_id"] for a in approved}
                lang_pending_ids = {p["chat_id"] for p in lang_pending}
                approved_by_id = {a["chat_id"]: a for a in approved}

                for upd in message_updates:
                    # (offset allaqachon yuqorida, qayta ishlashdan OLDIN saqlangan)
                    msg = upd.get("message") or upd.get("edited_message")
                    if not msg:
                        continue
                    chat = msg.get("chat", {})
                    cid = chat.get("id")
                    if cid is None:
                        continue
                    if admin_chat_id and str(cid) == str(admin_chat_id):
                        continue

                    # Ruxsat berilgan (approved) foydalanuvchi -- agar unga
                    # "mahsulot narxi/qoldig'ini so'rash" huquqi berilgan
                    # bo'lsa, yuborgan matnini mahsulot qidiruvi deb qabul
                    # qilamiz (bu — MUHIM: bu huquq FAQAT dastur ichidan,
                    # Telegram sozlamalari oynasidan admin tomonidan beriladi).
                    if cid in approved_ids:
                        text = (msg.get("text") or "").strip()
                        cmd_lower = text.split("@")[0].split()[0].lower() if text else ""
                        if cmd_lower == "/til":
                            # MUHIM: /til -- ALLAQACHON ruxsat berilgan
                            # foydalanuvchi tilini istalgan vaqtda
                            # o'zgartirishi uchun (foydalanuvchi so'rovi).
                            try:
                                _send_language_change_picker(token, cid)
                            except Exception:
                                pass
                        elif text and not text.startswith("/"):
                            u = approved_by_id.get(cid) or {}
                            lang = u.get("language") or "uz"
                            if u.get("can_query_products"):
                                try:
                                    rows = search_products_for_bot(text)
                                    reply = build_product_query_reply(text, rows, lang=lang)
                                except Exception:
                                    reply = _tg_str(lang, "not_found", q=text)
                            else:
                                reply = _tg_str(lang, "no_permission")
                            _telegram_send(token, cid, reply)
                        continue

                    if cid in pending_ids or cid in lang_pending_ids:
                        text = (msg.get("text") or "").strip()
                        cmd_lower = text.split("@")[0].split()[0].lower() if text else ""
                        if cmd_lower == "/til":
                            try:
                                _send_language_change_picker(token, cid)
                            except Exception:
                                pass
                        continue

                    # Yangi so'rovchi -- avval til tanlashini so'raymiz,
                    # admin tasdig'iga ESA faqat tilni tanlagandan keyin
                    # o'tkazamiz (callback_updates bo'limidagi "tglang:" ga qarang).
                    lang_entry = {
                        "chat_id": cid,
                        "username": chat.get("username"),
                        "first_name": chat.get("first_name"),
                        "last_name": chat.get("last_name"),
                        "requested_at": now_str(),
                    }
                    lang_pending.append(lang_entry)
                    lang_pending_ids.add(cid)
                    try:
                        _send_language_picker(token, cid)
                    except Exception:
                        pass

                settings["telegram_pending_requests"] = pending
                settings["telegram_lang_pending"] = lang_pending
                settings["telegram_last_update_id"] = last_update_id
                save_settings(settings)
        except Exception:
            time.sleep(5)


# ---------------------------------------------------------------------------
# Telegram Mini App -- botning ichida ochiladigan, tepasida qidiruv qatori
# bo'lgan alohida sahifa (chat xabari emas). Telegram bunday sahifani FAQAT
# HTTPS manzil orqali ochadi -- shuning uchun lokal http server + cloudflared
# "quick tunnel" (bepul, ro'yxatdan o'tish shart emas, uchinchi tomon hech
# qanday ma'lumot saqlamaydi -- faqat shifrlangan trafikni o'tkazadi) orqali
# ishlaydi. Ma'lumot HAR DOIM to'g'ridan-to'g'ri sizning bazangizdan (jonli)
# o'qiladi, shuning uchun sotuv bo'lganda mahsulot qoldig'i mini appda ham
# darhol yangilanadi -- alohida "sinxronlash" kerak emas.
# ---------------------------------------------------------------------------

_MINIAPP_PORT = 8934
_MINIAPP_STATE = {
    "started": False,
    "url": None,
    "error": None,
    "cloudflared_missing": False,
    "menu_button_error": None,
}


def _product_image_url(image_path):
    """Mahsulot rasmining fayl nomidan (masalan "42.jpg"), Mini App
    frontendi <img src> sifatida ishlatadigan NISBIY manzilni yasaydi.
    Haqiqiy autentifikatsiya (initData) frontend tomonidan so'rov
    yuborilganda query-parametr sifatida qo'shiladi.

    MUHIM TUZATISH (foydalanuvchi so'rovi bilan): rasm fayl nomi HAR
    DOIM bir xil (masalan "42.jpg") -- mahsulot rasmi keyinchalik
    ALMASHTIRILSA ham nomi o'zgarmaydi. Ilgari bu URL'ga "v=" parametri
    qo'shilmagan edi, natijada brauzer/Mini App eski (keshlangan) rasmni
    ko'rsatishda davom etar, yangi rasm yuklanmagan bo'lib ko'rinar edi
    (Mini App'ni yopib qayta ochgandagina yangilanardi). Endi URL'ga
    faylning O'ZGARISH VAQTI (mtime) qo'shiladi -- rasm har safar
    yangilanganda URL ham o'zgaradi, shuning uchun brauzer HAR DOIM
    yangi (eski emas) rasmni so'raydi."""
    if not image_path:
        return None
    full_path = os.path.join(PRODUCT_IMAGES_DIR, image_path)
    try:
        v = int(os.path.getmtime(full_path))
    except OSError:
        v = 0
    return f"/api/product_image/{image_path}?v={v}"


def remove_bg_square_white_bytes(raw_bytes):
    """MUHIM (foydalanuvchi so'rovi bilan): mahsulot rasmidan sun'iy
    intellekt (rembg kutubxonasi) yordamida orqa fonni avtomatik olib
    tashlaydi, mahsulotni oq fonga markazlashtirib qo'yadi va kvadrat
    shaklda qaytaradi. Bu funksiya ham kompyuterdagi dastur, ham Mini App
    (Telegram) uchun umumiy -- ikkalasi ham bir xil natijaga ega bo'lishi
    uchun shu yerda, backend'da joylashgan.

    Qaytaradi: qayta ishlangan JPEG baytlari, yoki rembg mavjud bo'lmasa/
    xato yuz bersa None (bu holda chaqiruvchi tomon oddiy saqlashga
    qaytishi kerak)."""
    try:
        from rembg import remove as rembg_remove
    except Exception:
        return None
    try:
        import io
        out_bytes = rembg_remove(raw_bytes)
        cut = Image.open(io.BytesIO(out_bytes)).convert("RGBA")

        alpha = cut.split()[-1]
        bbox = alpha.getbbox()
        if bbox:
            w, h = cut.size
            pad_x = max(4, int((bbox[2] - bbox[0]) * 0.06))
            pad_y = max(4, int((bbox[3] - bbox[1]) * 0.06))
            left = max(0, bbox[0] - pad_x)
            top = max(0, bbox[1] - pad_y)
            right = min(w, bbox[2] + pad_x)
            bottom = min(h, bbox[3] + pad_y)
            cut = cut.crop((left, top, right, bottom))

        white_flat = Image.new("RGB", cut.size, (255, 255, 255))
        white_flat.paste(cut, mask=cut.split()[-1])

        side = max(white_flat.size)
        square = Image.new("RGB", (side, side), (255, 255, 255))
        offset = ((side - white_flat.width) // 2, (side - white_flat.height) // 2)
        square.paste(white_flat, offset)

        max_side = 900
        if side > max_side:
            square = square.resize((max_side, max_side), Image.LANCZOS)

        out = io.BytesIO()
        square.save(out, format="JPEG", quality=90)
        return out.getvalue()
    except Exception:
        return None


def save_product_image_bytes(product_id, raw_bytes, ai_remove_bg=False):
    """Berilgan xom bayt (fayl kontenti)ni mahsulot rasmi sifatida
    saqlaydi -- ham kompyuterdagi dastur (fayldan tanlanganda), ham Mini
    App (telefon kamerasi/galereyasidan, base64 orqali) shu funksiyani
    ishlatadi. PIL mavjud bo'lsa, rasm ortiqcha katta bo'lib
    ketmasligi (va disk/tarmoq tejash) uchun eng katta tomoni 900px'gacha
    kichraytiriladi va sifatli JPEG qilib qayta saqlanadi; PIL bo'lmasa,
    xom baytlar o'zgarishsiz saqlanadi (kengaytma aniqlanmasa ".jpg" deb
    olinadi).

    ai_remove_bg=True bo'lsa, saqlashdan oldin remove_bg_square_white_bytes()
    orqali orqa fon avtomatik olib tashlanadi (agar rembg mavjud bo'lib,
    muvaffaqiyatli ishlasa) -- bo'lmasa, oddiy (o'zgarishsiz) rasm saqlanadi.

    Qaytaradi: yangi fayl nomi (masalan "42.jpg"), yoki xato bo'lsa
    Exception ko'taradi."""
    if ai_remove_bg and _PIL_AVAILABLE:
        processed = remove_bg_square_white_bytes(raw_bytes)
        if processed:
            raw_bytes = processed
    try:
        os.makedirs(PRODUCT_IMAGES_DIR, exist_ok=True)
    except Exception:
        pass
    filename = f"{int(product_id)}.jpg"
    full_path = os.path.join(PRODUCT_IMAGES_DIR, filename)
    if _PIL_AVAILABLE:
        import io
        img = Image.open(io.BytesIO(raw_bytes))
        img = img.convert("RGB")
        max_side = 900
        w, h = img.size
        if max(w, h) > max_side:
            if w >= h:
                new_w, new_h = max_side, int(h * max_side / w)
            else:
                new_h, new_w = max_side, int(w * max_side / h)
            img = img.resize((max(new_w, 1), max(new_h, 1)))
        img.save(full_path, format="JPEG", quality=82)
    else:
        with open(full_path, "wb") as f:
            f.write(raw_bytes)
    conn = get_conn()
    conn.execute("UPDATE products SET image_path=? WHERE id=?", (filename, int(product_id)))
    conn.commit()
    conn.close()
    return filename


def save_product_image_from_base64(product_id, image_b64, ai_remove_bg=False):
    """Mini App'dan (kamera/galereya orqali) kelgan base64 (data URL
    prefiksisiz yoki bilan) rasm ma'lumotini dekodlab saqlaydi."""
    import base64
    if "," in image_b64 and image_b64.strip().startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    raw_bytes = base64.b64decode(image_b64)
    return save_product_image_bytes(product_id, raw_bytes, ai_remove_bg=ai_remove_bg)


def save_product_image_from_file(product_id, source_path, ai_remove_bg=False):
    """Kompyuterdagi dasturda foydalanuvchi fayl tanlash oynasidan
    tanlagan rasm faylini o'qib saqlaydi."""
    with open(source_path, "rb") as f:
        raw_bytes = f.read()
    return save_product_image_bytes(product_id, raw_bytes, ai_remove_bg=ai_remove_bg)


def delete_product_image(product_id):
    """Mahsulot rasmini butunlay o'chiradi -- ham diskdagi faylni, ham
    bazadagi image_path yozuvini."""
    conn = get_conn()
    row = conn.execute("SELECT image_path FROM products WHERE id=?", (int(product_id),)).fetchone()
    image_path = row[0] if row else None
    conn.execute("UPDATE products SET image_path=NULL WHERE id=?", (int(product_id),))
    conn.commit()
    conn.close()
    if image_path:
        try:
            os.remove(os.path.join(PRODUCT_IMAGES_DIR, image_path))
        except Exception:
            pass


def get_product_image_full_path(image_path):
    """Bazada saqlangan fayl nomidan (masalan "42.jpg"), diskdagi TO'LIQ
    yo'lni yasaydi -- kompyuterdagi dasturda thumbnail ko'rsatish uchun."""
    if not image_path:
        return None
    full_path = os.path.join(PRODUCT_IMAGES_DIR, image_path)
    return full_path if os.path.exists(full_path) else None


def list_products_for_webapp(query="", limit=300):
    """Mini App uchun mahsulotlar ro'yxati/qidiruvi -- har chaqiriqda
    to'g'ridan-to'g'ri bazadan o'qiladi (shuning uchun har doim "jonli")."""
    query = (query or "").strip()
    conn = get_conn()
    if query:
        like = f"%{query}%"
        rows = conn.execute(
            "SELECT id, name, price, qty, unit, barcode, cost_price, image_path FROM products "
            "WHERE barcode=? OR name LIKE ? ORDER BY name LIMIT ?",
            (query, like, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name, price, qty, unit, barcode, cost_price, image_path FROM products "
            "ORDER BY name LIMIT ?", (limit,)).fetchall()
    conn.close()
    result = []
    for pid, name, price, qty, unit, barcode, cost_price, image_path in rows:
        result.append({
            "id": pid,
            "name": name,
            "price": price,
            "qty": qty,
            "unit": unit,
            "barcode": barcode,
            "cost_price": cost_price,
            "image_url": _product_image_url(image_path),
        })
    return result


def set_telegram_sale_permission(cid, allowed):
    """Admin dastur ichidan (Telegram sozlamalari oynasidan) ruxsat
    berilgan foydalanuvchiga Mini App orqali TELEFONDAN SAVDO QILISH
    huquqini yoqadi/o'chiradi. Bu -- 'narx so'rash' ruxsatidan alohida,
    chunki savdo qilish bazani o'zgartiradi (mahsulot qoldig'ini
    kamaytiradi, yangi sotuv yozadi) -- shuning uchun bu ancha jiddiyroq
    huquq va admin buni alohida, ongli ravishda berishi kerak."""
    with _telegram_lock():
        settings = load_settings()
        approved = settings.get("telegram_approved_users") or []
        changed = False
        for u in approved:
            if str(u.get("chat_id")) == str(cid):
                u["can_make_sales"] = bool(allowed)
                changed = True
        if changed:
            settings["telegram_approved_users"] = approved
            save_settings(settings)
        return changed


def set_telegram_manage_products_permission(cid, allowed):
    """Mini App orqali YANGI MAHSULOT QO'SHISH (va shtrix kod yaratish)
    huquqini yoqadi/o'chiradi -- savdo qilishdan ham alohida, chunki bu
    mahsulotlar ro'yxatini o'zgartiradi."""
    with _telegram_lock():
        settings = load_settings()
        approved = settings.get("telegram_approved_users") or []
        changed = False
        for u in approved:
            if str(u.get("chat_id")) == str(cid):
                u["can_manage_products"] = bool(allowed)
                changed = True
        if changed:
            settings["telegram_approved_users"] = approved
            save_settings(settings)
        return changed


def set_telegram_reports_permission(cid, allowed):
    """Mini App orqali SAVDO TARIXI VA FOYDA HISOBOTLARINI ko'rish
    huquqini yoqadi/o'chiradi -- bu faqat O'QISH huquqi (bazani
    o'zgartirmaydi), lekin moliyaviy ma'lumot bo'lgani uchun alohida
    ruxsat sifatida saqlanadi."""
    with _telegram_lock():
        settings = load_settings()
        approved = settings.get("telegram_approved_users") or []
        changed = False
        for u in approved:
            if str(u.get("chat_id")) == str(cid):
                u["can_view_reports"] = bool(allowed)
                changed = True
        if changed:
            settings["telegram_approved_users"] = approved
            save_settings(settings)
        return changed


def commit_sale_transaction(cart, payment_type, method_label=None, customer_name=None, phone=None,
                            paid_now=0):
    """Savatni bazaga BITTA amalda (tranzaksiyada) yozadi: sotuv qatorlari,
    ombor qoldig'ini kamaytirish, nasiya uchun "hozir to'langan" summa va
    qarz. Ham kompyuterdagi Savdo sahifasi, ham Mini App shu funksiyadan
    foydalanadi. Ombor qoldig'i yozish paytida QAYTA tekshiriladi -- shu
    bilan bir vaqtda ikki joydan sotuv bo'lsa ham ombor minusga tushmaydi.

    cart -- [{"product_id","name","unit","qty","cost_price","price","list_price","total"}, ...]
    Qaytaradi: (ok, error, {"sale_batch","total","total_profit","paid_now"})."""
    import uuid
    if not cart:
        return False, "Savat bo'sh.", None
    if payment_type not in ("naqd", "nasiya"):
        return False, "To'lov turi noto'g'ri.", None
    customer_name = (customer_name or "").strip() or None
    if payment_type == "nasiya" and not customer_name:
        return False, "Nasiya uchun xaridor ismi kerak.", None
    try:
        paid_now = float(paid_now or 0)
    except (TypeError, ValueError):
        paid_now = 0.0
    if not math.isfinite(paid_now) or paid_now < 0 or payment_type != "nasiya":
        paid_now = 0.0
    total = sum(i["total"] for i in cart)
    if paid_now > total + 1e-9:
        return False, "To'langan summa jami summadan katta bo'lishi mumkin emas.", None
    total_profit = sum((i["price"] - i["cost_price"]) * i["qty"] for i in cart)
    sale_batch = uuid.uuid4().hex
    date = today_str()
    created_at = now_str()

    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        need = {}
        for item in cart:
            need[item["product_id"]] = need.get(item["product_id"], 0.0) + item["qty"]
        for pid, qty_needed in need.items():
            row = conn.execute("SELECT name, qty FROM products WHERE id=?", (pid,)).fetchone()
            if not row or row[1] < qty_needed - 1e-9:
                conn.rollback()
                shown = row[0] if row else next(i["name"] for i in cart if i["product_id"] == pid)
                return False, f"\"{shown}\" mahsulotidan omborda yetarli miqdor yo'q.", None
        for item in cart:
            conn.execute(
                "INSERT INTO sales (product_id, product_name, qty, unit, cost_price, price, list_price, "
                "total, profit, payment_type, payment_method, sale_batch, date, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item["product_id"], item["name"], item["qty"], item["unit"], item["cost_price"],
                 item["price"], item["list_price"], item["total"],
                 (item["price"] - item["cost_price"]) * item["qty"], payment_type, method_label,
                 sale_batch, date, created_at))
            conn.execute("UPDATE products SET qty = qty - ? WHERE id=?", (item["qty"], item["product_id"]))

        if payment_type == "nasiya":
            conn.execute(
                "INSERT OR REPLACE INTO sale_batch_meta (sale_batch, paid_now) VALUES (?, ?)",
                (sale_batch, paid_now))
            debt_amount = total - paid_now
            if debt_amount > 1e-9:
                note = "Nasiyaga savdo"
                if paid_now > 0:
                    note = f"{fmt_money(paid_now)} to'landi, {fmt_money(debt_amount)} qoldi"
                cur = conn.execute(
                    "INSERT INTO debts (customer_name, phone, amount, note, date, paid, sale_batch) "
                    "VALUES (?,?,?,?,?,0,?)",
                    (customer_name, phone, debt_amount, note, date, sale_batch))
            else:
                # Hammasi darhol to'langan: qarz qolmaydi, lekin yozuv "to'langan"
                # holatda saqlanadi -- shunda bu sotuvning foydasi ham darhol
                # hisoblanadi (aks holda u abadiy "kutilayotgan" bo'lib qolardi).
                cur = conn.execute(
                    "INSERT INTO debts (customer_name, phone, amount, note, date, paid, sale_batch, paid_date) "
                    "VALUES (?,?,0,?,?,1,?,?)",
                    (customer_name, phone, f"{fmt_money(paid_now)} to'landi, 0 qoldi", date, sale_batch, date))
            debt_id = cur.lastrowid
            for item in cart:
                conn.execute(
                    "INSERT INTO debt_items (debt_id, product_name, qty, unit) VALUES (?,?,?,?)",
                    (debt_id, item["name"], item["qty"], item["unit"]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True, None, {"sale_batch": sale_batch, "total": total,
                        "total_profit": total_profit, "paid_now": paid_now}


def record_webapp_sale(items, payment_type, method_label=None, customer_name=None, phone=None,
                        print_receipt=False, printer_name=None, copies=1, paid_now=0):
    """Mini App'dan (telefondan) kelgan savdoni bazaga yozadi -- xuddi
    kompyuterdagi Savdo sahifasidagi kabi: sales jadvaliga qator(lar)
    qo'shadi, mahsulot qoldig'ini kamaytiradi, nasiya bo'lsa qarz
    yozadi, chek matnini tayyorlaydi va Telegram xabarnomasini
    yuboradi. 'items' -- [{"id": <mahsulot id>, "qty": <son>, "price":
    <ixtiyoriy, kelishilgan narx>}, ...]. MUHIM (foydalanuvchi so'rovi
    bilan): kompyuterdagi Savdo sahifasidagi "Narxni pasaytirish
    (chegirma)" imkoniyati Mini App savatiga ham qo'shildi -- agar
    "price" berilgan va musbat bo'lsa, o'sha (kelishilgan) narx
    ishlatiladi, mahsulotning ombordagi ASL narxi esa "list_price"
    sifatida saqlanadi (mahsulotning o'zining doimiy narxi o'zgarmaydi,
    faqat shu sotuvga tegishli).

    'print_receipt' -- True bo'lsa, chek TANLOVLI ravishda kompyuterga
    ulangan (yoki sozlamalarda eslab qolingan) chek printeriga ham
    avtomatik chop etiladi -- foydalanuvchi telefondan sotuv qilganda
    har safar o'zi tanlaydi, majburiy emas.

    Qaytaradi: (ok: bool, error: str|None, result: dict|None)."""
    if not items:
        return False, "Savat bo'sh.", None
    if payment_type not in ("naqd", "nasiya"):
        return False, "To'lov turi noto'g'ri.", None

    conn = get_conn()
    cart = []
    reserved = {}
    try:
        for it in items:
            try:
                pid = int(it.get("id"))
                qty = float(it.get("qty"))
            except (TypeError, ValueError):
                conn.close()
                return False, "Noto'g'ri mahsulot ma'lumoti.", None
            if not math.isfinite(qty) or qty <= 0:
                return False, "Miqdor noto'g'ri.", None
            row = conn.execute(
                "SELECT id, name, cost_price, price, qty, unit FROM products WHERE id=?",
                (pid,)).fetchone()
            if not row:
                return False, "Mahsulot topilmadi.", None
            _id, name, cost_price, list_price, avail_qty, unit = row
            # Savatda bir xil mahsulot bir necha qatorda bo'lsa, ularning
            # JAMI miqdori ombordagidan oshmasligi kerak (aks holda ombor
            # minusga tushib ketardi).
            reserved[_id] = reserved.get(_id, 0.0) + qty
            if avail_qty < reserved[_id]:
                return False, f"\"{name}\" mahsulotidan omborda yetarli miqdor yo'q.", None
            # MUHIM (foydalanuvchi so'rovi bilan -- Mini App savatiga
            # chegirma): agar frontend'dan "price" (kelishilgan narx)
            # kelgan bo'lsa va u musbat bo'lsa, o'shani ishlatamiz;
            # bo'lmasa (yoki noto'g'ri bo'lsa) mahsulotning ombordagi
            # ASL narxiga tushamiz.
            price = list_price
            raw_price = it.get("price")
            if raw_price is not None:
                try:
                    candidate = float(raw_price)
                    if math.isfinite(candidate) and candidate > 0:
                        price = candidate
                except (TypeError, ValueError):
                    pass
            cart.append({
                "product_id": _id, "name": name, "cost_price": cost_price,
                "price": price, "list_price": list_price, "qty": qty, "unit": unit,
                "total": price * qty,
            })
    finally:
        conn.close()

    ok, err, info = commit_sale_transaction(
        cart, payment_type, method_label=method_label, customer_name=customer_name,
        phone=phone, paid_now=paid_now)
    if not ok:
        return False, err, None
    sale_batch = info["sale_batch"]
    total = info["total"]
    total_profit = info["total_profit"]
    paid_now = info["paid_now"]

    receipt_text = build_receipt_text(cart, total, payment_type, customer_name=customer_name,
                                       phone=phone, method_label=method_label, paid_now=paid_now)
    receipt_path = None
    try:
        receipt_path = save_receipt_file(receipt_text)
    except Exception:
        pass

    print_ok = None
    print_error = None
    if print_receipt and receipt_path:
        # MUHIM: bu -- ADMIN telefondan sotuv qilganda TANLOVLI ravishda
        # so'raydigan chop etish -- agar chek printeri ulanmagan yoki
        # xato bo'lsa ham, sotuvning o'zi ALLAQACHON bazaga yozilgan
        # bo'ladi (yuqorida) -- shuning uchun bu yerdagi xato sotuvni
        # BEKOR qilmaydi, faqat natijada xabar sifatida qaytariladi.
        try:
            with _telegram_lock():
                settings = load_settings()
                pname = printer_name or settings.get("receipt_printer")
                # MUHIM (foydalanuvchi so'rovi bilan): endi tanlangan printer
                # ESLAB QOLINADI -- keyingi safar chek chop etilganda (yoki
                # qayta chop etilganda) shu printer avtomatik standart
                # sifatida tanlangan holda ko'rinadi. BUG TUZATISH: bu
                # o'qish+yozish endi umumiy qulf ostida -- shunda Telegram
                # fon oqimi bilan bir vaqtga to'g'ri kelib, printer
                # sozlamasi "yutib yuborilib" yo'qolib qolmaydi.
                if printer_name and printer_name != settings.get("receipt_printer"):
                    settings["receipt_printer"] = printer_name
                    save_settings(settings)
            n_copies = max(1, int(copies or 1))
            print_ok, print_error = True, None
            for _ in range(n_copies):
                print_ok, print_error = print_receipt_file(receipt_path, pname)
                if not print_ok:
                    break
        except Exception as e:
            print_ok, print_error = False, str(e)

    try:
        send_sale_notifications(cart, total, total_profit, payment_type,
                                 method_label=method_label, customer_name=customer_name,
                                 sale_batch=sale_batch)
    except Exception:
        pass

    return True, None, {"total": total, "receipt_text": receipt_text, "sale_batch": sale_batch,
                         "print_ok": print_ok, "print_error": print_error}


def get_webapp_barcode_settings():
    """Mini App'ning 'Mahsulot qo'shish' sahifasi ochilganda, OXIRGI
    ishlatilgan yorliq o'lchamlarini (nomi/narx shrifti, shtrix kod
    o'lchami) va oxirgi dollar kursini qaytaradi -- kompyuterdagi
    BarcodeLabelDialog bilan BIR XIL sozlama kalitlaridan ("barcode_label_
    name_size" va h.k.) foydalanadi, shu bilan ikkalasi bir-biridan
    mustaqil ishlatilsa ham, ESLAB QOLINGAN o'lcham BIR XIL bo'lib qoladi."""
    s = load_settings()
    return {
        "name_font_size": s.get("barcode_label_name_size", 23),
        "price_font_size": s.get("barcode_label_price_size", 25),
        "barcode_scale": s.get("barcode_label_scale", 100),
        "last_usd_rate": s.get("last_usd_rate"),
    }


def _save_webapp_barcode_sizes(name_font_size=None, price_font_size=None, barcode_scale=None):
    """Mini App'dan shtrix kod yaratilgan/qayta chizilgan/chop etilgan HAR
    SAFAR, ishlatilgan o'lchamlarni sozlamalarga yozib qo'yadi -- shu
    orqali keyingi safar Mini App ochilganda ham o'sha o'lcham
    ko'rsatiladi (kompyuterdagi BarcodeLabelDialog'ning "eslab qolish"
    xatti-harakati bilan bir xil)."""
    try:
        with _telegram_lock():
            s = load_settings()
            if name_font_size is not None:
                s["barcode_label_name_size"] = int(name_font_size)
            if price_font_size is not None:
                s["barcode_label_price_size"] = int(price_font_size)
            if barcode_scale is not None:
                s["barcode_label_scale"] = int(barcode_scale)
            save_settings(s)
    except Exception:
        pass


def save_webapp_usd_rate(rate):
    """Mini App'dan dollar/so'm kursi ishlatilganda, uni sozlamalarga
    yozadi -- desktop bilan bir xil "last_usd_rate" kaliti orqali."""
    try:
        with _telegram_lock():
            s = load_settings()
            s["last_usd_rate"] = float(rate)
            save_settings(s)
    except Exception:
        pass


def record_webapp_add_product(name, cost_price, price, qty, unit, barcode=None,
                               name_font_size=None, price_font_size=None, barcode_scale=None,
                               image_base64=None, ai_remove_bg=False):
    """Mini App'dan (telefondan) yangi mahsulot qo'shadi -- kompyuterdagi
    "Mahsulot qo'shish" oynasining soddalashtirilgan varianti: shtrix kod
    berilmasa, avtomatik (tasodifiy, EAN-13) kod yaratiladi va uning
    rasmi (label) tayyorlanadi.

    MUHIM CHEKLOV: kompyuterdagi oyna xuddi shu nomli mahsulot topilsa,
    foydalanuvchidan "qo'shiladimi yoki mavjudiga qo'shiladimi" deb
    so'raydi (interaktiv dialog) -- Mini App'da bunday interaktiv
    so'rov imkoni yo'q, shuning uchun bu yerda oddiy nomdosh mahsulot
    bo'lsa ham baribir ALOHIDA yangi qator sifatida qo'shiladi. Agar
    xato bilan takror kiritilgan bo'lsa, buni kompyuterdagi Mahsulotlar
    bo'limida qo'lda tuzatish/o'chirish mumkin.

    Qaytaradi: (ok: bool, error: str|None, result: dict|None) -- result
    ichida {"id", "barcode", "barcode_image_base64"}."""
    name = (name or "").strip()
    if not name:
        return False, "Mahsulot nomini kiriting.", None
    try:
        cost_price = float(cost_price)
        price = float(price)
        qty = float(qty)
    except (TypeError, ValueError):
        return False, "Narx yoki miqdor noto'g'ri.", None
    if price <= 0:
        return False, "Narx noto'g'ri.", None
    unit = (unit or "dona").strip() or "dona"
    barcode = (barcode or "").strip()

    conn = get_conn()
    try:
        if not barcode:
            existing = [r[0] for r in conn.execute(
                "SELECT barcode FROM products WHERE barcode IS NOT NULL AND barcode != ''").fetchall()]
            barcode = generate_random_barcode(existing)
        conn.execute(
            "INSERT INTO products (name, cost_price, price, qty, unit, barcode) VALUES (?,?,?,?,?,?)",
            (name, cost_price, price, qty, unit, barcode))
        conn.commit()
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()

    # MUHIM (foydalanuvchi so'rovi bilan): agar Mini App'dan (kamera/
    # galereya orqali) mahsulot rasmi yuborilgan bo'lsa, uni saqlaymiz.
    # Xato bo'lsa ham (masalan noto'g'ri format), mahsulotning o'zi
    # ALLAQACHON qo'shilgan bo'lgani uchun butun amalni bekor qilmaymiz.
    if image_base64:
        try:
            save_product_image_from_base64(pid, image_base64, ai_remove_bg=ai_remove_bg)
        except Exception:
            pass

    image_b64 = None
    try:
        import base64
        import io
        image = build_barcode_label_image(
            barcode, name, price,
            name_font_size=name_font_size,
            price_font_size=price_font_size if price_font_size else 25,
            barcode_scale=(barcode_scale / 100.0) if barcode_scale else 1.0)
        save_barcode_label(image, barcode)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        pass

    return True, None, {"id": pid, "barcode": barcode, "barcode_image_base64": image_b64}


def get_webapp_product(pid):
    """Mini App'da mahsulotni tahrirlash oynasini oldindan to'ldirish uchun,
    bitta mahsulotning to'liq ma'lumotini qaytaradi (yoki topilmasa None)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT id, name, cost_price, price, qty, unit, barcode, image_path FROM products WHERE id=?",
        (pid,)).fetchone()
    conn.close()
    if not row:
        return None
    _id, name, cost_price, price, qty, unit, barcode, image_path = row
    return {"id": _id, "name": name, "cost_price": cost_price, "price": price,
            "qty": qty, "unit": unit, "barcode": barcode,
            "image_url": _product_image_url(image_path)}


def update_webapp_product(pid, name, cost_price, price, qty, unit, barcode=None,
                           image_base64=None, remove_image=False, ai_remove_bg=False):
    """Mini App'dan mahsulotni tahrirlaydi -- kompyuterdagi Mahsulotlar
    sahifasining "Tahrirlash" tugmasi bilan bir xil: nomi, tan narxi, sotish
    narxi, miqdori, o'lchov birligi va shtrix kodni yangilaydi. MUHIM: bir
    xil nomli BOSHQA mahsulot bo'lsa (kompyuterdagi bilan bir xil tekshiruv),
    xato qaytaradi.

    Qaytaradi: (ok: bool, error: str|None)."""
    try:
        pid = int(pid)
        cost_price = float(cost_price)
        price = float(price)
        qty = float(qty)
    except (TypeError, ValueError):
        return False, "Narx yoki miqdor noto'g'ri."
    name = (name or "").strip()
    if not name:
        return False, "Mahsulot nomini kiriting."
    if price <= 0:
        return False, "Narx noto'g'ri."
    unit = (unit or "dona").strip() or "dona"
    barcode = (barcode or "").strip() or None

    dup = find_product_by_name(name, exclude_id=pid)
    if dup:
        return False, f"\"{dup[1]}\" nomli boshqa mahsulot allaqachon mavjud. Boshqa nom tanlang."

    conn = get_conn()
    row = conn.execute("SELECT id FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        conn.close()
        return False, "Mahsulot topilmadi."
    conn.execute(
        "UPDATE products SET name=?, cost_price=?, price=?, qty=?, unit=?, barcode=? WHERE id=?",
        (name, cost_price, price, qty, unit, barcode, pid))
    conn.commit()
    conn.close()

    # MUHIM (foydalanuvchi so'rovi bilan): mahsulot rasmini Mini App
    # orqali ham yangilash/o'chirish mumkin.
    if remove_image:
        try:
            delete_product_image(pid)
        except Exception:
            pass
    elif image_base64:
        try:
            save_product_image_from_base64(pid, image_base64, ai_remove_bg=ai_remove_bg)
        except Exception:
            pass

    return True, None


def delete_webapp_product(pid):
    """Mini App'dan mahsulotni butunlay o'chiradi -- kompyuterdagi
    Mahsulotlar sahifasining "O'chirish" tugmasi bilan bir xil. MUHIM:
    o'tgan sotuvlar (sales) ta'sirlanmaydi, chunki ular mahsulot nomi/
    narxini o'z ichiga OLADI (product_id ga bog'liq emas, faqat izoh
    sifatida saqlanadi).

    Qaytaradi: (ok: bool, error: str|None)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False, "Noto'g'ri mahsulot."
    conn = get_conn()
    row = conn.execute("SELECT id FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        conn.close()
        return False, "Mahsulot topilmadi."
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    # MUHIM: mahsulot o'chirilganda, uning rasm fayli ham diskda
    # "yetim" bo'lib qolmasligi uchun o'chiriladi.
    try:
        delete_product_image(pid)
    except Exception:
        pass
    return True, None


def render_webapp_barcode_preview(barcode, name, price, name_font_size=None,
                                   price_font_size=None, barcode_scale=None):
    """Mini App'da shtrix kod ALLAQACHON yaratilgandan SO'NG ham, tanlangan
    o'lchamlar (nomi/narx shrifti, shtrix kod o'lchami) bilan yorliqni
    QAYTA chizadi -- mahsulotni qayta qo'shmasdan, faqat KO'RINISHNI
    yangilash uchun (foydalanuvchi avval yaratib, keyin ham resize
    qila olishi kerak degan aniq talabga javoban).

    Qaytaradi: (ok: bool, error: str|None, image_base64: str|None)."""
    try:
        import base64
        import io
        price = float(price or 0)
        image = build_barcode_label_image(
            barcode, name, price,
            name_font_size=name_font_size,
            price_font_size=price_font_size if price_font_size else 25,
            barcode_scale=(barcode_scale / 100.0) if barcode_scale else 1.0)
        save_barcode_label(image, barcode)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return True, None, base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        return False, str(e), None


def _webapp_period_where(period):
    """Mini App hisobotlari uchun davr bo'yicha SQL WHERE qismini quradi.
    Qo'llab-quvvatlanadigan qiymatlar:
      "today"      -- faqat bugun
      "last30"     -- so'nggi 30 kun (bugun bilan birga)
      "YYYY-MM"    -- aniq bir oy (masalan "2026-06" -- iyun)
    Noma'lum/bo'sh qiymat bo'lsa, "today"ga tushadi."""
    import re as _re
    if period == "last30":
        start = (datetime.date.today() - datetime.timedelta(days=29)).isoformat()
        return "WHERE date >= ?", (start,)
    if period and _re.match(r"^\d{4}-\d{2}$", period):
        return "WHERE substr(date, 1, 7) = ?", (period,)
    # "today" yoki eski "month" qiymati (orqaga moslik uchun joriy oyga tushadi)
    if period == "month":
        return "WHERE substr(date, 1, 7) = ?", (today_str()[:7],)
    return "WHERE date = ?", (today_str(),)


def get_webapp_reports(period="today"):
    """Mini App uchun soddalashtirilgan hisobot -- tanlangan davr bo'yicha
    jami savdo, foyda va to'lanmagan nasiya (qarz) summasini qaytaradi.
    Shu bilan birga, eng ko'p sotilgan 5 ta mahsulotni ham (miqdoriga
    qarab) qo'shadi.

    MUHIM O'ZGARISH (foydalanuvchi so'rovi bilan): "Foyda" endi FAQAT
    HAQIQIY (realizatsiya qilingan) foydani ko'rsatadi -- ya'ni naqd
    sotuvlar foydasi + BUGUNGACHA TO'LANGAN nasiya qarzlarning foydasi
    (debts.paid=1, sale_batch orqali bog'langan). "Nasiya foydasi" esa endi
    HALI TO'LANMAGAN (kutilayotgan) nasiya sotuvlar foydasini ko'rsatadi --
    qarz to'langanda, bu summa "Nasiya foydasi"dan chiqib, "Foyda"ga
    qo'shiladi (ikki marta hisoblanmasligi uchun). Qarzning o'zi (summasi)
    esa to'lanmaguncha "Jami to'lanmagan qarz"da ko'rsatilaverdi -- bu
    o'zgarmadi.

    MUHIM: "sale_count" -- SOTILGAN QATORLAR SONI (har bir savatdagi
    mahsulot алohida qator), sotuv "cheklari" (sale_batch) soni EMAS --
    chunki bitta chekda bir nechta mahsulot bo'lishi mumkin, va
    foydalanuvchi bu sonni kompyuterdagi Savdo tarixi jadvalidagi qatorlar
    soniga solishtirmoqchi bo'lgani uchun, ikkalasi bir xil ma'noda
    hisoblanishi kerak."""
    where, params = _webapp_period_where(period)
    conn = get_conn()

    # MUHIM TUZATISH (foydalanuvchi so'rovi bilan): "Jami savdo" endi
    # FAQAT naqd sotuvlar summasini ko'rsatadi -- ilgari bu yerda naqd VA
    # nasiya sotuvlar QO'SHIB hisoblanardi, bu esa noto'g'ri edi. Foyda
    # bo'yicha qilingan "to'langanda birlashtirish" mantig'i FAQAT foyda
    # ko'rsatkichiga tegishli -- "Jami savdo" bunga aloqasi yo'q, hamon
    # sof naqd summa bo'lib qolishi kerak (nasiya summasi alohida "Nasiya
    # (shu davr)" kartochkasida ko'rsatiladi).
    # "sale_count"/"batch_count" hamon BARCHA (naqd+nasiya) sotuvlar
    # bo'yicha hisoblanadi -- bu "Jami savdo" (faqat naqd) dan MUSTAQIL,
    # chunki u kompyuterdagi Savdo tarixi bilan solishtirish uchun ishlatiladi.
    count_row = conn.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT sale_batch) FROM sales {where}", params).fetchone()
    sale_count, batch_count = count_row

    # MUHIM (foydalanuvchi so'rovi bilan -- "to'langani naqdga
    # qo'shilsinmi?"): nasiyaga savdo qilinganda xaridor hozir bir
    # qismini (paid_now) darhol to'lagan bo'lsa, o'sha qism endi
    # "Jami savdo" (naqd)ga, qolgani "Nasiya (shu davr)"ga hisoblanadi.
    total_sum, naqd_profit, nasiya_sum, nasiya_total_profit = get_naqd_nasiya_totals_where(where, params)

    # MUHIM: quyidagi so'rovda "sales" jadvali "s" bilan, "debts" esa "d"
    # bilan belgilanadi -- ikkalasida ham "date" ustuni bo'lgani uchun,
    # "_webapp_period_where()"dan kelgan WHERE qismidagi "date" so'ziga
    # ANIQ "s." prefiksi qo'shiladi (re.sub bilan, so'z chegarasi bo'yicha),
    # aks holda SQLite "ambiguous column name" xatosini berardi.
    import re as _re2
    qualified_where = _re2.sub(r"\bdate\b", "s.date", where)
    paid_nasiya_profit_row = conn.execute(
        f"SELECT COALESCE(SUM(s.profit),0) FROM sales s "
        f"JOIN debts d ON d.sale_batch = s.sale_batch "
        f"{qualified_where} AND s.payment_type='nasiya' AND d.paid=1",
        params).fetchone()
    paid_nasiya_profit = paid_nasiya_profit_row[0]
    pending_nasiya_profit = nasiya_total_profit - paid_nasiya_profit

    total_profit = naqd_profit + paid_nasiya_profit

    top_rows = conn.execute(
        f"SELECT product_name, unit, SUM(qty) as q, SUM(total) as t FROM sales {where} "
        "GROUP BY product_name ORDER BY q DESC LIMIT 5", params).fetchall()

    unpaid_debt_row = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM debts WHERE paid=0").fetchone()
    unpaid_debt_total = unpaid_debt_row[0]

    # Ombor qiymati -- omborda hozir turgan barcha mahsulotlarning sotish
    # narxi bo'yicha umumiy qiymati (desktopdagi bilan bir xil convention).
    warehouse_row = conn.execute(
        "SELECT COALESCE(SUM(price*qty),0) FROM products").fetchone()
    warehouse_value = warehouse_row[0]

    conn.close()

    return {
        "period": period,
        "total_sum": total_sum,
        "total_profit": total_profit,
        "sale_count": sale_count,
        "batch_count": batch_count,
        "nasiya_sum": nasiya_sum,
        "nasiya_profit": pending_nasiya_profit,
        "unpaid_debt_total": unpaid_debt_total,
        "warehouse_value": warehouse_value,
        "top_products": [{"name": n, "unit": u, "qty": q, "total": t} for n, u, q, t in top_rows],
    }


def get_webapp_recent_sales(period="today", limit=50):
    """Mini App uchun tanlangan davrdagi sotuvlar ro'yxati (eng yangisi
    birinchi). MUHIM: endi "id" ham qaytariladi -- shu orqali Mini App'dan
    sotuvni bekor qilish (delete_webapp_sale) mumkin bo'lishi uchun.
    MUHIM (2): endi "sale_batch" ham qaytariladi -- shu orqali bitta
    "chek"ga tegishli barcha qatorlarni birlashtirib, chekni QAYTA CHOP
    ETISH (reprint_webapp_receipt) mumkin bo'ladi."""
    where, params = _webapp_period_where(period)
    conn = get_conn()
    rows = conn.execute(
        f"SELECT id, product_name, qty, unit, total, payment_type, payment_method, created_at, sale_batch, price "
        f"FROM sales {where} ORDER BY id DESC LIMIT ?",
        params + (limit,)).fetchall()
    conn.close()
    result = []
    for sid, name, qty, unit, total, ptype, pmethod, created_at, sale_batch, price in rows:
        result.append({
            "id": sid, "name": name, "qty": qty, "unit": unit, "total": total, "price": price,
            "sale_batch": sale_batch,
            "payment_type": ptype, "payment_method": pmethod, "created_at": created_at,
        })
    return result


def reprint_webapp_receipt(sale_batch, printer_name=None, copies=1):
    """Mini App'dagi 'So'nggi sotuvlar' ro'yxatidan tanlangan sotuv uchun
    chekni QAYTA TIKLAB, kompyuterga ulangan chek printeriga chop etadi --
    foydalanuvchi mijozga chek qayta bermoqchi bo'lganda (masalan birinchi
    chop etish muvaffaqiyatsiz bo'lgan yoki chek yo'qolgan bo'lsa) ishlatiladi.

    'sale_batch' -- bitta "chek"ka tegishli BARCHA sotuv qatorlarini
    (bir nechta mahsulot bo'lishi mumkin) bog'lovchi umumiy identifikator.

    Qaytaradi: (ok: bool, error: str|None)."""
    if not sale_batch:
        return False, "Sotuv topilmadi."
    conn = get_conn()
    rows = conn.execute(
        "SELECT product_name, qty, unit, price, total, payment_type, payment_method "
        "FROM sales WHERE sale_batch=?", (sale_batch,)).fetchall()
    if not rows:
        conn.close()
        return False, "Sotuv topilmadi."
    customer_name = phone = None
    payment_type = rows[0][5]
    method_label = rows[0][6]
    if payment_type == "nasiya":
        debt_row = conn.execute(
            "SELECT customer_name, phone FROM debts WHERE sale_batch=?", (sale_batch,)).fetchone()
        if debt_row:
            customer_name, phone = debt_row
    conn.close()

    items = [{"name": n, "qty": q, "unit": u, "price": p, "total": t} for n, q, u, p, t, _, _ in rows]
    total = sum(i["total"] for i in items)
    receipt_text = build_receipt_text(items, total, payment_type, customer_name=customer_name,
                                       phone=phone, method_label=method_label)
    try:
        receipt_path = save_receipt_file(receipt_text)
    except Exception as e:
        return False, str(e)

    with _telegram_lock():
        settings = load_settings()
        pname = printer_name or settings.get("receipt_printer")
        if printer_name and printer_name != settings.get("receipt_printer"):
            settings["receipt_printer"] = printer_name
            save_settings(settings)
    n_copies = max(1, int(copies or 1))
    ok, err = True, None
    for _ in range(n_copies):
        ok, err = print_receipt_file(receipt_path, pname)
        if not ok:
            break
    return ok, err


def print_custom_webapp_receipt(items, printer_name=None, copies=1):
    """Mini App'dagi 'So'nggi sotuvlar' ro'yxatidan foydalanuvchi BIR
    NECHTA turli mahsulotni (hattoki turli sotuvlardan/vaqtlardan bo'lsa
    ham) o'zi tanlab, ularning barchasini BITTA yangi (moslashtirilgan)
    chekka birlashtirib chop etishi uchun. 'items' -- har biri
    {"name","qty","unit","price","total"} kalitlariga ega lug'atlar
    ro'yxati (Mini App frontendidan keladi).

    Qaytaradi: (ok: bool, error: str|None)."""
    if not items:
        return False, "Mahsulot tanlanmagan."
    clean_items = []
    for it in items:
        try:
            clean_items.append({
                "name": str(it.get("name", "")),
                "qty": float(it.get("qty", 0) or 0),
                "unit": it.get("unit", ""),
                "price": float(it.get("price", 0) or 0),
                "total": float(it.get("total", 0) or 0),
            })
        except (TypeError, ValueError):
            continue
    if not clean_items:
        return False, "Mahsulot tanlanmagan."
    total = sum(i["total"] for i in clean_items)
    receipt_text = build_receipt_text(clean_items, total, "naqd")
    try:
        receipt_path = save_receipt_file(receipt_text)
    except Exception as e:
        return False, str(e)

    with _telegram_lock():
        settings = load_settings()
        pname = printer_name or settings.get("receipt_printer")
        if printer_name and printer_name != settings.get("receipt_printer"):
            settings["receipt_printer"] = printer_name
            save_settings(settings)
    n_copies = max(1, int(copies or 1))
    ok, err = True, None
    for _ in range(n_copies):
        ok, err = print_receipt_file(receipt_path, pname)
        if not ok:
            break
    return ok, err


def delete_webapp_sale(sale_id):
    """Mini App'dan sotuvni bekor qiladi (o'chiradi) -- xuddi kompyuterdagi
    Savdo tarixi sahifasidagi 'O'chirish (omborga qaytarish)' tugmasi kabi:
    mahsulot miqdorini omborga qaytaradi, sotuv qatorini o'chiradi va agar
    shu sotuv "partiyasi" (sale_batch) da boshqa qator qolmagan bo'lsa,
    Telegram xabarnomasini ham o'chiradi.

    Qaytaradi: (ok: bool, error: str|None)."""
    try:
        sale_id = int(sale_id)
    except (TypeError, ValueError):
        return False, "Noto'g'ri sotuv."

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT product_id, qty, sale_batch, payment_type, total, product_name FROM sales WHERE id=?",
            (sale_id,)).fetchone()
        if not row:
            return False, "Sotuv topilmadi."
        pid, qty, sale_batch, ptype, row_total, pname = row
        if pid is not None:
            conn.execute("UPDATE products SET qty = qty + ? WHERE id=?", (qty, pid))
        conn.execute("DELETE FROM sales WHERE id=?", (sale_id,))
        remaining = 0
        if sale_batch:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM sales WHERE sale_batch=?", (sale_batch,)).fetchone()[0]
        # Nasiya sotuv o'chirilsa, unga bog'liq (hali to'lanmagan) qarz ham
        # to'g'rilanadi -- aks holda xaridor bekor qilingan sotuv uchun
        # qarzdor bo'lib qolardi.
        if ptype == "nasiya" and sale_batch:
            if remaining == 0:
                conn.execute("DELETE FROM debts WHERE sale_batch=? AND paid=0", (sale_batch,))
                conn.execute("DELETE FROM sale_batch_meta WHERE sale_batch=?", (sale_batch,))
            else:
                debt = conn.execute(
                    "SELECT id, amount, note FROM debts WHERE sale_batch=? AND paid=0", (sale_batch,)).fetchone()
                if debt:
                    did, damount, dnote = debt
                    new_amount = damount - (row_total or 0)
                    if new_amount <= 1e-9:
                        conn.execute("DELETE FROM debts WHERE id=?", (did,))
                    else:
                        new_note = dnote
                        m = _DEBT_NOTE_PAT.match(dnote or "")
                        if m:
                            new_note = f"{m.group(1).strip()} to'landi, {fmt_money(new_amount)} qoldi"
                        conn.execute("UPDATE debts SET amount=?, note=? WHERE id=?",
                                     (new_amount, new_note, did))
                        conn.execute(
                            "DELETE FROM debt_items WHERE id=(SELECT id FROM debt_items "
                            "WHERE debt_id=? AND product_name=? AND qty=? LIMIT 1)",
                            (did, pname, qty))
        conn.commit()
    finally:
        conn.close()

    if sale_batch and remaining == 0:
        try:
            delete_telegram_messages_for_sale_batch(sale_batch)
        except Exception:
            pass
    return True, None


def get_webapp_debtors(limit=100):
    """Mini App uchun QARZDORLAR (to'lanmagan nasiya) ro'yxati -- eng
    yangi qarz birinchi. Kompyuterdagi 'Qarzdorlar daftari' bilan bir xil
    mantiq: faqat paid=0 (hali to'lanmagan) qarzlar ko'rsatiladi. Har bir
    qarzdor uchun, u NIMA OLGANI (debt_items) ham qo'shiladi -- shu orqali
    Mini App'da qarzdorga bosilganda, sotib olgan mahsulotlari ko'rinadi."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, customer_name, phone, amount, note, date FROM debts "
        "WHERE paid=0 ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    result = []
    for did, name, phone, amount, note, date in rows:
        items = conn.execute(
            "SELECT product_name, qty, unit FROM debt_items WHERE debt_id=?", (did,)).fetchall()
        result.append({
            "id": did, "customer_name": name, "phone": phone,
            "amount": amount, "note": note, "date": date,
            "items": [{"name": n, "qty": q, "unit": u} for n, q, u in items],
        })
    conn.close()
    return result


def get_known_customers(limit=300):
    """Mini App'da NASIYAGA sotish paytida, xaridor ismini kiritishda
    OLDIN qarz daftariga yozilgan (to'langan yoki hali to'lanmagan --
    farqi yo'q, chunki bir mijoz oldingi qarzini to'lab bo'lib, keyin
    yana nasiyaga olishi mumkin) barcha xaridorlarni taklif qilish
    (autocomplete) uchun. Har bir ism uchun ENG SO'NGGI telefon raqami
    saqlanadi (agar xaridor telefon raqamini keyinroq bergan/o'zgartirgan
    bo'lsa)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT customer_name, phone FROM debts WHERE customer_name IS NOT NULL AND customer_name != '' "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    seen = {}
    for name, phone in rows:
        key = name.strip().lower()
        if key and key not in seen:
            seen[key] = {"name": name.strip(), "phone": phone or ""}
    return list(seen.values())


def get_webapp_day_closures(limit=30):
    """Mini App uchun so'nggi yopilgan kunlar ro'yxati (day_closures
    jadvalidan, eng yangisi birinchi)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, closed_at, sales_naqd, profit_naqd, sales_nasiya, profit_nasiya "
        "FROM day_closures ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    result = []
    for date, closed_at, s_naqd, p_naqd, s_nasiya, p_nasiya in rows:
        result.append({
            "date": date, "closed_at": closed_at,
            "sales_naqd": s_naqd, "profit_naqd": p_naqd,
            "sales_nasiya": s_nasiya, "profit_nasiya": p_nasiya,
            "total_sales": s_naqd + s_nasiya, "total_profit": p_naqd + p_nasiya,
        })
    return result


def print_webapp_barcode(barcode, name, price, printer_name=None,
                          name_font_size=None, price_font_size=None, barcode_scale=None,
                          copies=1):
    """Mini App'dan (telefondan) YANGI YARATILGAN shtrix kod yorlig'ini,
    kompyuterga ulangan (yoki sozlamalarda eslab qolingan) shtrix kod
    printeriga chop etadi -- xuddi kompyuterdagi 'Shtrix kod' oynasidagi
    'Chop etish' tugmasi kabi. name_font_size/price_font_size/barcode_scale
    -- foydalanuvchi Mini App'da tanlagan (agar tanlagan bo'lsa) alohida
    o'lchamlar.

    Qaytaradi: (ok: bool, error: str|None)."""
    try:
        # MUHIM TUZATISH: Mini App'dan narx ba'zan matn (str) sifatida
        # kelishi mumkin (masalan JSON'da raqam o'rniga "9000" kabi) --
        # build_barcode_label_image esa narxni f"{price:,.0f}" kabi
        # RAQAM sifatida formatlaydi, shuning uchun bu yerda oldindan
        # float()ga aylantiramiz, aks holda "Unknown format code 'f' for
        # object of type 'str'" xatosi chiqadi.
        price = float(price or 0)
        image = build_barcode_label_image(
            barcode, name, price,
            name_font_size=name_font_size,
            price_font_size=price_font_size if price_font_size else 25,
            barcode_scale=(barcode_scale / 100.0) if barcode_scale else 1.0)
        path = save_barcode_label(image, barcode)
    except Exception as e:
        return False, str(e)
    with _telegram_lock():
        settings = load_settings()
        pname = printer_name or settings.get("barcode_printer")
        if printer_name and printer_name != settings.get("barcode_printer"):
            settings["barcode_printer"] = printer_name
            save_settings(settings)
        label_size = tuple(settings.get("barcode_label_size", [58, 38]))
    try:
        return print_barcode_label_file(path, pname, label_size, copies=copies)
    except Exception as e:
        return False, str(e)


_LAST_WEBAPP_AUTH_REASON = None


def _validate_webapp_init_data(token, init_data):
    """Telegram'ning rasmiy WebApp initData tekshiruv algoritmi (HMAC-SHA256).
    Rasmiy hujjat: https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
    To'g'ri bo'lsa, ichidagi "user" obyektini (dict) qaytaradi, aks holda None.

    MUHIM: xato bo'lsa, sababi _LAST_WEBAPP_AUTH_REASON'ga yoziladi -- bu
    "Ruxsatsiz so'rov" degan umumiy xabar ORTIDA aslida NIMA noto'g'ri
    ekanini (token yo'qmi, initData bo'shmi, hash mos kelmayaptimi)
    aniqlash uchun, diagnostika maqsadida ishlatiladi."""
    global _LAST_WEBAPP_AUTH_REASON
    import hmac
    import hashlib
    import time as _time
    import urllib.parse
    import json as _json
    if not token:
        _LAST_WEBAPP_AUTH_REASON = "Bot tokeni sozlamalarda kiritilmagan."
        return None
    if not init_data:
        _LAST_WEBAPP_AUTH_REASON = ("initData bo'sh keldi -- odatda ilova Telegram'dan "
                                     "TASHQARIDA (oddiy brauzerda) ochilganda yoki Telegram "
                                     "Desktop'ning ba'zi eski versiyalarida yuz beradi.")
        return None
    try:
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        recv_hash = data.pop("hash", None)
        if not recv_hash:
            _LAST_WEBAPP_AUTH_REASON = "initData ichida 'hash' maydoni yo'q."
            return None
        data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
        secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc_hash, recv_hash):
            _LAST_WEBAPP_AUTH_REASON = ("Hash mos kelmadi -- sozlamalardagi bot tokeni, Mini "
                                         "App'ni ochayotgan botning tokeni bilan bir xil emas.")
            return None
        user_json = data.get("user")
        if not user_json:
            _LAST_WEBAPP_AUTH_REASON = "initData ichida 'user' maydoni yo'q."
            return None
        # XAVFSIZLIK KUCHAYTIRISH: agar kimdir (masalan tarmoqni "tinglab")
        # haqiqiy foydalanuvchining initData'sini bir marta qo'lga kiritib
        # olsa, uni CHEKSIZ qayta-qayta ishlatib bo'lmasin -- Telegram har
        # bir initData'ga "auth_date" (yaratilgan vaqti, unix timestamp)
        # qo'shadi; agar bu 24 soatdan eski bo'lsa, endi ESKIRGAN deb rad
        # etiladi (Telegram'ning o'zi ham buni tavsiya qiladi). 24 soat --
        # do'kon xodimlari bir ish kuni davomida ilovani qayta ochmasdan
        # ishlata olishi uchun YETARLICHA UZOQ, lekin o'g'irlangan initData
        # CHEKSIZ qayta ishlatilishining oldini oladigan darajada QISQA
        # muddat sifatida tanlandi.
        MAX_INIT_DATA_AGE_SECONDS = 24 * 3600
        auth_date_raw = data.get("auth_date")
        try:
            auth_date = int(auth_date_raw)
        except (TypeError, ValueError):
            _LAST_WEBAPP_AUTH_REASON = "initData ichida 'auth_date' maydoni yo'q yoki noto'g'ri."
            return None
        age = _time.time() - auth_date
        if age > MAX_INIT_DATA_AGE_SECONDS:
            _LAST_WEBAPP_AUTH_REASON = (
                "initData eskirgan (mini app'ni Telegram botdan QAYTA oching) -- "
                "xavfsizlik uchun eski so'rovlar qayta ishlatilmaydi.")
            return None
        _LAST_WEBAPP_AUTH_REASON = None
        return _json.loads(user_json)
    except Exception as e:
        _LAST_WEBAPP_AUTH_REASON = f"Kutilmagan xato: {e}"
        return None


_MINIAPP_HTML = """<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Treydchi</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    background: var(--tg-theme-bg-color, #ffffff);
    color: var(--tg-theme-text-color, #111111);
  }
  .page { display: none; }
  .page.active { display: block; }

  #tabbar {
    position: sticky; top: 0; z-index: 15;
    display: flex;
    background: var(--tg-theme-secondary-bg-color, #f2f2f2);
    border-bottom: 1px solid rgba(128,128,128,0.25);
  }
  #tabbar button {
    flex: 1; padding: 12px 4px; border: none; background: none; color: inherit;
    font-size: 13px; opacity: 0.6;
  }
  #tabbar button.active { opacity: 1; font-weight: 700; color: var(--tg-theme-link-color, #3390ec); }

  #search-bar {
    position: sticky; top: 44px; z-index: 5;
    padding: 10px 12px;
    background: var(--tg-theme-secondary-bg-color, #f2f2f2);
    border-bottom: 1px solid rgba(128,128,128,0.25);
  }
  #search-input {
    width: 100%; padding: 10px 14px; font-size: 16px;
    border-radius: 10px; border: 1px solid rgba(128,128,128,0.35);
    background: var(--tg-theme-bg-color, #fff);
    color: var(--tg-theme-text-color, #111);
    outline: none;
  }
  #list { padding: 8px 12px 90px; }
  .item {
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 10px; margin-bottom: 8px; border-radius: 10px;
    background: var(--tg-theme-secondary-bg-color, #f7f7f7);
  }
  .item.sellable { cursor: pointer; }
  .item.sellable:active { opacity: 0.7; }
  .item .name { font-size: 15px; font-weight: 600; flex: 1; margin-right: 10px; }
  .item .meta { text-align: right; font-size: 13px; opacity: 0.85; white-space: nowrap; }
  .item .price { font-weight: 700; }
  /* MUHIM (foydalanuvchi so'rovi bilan): mahsulot ro'yxatida (savdo
     qilishda) har bir mahsulot yonida kichik rasm (thumbnail). */
  .item .thumb {
    width: 44px; height: 44px; border-radius: 8px; object-fit: cover;
    margin-right: 10px; flex-shrink: 0; background: rgba(128,128,128,0.15);
  }
  .edit-product-btn {
    flex: 0 0 auto; margin-left: 8px; border: none; background: none;
    font-size: 17px; padding: 4px 6px; opacity: 0.75;
  }
  #empty, #err { text-align: center; padding: 30px 10px; opacity: 0.6; font-size: 14px; }

  #cart-bar {
    /* MUHIM TUZATISH: foydalanuvchi so'ragani bo'yicha, savat paneli
       endi pastda EMAS -- qidiruv qatoridan darhol keyin, TEPADA,
       "yopishqoq" (sticky) holda turadi. "top" qiymati JS orqali
       (tabbar + qidiruv qatorining haqiqiy balandligiga qarab)
       dinamik hisoblanadi -- pastda ko'ring. */
    position: sticky; z-index: 6;
    display: none; align-items: center; justify-content: space-between;
    padding: 10px 16px;
    background: var(--tg-theme-button-color, #3390ec);
    color: var(--tg-theme-button-text-color, #fff);
    font-weight: 600; font-size: 15px;
  }
  #cart-bar span.total { font-weight: 800; }

  /* MUHIM (foydalanuvchi so'rovi bilan): "So'nggi sotuvlar" ro'yxatidan
     BIR NECHTA mahsulotni tanlab, ularni BITTA yangi chekka birlashtirib
     chop etish uchun paydo bo'ladigan panel (checkbox bilan tanlanganda
     ko'rinadi). */
  #receipt-select-bar {
    display: none; align-items: center; gap: 8px; flex-wrap: wrap;
    padding: 10px 12px; margin-bottom: 10px; border-radius: 10px;
    background: var(--tg-theme-button-color, #3390ec);
    color: var(--tg-theme-button-text-color, #fff);
    font-size: 13px; font-weight: 600;
  }
  #receipt-select-bar .rsel-count { flex: 1; }
  #receipt-select-bar button {
    border: none; border-radius: 8px; padding: 6px 10px; font-size: 13px;
    font-weight: 700; cursor: pointer;
  }
  #receipt-select-bar #receipt-select-print-btn {
    background: #fff; color: var(--tg-theme-button-color, #3390ec);
  }
  #receipt-select-bar #receipt-select-clear-btn {
    background: rgba(255,255,255,0.2); color: #fff;
  }
  .hist-row .hsel { margin-right: 10px; width: 19px; height: 19px; flex-shrink: 0; }

  /* MUHIM (foydalanuvchi so'rovi bilan): brauzerning standart <datalist>
     taklif satri (native klaviatura ustida) faqat 3 ta natijani ko'rsatib
     judayam cheklangan edi -- shuning uchun xaridor ismi uchun o'zimizning
     TO'LIQ nazorat qilinadigan ochiladigan ro'yxat (dropdown). */
  .suggest-dropdown {
    display: none; position: absolute; left: 0; right: 0; top: 100%;
    z-index: 15; max-height: 220px; overflow-y: auto; margin-top: 2px;
    border-radius: 8px; border: 1px solid rgba(128,128,128,0.35);
    background: var(--tg-theme-bg-color, #fff); box-shadow: 0 4px 14px rgba(0,0,0,0.18);
  }
  .suggest-dropdown .suggest-item {
    padding: 10px 12px; font-size: 14px; cursor: pointer;
    border-bottom: 1px solid rgba(128,128,128,0.15);
  }
  .suggest-dropdown .suggest-item:last-child { border-bottom: none; }
  .suggest-dropdown .suggest-item:active,
  .suggest-dropdown .suggest-item.active {
    background: var(--tg-theme-secondary-bg-color, rgba(51,144,236,0.12));
  }
  .suggest-dropdown .suggest-item .sname { font-weight: 600; }
  .suggest-dropdown .suggest-item .sphone { opacity: 0.65; font-size: 12px; margin-left: 6px; }

  .modal-overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.45); z-index: 20;
    display: none; align-items: flex-end; justify-content: center;
  }
  .modal-sheet {
    width: 100%; max-height: 86vh; overflow-y: auto;
    background: var(--tg-theme-bg-color, #fff);
    border-radius: 16px 16px 0 0; padding: 16px 16px calc(16px + env(safe-area-inset-bottom));
  }
  .modal-sheet h3 { margin: 0 0 12px; font-size: 17px; }
  /* MUHIM TUZATISH: dastlab "chegirma tahrirlash qatori" savat qatorining
     O'ZI (flex, bitta qatorga sig'diriladigan) ICHIGA joylashtirilgan
     edi -- shu sababli u boshqa tugmalar (miqdor +/-, o'chirish) bilan
     bitta tor qatorga siqilib qolib, katta narx (masalan 500000) yozilsa
     ham input maydoni juda tor bo'lib, matn ko'rinmay qolardi. Endi har
     bir savat elementi ".cart-entry" (oddiy, flex BO'LMAGAN) konteynerga
     o'raladi -- ICHIDA yuqorida savat qatori (nomi/narxi/tugmalar),
     PASTDA esa (agar ochilgan bo'lsa) chegirma tahrirlash qatori TO'LIQ
     KENGLIKDA, alohida qator sifatida chiqadi. */
  .cart-entry { padding: 8px 0; border-bottom: 1px solid rgba(128,128,128,0.2); }
  .cart-row {
    display: flex; align-items: center; gap: 8px;
  }
  .cart-row .cname { flex: 1; font-size: 14px; }
  .cart-row .cprice { font-size: 12px; opacity: 0.7; }
  .qty-btn {
    width: 28px; height: 28px; border-radius: 8px; border: none;
    background: var(--tg-theme-secondary-bg-color, #eee);
    color: var(--tg-theme-text-color, #111); font-size: 16px; font-weight: 700;
  }
  .qty-val { min-width: 44px; text-align: center; font-size: 14px; }
  .remove-btn { color: #d33; font-size: 12px; background: none; border: none; padding: 4px 6px; }
  /* MUHIM (foydalanuvchi so'rovi bilan): kompyuterdagi Savdo sahifasida
     bor "Narxni pasaytirish (chegirma)" imkoniyati Mini App savatida ham
     bo'lishi kerak -- shu tugma va uning ochiladigan narx tahrirlash
     qatori uchun. */
  .discount-btn {
    background: none; border: none; font-size: 15px; padding: 4px 6px;
    opacity: 0.8; flex-shrink: 0;
  }
  .cprice .old-price { text-decoration: line-through; opacity: 0.6; margin-right: 4px; }
  .cprice .new-price { color: #2ECC71; font-weight: 700; }
  .discount-edit-row {
    display: none; align-items: center; gap: 6px; margin-top: 8px;
    width: 100%; box-sizing: border-box;
    padding: 8px; border-radius: 8px;
    background: var(--tg-theme-secondary-bg-color, rgba(128,128,128,0.08));
  }
  .discount-edit-row input {
    flex: 1 1 auto; min-width: 0; width: 100%; padding: 9px 10px; border-radius: 6px;
    border: 1px solid rgba(128,128,128,0.35); background: var(--tg-theme-bg-color, #fff);
    color: inherit; font-size: 15px; box-sizing: border-box;
  }
  .discount-edit-row button {
    flex-shrink: 0;
    border: none; border-radius: 6px; padding: 9px 12px; font-size: 12px; font-weight: 700;
    white-space: nowrap;
  }
  .discount-edit-row .disc-apply { background: var(--tg-theme-button-color, #3390ec); color: #fff; }
  .discount-edit-row .disc-cancel { background: rgba(128,128,128,0.25); color: inherit; }
  .pay-choice { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
  .pay-choice button {
    flex: 1 1 calc(33% - 8px); min-width: 90px; padding: 10px; border-radius: 10px;
    border: 1px solid rgba(128,128,128,0.35);
    background: var(--tg-theme-secondary-bg-color, #f2f2f2); color: inherit; font-size: 13px; font-weight: 600;
  }
  .pay-choice button.active {
    background: var(--tg-theme-button-color, #3390ec); color: var(--tg-theme-button-text-color, #fff);
    border-color: transparent;
  }
  .field { margin-bottom: 10px; }
  .field label { display: block; font-size: 12px; opacity: 0.75; margin-bottom: 4px; }
  /* MUHIM: desktopdagi "dollardan avtomatik hisoblash" va "foyda foizi"
     yordamchilarining Mini App varianti. */
  .helper-card {
    background: var(--tg-theme-secondary-bg-color, #f2f2f2); border-radius: 10px;
    padding: 10px 12px; margin-bottom: 12px;
  }
  .helper-title { font-size: 12px; opacity: 0.75; margin-bottom: 6px; }
  .helper-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .helper-row input {
    flex: 1 1 80px; min-width: 70px; padding: 8px 10px; border-radius: 8px;
    border: 1px solid rgba(128,128,128,0.35); background: var(--tg-theme-bg-color, #fff);
    color: inherit; font-size: 13px;
  }
  .helper-row button {
    flex: 1 1 auto; padding: 8px 10px; border-radius: 8px; border: none;
    background: var(--tg-theme-button-color, #3390ec); color: var(--tg-theme-button-text-color, #fff);
    font-size: 12px; font-weight: 600; white-space: nowrap;
  }
  .field input, .field select {
    width: 100%; padding: 10px; border-radius: 8px; border: 1px solid rgba(128,128,128,0.35);
    background: var(--tg-theme-bg-color, #fff); color: inherit; font-size: 14px;
  }
  .check-row { display: flex; align-items: center; gap: 8px; margin: 10px 0; font-size: 13px; }
  .check-row input { width: 18px; height: 18px; }
  #cart-total-row { display: flex; justify-content: space-between; font-size: 16px; font-weight: 700; margin: 12px 0; }
  #checkout-btn, #close-cart-btn, .primary-btn, #ep-delete-btn, #ep-close-btn {
    width: 100%; padding: 13px; border-radius: 10px; border: none; font-size: 15px; font-weight: 700;
    margin-top: 6px;
  }
  #checkout-btn, .primary-btn { background: var(--tg-theme-button-color, #3390ec); color: var(--tg-theme-button-text-color, #fff); }
  #close-cart-btn { background: var(--tg-theme-secondary-bg-color, #eee); color: inherit; }
  #sale-msg, #add-product-msg { text-align: center; font-size: 13px; margin-top: 8px; min-height: 18px; }

  #add-product-page { padding: 16px 16px 90px; }
  #add-product-page h2 { font-size: 18px; margin: 4px 0 16px; }
  #barcode-result { text-align: center; margin-top: 14px; }
  #barcode-result img { max-width: 100%; border-radius: 8px; background: #fff; padding: 8px; }

  #reports-page { padding: 16px 16px 90px; }
  #reports-page h2 { font-size: 18px; margin: 4px 0 12px; }
  .report-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  .report-tabs button {
    flex: 1 1 calc(33% - 8px); min-width: 90px; padding: 12px 6px; border-radius: 10px;
    border: 1px solid rgba(128,128,128,0.35);
    background: var(--tg-theme-secondary-bg-color, #f2f2f2); color: inherit; font-size: 14px; font-weight: 700;
  }
  .report-tabs button.active {
    background: var(--tg-theme-button-color, #3390ec); color: var(--tg-theme-button-text-color, #fff);
    border-color: transparent;
  }
  .stat-card {
    background: var(--tg-theme-secondary-bg-color, #f7f7f7); border-radius: 10px;
    padding: 12px 14px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;
  }
  .stat-card .label { font-size: 13px; opacity: 0.75; }
  .stat-card .value { font-size: 16px; font-weight: 700; }
  /* MUHIM: foydalanuvchi so'ragani bo'yicha -- "Eng ko'p sotilganlar",
     "Yopilgan kunlar" va boshqa ro'yxatlardagi qatorlar bir-biriga
     qo'shilib ketmasligi uchun, har bir qator o'z FONI (bir qatorlan-bir
     qator, "zebra" chizig'i), chapdan rangli chiziq va yaxlitlangan
     burchaklar bilan ajratiladi -- shu bilan ko'z ilg'ashi osonlashadi. */
  .hist-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 12px; margin-bottom: 4px; font-size: 13px;
    border-radius: 8px; border-left: 3px solid transparent;
    background: var(--tg-theme-secondary-bg-color, rgba(128,128,128,0.06));
  }
  .hist-row:nth-child(even) {
    background: rgba(128,128,128,0.13);
  }
  /* MUHIM (foydalanuvchi so'rovi bilan): rang endi Telegram'ning ko'k
     rangi EMAS, balki kompyuterdagi dasturning o'zidagi "Treydchi"
     yozuvi rangi (ACCENT_COLOR = #F0641E, to'q sariq) bilan bir xil --
     qatorlar (hist-row) esa o'sha rangning QORAMTIR (to'qroq) shakli
     bilan ajratiladi. */
  .hist-row { border-left-color: #8c3a11; }
  .hist-row .hname { flex: 1; font-weight: 700; }
  .hist-row .hmeta { opacity: 0.75; margin-left: 8px; text-align: right; font-weight: 500; }
  /* MUHIM: foydalanuvchi so'ragani bo'yicha -- "So'nggi sotuvlar",
     "Qarzdorlar", "Yopilgan kunlar" kabi bo'lim sarlavhalari endi
     kattaroq, qalinroq va rangli chap chiziq bilan aniq ajralib turadi. */
  .section-title {
    font-size: 16px; font-weight: 800; margin: 20px 0 10px;
    padding-left: 10px; border-left: 4px solid #F0641E; color: #F0641E;
    letter-spacing: 0.2px;
  }
</style>
</head>
<body>

  <div id="tabbar">
    <button id="tab-shop" class="active">🛍️ <span data-i18n="tab_shop">Do'kon</span></button>
    <button id="tab-add-product" style="display:none;">➕ <span data-i18n="tab_add_product">Mahsulot</span></button>
    <button id="tab-reports" style="display:none;">📊 <span data-i18n="tab_reports">Hisobot</span></button>
  </div>

  <div id="page-shop" class="page active">
    <div id="search-bar">
      <input id="search-input" type="text" placeholder="Qidirish..." data-i18n-placeholder="search_placeholder" autocomplete="off">
    </div>
    <div id="cart-bar">
      <span id="cart-count">0</span>
      <span class="total" id="cart-total-mini">0 so'm</span>
    </div>
    <div id="list"></div>
    <div id="empty" style="display:none;" data-i18n="empty_products">Mahsulot topilmadi</div>
    <div id="err" style="display:none;"></div>
  </div>

  <div id="page-add-product" class="page">
    <div id="add-product-page">
      <h2 data-i18n="ap_title">Yangi mahsulot qo'shish</h2>
      <div class="field">
        <label data-i18n="ap_name">Nomi</label>
        <input id="ap-name" type="text" placeholder="Mahsulot nomi">
      </div>
      <div class="field">
        <label data-i18n="ap_cost">Tan narxi (so'm)</label>
        <input id="ap-cost" type="number" inputmode="decimal" placeholder="0">
      </div>
      <div class="helper-card">
        <div class="helper-title" data-i18n="ap_usd_helper_title">Yordamchi: dollardan so'mga avtomatik hisoblash</div>
        <div class="helper-row">
          <input id="ap-usd-cost" type="number" inputmode="decimal" placeholder="1.5" data-i18n-placeholder="ap_usd_amount_ph">
          <input id="ap-usd-rate" type="number" inputmode="decimal" placeholder="12000" data-i18n-placeholder="ap_usd_rate_ph">
          <button id="ap-usd-apply" data-i18n="ap_usd_calc_btn">Hisoblash</button>
        </div>
      </div>
      <div class="field">
        <label data-i18n="ap_price">Sotish narxi (so'm)</label>
        <input id="ap-price" type="number" inputmode="decimal" placeholder="0">
      </div>
      <div class="helper-card">
        <div class="helper-row">
          <label style="flex:0 0 auto; font-size:12px; opacity:0.75; margin:0;" data-i18n="ap_markup_label">Foyda foizi (%):</label>
          <input id="ap-markup" type="number" inputmode="decimal" placeholder="20" data-i18n-placeholder="ap_markup_ph">
          <button id="ap-markup-apply" data-i18n="ap_markup_calc_btn">Sotish narxini hisoblash</button>
        </div>
        <div id="ap-markup-msg" style="font-size:12px; opacity:0.8; margin-top:6px;"></div>
      </div>
      <div class="field">
        <label data-i18n="ap_qty">Miqdor</label>
        <input id="ap-qty" type="number" inputmode="decimal" placeholder="0">
      </div>
      <div class="field">
        <label data-i18n="ap_unit">O'lchov birligi</label>
        <select id="ap-unit">
          <option value="dona">dona</option>
          <option value="kg">kg</option>
          <option value="metr">metr</option>
          <option value="litr">litr</option>
        </select>
      </div>
      <div class="field">
        <label data-i18n="ap_barcode">Shtrix kod (bo'sh qoldirsangiz, o'zi yaratiladi)</label>
        <input id="ap-barcode" type="text" placeholder="Ixtiyoriy">
      </div>
      <!-- MUHIM (foydalanuvchi so'rovi bilan): har bir mahsulot uchun
           rasm qo'shish -- telefon kamerasi yoki galereyadan tanlash
           mumkin. capture="environment" telefonda to'g'ridan-to'g'ri
           kamerani ochishga undaydi (lekin galereyadan ham tanlash
           imkoniyati saqlanadi). -->
      <div class="field">
        <label data-i18n="product_image_label">Mahsulot rasmi (ixtiyoriy)</label>
        <input id="ap-image-input" type="file" accept="image/*" capture="environment">
        <img id="ap-image-preview" style="display:none; max-width:100%; max-height:180px; border-radius:8px; margin-top:8px;">
        <!-- MUHIM (foydalanuvchi so'rovi bilan): kompyuterdagi dasturdagi
             bilan bir xil "AI: fonni olib tashlash" belgisi -- yoqilsa,
             mahsulot rasmdan avtomatik ajratib olinib, oq fonga qo'yiladi. -->
        <label class="check-row" style="margin-top:8px;">
          <input type="checkbox" id="ap-ai-bg-check">
          <span data-i18n="product_ai_bg_label">AI: fonni olib tashlash</span>
        </label>
      </div>
      <div class="section-title" data-i18n="ap_label_size_title">Yorliqdagi yozuvlar o'lchami</div>
      <div class="field">
        <label><span data-i18n="ap_name_font">Nomi shrifti</span>: <span id="ap-name-size-val">23</span></label>
        <input id="ap-name-size" type="range" min="10" max="50" value="23">
      </div>
      <div class="field">
        <label><span data-i18n="ap_price_font">Narx shrifti</span>: <span id="ap-price-size-val">25</span></label>
        <input id="ap-price-size" type="range" min="10" max="50" value="25">
      </div>
      <div class="field">
        <label><span data-i18n="ap_barcode_scale">Shtrix kod o'lchami (%)</span>: <span id="ap-barcode-scale-val">100</span></label>
        <input id="ap-barcode-scale" type="range" min="50" max="200" value="100">
      </div>
      <button class="primary-btn" id="ap-submit" data-i18n="ap_submit">Qo'shish</button>
      <div id="add-product-msg"></div>
      <div id="barcode-result"></div>
    </div>
  </div>

  <div id="page-reports" class="page">
    <div id="reports-page">
      <h2 data-i18n="rep_title">Hisobotlar</h2>
      <div class="report-tabs">
        <button id="rep-today" class="active" data-period="today" data-i18n="rep_today">Bugun</button>
        <button id="rep-last30" data-period="last30" data-i18n="rep_last30">So'nggi 30 kun</button>
        <button id="rep-month-current" data-period="__current_month__">Shu oy</button>
      </div>
      <div class="field">
        <label data-i18n="rep_pick_month">Boshqa oy tanlash</label>
        <select id="rep-month-picker"></select>
      </div>
      <div id="reports-content"></div>
      <div class="section-title" data-i18n="rep_recent_sales">So'nggi sotuvlar</div>
      <div id="receipt-select-bar">
        <span class="rsel-count"></span>
        <span class="rsel-total"></span>
        <button id="receipt-select-print-btn" data-i18n="custom_receipt_btn">Chek chiqarish</button>
        <button id="receipt-select-clear-btn" data-i18n="custom_receipt_clear">Bekor qilish</button>
      </div>
      <div id="history-content"></div>
      <div class="section-title" data-i18n="rep_debtors">Qarzdorlar (to'lanmagan nasiya)</div>
      <div id="debtors-content"></div>
      <div class="section-title" data-i18n="rep_closures">Yopilgan kunlar</div>
      <div id="closures-content"></div>
      <div class="section-title" data-i18n="rep_top_products">Eng ko'p sotilganlar</div>
      <div id="top-products-content"></div>
    </div>
  </div>

  <div class="modal-overlay" id="detail-modal">
    <div class="modal-sheet">
      <h3 id="detail-title" data-i18n="detail_default_title">Tafsilot</h3>
      <div id="detail-content"></div>
      <button class="primary-btn" id="detail-close-btn" data-i18n="btn_close">Yopish</button>
    </div>
  </div>

  <div class="modal-overlay" id="edit-product-modal">
    <div class="modal-sheet">
      <h3 data-i18n="edit_product_title">Mahsulotni tahrirlash</h3>
      <div class="field">
        <label data-i18n="ap_name">Nomi</label>
        <input id="ep-name" type="text">
      </div>
      <div class="field">
        <label data-i18n="ap_cost">Tan narxi (so'm)</label>
        <input id="ep-cost" type="number" inputmode="decimal">
      </div>
      <div class="field">
        <label data-i18n="ap_price">Sotish narxi (so'm)</label>
        <input id="ep-price" type="number" inputmode="decimal">
      </div>
      <div class="field">
        <label data-i18n="ap_qty">Miqdor</label>
        <input id="ep-qty" type="number" inputmode="decimal">
      </div>
      <div class="field">
        <label data-i18n="ap_unit">O'lchov birligi</label>
        <select id="ep-unit">
          <option value="dona">dona</option>
          <option value="kg">kg</option>
          <option value="metr">metr</option>
          <option value="litr">litr</option>
        </select>
      </div>
      <div class="field">
        <label data-i18n="ap_barcode">Shtrix kod</label>
        <input id="ep-barcode" type="text">
      </div>
      <!-- MUHIM (foydalanuvchi so'rovi bilan): mavjud mahsulotga rasm
           qo'shish/almashtirish/o'chirish. -->
      <div class="field">
        <label data-i18n="product_image_label">Mahsulot rasmi (ixtiyoriy)</label>
        <img id="ep-image-preview" style="display:none; max-width:100%; max-height:180px; border-radius:8px; margin-bottom:8px;">
        <input id="ep-image-input" type="file" accept="image/*" capture="environment">
        <button id="ep-image-remove-btn" style="background:none;border:none;color:#d33;font-size:13px;padding:6px 0;display:none;" data-i18n="product_image_remove">🗑 Rasmni olib tashlash</button>
        <label class="check-row" style="margin-top:4px;">
          <input type="checkbox" id="ep-ai-bg-check">
          <span data-i18n="product_ai_bg_label">AI: fonni olib tashlash</span>
        </label>
      </div>
      <!-- MUHIM (foydalanuvchi so'rovi bilan): endi FAQAT yangi qo'shilgan
           mahsulot uchun emas, balki OMBORDA ALLAQACHON turgan (mavjud)
           mahsulotlar uchun ham shtrix kod chop etish mumkin -- to'g'ridan
           to'g'ri shu tahrirlash oynasidan. O'lcham (resize) slayderlari
           bu yerda ALOHIDA va KO'RINADIGAN qilib qo'shildi (avval "Mahsulot
           qo'shish" sahifasidagi yashirin slayderlar ishlatilar edi, lekin
           foydalanuvchi ularni bu oynada UMUMAN ko'rmas edi) -- ochilganda
           oxirgi eslab qolingan o'lchamlar bilan boshlanadi. -->
      <div class="section-title" data-i18n="ep_barcode_print_title">Shtrix kodni chop etish</div>
      <div class="field">
        <label><span data-i18n="ap_name_font">Nomi shrifti</span>: <span id="ep-bc-name-size-val">23</span></label>
        <input id="ep-bc-name-size" type="range" min="10" max="50" value="23">
      </div>
      <div class="field">
        <label><span data-i18n="ap_price_font">Narx shrifti</span>: <span id="ep-bc-price-size-val">25</span></label>
        <input id="ep-bc-price-size" type="range" min="10" max="50" value="25">
      </div>
      <div class="field">
        <label><span data-i18n="ap_barcode_scale">Shtrix kod o'lchami (%)</span>: <span id="ep-bc-scale-val">100</span></label>
        <input id="ep-bc-scale" type="range" min="50" max="200" value="100">
      </div>
      <div class="field">
        <label data-i18n="ap_printer_label">Shtrix kod printeri</label>
        <select id="ep-bc-printer"></select>
      </div>
      <div class="field">
        <label data-i18n="ap_copies_label">Nechta nusxa</label>
        <input id="ep-bc-copies" type="number" inputmode="numeric" min="1" max="50" value="1">
      </div>
      <button class="primary-btn" id="ep-bc-print-btn" data-i18n="ap_print_barcode">Shtrix kodni chop etish</button>
      <div id="ep-bc-msg" style="font-size:13px; text-align:center; margin-top:6px; min-height:16px;"></div>
      <div id="ep-msg" style="font-size:13px; text-align:center; margin-top:6px; min-height:16px;"></div>
      <button class="primary-btn" id="ep-save-btn" data-i18n="btn_save">Saqlash</button>
      <button id="ep-delete-btn" style="background:#d33; color:#fff; margin-top:8px;" data-i18n="btn_delete_product">🗑 Mahsulotni o'chirish</button>
      <button id="ep-close-btn" style="background:var(--tg-theme-secondary-bg-color,#eee); color:inherit; margin-top:8px;" data-i18n="btn_close">Yopish</button>
    </div>
  </div>

  <div class="modal-overlay" id="cart-modal">
    <div class="modal-sheet">
      <h3 data-i18n="cart_title">Savat</h3>
      <div id="cart-items"></div>
      <div id="cart-total-row"><span data-i18n="cart_total">Jami:</span><span id="cart-total-full">0 so'm</span></div>
      <button id="clear-cart-btn" style="background:none;border:none;color:#d33;font-size:13px;padding:6px 0;">🗑 <span data-i18n="cart_clear">Savatni tozalash</span></button>

      <div class="pay-choice">
        <button id="pay-naqd" class="active" data-label="Naqd" data-i18n="pay_naqd">Naqd</button>
        <button id="pay-karta" data-label="Plastik karta" data-i18n="pay_karta">Plastik karta</button>
        <button id="pay-nasiya" data-i18n="pay_nasiya">Nasiya</button>
      </div>

      <div id="nasiya-fields" style="display:none;">
        <div class="field" style="position:relative;">
          <label data-i18n="customer_name">Xaridor ismi</label>
          <!-- MUHIM (foydalanuvchi so'rovi bilan): oldin qarz daftariga
               yozilgan xaridorlar shu yerda taklif qilinadi. Avval
               brauzerning standart <datalist> (native klaviatura ustidagi
               taklif satri) ishlatilgan edi, lekin u faqat 3 tasini
               ko'rsatib, judayam cheklangan edi -- endi o'zimizning
               to'liq nazorat qilinadigan ochiladigan ro'yxat (dropdown)
               ishlatiladi. -->
          <input id="customer-name" type="text" placeholder="Ism familiya" autocomplete="off">
          <div id="customer-name-suggestions" class="suggest-dropdown"></div>
        </div>
        <div class="field">
          <label data-i18n="customer_phone">Telefon (ixtiyoriy)</label>
          <input id="customer-phone" type="text" placeholder="+998...">
        </div>
        <!-- MUHIM (foydalanuvchi so'rovi bilan): "Qisman to'lov" alohida
             tugma EMAS -- "Nasiya" tanlanganda shu maydon ham ko'rinadi.
             0 qoldirilsa, xuddi ilgarigidek hammasi qarzga yoziladi;
             musbat son kiritilsa, qolgani avtomatik qarz daftariga
             yoziladi (kompyuterdagi "Nasiyaga berish" oynasidagi "Hozir
             to'lanadigan summa" bilan bir xil). -->
        <div class="field">
          <label data-i18n="paid_now_label">Hozir to'lanadigan summa</label>
          <input id="paid-now-amount" type="number" inputmode="decimal" min="0" step="any" placeholder="0">
        </div>
      </div>

      <label class="check-row">
        <input type="checkbox" id="print-receipt-check">
        <span data-i18n="print_receipt_check">Chekni kompyuterdagi printerga ham chop etish</span>
      </label>
      <div class="field" id="receipt-printer-field" style="display:none;">
        <label data-i18n="receipt_printer">Chek printeri</label>
        <select id="receipt-printer-select"></select>
        <label data-i18n="receipt_copies" style="margin-top:8px;">Nechta nusxa</label>
        <input id="receipt-copies" type="number" inputmode="numeric" min="1" max="20" value="1">
      </div>

      <button id="checkout-btn" data-i18n="checkout_btn">Sotishni yakunlash</button>
      <button id="close-cart-btn" data-i18n="btn_close">Yopish</button>
      <div id="sale-msg"></div>
    </div>
  </div>

<script>
  // MUHIM: agar biror joyda kutilmagan JS xatolik (exception) yuz bersa,
  // ilova butunlay "qotib" (bo'sh ekran holida) qolmasligi uchun, xato
  // matnini to'g'ridan-to'g'ri ekranga ("err" konteyneriga) chiqaramiz --
  // shunda konsolga kira olmasak ham, aynan qaysi qatorda va nima uchun
  // ishlamayotgani ko'rinadi.
  window.onerror = function (msg, src, line, col, err) {
    try {
      var e = document.getElementById("err");
      if (e) {
        e.style.display = "block";
        e.textContent = "JS xatolik: " + msg + " (qator " + line + ":" + col + ")";
      }
    } catch (ignored) {}
    return false;
  };
  window.addEventListener("unhandledrejection", function (ev) {
    try {
      var e = document.getElementById("err");
      if (e) {
        e.style.display = "block";
        e.textContent = "JS xatolik (promise): " + (ev.reason && ev.reason.message ? ev.reason.message : ev.reason);
      }
    } catch (ignored) {}
  });

  const tg = window.Telegram ? window.Telegram.WebApp : null;
  if (tg) { tg.ready(); tg.expand(); }
  const initData = tg ? tg.initData : "";

  // --- Ko'p tillilik (i18n) ---------------------------------------------
  // MUHIM: Mini App endi ochilgan foydalanuvchining TILIGA qarab (bot orqali
  // tanlagan tili, yoki hali tanlanmagan bo'lsa -- Telegram ilovasining o'zi
  // yuboradigan tili) UZ/EN/RU ko'rinishda ishlaydi. Server /api/products
  // javobida "language" maydonini qaytaradi (curLang shu yerdan o'rnatiladi).
  const I18N = {
    uz: {
      tab_shop: "Do'kon", tab_add_product: "Mahsulot", tab_reports: "Hisobot",
      search_placeholder: "Qidirish...",
      empty_products: "Mahsulot topilmadi", error_generic: "Xatolik yuz berdi",
      error_connection: "Ulanishda xatolik.", currency: "so'm",
      cart_count_suffix: "ta mahsulot",
      ap_title: "Yangi mahsulot qo'shish", ap_name: "Nomi", ap_cost: "Tan narxi (so'm)",
      ap_price: "Sotish narxi (so'm)", ap_qty: "Miqdor", ap_unit: "O'lchov birligi",
      ap_barcode: "Shtrix kod (bo'sh qoldirsangiz, o'zi yaratiladi)",
      product_image_label: "Mahsulot rasmi (ixtiyoriy)", product_image_remove: "🗑 Rasmni olib tashlash",
      product_ai_bg_label: "AI: fonni olib tashlash",
      ap_ai_bg_processing: "AI ishlamoqda... (birinchi marta biroz vaqt olishi mumkin)",
      ap_label_size_title: "Yorliqdagi yozuvlar o'lchami",
      ap_name_font: "Nomi shrifti", ap_price_font: "Narx shrifti",
      ap_barcode_scale: "Shtrix kod o'lchami (%)", ap_submit: "Qo'shish",
      ap_usd_helper_title: "Yordamchi: dollardan so'mga avtomatik hisoblash",
      ap_usd_amount_ph: "masalan 1.5", ap_usd_rate_ph: "masalan 12000",
      ap_usd_calc_btn: "Hisoblash",
      ap_markup_label: "Foyda foizi (%):", ap_markup_ph: "masalan 20",
      ap_markup_calc_btn: "Sotish narxini hisoblash",
      ap_usd_fill_first: "Dollar summasi va kursni to'g'ri kiriting (masalan 1.5 va 12000).",
      ap_positive_required: "Qiymatlar musbat bo'lishi kerak.",
      ap_cost_calculated: "Tan narxi", ap_cost_first: "Avval tan narxini to'g'ri kiriting.",
      ap_price_calc_result: "Sotish narxi: {price} so'm ({pct}% foyda bilan)",
      ap_price_calc_rounded: "Sotish narxi: {raw} so'm bo'ldi, {price} so'm ga yaxlitlandi ({pct}% foyda bilan)",
      edit_product_title: "Mahsulotni tahrirlash", btn_save: "Saqlash",
      ep_barcode_print_title: "Shtrix kodni chop etish",
      ep_barcode_missing: "Avval shtrix kodni to'ldiring va saqlang.",
      btn_delete_product: "🗑 Mahsulotni o'chirish",
      confirm_delete_product: "\\"{name}\\" mahsulotini butunlay o'chirmoqchimisiz?",
      product_updated: "✅ Mahsulot ma'lumotlari yangilandi.",
      product_deleted: "✅ Mahsulot o'chirildi.",
      ap_added_ok: "✅ Mahsulot qo'shildi.", ap_refresh_preview: "Ko'rinishni yangilash",
      ap_printer_label: "Shtrix kod printeri", ap_copies_label: "Nechta nusxa",
      ap_print_barcode: "Shtrix kodni chop etish",
      ap_print_ok: "✅ Chop etildi.", ap_print_err: "Chop etishda xatolik",
      ap_refresh_ok: "✅ Yangilandi.",
      rep_title: "Hisobotlar", rep_today: "Bugun", rep_last30: "So'nggi 30 kun",
      rep_this_month: "Shu oy", rep_pick_month: "Boshqa oy tanlash",
      rep_recent_sales: "So'nggi sotuvlar", rep_debtors: "Qarzdorlar (to'lanmagan nasiya)",
      rep_closures: "Yopilgan kunlar", rep_top_products: "Eng ko'p sotilganlar",
      stat_total_sum: "Jami savdo", stat_profit: "Foyda", stat_sale_count: "Sotuvlar soni (qatorlar)",
      stat_nasiya_profit: "Nasiya foydasi", stat_nasiya_sum: "Nasiya (shu davr)",
      stat_unpaid_debt: "Jami to'lanmagan qarz", stat_warehouse_value: "Ombor qiymati",
      no_sales_period: "Bu davrda hali sotuv bo'lmagan", no_debt: "To'lanmagan qarz yo'q",
      no_closures: "Hali yopilgan kun yo'q",
      detail_default_title: "Tafsilot", btn_close: "Yopish",
      sale_detail_title: "Sotuv tafsiloti", debtor_detail_title: "Qarzdor tafsiloti",
      sum_label: "Summa", payment_type_label: "To'lov turi", time_label: "Vaqti",
      phone_label: "Telefon", what_bought: "Nima olgan", no_product_info: "Mahsulot ma'lumoti yo'q",
      reprint_receipt_title: "Chekni qayta chop etish", reprint_receipt_btn: "🖨 Chekni chop etish",
      custom_receipt_selected: "{n} ta mahsulot tanlandi", custom_receipt_btn: "🖨 Chek chiqarish",
      custom_receipt_clear: "Bekor qilish", custom_receipt_title: "Tanlangan mahsulotlar uchun chek",
      delete_sale_btn: "🗑 Sotuvni bekor qilish", confirm_delete_sale: "Ushbu sotuvni bekor qilishni tasdiqlaysizmi? Mahsulot omborga qaytariladi.",
      delete_sale_err: "Bekor qilishda xatolik.",
      naqd_sales: "Naqd savdo", naqd_profit: "Naqd foyda", nasiya_sales: "Nasiya savdo",
      nasiya_profit_label: "Nasiya foyda", total_label: "Jami", closed_at_label: "Yopilgan vaqti",
      cart_title: "Savat", cart_total: "Jami:", cart_clear: "Savatni tozalash",
      pay_naqd: "Naqd", pay_karta: "Plastik karta", pay_nasiya: "Nasiya",
      customer_name: "Xaridor ismi", customer_phone: "Telefon (ixtiyoriy)",
      paid_now_label: "Hozir to'lanadigan summa",
      print_receipt_check: "Chekni kompyuterdagi printerga ham chop etish",
      receipt_printer: "Chek printeri", receipt_copies: "Nechta nusxa",
      checkout_btn: "Sotishni yakunlash",
      remove: "O'chirish", nasiya_name_required: "Nasiya uchun xaridor ismini kiriting.",
      paid_now_invalid: "To'lanadigan summani to'g'ri kiriting (0 dan jami summagacha).",
      discount_btn: "Narxni pasaytirish (chegirma)", discount_apply: "Qo'llash",
      sending: "Yuborilmoqda...", loading: "Yuklanmoqda...",
      sold_prefix: "✅ Sotildi:", receipt_printed: "(chek chop etildi)",
      receipt_not_printed: "(chek chop etilmadi:", unknown_error: "xato",
    },
    en: {
      tab_shop: "Shop", tab_add_product: "Product", tab_reports: "Reports",
      search_placeholder: "Search...",
      empty_products: "No products found", error_generic: "An error occurred",
      error_connection: "Connection error.", currency: "so'm",
      cart_count_suffix: "items",
      ap_title: "Add new product", ap_name: "Name", ap_cost: "Cost price (so'm)",
      ap_price: "Sale price (so'm)", ap_qty: "Quantity", ap_unit: "Unit",
      ap_barcode: "Barcode (leave blank to auto-generate)",
      product_image_label: "Product photo (optional)", product_image_remove: "🗑 Remove photo",
      product_ai_bg_label: "AI: remove background",
      ap_ai_bg_processing: "AI is working... (may take a bit the first time)",
      ap_label_size_title: "Label text size",
      ap_name_font: "Name font", ap_price_font: "Price font",
      ap_barcode_scale: "Barcode size (%)", ap_submit: "Add",
      ap_usd_helper_title: "Helper: auto-calculate so'm from USD",
      ap_usd_amount_ph: "e.g. 1.5", ap_usd_rate_ph: "e.g. 12000",
      ap_usd_calc_btn: "Calculate",
      ap_markup_label: "Profit margin (%):", ap_markup_ph: "e.g. 20",
      ap_markup_calc_btn: "Calculate sale price",
      ap_usd_fill_first: "Enter a valid USD amount and rate (e.g. 1.5 and 12000).",
      ap_positive_required: "Values must be positive.",
      ap_cost_calculated: "Cost price", ap_cost_first: "Enter a valid cost price first.",
      ap_price_calc_result: "Sale price: {price} so'm ({pct}% margin)",
      ap_price_calc_rounded: "Sale price came to {raw} so'm, rounded to {price} so'm ({pct}% margin)",
      edit_product_title: "Edit product", btn_save: "Save",
      ep_barcode_print_title: "Print barcode",
      ep_barcode_missing: "Fill in the barcode and save first.",
      btn_delete_product: "🗑 Delete product",
      confirm_delete_product: "Delete \\"{name}\\" permanently?",
      product_updated: "✅ Product updated.",
      product_deleted: "✅ Product deleted.",
      ap_added_ok: "✅ Product added.", ap_refresh_preview: "Refresh preview",
      ap_printer_label: "Barcode printer", ap_copies_label: "Number of copies",
      ap_print_barcode: "Print barcode",
      ap_print_ok: "✅ Printed.", ap_print_err: "Print error",
      ap_refresh_ok: "✅ Refreshed.",
      rep_title: "Reports", rep_today: "Today", rep_last30: "Last 30 days",
      rep_this_month: "This month", rep_pick_month: "Pick another month",
      rep_recent_sales: "Recent sales", rep_debtors: "Debtors (unpaid credit)",
      rep_closures: "Closed days", rep_top_products: "Top selling products",
      stat_total_sum: "Total sales", stat_profit: "Profit", stat_sale_count: "Sale count (rows)",
      stat_nasiya_profit: "Credit profit", stat_nasiya_sum: "Credit (this period)",
      stat_unpaid_debt: "Total unpaid debt", stat_warehouse_value: "Inventory value",
      no_sales_period: "No sales yet in this period", no_debt: "No unpaid debt",
      no_closures: "No closed days yet",
      detail_default_title: "Details", btn_close: "Close",
      sale_detail_title: "Sale details", debtor_detail_title: "Debtor details",
      sum_label: "Amount", payment_type_label: "Payment type", time_label: "Time",
      phone_label: "Phone", what_bought: "Items bought", no_product_info: "No product info",
      reprint_receipt_title: "Reprint receipt", reprint_receipt_btn: "🖨 Print receipt",
      custom_receipt_selected: "{n} item(s) selected", custom_receipt_btn: "🖨 Print receipt",
      custom_receipt_clear: "Cancel", custom_receipt_title: "Receipt for selected items",
      delete_sale_btn: "🗑 Cancel sale", confirm_delete_sale: "Confirm cancelling this sale? Stock will be restored.",
      delete_sale_err: "Error cancelling sale.",
      naqd_sales: "Cash sales", naqd_profit: "Cash profit", nasiya_sales: "Credit sales",
      nasiya_profit_label: "Credit profit", total_label: "Total", closed_at_label: "Closed at",
      cart_title: "Cart", cart_total: "Total:", cart_clear: "Clear cart",
      pay_naqd: "Cash", pay_karta: "Card", pay_nasiya: "Credit",
      customer_name: "Customer name", customer_phone: "Phone (optional)",
      paid_now_label: "Amount paid now",
      print_receipt_check: "Also print receipt on computer printer",
      receipt_printer: "Receipt printer", receipt_copies: "Number of copies",
      checkout_btn: "Complete sale",
      remove: "Remove", nasiya_name_required: "Please enter the customer's name for credit.",
      paid_now_invalid: "Enter a valid amount paid (between 0 and the total).",
      discount_btn: "Lower price (discount)", discount_apply: "Apply",
      sending: "Sending...", loading: "Loading...",
      sold_prefix: "✅ Sold:", receipt_printed: "(receipt printed)",
      receipt_not_printed: "(receipt not printed:", unknown_error: "error",
    },
    ru: {
      tab_shop: "Магазин", tab_add_product: "Товар", tab_reports: "Отчёт",
      search_placeholder: "Поиск...",
      empty_products: "Товары не найдены", error_generic: "Произошла ошибка",
      error_connection: "Ошибка соединения.", currency: "сум",
      cart_count_suffix: "товар(ов)",
      ap_title: "Добавить новый товар", ap_name: "Название", ap_cost: "Себестоимость (сум)",
      ap_price: "Цена продажи (сум)", ap_qty: "Количество", ap_unit: "Единица измерения",
      ap_barcode: "Штрих-код (оставьте пустым для автогенерации)",
      product_image_label: "Фото товара (необязательно)", product_image_remove: "🗑 Удалить фото",
      product_ai_bg_label: "ИИ: удалить фон",
      ap_ai_bg_processing: "ИИ обрабатывает... (в первый раз может занять немного времени)",
      ap_label_size_title: "Размер текста этикетки",
      ap_name_font: "Шрифт названия", ap_price_font: "Шрифт цены",
      ap_barcode_scale: "Размер штрих-кода (%)", ap_submit: "Добавить",
      ap_usd_helper_title: "Помощник: автоматический расчёт сум из долларов",
      ap_usd_amount_ph: "напр. 1.5", ap_usd_rate_ph: "напр. 12000",
      ap_usd_calc_btn: "Рассчитать",
      ap_markup_label: "Процент прибыли (%):", ap_markup_ph: "напр. 20",
      ap_markup_calc_btn: "Рассчитать цену продажи",
      ap_usd_fill_first: "Введите корректную сумму в долларах и курс (напр. 1.5 и 12000).",
      ap_positive_required: "Значения должны быть положительными.",
      ap_cost_calculated: "Себестоимость", ap_cost_first: "Сначала введите корректную себестоимость.",
      ap_price_calc_result: "Цена продажи: {price} сум ({pct}% наценка)",
      ap_price_calc_rounded: "Цена продажи составила {raw} сум, округлена до {price} сум ({pct}% наценка)",
      edit_product_title: "Редактировать товар", btn_save: "Сохранить",
      ep_barcode_print_title: "Печать штрих-кода",
      ep_barcode_missing: "Сначала заполните и сохраните штрих-код.",
      btn_delete_product: "🗑 Удалить товар",
      confirm_delete_product: "Удалить \\"{name}\\" навсегда?",
      product_updated: "✅ Товар обновлён.",
      product_deleted: "✅ Товар удалён.",
      ap_added_ok: "✅ Товар добавлен.", ap_refresh_preview: "Обновить превью",
      ap_printer_label: "Принтер штрих-кодов", ap_copies_label: "Количество копий",
      ap_print_barcode: "Печать штрих-кода",
      ap_print_ok: "✅ Напечатано.", ap_print_err: "Ошибка печати",
      ap_refresh_ok: "✅ Обновлено.",
      rep_title: "Отчёты", rep_today: "Сегодня", rep_last30: "Последние 30 дней",
      rep_this_month: "Этот месяц", rep_pick_month: "Выбрать другой месяц",
      rep_recent_sales: "Недавние продажи", rep_debtors: "Должники (непогашенный долг)",
      rep_closures: "Закрытые дни", rep_top_products: "Самые продаваемые",
      stat_total_sum: "Всего продаж", stat_profit: "Прибыль", stat_sale_count: "Кол-во продаж (строк)",
      stat_nasiya_profit: "Прибыль с долга", stat_nasiya_sum: "В долг (за период)",
      stat_unpaid_debt: "Всего непогашенный долг", stat_warehouse_value: "Стоимость склада",
      no_sales_period: "За этот период продаж пока не было", no_debt: "Нет непогашенного долга",
      no_closures: "Пока нет закрытых дней",
      detail_default_title: "Подробности", btn_close: "Закрыть",
      sale_detail_title: "Детали продажи", debtor_detail_title: "Детали должника",
      sum_label: "Сумма", payment_type_label: "Способ оплаты", time_label: "Время",
      phone_label: "Телефон", what_bought: "Что купил(а)", no_product_info: "Нет данных о товаре",
      reprint_receipt_title: "Повторная печать чека", reprint_receipt_btn: "🖨 Печать чека",
      custom_receipt_selected: "Выбрано товаров: {n}", custom_receipt_btn: "🖨 Печать чека",
      custom_receipt_clear: "Отмена", custom_receipt_title: "Чек для выбранных товаров",
      delete_sale_btn: "🗑 Отменить продажу", confirm_delete_sale: "Подтвердите отмену продажи? Товар вернётся на склад.",
      delete_sale_err: "Ошибка при отмене продажи.",
      naqd_sales: "Продажи наличными", naqd_profit: "Прибыль наличными", nasiya_sales: "Продажи в долг",
      nasiya_profit_label: "Прибыль с долга", total_label: "Итого", closed_at_label: "Время закрытия",
      cart_title: "Корзина", cart_total: "Итого:", cart_clear: "Очистить корзину",
      pay_naqd: "Наличные", pay_karta: "Карта", pay_nasiya: "В долг",
      customer_name: "Имя покупателя", customer_phone: "Телефон (необязательно)",
      paid_now_label: "Сумма, оплачиваемая сейчас",
      print_receipt_check: "Также распечатать чек на компьютерном принтере",
      receipt_printer: "Принтер чеков", receipt_copies: "Количество копий",
      checkout_btn: "Завершить продажу",
      remove: "Удалить", nasiya_name_required: "Введите имя покупателя для продажи в долг.",
      paid_now_invalid: "Введите правильную сумму оплаты (от 0 до итоговой суммы).",
      discount_btn: "Снизить цену (скидка)", discount_apply: "Применить",
      sending: "Отправка...", loading: "Загрузка...",
      sold_prefix: "✅ Продано:", receipt_printed: "(чек напечатан)",
      receipt_not_printed: "(чек не напечатан:", unknown_error: "ошибка",
    },
  };
  let curLang = "uz";
  function t(key) { return (I18N[curLang] && I18N[curLang][key]) || I18N.uz[key] || key; }
  function applyI18n(lang) {
    curLang = (I18N[lang]) ? lang : "uz";
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
    });
    document.getElementById("pay-naqd").dataset.label = t("pay_naqd");
    document.getElementById("pay-karta").dataset.label = t("pay_karta");
    if (paymentType === "naqd" && paymentLabel !== null) { paymentLabel = t("pay_naqd"); }
    if (typeof renderMonthPicker === "function") {
      try { renderMonthPicker(); } catch (e) { /* hali e'lon qilinmagan bo'lishi mumkin (birinchi chaqiriqda) */ }
    }
  }

  const listEl = document.getElementById("list");
  const emptyEl = document.getElementById("empty");
  const errEl = document.getElementById("err");
  const input = document.getElementById("search-input");
  const cartBar = document.getElementById("cart-bar");
  const cartCountEl = document.getElementById("cart-count");
  const cartTotalMiniEl = document.getElementById("cart-total-mini");
  const cartModal = document.getElementById("cart-modal");
  const cartItemsEl = document.getElementById("cart-items");
  const cartTotalFullEl = document.getElementById("cart-total-full");
  const nasiyaFields = document.getElementById("nasiya-fields");
  const paidNowInput = document.getElementById("paid-now-amount");
  const checkoutBtn = document.getElementById("checkout-btn");
  const closeCartBtn = document.getElementById("close-cart-btn");
  const saleMsg = document.getElementById("sale-msg");
  const printReceiptCheck = document.getElementById("print-receipt-check");
  const receiptPrinterField = document.getElementById("receipt-printer-field");
  const receiptPrinterSelect = document.getElementById("receipt-printer-select");

  const payButtons = [
    document.getElementById("pay-naqd"),
    document.getElementById("pay-karta"),
    document.getElementById("pay-nasiya"),
  ];

  let canSell = false;
  let canManageProducts = false;
  let canViewReports = false;
  let cart = {}; // id -> {product, qty}
  let paymentType = "naqd";
  let paymentLabel = "Naqd";
  let printersLoaded = false;
  let availablePrinters = [];

  function fmtMoney(n) {
    n = Math.round(n || 0);
    return n.toString().replace(/\\B(?=(\\d{3})+(?!\\d))/g, " ");
  }

  // --- Tab navigation -------------------------------------------------
  const tabShop = document.getElementById("tab-shop");
  const tabAddProduct = document.getElementById("tab-add-product");
  const tabReports = document.getElementById("tab-reports");
  const pageShop = document.getElementById("page-shop");
  const pageAddProduct = document.getElementById("page-add-product");
  const pageReports = document.getElementById("page-reports");

  function showPage(name) {
    for (const p of [pageShop, pageAddProduct, pageReports]) p.classList.remove("active");
    for (const t of [tabShop, tabAddProduct, tabReports]) t.classList.remove("active");
    if (name === "shop") { pageShop.classList.add("active"); tabShop.classList.add("active"); }
    if (name === "add-product") {
      pageAddProduct.classList.add("active"); tabAddProduct.classList.add("active");
      ensurePrintersLoaded();
      ensureBarcodeSettingsLoaded();
    }
    if (name === "reports") {
      pageReports.classList.add("active"); tabReports.classList.add("active");
      loadReports(currentReportPeriod);
    }
    updateCartBarVisibility();
  }
  tabShop.addEventListener("click", () => showPage("shop"));
  tabAddProduct.addEventListener("click", () => showPage("add-product"));
  tabReports.addEventListener("click", () => showPage("reports"));

  function updateCartBarVisibility() {
    const onShop = pageShop.classList.contains("active");
    cartBar.style.display = (onShop && cartList().length) ? "flex" : "none";
    if (cartBar.style.display === "flex") positionCartBar();
  }

  // MUHIM: savat paneli endi TEPADA, tabbar + qidiruv qatoridan keyin
  // "yopishqoq" (sticky) turadi -- shu ikkisining HAQIQIY balandligini
  // o'lchab, "top" qiymatini shunga qarab dinamik hisoblaymiz (turli
  // ekran/shrift o'lchamlarida ham to'g'ri joylashishi uchun).
  const tabbarEl = document.getElementById("tabbar");
  const searchBarEl = document.getElementById("search-bar");
  function positionCartBar() {
    const offset = (tabbarEl.offsetHeight || 0) + (searchBarEl.offsetHeight || 0);
    cartBar.style.top = offset + "px";
  }
  window.addEventListener("resize", () => { if (cartBar.style.display === "flex") positionCartBar(); });

  // --- Printers -----------------------------------------------------------
  let lastReceiptPrinterDefault = null;
  let lastBarcodePrinterDefault = null;

  // MUHIM (foydalanuvchi so'rovi bilan): "So'nggi sotuvlar" ro'yxatidan
  // BIR NECHTA turli mahsulotni (checkbox bilan) tanlab, ularni BITTA
  // yangi chekka birlashtirib chop etish uchun -- oldin faqat 1 ta
  // qatorni bosib, o'sha sotuvning O'ZINI qayta chop etish mumkin edi,
  // bir nechtasini birga tanlab bo'lmasdi.
  const selectedReceiptItems = new Map();
  function updateReceiptSelectBar() {
    const bar = document.getElementById("receipt-select-bar");
    if (!bar) return;
    const n = selectedReceiptItems.size;
    if (n === 0) {
      bar.style.display = "none";
      return;
    }
    let total = 0;
    for (const it of selectedReceiptItems.values()) { total += it.total; }
    bar.style.display = "flex";
    bar.querySelector(".rsel-count").textContent = t("custom_receipt_selected").replace("{n}", n);
    bar.querySelector(".rsel-total").textContent = fmtMoney(total) + " " + t("currency");
  }
  function clearReceiptSelection() {
    selectedReceiptItems.clear();
    updateReceiptSelectBar();
    document.querySelectorAll(".hist-row .hsel").forEach(cb => { cb.checked = false; });
  }
  document.getElementById("receipt-select-clear-btn").addEventListener("click", clearReceiptSelection);
  document.getElementById("receipt-select-print-btn").addEventListener("click", async () => {
    if (selectedReceiptItems.size === 0) return;
    const cur = t("currency");
    let html = "";
    for (const it of selectedReceiptItems.values()) {
      html += `<div class="hist-row"><span class="hname">${it.name}</span><span class="hmeta">${it.qty} ${it.unit} — ${fmtMoney(it.total)} ${cur}</span></div>`;
    }
    html += `<div class="field"><label>${t("ap_printer_label")}</label><select id="custom-receipt-printer"></select></div>`;
    html += `<div class="field"><label>${t("ap_copies_label")}</label><input id="custom-receipt-copies" type="number" inputmode="numeric" min="1" max="20" value="1"></div>`;
    html += `<button class="primary-btn" id="custom-receipt-confirm-btn">${t("custom_receipt_btn")}</button>`;
    html += `<div id="custom-receipt-msg" style="text-align:center; font-size:13px; margin-top:6px;"></div>`;
    openDetail(t("custom_receipt_title"), html);
    await ensurePrintersLoaded();
    const printerSel = document.getElementById("custom-receipt-printer");
    populatePrinterSelect(printerSel, lastReceiptPrinterDefault);
    document.getElementById("custom-receipt-confirm-btn").addEventListener("click", async () => {
      const msgEl = document.getElementById("custom-receipt-msg");
      const copiesEl = document.getElementById("custom-receipt-copies");
      msgEl.textContent = t("sending");
      try {
        const r = await fetch("/api/receipt/custom_print", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            initData,
            items: Array.from(selectedReceiptItems.values()),
            printer_name: printerSel.value || null,
            copies: parseInt(copiesEl.value, 10) || 1,
          }),
        });
        const rd = await r.json();
        msgEl.textContent = rd.ok ? t("ap_print_ok") : (t("ap_print_err") + ": " + (rd.message || t("unknown_error")));
        if (rd.ok) {
          lastReceiptPrinterDefault = printerSel.value || lastReceiptPrinterDefault;
          if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred("success"); }
          clearReceiptSelection();
        }
      } catch (e) {
        msgEl.textContent = t("error_connection");
      }
    });
  });

  // MUHIM (foydalanuvchi so'rovi bilan): nasiyaga sotish paytida "Xaridor
  // ismi" maydonida OLDIN qarz daftariga yozilgan mijozlar taklif
  // qilinadi -- ro'yxatdan tanlanganda telefon raqami ham avtomatik
  // to'ldiriladi. MUHIM TUZATISH: dastlab brauzerning standart <datalist>
  // (native klaviatura ustidagi taklif satri) ishlatilgan edi, lekin
  // foydalanuvchi ko'p mijoz bo'lganda FAQAT 3 tasi ko'rinishini xabar
  // qildi (bu -- OS klaviaturasining o'zining cheklovi, biz nazorat qila
  // olmaymiz). Shuning uchun endi sahifaning O'ZIDA, to'liq nazorat
  // qilinadigan ochiladigan ro'yxat (dropdown) ishlatiladi -- barcha mos
  // keluvchi mijozlarni ko'rsatadi.
  let customersLoaded = false;
  let knownCustomers = [];
  async function ensureCustomersLoaded() {
    if (customersLoaded) return;
    try {
      const url = "/api/customers?initData=" + encodeURIComponent(initData || "");
      const resp = await fetch(url);
      const data = await resp.json();
      if (resp.ok && data.customers) {
        knownCustomers = data.customers;
        customersLoaded = true;
      }
    } catch (e) { /* jimgina e'tiborsiz qoldiriladi -- shunchaki taklif ishlamaydi */ }
  }
  const customerNameInput = document.getElementById("customer-name");
  const customerPhoneInput = document.getElementById("customer-phone");
  const customerSuggestEl = document.getElementById("customer-name-suggestions");

  function renderCustomerSuggestions() {
    if (!customerSuggestEl || !customerNameInput) return;
    const q = customerNameInput.value.trim().toLowerCase();
    const matches = (q
      ? knownCustomers.filter(c => c.name.toLowerCase().includes(q))
      : knownCustomers
    ).slice(0, 30);
    if (!matches.length) {
      customerSuggestEl.style.display = "none";
      customerSuggestEl.innerHTML = "";
      return;
    }
    customerSuggestEl.innerHTML = "";
    for (const c of matches) {
      const item = document.createElement("div");
      item.className = "suggest-item";
      item.innerHTML = `<span class="sname"></span><span class="sphone"></span>`;
      item.querySelector(".sname").textContent = c.name;
      item.querySelector(".sphone").textContent = c.phone || "";
      // MUHIM: "mousedown" ishlatilgan, "click" EMAS -- chunki input'dagi
      // "blur" hodisasi "click"dan OLDIN sodir bo'lib, ro'yxat allaqachon
      // yashiringan bo'lardi va tanlash ishlamay qolardi.
      item.addEventListener("mousedown", (e) => {
        e.preventDefault();
        customerNameInput.value = c.name;
        if (c.phone && customerPhoneInput && !customerPhoneInput.value.trim()) {
          customerPhoneInput.value = c.phone;
        }
        customerSuggestEl.style.display = "none";
      });
      customerSuggestEl.appendChild(item);
    }
    customerSuggestEl.style.display = "block";
  }

  if (customerNameInput) {
    customerNameInput.addEventListener("input", renderCustomerSuggestions);
    customerNameInput.addEventListener("focus", async () => {
      await ensureCustomersLoaded();
      renderCustomerSuggestions();
    });
    customerNameInput.addEventListener("blur", () => {
      // Ozgina kechikish -- shu bilan yuqoridagi "mousedown" ulgurib
      // ishlaydi (aks holda ro'yxat "blur" bilan darhol yashirinib,
      // tanlash amalga oshmay qolardi).
      setTimeout(() => { customerSuggestEl.style.display = "none"; }, 150);
    });
  }

  async function ensurePrintersLoaded() {
    if (printersLoaded) return;
    try {
      const url = "/api/printers?initData=" + encodeURIComponent(initData || "");
      const resp = await fetch(url);
      const data = await resp.json();
      if (resp.ok && data.printers) {
        availablePrinters = data.printers;
        printersLoaded = true;
        lastReceiptPrinterDefault = data.receipt_printer || null;
        lastBarcodePrinterDefault = data.barcode_printer || null;
        receiptPrinterSelect.innerHTML = "";
        const barcodeSelect = document.getElementById("ap-printer-select");
        for (const p of availablePrinters) {
          const opt1 = document.createElement("option");
          opt1.value = p; opt1.textContent = p;
          if (p === data.receipt_printer) opt1.selected = true;
          receiptPrinterSelect.appendChild(opt1);
          if (barcodeSelect) {
            const opt2 = document.createElement("option");
            opt2.value = p; opt2.textContent = p;
            if (p === data.barcode_printer) opt2.selected = true;
            barcodeSelect.appendChild(opt2);
          }
        }
      }
    } catch (e) { /* jim -- printer tanlash ixtiyoriy, xato bo'lsa e'tiborsiz qoldiramiz */ }
  }
  // MUHIM: foydalanuvchi tanlagan har qanday printer endi ESLAB QOLINADI
  // (backendda sozlamalarga yoziladi) -- shu funksiya har qanday <select>
  // elementiga printerlar ro'yxatini quyib, OXIRGI ESLAB QOLINGAN
  // printerni avtomatik tanlangan holda ko'rsatadi.
  function populatePrinterSelect(selectEl, defaultPrinter) {
    selectEl.innerHTML = "";
    for (const p of availablePrinters) {
      const opt = document.createElement("option");
      opt.value = p; opt.textContent = p;
      if (p === defaultPrinter) opt.selected = true;
      selectEl.appendChild(opt);
    }
  }
  printReceiptCheck.addEventListener("change", () => {
    receiptPrinterField.style.display = printReceiptCheck.checked ? "block" : "none";
    if (printReceiptCheck.checked) ensurePrintersLoaded();
  });

  // --- Product list / cart ---------------------------------------------
  async function loadProducts(q) {
    errEl.style.display = "none";
    emptyEl.style.display = "none";
    // MUHIM: agar server/tunnel javob bermay "osilib qolsa", so'rov
    // CHEKSIZ kutmasin -- 15 soniyadan keyin avtomatik bekor qilinadi va
    // ekranda aniq xabar chiqadi (bo'sh, hech narsa ko'rsatilmagan holat
    // o'rniga).
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);
    try {
      const url = "/api/products?q=" + encodeURIComponent(q || "") +
                  "&initData=" + encodeURIComponent(initData || "");
      const resp = await fetch(url, { signal: controller.signal });
      const data = await resp.json();
      applyI18n(data.language || "uz");
      if (!resp.ok) {
        errEl.textContent = data.message || t("error_generic");
        errEl.style.display = "block";
        listEl.innerHTML = "";
        return;
      }
      canSell = !!data.can_sell;
      canManageProducts = !!data.can_manage_products;
      canViewReports = !!data.can_view_reports;
      tabAddProduct.style.display = canManageProducts ? "" : "none";
      tabReports.style.display = canViewReports ? "" : "none";
      render(data.items || []);
    } catch (e) {
      errEl.textContent = (e && e.name === "AbortError")
        ? "Server javob bermadi (timeout). Kompyuterdagi dastur ishlab turganini tekshiring."
        : (t("error_connection") + (e && e.message ? " (" + e.message + ")" : ""));
      errEl.style.display = "block";
    } finally {
      clearTimeout(timeoutId);
    }
  }

  function render(items) {
    listEl.innerHTML = "";
    if (!items.length) {
      emptyEl.style.display = "block";
      return;
    }
    for (const it of items) {
      const row = document.createElement("div");
      row.className = "item" + (canSell ? " sellable" : "");
      // MUHIM (foydalanuvchi so'rovi bilan): agar mahsulotga rasm
      // qo'yilgan bo'lsa, ro'yxatda kichik rasm (thumbnail) ko'rsatiladi.
      const thumbHtml = it.image_url
        ? `<img class="thumb" src="${it.image_url}${it.image_url.includes('?') ? '&' : '?'}initData=${encodeURIComponent(initData || '')}">`
        : "";
      row.innerHTML = `
        ${thumbHtml}
        <div class="name"></div>
        <div class="meta"><span class="price"></span><br>${it.qty} ${it.unit}</div>
      `;
      row.querySelector(".name").textContent = it.name;
      row.querySelector(".price").textContent = fmtMoney(it.price) + " " + t("currency");
      if (canSell) {
        row.addEventListener("click", () => addToCart(it));
      }
      if (canManageProducts) {
        const editBtn = document.createElement("button");
        editBtn.className = "edit-product-btn";
        editBtn.textContent = "✏️";
        editBtn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          openEditProductModal(it);
        });
        row.appendChild(editBtn);
      }
      listEl.appendChild(row);
    }
  }

  function addToCart(product) {
    const existing = cart[product.id];
    if (existing) {
      if (existing.qty + 1 > product.qty) return;
      existing.qty += 1;
    } else {
      if (product.qty < 1) return;
      // MUHIM (foydalanuvchi so'rovi bilan): kompyuterdagi savat kabi,
      // har bir savat qatori o'zining "price" (kelishilgan narx) maydoniga
      // ega -- boshida mahsulotning ombordagi narxiga teng, lekin
      // "Chegirma" tugmasi orqali FAQAT shu sotuv uchun pasaytirilishi
      // mumkin (mahsulotning ombordagi doimiy narxi o'zgarmaydi).
      cart[product.id] = { product, qty: 1, price: product.price };
    }
    if (tg && tg.HapticFeedback) { tg.HapticFeedback.impactOccurred("light"); }
    updateCartBar();
  }

  function cartList() { return Object.values(cart); }

  function cartTotal() {
    return cartList().reduce((s, e) => s + (e.price != null ? e.price : e.product.price) * e.qty, 0);
  }

  function updateCartBar() {
    const entries = cartList();
    const count = entries.reduce((s, e) => s + e.qty, 0);
    if (!entries.length) {
      cartBar.style.display = "none";
      return;
    }
    updateCartBarVisibility();
    cartCountEl.textContent = count + " " + t("cart_count_suffix");
    cartTotalMiniEl.textContent = fmtMoney(cartTotal()) + " " + t("currency");
  }

  function renderCartModal() {
    cartItemsEl.innerHTML = "";
    for (const entry of cartList()) {
      if (entry.price == null) entry.price = entry.product.price;
      const discounted = entry.price !== entry.product.price;
      // MUHIM TUZATISH (foydalanuvchi so'rovi bilan): chegirma tahrirlash
      // qatori endi savat qatorining flex-tuzilishi ICHIDA emas, balki
      // ALOHIDA, to'liq kenglikdagi ".cart-entry" konteyner ichida --
      // shu bilan katta narx (masalan 500 000) yozilganda ham matn
      // to'liq ko'rinadi, boshqa tugmalar bilan siqilib qolmaydi.
      const entryWrap = document.createElement("div");
      entryWrap.className = "cart-entry";
      entryWrap.innerHTML = `
        <div class="cart-row">
          <div style="flex:1; min-width:0;">
            <div class="cname"></div>
            <div class="cprice"></div>
          </div>
          <button class="discount-btn" title="${t('discount_btn')}">🏷</button>
          <button class="qty-btn minus">-</button>
          <span class="qty-val"></span>
          <button class="qty-btn plus">+</button>
          <button class="remove-btn"></button>
        </div>
        <div class="discount-edit-row">
          <input type="text" inputmode="decimal" class="disc-input">
          <button class="disc-apply"></button>
          <button class="disc-cancel">✕</button>
        </div>
      `;
      entryWrap.querySelector(".cname").textContent = entry.product.name;
      const cpriceEl = entryWrap.querySelector(".cprice");
      if (discounted) {
        cpriceEl.innerHTML = `<span class="old-price"></span><span class="new-price"></span>`;
        cpriceEl.querySelector(".old-price").textContent = fmtMoney(entry.product.price) + " " + t("currency");
        cpriceEl.querySelector(".new-price").textContent = fmtMoney(entry.price) + " " + t("currency") + " / " + entry.product.unit;
      } else {
        cpriceEl.textContent = fmtMoney(entry.price) + " " + t("currency") + " / " + entry.product.unit;
      }
      entryWrap.querySelector(".qty-val").textContent = entry.qty + " " + entry.product.unit;
      entryWrap.querySelector(".remove-btn").textContent = t("remove");
      entryWrap.querySelector(".disc-apply").textContent = t("discount_apply");
      entryWrap.querySelector(".minus").addEventListener("click", () => {
        entry.qty -= 1;
        if (entry.qty <= 0) { delete cart[entry.product.id]; }
        renderCartModal(); updateCartBar();
      });
      entryWrap.querySelector(".plus").addEventListener("click", () => {
        if (entry.qty + 1 <= entry.product.qty) { entry.qty += 1; }
        renderCartModal(); updateCartBar();
      });
      entryWrap.querySelector(".remove-btn").addEventListener("click", () => {
        delete cart[entry.product.id];
        renderCartModal(); updateCartBar();
      });
      // MUHIM (foydalanuvchi so'rovi bilan): kompyuterdagi savatdagi
      // "Narxni pasaytirish (chegirma)" imkoniyati -- bosilganda shu
      // qatorning O'ZIDA narx tahrirlash maydoni ochiladi (alohida oyna
      // emas), yangi narx faqat shu sotuvga tegishli bo'ladi.
      const discEditRow = entryWrap.querySelector(".discount-edit-row");
      const discInput = entryWrap.querySelector(".disc-input");
      entryWrap.querySelector(".discount-btn").addEventListener("click", () => {
        discInput.value = String(entry.price);
        discInput.style.borderColor = "";
        discEditRow.style.display = discEditRow.style.display === "flex" ? "none" : "flex";
        if (discEditRow.style.display === "flex") { discInput.focus(); discInput.select(); }
      });
      entryWrap.querySelector(".disc-cancel").addEventListener("click", () => {
        discEditRow.style.display = "none";
      });
      entryWrap.querySelector(".disc-apply").addEventListener("click", () => {
        const val = parseFloat(discInput.value);
        if (isNaN(val) || val <= 0) {
          discInput.style.borderColor = "#d33";
          return;
        }
        entry.price = val;
        renderCartModal(); updateCartBar();
      });
      cartItemsEl.appendChild(entryWrap);
    }
    cartTotalFullEl.textContent = fmtMoney(cartTotal()) + " " + t("currency");
  }

  cartBar.addEventListener("click", () => {
    if (!cartList().length) return;
    saleMsg.textContent = "";
    renderCartModal();
    cartModal.style.display = "flex";
  });

  closeCartBtn.addEventListener("click", () => { cartModal.style.display = "none"; });

  const clearCartBtn = document.getElementById("clear-cart-btn");
  clearCartBtn.addEventListener("click", () => {
    cart = {};
    renderCartModal();
    updateCartBar();
    cartModal.style.display = "none";
  });

  for (const btn of payButtons) {
    btn.addEventListener("click", () => {
      for (const b of payButtons) b.classList.remove("active");
      btn.classList.add("active");
      if (btn.id === "pay-nasiya") {
        paymentType = "nasiya";
        paymentLabel = null;
        nasiyaFields.style.display = "block";
        // MUHIM (foydalanuvchi so'rovi bilan): "Qisman to'lov" alohida
        // tugma emas -- "Nasiya" tanlanganda "Hozir to'lanadigan summa"
        // maydoni ham shu bilan birga ko'rinadi. 0 qoldirilsa, xuddi
        // ilgarigidek hammasi qarzga yoziladi.
        paidNowInput.value = "";
        ensureCustomersLoaded();
      } else {
        paymentType = "naqd";
        paymentLabel = btn.dataset.label || t("pay_naqd");
        nasiyaFields.style.display = "none";
        paidNowInput.value = "";
      }
    });
  }

  checkoutBtn.addEventListener("click", async () => {
    const entries = cartList();
    if (!entries.length) return;
    let customerName = "";
    let phone = "";
    let paidNow = 0;
    if (paymentType === "nasiya") {
      customerName = document.getElementById("customer-name").value.trim();
      phone = document.getElementById("customer-phone").value.trim();
      if (!customerName) {
        saleMsg.textContent = t("nasiya_name_required");
        return;
      }
      // MUHIM (foydalanuvchi so'rovi bilan): maydon bo'sh qoldirilsa,
      // 0 deb hisoblanadi -- ya'ni ilgarigidek hammasi qarzga yoziladi.
      const rawPaidNow = (paidNowInput.value || "").trim();
      paidNow = rawPaidNow === "" ? 0 : parseFloat(rawPaidNow);
      if (!(paidNow >= 0) || paidNow > cartTotal() + 1e-9) {
        saleMsg.textContent = t("paid_now_invalid");
        return;
      }
    }
    checkoutBtn.disabled = true;
    saleMsg.textContent = t("sending");
    try {
      const resp = await fetch("/api/sale", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData,
          items: entries.map(e => ({ id: e.product.id, qty: e.qty, price: (e.price != null ? e.price : e.product.price) })),
          payment_type: paymentType,
          method_label: paymentLabel,
          customer_name: customerName,
          phone: phone,
          paid_now: paidNow,
          print_receipt: !!printReceiptCheck.checked,
          printer_name: printReceiptCheck.checked ? (receiptPrinterSelect.value || null) : null,
          copies: printReceiptCheck.checked ? (parseInt(document.getElementById("receipt-copies").value, 10) || 1) : 1,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        saleMsg.textContent = data.message || t("error_generic");
        checkoutBtn.disabled = false;
        return;
      }
      let msg = t("sold_prefix") + " " + fmtMoney(data.total) + " " + t("currency");
      if (printReceiptCheck.checked) {
        msg += data.print_ok ? " " + t("receipt_printed") : " " + t("receipt_not_printed") + " " + (data.print_error || t("unknown_error")) + ")";
      }
      saleMsg.textContent = msg;
      if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred("success"); }
      cart = {};
      updateCartBar();
      setTimeout(() => { cartModal.style.display = "none"; }, 1600);
      loadProducts(input.value);
    } catch (e) {
      saleMsg.textContent = t("error_connection");
    } finally {
      checkoutBtn.disabled = false;
    }
  });

  let debounceTimer = null;
  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => loadProducts(input.value), 250);
  });

  // --- Add product ------------------------------------------------------
  const barcodeResultEl = document.getElementById("barcode-result");
  let lastCreatedBarcode = null;

  // --- Yorliq yozuvlari o'lchamlari (slayderlar) ---------------------
  const apNameSize = document.getElementById("ap-name-size");
  const apPriceSize = document.getElementById("ap-price-size");
  const apBarcodeScale = document.getElementById("ap-barcode-scale");
  const apNameSizeVal = document.getElementById("ap-name-size-val");
  const apPriceSizeVal = document.getElementById("ap-price-size-val");
  const apBarcodeScaleVal = document.getElementById("ap-barcode-scale-val");
  apNameSize.addEventListener("input", () => { apNameSizeVal.textContent = apNameSize.value; });
  apPriceSize.addEventListener("input", () => { apPriceSizeVal.textContent = apPriceSize.value; });
  apBarcodeScale.addEventListener("input", () => { apBarcodeScaleVal.textContent = apBarcodeScale.value; });

  // MUHIM: "Mahsulot qo'shish" sahifasi ochilganda, OXIRGI ishlatilgan
  // yorliq o'lchamlari (kompyuterdagi bilan bir xil sozlama) va oxirgi
  // dollar kursi bir marta yuklab olinadi -- shu orqali razmer HAR SAFAR
  // standart qiymatga (23/25/100) qaytib qolmaydi.
  let barcodeSettingsLoaded = false;
  async function ensureBarcodeSettingsLoaded() {
    if (barcodeSettingsLoaded) return;
    try {
      const url = "/api/barcode/settings?initData=" + encodeURIComponent(initData || "");
      const resp = await fetch(url);
      const data = await resp.json();
      if (resp.ok && !data.error) {
        barcodeSettingsLoaded = true;
        if (data.name_font_size) {
          apNameSize.value = data.name_font_size;
          apNameSizeVal.textContent = data.name_font_size;
        }
        if (data.price_font_size) {
          apPriceSize.value = data.price_font_size;
          apPriceSizeVal.textContent = data.price_font_size;
        }
        if (data.barcode_scale) {
          apBarcodeScale.value = data.barcode_scale;
          apBarcodeScaleVal.textContent = data.barcode_scale;
        }
        if (data.last_usd_rate) {
          const rateEl = document.getElementById("ap-usd-rate");
          if (rateEl && !rateEl.value) rateEl.value = data.last_usd_rate;
        }
      }
    } catch (e) { /* ixtiyoriy -- xato bo'lsa standart qiymatlar qoladi */ }
  }

  // --- Dollardan so'mga avtomatik hisoblash (tan narxi uchun) ------------
  document.getElementById("ap-usd-apply").addEventListener("click", async () => {
    const usdEl = document.getElementById("ap-usd-cost");
    const rateEl = document.getElementById("ap-usd-rate");
    const usdAmount = parseFloat(usdEl.value);
    const rate = parseFloat(rateEl.value);
    if (isNaN(usdAmount) || isNaN(rate)) {
      alert(t("ap_usd_fill_first"));
      return;
    }
    if (usdAmount <= 0 || rate <= 0) {
      alert(t("ap_positive_required"));
      return;
    }
    const costSom = Math.round(usdAmount * rate);
    document.getElementById("ap-cost").value = costSom;
    try {
      await fetch("/api/usd_rate/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData, rate }),
      });
    } catch (e) { /* ixtiyoriy */ }
    if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred("success"); }
  });

  // --- Foyda foizi bo'yicha sotish narxini avtomatik hisoblash -----------
  document.getElementById("ap-markup-apply").addEventListener("click", () => {
    const msgEl = document.getElementById("ap-markup-msg");
    const costPrice = parseFloat(document.getElementById("ap-cost").value);
    const pct = parseFloat(document.getElementById("ap-markup").value);
    if (isNaN(costPrice) || costPrice <= 0) {
      msgEl.textContent = t("ap_cost_first");
      return;
    }
    if (isNaN(pct)) {
      msgEl.textContent = t("ap_cost_first");
      return;
    }
    const rawPrice = costPrice * (1 + pct / 100.0);
    // MUHIM O'ZGARISH (foydalanuvchi so'rovi bilan): endi eng yaqin 500
    // so'mgacha, HAR DOIM YUQORIGA qarab yaxlitlanadi (masalan 32167 ->
    // 32500, 32523 -> 33000) -- kompyuterdagi bilan bir xil.
    const newPrice = Math.ceil(rawPrice / 500.0) * 500;
    document.getElementById("ap-price").value = newPrice;
    const rawRounded = Math.round(rawPrice);
    // MUHIM (foydalanuvchi so'rovi bilan): endi HAR DOIM ikkalasi ham
    // ko'rsatiladi -- avval AYNAN hisoblangan (yaxlitlanmagan) summa,
    // keyin 1000 so'mgacha yaxlitlangan summa -- ular teng bo'lsa ham.
    msgEl.textContent = t("ap_price_calc_rounded")
      .replace("{raw}", fmtMoney(rawRounded)).replace("{price}", fmtMoney(newPrice)).replace("{pct}", pct);
    if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred("success"); }
  });

  // MUHIM (foydalanuvchi so'rovi bilan): mahsulot rasmini tanlanganda
  // (kamera yoki galereyadan) darhol oldindan ko'rish (preview) uchun,
  // va yuborishdan oldin base64'ga aylantirish uchun umumiy yordamchi.
  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }
  const apImageInput = document.getElementById("ap-image-input");
  const apImagePreview = document.getElementById("ap-image-preview");
  let apImageDataUrl = null;
  if (apImageInput) {
    apImageInput.addEventListener("change", async () => {
      const file = apImageInput.files && apImageInput.files[0];
      if (!file) { apImageDataUrl = null; apImagePreview.style.display = "none"; return; }
      apImageDataUrl = await fileToBase64(file);
      apImagePreview.src = apImageDataUrl;
      apImagePreview.style.display = "block";
    });
  }

  document.getElementById("ap-submit").addEventListener("click", async () => {
    const name = document.getElementById("ap-name").value.trim();
    const cost = document.getElementById("ap-cost").value;
    const price = document.getElementById("ap-price").value;
    const qty = document.getElementById("ap-qty").value;
    const unit = document.getElementById("ap-unit").value;
    const barcode = document.getElementById("ap-barcode").value.trim();
    const nameFontSize = parseInt(apNameSize.value, 10);
    const priceFontSize = parseInt(apPriceSize.value, 10);
    const barcodeScale = parseInt(apBarcodeScale.value, 10);
    const msgEl = document.getElementById("add-product-msg");
    barcodeResultEl.innerHTML = "";
    if (!name || !price) {
      msgEl.textContent = t("ap_name") + " / " + t("ap_price");
      return;
    }
    const apAiBgCheck = document.getElementById("ap-ai-bg-check");
    const aiRemoveBg = !!(apAiBgCheck && apAiBgCheck.checked && apImageDataUrl);
    // MUHIM: AI fon olib tashlash birinchi marta bir necha o'nlab
    // soniya davom etishi mumkin (model internetdan yuklanadi) --
    // foydalanuvchiga shuni ogohlantiramiz, aks holda "osilib qoldi"
    // deb o'ylashi mumkin.
    msgEl.textContent = aiRemoveBg ? t("ap_ai_bg_processing") : t("sending");
    try {
      const resp = await fetch("/api/product/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData, name, cost_price: cost || 0, price, qty: qty || 0, unit, barcode,
          name_font_size: nameFontSize, price_font_size: priceFontSize, barcode_scale: barcodeScale,
          image_base64: apImageDataUrl || null, ai_remove_bg: aiRemoveBg,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        msgEl.textContent = data.message || t("error_generic");
        return;
      }
      // MUHIM: mahsulot muvaffaqiyatli qo'shilgach, keyingi mahsulot
      // uchun eski rasm/preview qolib ketmasligi kerak.
      apImageDataUrl = null;
      if (apImageInput) { apImageInput.value = ""; }
      if (apImagePreview) { apImagePreview.style.display = "none"; }
      if (apAiBgCheck) { apAiBgCheck.checked = false; }
      msgEl.textContent = t("ap_added_ok") + " " + data.barcode;
      lastCreatedBarcode = { code: data.barcode, name, price, nameFontSize, priceFontSize, barcodeScale };
      let html = `<img id="ap-barcode-img" src="${data.barcode_image_base64 ? 'data:image/png;base64,' + data.barcode_image_base64 : ''}">`;
      html += `
        <div class="section-title">${t("ap_label_size_title")}</div>
        <button class="primary-btn" id="ap-refresh-preview">${t("ap_refresh_preview")}</button>
        <div id="ap-refresh-msg" style="text-align:center; font-size:13px; margin-top:6px;"></div>
        <div class="field" style="margin-top:12px;">
          <label>${t("ap_printer_label")}</label>
          <select id="ap-printer-select"></select>
        </div>
        <div class="field">
          <label>${t("ap_copies_label")}</label>
          <input id="ap-copies" type="number" inputmode="numeric" min="1" max="50" value="1">
        </div>
        <button class="primary-btn" id="ap-print-barcode">${t("ap_print_barcode")}</button>
        <div id="ap-print-msg" style="text-align:center; font-size:13px; margin-top:6px;"></div>
      `;
      barcodeResultEl.innerHTML = html;
      printersLoaded = false;
      await ensurePrintersLoaded();
      document.getElementById("ap-refresh-preview").addEventListener("click", async () => {
        const refreshMsgEl = document.getElementById("ap-refresh-msg");
        lastCreatedBarcode.nameFontSize = parseInt(apNameSize.value, 10);
        lastCreatedBarcode.priceFontSize = parseInt(apPriceSize.value, 10);
        lastCreatedBarcode.barcodeScale = parseInt(apBarcodeScale.value, 10);
        refreshMsgEl.textContent = t("loading");
        try {
          const r = await fetch("/api/barcode/preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              initData, barcode: lastCreatedBarcode.code, name: lastCreatedBarcode.name,
              price: lastCreatedBarcode.price,
              name_font_size: lastCreatedBarcode.nameFontSize,
              price_font_size: lastCreatedBarcode.priceFontSize,
              barcode_scale: lastCreatedBarcode.barcodeScale,
            }),
          });
          const rd = await r.json();
          if (!r.ok || rd.error) {
            refreshMsgEl.textContent = rd.message || t("error_generic");
            return;
          }
          document.getElementById("ap-barcode-img").src = "data:image/png;base64," + rd.barcode_image_base64;
          refreshMsgEl.textContent = t("ap_refresh_ok");
        } catch (e) {
          refreshMsgEl.textContent = t("error_connection");
        }
      });
      document.getElementById("ap-print-barcode").addEventListener("click", async () => {
        const printMsgEl = document.getElementById("ap-print-msg");
        const printerSel = document.getElementById("ap-printer-select");
        const copiesEl = document.getElementById("ap-copies");
        printMsgEl.textContent = t("sending");
        try {
          const r = await fetch("/api/barcode/print", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              initData, barcode: lastCreatedBarcode.code, name: lastCreatedBarcode.name,
              price: lastCreatedBarcode.price, printer_name: printerSel.value || null,
              name_font_size: lastCreatedBarcode.nameFontSize,
              price_font_size: lastCreatedBarcode.priceFontSize,
              barcode_scale: lastCreatedBarcode.barcodeScale,
              copies: parseInt(copiesEl.value, 10) || 1,
            }),
          });
          const rd = await r.json();
          printMsgEl.textContent = rd.ok ? t("ap_print_ok") : (t("ap_print_err") + ": " + (rd.message || t("unknown_error")));
        } catch (e) {
          printMsgEl.textContent = t("error_connection");
        }
      });
      document.getElementById("ap-name").value = "";
      document.getElementById("ap-cost").value = "";
      document.getElementById("ap-price").value = "";
      document.getElementById("ap-qty").value = "";
      document.getElementById("ap-barcode").value = "";
      if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred("success"); }
    } catch (e) {
      msgEl.textContent = t("error_connection");
    }
  });

  // --- Reports -----------------------------------------------------------
  const now = new Date();
  const MONTH_NAMES = {
    uz: ["Yanvar","Fevral","Mart","Aprel","May","Iyun","Iyul","Avgust","Sentabr","Oktabr","Noyabr","Dekabr"],
    en: ["January","February","March","April","May","June","July","August","September","October","November","December"],
    ru: ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"],
  };
  function monthNames() { return MONTH_NAMES[curLang] || MONTH_NAMES.uz; }
  let currentReportPeriod = "today";

  const repTodayBtn = document.getElementById("rep-today");
  const repLast30Btn = document.getElementById("rep-last30");
  const repMonthCurrentBtn = document.getElementById("rep-month-current");
  const monthPicker = document.getElementById("rep-month-picker");
  const quickButtons = [repTodayBtn, repLast30Btn, repMonthCurrentBtn];

  const currentMonthKey = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0");
  repMonthCurrentBtn.dataset.period = currentMonthKey;

  // MUHIM: oy nomlari (joriy oy tugmasi + tanlov ro'yxati) tanlangan tilga
  // qarab qayta chiziladi -- applyI18n() chaqirilganda ham qayta ishga
  // tushiriladi (pastga qarang).
  function renderMonthPicker() {
    repMonthCurrentBtn.textContent = t("rep_this_month") + " (" + monthNames()[now.getMonth()] + ")";
    monthPicker.innerHTML = "";
    const blankOpt = document.createElement("option");
    blankOpt.value = ""; blankOpt.textContent = t("rep_pick_month") + "...";
    monthPicker.appendChild(blankOpt);
    for (let i = 1; i <= 12; i++) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const key = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = monthNames()[d.getMonth()] + " " + d.getFullYear();
      if (key === currentReportPeriod) opt.selected = true;
      monthPicker.appendChild(opt);
    }
  }
  renderMonthPicker();
  monthPicker.addEventListener("change", () => {
    if (!monthPicker.value) return;
    for (const b of quickButtons) b.classList.remove("active");
    currentReportPeriod = monthPicker.value;
    loadReports(currentReportPeriod);
  });

  function selectQuickPeriod(btn) {
    for (const b of quickButtons) b.classList.remove("active");
    btn.classList.add("active");
    monthPicker.value = "";
    currentReportPeriod = btn.dataset.period;
    loadReports(currentReportPeriod);
  }
  repTodayBtn.addEventListener("click", () => selectQuickPeriod(repTodayBtn));
  repLast30Btn.addEventListener("click", () => selectQuickPeriod(repLast30Btn));
  repMonthCurrentBtn.addEventListener("click", () => selectQuickPeriod(repMonthCurrentBtn));

  const detailModal = document.getElementById("detail-modal");
  const detailTitle = document.getElementById("detail-title");
  const detailContent = document.getElementById("detail-content");
  const detailCloseBtn = document.getElementById("detail-close-btn");
  detailCloseBtn.addEventListener("click", () => { detailModal.style.display = "none"; });

  function openDetail(title, html) {
    detailTitle.textContent = title;
    detailContent.innerHTML = html;
    detailModal.style.display = "flex";
  }

  // --- Mahsulotni tahrirlash/o'chirish (faqat can_manage_products) -------
  const editProductModal = document.getElementById("edit-product-modal");
  const epName = document.getElementById("ep-name");
  const epCost = document.getElementById("ep-cost");
  const epPrice = document.getElementById("ep-price");
  const epQty = document.getElementById("ep-qty");
  const epUnit = document.getElementById("ep-unit");
  const epBarcode = document.getElementById("ep-barcode");
  const epMsg = document.getElementById("ep-msg");
  let editingProductId = null;

  const epBcPrinter = document.getElementById("ep-bc-printer");
  const epBcCopies = document.getElementById("ep-bc-copies");
  const epBcMsg = document.getElementById("ep-bc-msg");
  const epBcNameSize = document.getElementById("ep-bc-name-size");
  const epBcPriceSize = document.getElementById("ep-bc-price-size");
  const epBcScale = document.getElementById("ep-bc-scale");
  const epBcNameSizeVal = document.getElementById("ep-bc-name-size-val");
  const epBcPriceSizeVal = document.getElementById("ep-bc-price-size-val");
  const epBcScaleVal = document.getElementById("ep-bc-scale-val");
  epBcNameSize.addEventListener("input", () => { epBcNameSizeVal.textContent = epBcNameSize.value; });
  epBcPriceSize.addEventListener("input", () => { epBcPriceSizeVal.textContent = epBcPriceSize.value; });
  epBcScale.addEventListener("input", () => { epBcScaleVal.textContent = epBcScale.value; });

  // MUHIM (foydalanuvchi so'rovi bilan): mahsulotni tahrirlash oynasida
  // rasm bilan ishlash uchun holat -- yangi tanlangan rasm (base64) va
  // "rasmni olib tashlash" belgisi.
  const epImageInput = document.getElementById("ep-image-input");
  const epImagePreview = document.getElementById("ep-image-preview");
  const epImageRemoveBtn = document.getElementById("ep-image-remove-btn");
  const epAiBgCheck = document.getElementById("ep-ai-bg-check");
  let epImageDataUrl = null;
  let epImageRemove = false;
  if (epImageInput) {
    epImageInput.addEventListener("change", async () => {
      const file = epImageInput.files && epImageInput.files[0];
      if (!file) return;
      epImageDataUrl = await fileToBase64(file);
      epImageRemove = false;
      epImagePreview.src = epImageDataUrl;
      epImagePreview.style.display = "block";
      epImageRemoveBtn.style.display = "inline-block";
    });
  }
  if (epImageRemoveBtn) {
    epImageRemoveBtn.addEventListener("click", () => {
      epImageDataUrl = null;
      epImageRemove = true;
      if (epImageInput) { epImageInput.value = ""; }
      epImagePreview.style.display = "none";
      epImagePreview.src = "";
      epImageRemoveBtn.style.display = "none";
    });
  }

  async function openEditProductModal(product) {
    editingProductId = product.id;
    epName.value = product.name || "";
    epCost.value = product.cost_price != null ? product.cost_price : "";
    epPrice.value = product.price != null ? product.price : "";
    epQty.value = product.qty != null ? product.qty : "";
    epUnit.value = product.unit || "dona";
    epBarcode.value = product.barcode || "";
    epMsg.textContent = "";
    epBcMsg.textContent = "";
    epBcCopies.value = "1";
    // MUHIM: rasm holatini har safar oynani ochganda tozalab, mahsulotning
    // O'ZIDA saqlangan rasmini (bo'lsa) ko'rsatamiz.
    epImageDataUrl = null;
    epImageRemove = false;
    if (epImageInput) { epImageInput.value = ""; }
    if (epAiBgCheck) { epAiBgCheck.checked = false; }
    if (product.image_url) {
      epImagePreview.src = product.image_url + (product.image_url.includes("?") ? "&" : "?") + "initData=" + encodeURIComponent(initData || "");
      epImagePreview.style.display = "block";
      epImageRemoveBtn.style.display = "inline-block";
    } else {
      epImagePreview.style.display = "none";
      epImagePreview.src = "";
      epImageRemoveBtn.style.display = "none";
    }
    // MUHIM (foydalanuvchi so'rovi bilan): o'lcham slayderlari bu oynada
    // KO'RINADIGAN qilib qo'yildi -- ochilganda oxirgi ESLAB QOLINGAN
    // (barcha joyda umumiy) o'lchamlar bilan boshlanadi (get_webapp_
    // barcode_settings orqali), shundan keyin foydalanuvchi bu yerda
    // mustaqil o'zgartirishi mumkin.
    await ensureBarcodeSettingsLoaded();
    epBcNameSize.value = apNameSize.value; epBcNameSizeVal.textContent = apNameSize.value;
    epBcPriceSize.value = apPriceSize.value; epBcPriceSizeVal.textContent = apPriceSize.value;
    epBcScale.value = apBarcodeScale.value; epBcScaleVal.textContent = apBarcodeScale.value;
    // MUHIM: shtrix kod chop etish uchun printerlar ro'yxati -- ilgari
    // "Mahsulot qo'shish" sahifasi ochilganda yuklangan bo'lishi mumkin
    // (ensurePrintersLoaded() bir marta ishlaydi, keyin natijani eslab
    // qoladi), shuning uchun bu yerda faqat select'ni to'ldiramiz.
    await ensurePrintersLoaded();
    populatePrinterSelect(epBcPrinter, lastBarcodePrinterDefault);
    editProductModal.style.display = "flex";
  }

  document.getElementById("ep-close-btn").addEventListener("click", () => {
    editProductModal.style.display = "none";
  });

  document.getElementById("ep-save-btn").addEventListener("click", async () => {
    if (!editingProductId) return;
    const epAiRemoveBg = !!(epAiBgCheck && epAiBgCheck.checked && epImageDataUrl);
    epMsg.textContent = epAiRemoveBg ? t("ap_ai_bg_processing") : t("sending");
    try {
      const resp = await fetch("/api/product/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData, id: editingProductId, name: epName.value.trim(),
          cost_price: epCost.value || 0, price: epPrice.value, qty: epQty.value || 0,
          unit: epUnit.value, barcode: epBarcode.value.trim(),
          image_base64: epImageDataUrl || null, remove_image: epImageRemove,
          ai_remove_bg: epAiRemoveBg,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        epMsg.textContent = data.message || t("error_generic");
        return;
      }
      epMsg.textContent = t("product_updated");
      if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred("success"); }
      loadProducts(input.value);
      setTimeout(() => { editProductModal.style.display = "none"; }, 900);
    } catch (e) {
      epMsg.textContent = t("error_connection");
    }
  });

  document.getElementById("ep-delete-btn").addEventListener("click", async () => {
    if (!editingProductId) return;
    if (!confirm(t("confirm_delete_product").replace("{name}", epName.value))) return;
    epMsg.textContent = t("sending");
    try {
      const resp = await fetch("/api/product/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData, id: editingProductId }),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        epMsg.textContent = data.message || t("error_generic");
        return;
      }
      epMsg.textContent = t("product_deleted");
      if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred("success"); }
      // MUHIM: mahsulot bazadan o'chirilganda, agar u ALLAQACHON savatga
      // qo'shilgan bo'lsa, savatdan ham darhol olib tashlanadi -- aks
      // holda savatda mavjud bo'lmagan mahsulot "osilib" qolar edi.
      if (cart[editingProductId]) {
        delete cart[editingProductId];
        updateCartBar();
      }
      loadProducts(input.value);
      setTimeout(() => { editProductModal.style.display = "none"; }, 900);
    } catch (e) {
      epMsg.textContent = t("error_connection");
    }
  });

  document.getElementById("ep-bc-print-btn").addEventListener("click", async () => {
    if (!editingProductId) return;
    const code = epBarcode.value.trim();
    if (!code) {
      epBcMsg.textContent = t("ep_barcode_missing");
      return;
    }
    epBcMsg.textContent = t("sending");
    try {
      const resp = await fetch("/api/barcode/print", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData, barcode: code, name: epName.value.trim(), price: epPrice.value,
          printer_name: epBcPrinter.value || null,
          name_font_size: parseInt(epBcNameSize.value, 10),
          price_font_size: parseInt(epBcPriceSize.value, 10),
          barcode_scale: parseInt(epBcScale.value, 10),
          copies: parseInt(epBcCopies.value, 10) || 1,
        }),
      });
      const data = await resp.json();
      epBcMsg.textContent = data.ok ? t("ap_print_ok") : (t("ap_print_err") + ": " + (data.message || t("unknown_error")));
      if (data.ok) {
        lastBarcodePrinterDefault = epBcPrinter.value || lastBarcodePrinterDefault;
        if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred("success"); }
      }
    } catch (e) {
      epBcMsg.textContent = t("error_connection");
    }
  });

  async function deleteWebappSale(saleId, rowEl) {
    if (!confirm(t("confirm_delete_sale"))) return;
    try {
      const resp = await fetch("/api/sale/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData, sale_id: saleId }),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        alert(data.message || t("delete_sale_err"));
        return;
      }
      detailModal.style.display = "none";
      if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred("success"); }
      loadReports(currentReportPeriod);
    } catch (e) {
      alert(t("error_connection"));
    }
  }

  async function loadReports(period) {
    const contentEl = document.getElementById("reports-content");
    const histEl = document.getElementById("history-content");
    const debtorsEl = document.getElementById("debtors-content");
    const closuresEl = document.getElementById("closures-content");
    const topProductsEl = document.getElementById("top-products-content");
    contentEl.innerHTML = t("loading");
    try {
      const url = "/api/reports?period=" + encodeURIComponent(period) +
                  "&initData=" + encodeURIComponent(initData || "");
      const resp = await fetch(url);
      const data = await resp.json();
      if (!resp.ok || data.error) {
        contentEl.textContent = data.message || t("error_generic");
        return;
      }
      const cur = t("currency");
      contentEl.innerHTML = `
        <div class="stat-card"><span class="label">${t("stat_total_sum")}</span><span class="value">${fmtMoney(data.total_sum)} ${cur}</span></div>
        <div class="stat-card"><span class="label">${t("stat_profit")}</span><span class="value">${fmtMoney(data.total_profit)} ${cur}</span></div>
        <div class="stat-card"><span class="label">${t("stat_sale_count")}</span><span class="value">${data.sale_count}</span></div>
        <div class="stat-card"><span class="label">${t("stat_nasiya_profit")}</span><span class="value">${fmtMoney(data.nasiya_profit)} ${cur}</span></div>
        <div class="stat-card"><span class="label">${t("stat_nasiya_sum")}</span><span class="value">${fmtMoney(data.nasiya_sum)} ${cur}</span></div>
        <div class="stat-card"><span class="label">${t("stat_unpaid_debt")}</span><span class="value">${fmtMoney(data.unpaid_debt_total)} ${cur}</span></div>
        <div class="stat-card"><span class="label">${t("stat_warehouse_value")}</span><span class="value">${fmtMoney(data.warehouse_value)} ${cur}</span></div>
      `;

      topProductsEl.innerHTML = "";
      if (data.top_products && data.top_products.length) {
        for (const p of data.top_products) {
          topProductsEl.innerHTML += `<div class="hist-row"><span class="hname">${p.name}</span><span class="hmeta">${p.qty} ${p.unit} — ${fmtMoney(p.total)} ${cur}</span></div>`;
        }
      } else {
        topProductsEl.innerHTML = `<div style="opacity:0.6; font-size:13px;">${t("no_sales_period")}</div>`;
      }

      histEl.innerHTML = "";
      // MUHIM (foydalanuvchi so'rovi bilan): sahifa har safar qayta
      // yuklanganda avvalgi tanlov (checkbox holati) tozalanadi, chunki
      // yangi ro'yxatdagi qatorlar boshqa elementlar bo'ladi.
      clearReceiptSelection();
      for (const s of (data.recent_sales || [])) {
        const row = document.createElement("div");
        row.className = "hist-row";
        // MUHIM (foydalanuvchi so'rovi bilan): bir nechta mahsulotni
        // birgalikda tanlab, ularni BITTA yangi chekka birlashtirib chop
        // etish uchun har bir qatorga checkbox qo'shildi (faqat savdo
        // qilish huquqi bo'lganlarga ko'rinadi).
        const checkboxHtml = canSell ? `<input type="checkbox" class="hsel">` : "";
        row.innerHTML = `${checkboxHtml}<span class="hname"></span><span class="hmeta"></span>`;
        row.querySelector(".hname").textContent = s.name + " (" + s.qty + " " + s.unit + ")";
        row.querySelector(".hmeta").textContent = fmtMoney(s.total) + " " + cur + " — " + (s.payment_method || s.payment_type);
        row.style.cursor = "pointer";
        const selCheckbox = row.querySelector(".hsel");
        if (selCheckbox) {
          selCheckbox.addEventListener("click", (e) => e.stopPropagation());
          selCheckbox.addEventListener("change", () => {
            if (selCheckbox.checked) {
              selectedReceiptItems.set(s.id, {
                name: s.name, qty: s.qty, unit: s.unit,
                price: (s.price != null ? s.price : (s.qty ? s.total / s.qty : s.total)),
                total: s.total,
              });
            } else {
              selectedReceiptItems.delete(s.id);
            }
            updateReceiptSelectBar();
          });
        }
        row.addEventListener("click", async () => {
          let html = `<div class="hist-row"><span class="hname">${s.name}</span><span class="hmeta">${s.qty} ${s.unit}</span></div>`;
          html += `<div class="hist-row"><span class="hname">${t("sum_label")}</span><span class="hmeta">${fmtMoney(s.total)} ${cur}</span></div>`;
          html += `<div class="hist-row"><span class="hname">${t("payment_type_label")}</span><span class="hmeta">${s.payment_method || s.payment_type}</span></div>`;
          html += `<div class="hist-row"><span class="hname">${t("time_label")}</span><span class="hmeta">${s.created_at || ""}</span></div>`;
          if (canSell) {
            // MUHIM: foydalanuvchi so'rovi bilan -- sotilgan mahsulot(lar)
            // uchun CHEKNI QAYTA CHOP ETISH imkoniyati (masalan, mijozga
            // chek qayta kerak bo'lsa yoki birinchi chop etish muvaffaqiyatsiz
            // bo'lgan bo'lsa).
            html += `<div class="section-title">${t("reprint_receipt_title")}</div>`;
            html += `<div class="field"><label>${t("ap_printer_label")}</label><select id="detail-reprint-printer"></select></div>`;
            html += `<div class="field"><label>${t("ap_copies_label")}</label><input id="detail-reprint-copies" type="number" inputmode="numeric" min="1" max="20" value="1"></div>`;
            html += `<button class="primary-btn" id="detail-reprint-btn">${t("reprint_receipt_btn")}</button>`;
            html += `<div id="detail-reprint-msg" style="text-align:center; font-size:13px; margin-top:6px;"></div>`;
            html += `<button class="primary-btn" id="detail-delete-sale-btn" style="background:#d33; margin-top:12px;">${t("delete_sale_btn")}</button>`;
          }
          openDetail(t("sale_detail_title"), html);
          const delBtn = document.getElementById("detail-delete-sale-btn");
          if (delBtn) { delBtn.addEventListener("click", () => deleteWebappSale(s.id, row)); }
          const reprintBtn = document.getElementById("detail-reprint-btn");
          if (reprintBtn) {
            await ensurePrintersLoaded();
            const printerSel = document.getElementById("detail-reprint-printer");
            populatePrinterSelect(printerSel, lastReceiptPrinterDefault);
            reprintBtn.addEventListener("click", async () => {
              const msgEl = document.getElementById("detail-reprint-msg");
              const copiesEl = document.getElementById("detail-reprint-copies");
              msgEl.textContent = t("sending");
              try {
                const r = await fetch("/api/receipt/reprint", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    initData, sale_batch: s.sale_batch,
                    printer_name: printerSel.value || null,
                    copies: parseInt(copiesEl.value, 10) || 1,
                  }),
                });
                const rd = await r.json();
                msgEl.textContent = rd.ok ? t("ap_print_ok") : (t("ap_print_err") + ": " + (rd.message || t("unknown_error")));
                if (rd.ok) {
                  lastReceiptPrinterDefault = printerSel.value || lastReceiptPrinterDefault;
                  if (tg && tg.HapticFeedback) { tg.HapticFeedback.notificationOccurred("success"); }
                }
              } catch (e) {
                msgEl.textContent = t("error_connection");
              }
            });
          }
        });
        histEl.appendChild(row);
      }
      if (!data.recent_sales || !data.recent_sales.length) {
        histEl.innerHTML = `<div style="opacity:0.6; font-size:13px;">${t("no_sales_period")}</div>`;
      }

      debtorsEl.innerHTML = "";
      if (data.debtors && data.debtors.length) {
        for (const d of data.debtors) {
          const row = document.createElement("div");
          row.className = "hist-row";
          row.innerHTML = `<span class="hname"></span><span class="hmeta"></span>`;
          row.querySelector(".hname").textContent = d.customer_name + (d.phone ? " (" + d.phone + ")" : "");
          row.querySelector(".hmeta").textContent = fmtMoney(d.amount) + " " + cur + " — " + d.date;
          row.style.cursor = "pointer";
          row.addEventListener("click", () => {
            let html = `<div class="hist-row"><span class="hname">${d.customer_name}</span><span class="hmeta">${fmtMoney(d.amount)} ${cur}</span></div>`;
            if (d.phone) { html += `<div class="hist-row"><span class="hname">${t("phone_label")}</span><span class="hmeta">${d.phone}</span></div>`; }
            html += `<div class="section-title">${t("what_bought")}</div>`;
            if (d.items && d.items.length) {
              for (const it of d.items) {
                html += `<div class="hist-row"><span class="hname">${it.name}</span><span class="hmeta">${it.qty} ${it.unit}</span></div>`;
              }
            } else {
              html += `<div style="opacity:0.6; font-size:13px;">${t("no_product_info")}</div>`;
            }
            openDetail(t("debtor_detail_title"), html);
          });
          debtorsEl.appendChild(row);
        }
      } else {
        debtorsEl.innerHTML = `<div style="opacity:0.6; font-size:13px;">${t("no_debt")}</div>`;
      }

      closuresEl.innerHTML = "";
      if (data.day_closures && data.day_closures.length) {
        for (const c of data.day_closures) {
          const row = document.createElement("div");
          row.className = "hist-row";
          row.innerHTML = `<span class="hname"></span><span class="hmeta"></span>`;
          row.querySelector(".hname").textContent = c.date;
          row.querySelector(".hmeta").textContent = fmtMoney(c.total_sales) + " " + cur + " (" + t("stat_profit").toLowerCase() + " " + fmtMoney(c.total_profit) + ")";
          row.style.cursor = "pointer";
          row.addEventListener("click", () => {
            let html = `<div class="hist-row"><span class="hname">${t("naqd_sales")}</span><span class="hmeta">${fmtMoney(c.sales_naqd)} ${cur}</span></div>`;
            html += `<div class="hist-row"><span class="hname">${t("naqd_profit")}</span><span class="hmeta">${fmtMoney(c.profit_naqd)} ${cur}</span></div>`;
            html += `<div class="hist-row"><span class="hname">${t("nasiya_sales")}</span><span class="hmeta">${fmtMoney(c.sales_nasiya)} ${cur}</span></div>`;
            html += `<div class="hist-row"><span class="hname">${t("nasiya_profit_label")}</span><span class="hmeta">${fmtMoney(c.profit_nasiya)} ${cur}</span></div>`;
            html += `<div class="hist-row"><span class="hname">${t("total_label")}</span><span class="hmeta">${fmtMoney(c.total_sales)} ${cur} (${fmtMoney(c.total_profit)})</span></div>`;
            openDetail(c.date, html);
          });
          closuresEl.appendChild(row);
        }
      } else {
        closuresEl.innerHTML = `<div style="opacity:0.6; font-size:13px;">${t("no_closures")}</div>`;
      }
    } catch (e) {
      contentEl.textContent = t("error_connection");
    }
  }

  loadProducts("");
</script>
</body>
</html>

"""


def _miniapp_handler_factory():
    import http.server
    import urllib.parse
    import json as _json

    class Handler(http.server.BaseHTTPRequestHandler):
        # MUHIM TUZATISH: foydalanuvchi "bot sekin ishlayapti, mahsulotlar/
        # hisobotlar/sotuv ustiga bossam 3-4 soniya kutib keyin chiqadi"
        # deb shikoyat qildi. Sabablaridan biri -- standart
        # BaseHTTPRequestHandler HTTP/1.0 protokolida ishlaydi, ya'ni HAR
        # BIR so'rov (mahsulotlar ro'yxati, hisobot va h.k.) uchun ulanish
        # yopilib, KEYINGI so'rov uchun QAYTA yangi TCP+TLS ulanish
        # o'rnatiladi -- bu esa cloudflared tunnel orqali ishlaganda har
        # safar sezilarli kechikish (bir necha yuz millisekunddan
        # sekundlargacha) qo'shadi. "HTTP/1.1" (keep-alive) yoqilsa,
        # brauzer bitta ulanishni QAYTA-QAYTA ishlatadi, va Mini App ichida
        # ketma-ket qilinadigan so'rovlar SEZILARLI tezlashadi.
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass  # konsolni ifloslantirmaslik uchun jim turadi

        def _send_json(self, obj, status=200):
            body = _json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _resolve_user(self, init_data):
            """initData'ni tekshiradi va (tg_user, is_admin, approved_match, lang)
            qaytaradi -- tg_user None bo'lsa, initData yaroqsiz (ruxsatsiz so'rov)."""
            settings = load_settings()
            token = (settings.get("telegram_bot_token") or "").strip()
            # MUHIM TUZATISH: token bo'sh bo'lsa ham, _validate_webapp_init_data
            # albatta chaqiriladi -- chunki aynan o'sha funksiya ichida sabab
            # (_LAST_WEBAPP_AUTH_REASON) yoziladi. Ilgari "if token else None"
            # bilan bu funksiya CHAQIRILMASDAN o'tkazib yuborilar edi, shuning
            # uchun sababi hech qachon yozilmay, doim umumiy "Ruxsatsiz so'rov"
            # xabari chiqaverar edi.
            tg_user = _validate_webapp_init_data(token, init_data)
            if not tg_user:
                return None, False, None, "uz"
            cid = tg_user.get("id")
            admin_chat_id = (settings.get("telegram_admin_chat_id") or "").strip()
            is_admin = bool(admin_chat_id) and str(cid) == str(admin_chat_id)
            approved = settings.get("telegram_approved_users") or []
            match = next((u for u in approved if str(u.get("chat_id")) == str(cid)), None)
            # MUHIM: Mini App'ni ko'p tilli qilish uchun -- avval bot orqali
            # tanlangan til (match["language"]) ishlatiladi; agar bunday til
            # hali tanlanmagan bo'lsa (masalan admin -- u hech qachon
            # ro'yxatdan o'tmaydi), Telegram'ning o'zi yuborgan
            # "language_code" (foydalanuvchining Telegram ilovasidagi tili)
            # ga qaraladi -- shu orqali Mini App ochilganda til, chatdagi til
            # tanlanishini kutmasdan, darhol to'g'ri ko'rinadi.
            # MUHIM TUZATISH: ADMIN telegram_approved_users ro'yxatida
            # UMUMAN yo'q (u hech qachon ro'yxatdan o'tmaydi), shuning
            # uchun avvalgi kodda uning /til orqali tanlagan tili HECH
            # QACHON ishlatilmas, doim Telegram'ning o'z tiliga tushib
            # qolar edi. Endi, agar bu admin bo'lsa, avval uning ALOHIDA
            # saqlangan tilini ("telegram_admin_language") tekshiramiz.
            if is_admin:
                lang = settings.get("telegram_admin_language")
            else:
                lang = (match or {}).get("language")
            if not lang:
                tg_lang_code = (tg_user.get("language_code") or "").lower()
                lang = tg_lang_code if tg_lang_code in _TG_STRINGS else "uz"
            return tg_user, is_admin, match, lang

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in ("/webapp", "/webapp/", "/"):
                body = _MINIAPP_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/products":
                qs = dict(urllib.parse.parse_qsl(parsed.query))
                init_data = qs.get("initData", "")
                query = qs.get("q", "")
                tg_user, is_admin, match, lang = self._resolve_user(init_data)
                if not tg_user:
                    reason = _LAST_WEBAPP_AUTH_REASON or "Ruxsatsiz so'rov."
                    self._send_json({"error": "unauthorized", "message": reason}, 401)
                    return
                if not is_admin:
                    # MUHIM: do'kon egasi (admin) hech kimdan ruxsat so'ramasdan,
                    # avtomatik ravishda to'liq huquqqa ega -- faqat oddiy
                    # (admin bo'lmagan) foydalanuvchilar uchun ruxsat tekshiriladi.
                    if not match or not match.get("can_query_products"):
                        self._send_json({"error": "no_permission",
                                          "message": _tg_str(lang, "no_permission")}, 403)
                        return
                try:
                    items = list_products_for_webapp(query)
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                perms = {
                    "can_sell": bool(is_admin or (match and match.get("can_make_sales"))),
                    "can_manage_products": bool(is_admin or (match and match.get("can_manage_products"))),
                    "can_view_reports": bool(is_admin or (match and match.get("can_view_reports"))),
                    "is_admin": is_admin,
                    "language": lang,
                }
                self._send_json({"items": items, **perms})
                return

            if parsed.path == "/api/reports":
                qs = dict(urllib.parse.parse_qsl(parsed.query))
                init_data = qs.get("initData", "")
                period = qs.get("period", "today")
                tg_user, is_admin, match, lang = self._resolve_user(init_data)
                if not tg_user:
                    reason = _LAST_WEBAPP_AUTH_REASON or "Ruxsatsiz so'rov."
                    self._send_json({"error": "unauthorized", "message": reason}, 401)
                    return
                if not (is_admin or (match and match.get("can_view_reports"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                try:
                    data = get_webapp_reports(period)
                    data["recent_sales"] = get_webapp_recent_sales(period)
                    data["debtors"] = get_webapp_debtors()
                    data["day_closures"] = get_webapp_day_closures()
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                self._send_json(data)
                return

            if parsed.path == "/api/printers":
                qs = dict(urllib.parse.parse_qsl(parsed.query))
                init_data = qs.get("initData", "")
                tg_user, is_admin, match, lang = self._resolve_user(init_data)
                if not tg_user:
                    reason = _LAST_WEBAPP_AUTH_REASON or "Ruxsatsiz so'rov."
                    self._send_json({"error": "unauthorized", "message": reason}, 401)
                    return
                can_sell = bool(is_admin or (match and match.get("can_make_sales")))
                can_manage = bool(is_admin or (match and match.get("can_manage_products")))
                if not (can_sell or can_manage):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                settings = load_settings()
                self._send_json({
                    "printers": list_printers(),
                    "receipt_printer": settings.get("receipt_printer"),
                    "barcode_printer": settings.get("barcode_printer"),
                })
                return

            if parsed.path == "/api/customers":
                # MUHIM (foydalanuvchi so'rovi bilan): nasiyaga sotish
                # paytida xaridor ismini kiritishda, OLDIN qarz daftariga
                # yozilgan mijozlarni taklif qilish (autocomplete) uchun.
                qs = dict(urllib.parse.parse_qsl(parsed.query))
                init_data = qs.get("initData", "")
                tg_user, is_admin, match, lang = self._resolve_user(init_data)
                if not tg_user:
                    reason = _LAST_WEBAPP_AUTH_REASON or "Ruxsatsiz so'rov."
                    self._send_json({"error": "unauthorized", "message": reason}, 401)
                    return
                if not (is_admin or (match and match.get("can_make_sales"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                self._send_json({"customers": get_known_customers()})
                return

            if parsed.path == "/api/barcode/settings":
                # MUHIM: "Mahsulot qo'shish" sahifasi ochilganda, OXIRGI
                # ishlatilgan yorliq o'lchamlari (kompyuterdagi bilan bir
                # xil) va oxirgi dollar kursi shu yerdan olinadi -- shu
                # orqali Mini App'da razmer HAR SAFAR standart qiymatga
                # (23/25/100) qaytib qolmaydi.
                qs = dict(urllib.parse.parse_qsl(parsed.query))
                init_data = qs.get("initData", "")
                tg_user, is_admin, match, lang = self._resolve_user(init_data)
                if not tg_user:
                    reason = _LAST_WEBAPP_AUTH_REASON or "Ruxsatsiz so'rov."
                    self._send_json({"error": "unauthorized", "message": reason}, 401)
                    return
                if not (is_admin or (match and match.get("can_manage_products"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                self._send_json(get_webapp_barcode_settings())
                return

            if parsed.path.startswith("/api/product_image/"):
                # MUHIM (foydalanuvchi so'rovi bilan): mahsulot rasmini
                # <img src> sifatida chiqarish uchun -- ruxsat, mahsulot
                # ro'yxatini ko'rish huquqi bilan BIR XIL (agar mahsulot
                # nomini ko'ra olsa, rasmini ham ko'ra oladi).
                qs = dict(urllib.parse.parse_qsl(parsed.query))
                init_data = qs.get("initData", "")
                tg_user, is_admin, match, lang = self._resolve_user(init_data)
                if not tg_user:
                    reason = _LAST_WEBAPP_AUTH_REASON or "Ruxsatsiz so'rov."
                    self._send_json({"error": "unauthorized", "message": reason}, 401)
                    return
                if not is_admin and not (match and match.get("can_query_products")):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                # MUHIM (xavfsizlik): fayl nomidan faqat "basename"ni
                # olamiz -- shu bilan "../../" kabi yo'l bilan boshqa
                # papkadagi fayllarni o'qib olish (path traversal) oldi
                # olinadi.
                raw_name = parsed.path[len("/api/product_image/"):]
                filename = os.path.basename(urllib.parse.unquote(raw_name))
                full_path = os.path.join(PRODUCT_IMAGES_DIR, filename)
                if not filename or not os.path.isfile(full_path):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                try:
                    with open(full_path, "rb") as f:
                        body = f.read()
                except Exception:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                ext = os.path.splitext(filename)[1].lower()
                content_type = {
                    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp",
                }.get(ext, "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                # MUHIM: endi URL'ning o'zida rasm versiyasi (fayl
                # o'zgargan vaqti, "?v=...") bor -- shuning uchun bir xil
                # URL HAR DOIM bir xil kontentga mos keladi va uzoq
                # muddatga keshlash xavfsiz (rasm almashtirilsa, URL ham
                # o'zgaradi, eski kesh hech qachon ishlatilmaydi).
                self.send_header("Cache-Control", "public, max-age=2592000, immutable")
                self.end_headers()
                self.wfile.write(body)
                return

            # MUHIM: HTTP/1.1 keep-alive to'g'ri ishlashi uchun, HAR BIR
            # javobda (hatto 404'da ham) Content-Length ANIQ ko'rsatilishi
            # SHART -- aks holda brauzer ulanishni qachon "tugadi" deb
            # bilmay, keyingi so'rovlar sekinlashishi yoki osilib qolishi
            # mumkin.
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)

            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                payload = _json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._send_json({"error": "bad_request", "message": "Noto'g'ri so'rov."}, 400)
                return

            init_data = payload.get("initData", "")
            tg_user, is_admin, match, lang = self._resolve_user(init_data)
            if not tg_user:
                reason = _LAST_WEBAPP_AUTH_REASON or "Ruxsatsiz so'rov."
                self._send_json({"error": "unauthorized", "message": reason}, 401)
                return

            if parsed.path == "/api/sale":
                if not (is_admin or (match and match.get("can_make_sales"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return

                items = payload.get("items") or []
                payment_type = payload.get("payment_type") or "naqd"
                method_label = payload.get("method_label") or ("Naqd" if payment_type == "naqd" else None)
                customer_name = payload.get("customer_name")
                phone = payload.get("phone")
                print_receipt = bool(payload.get("print_receipt"))
                printer_name = payload.get("printer_name") or None
                copies = payload.get("copies") or 1
                # MUHIM (foydalanuvchi so'rovi bilan -- "qisman to'lov" Mini
                # App'ga ham qo'shildi): agar xaridor jami summaning bir
                # qismini darhol to'lagan bo'lsa, shu summa "paid_now"
                # sifatida keladi -- record_webapp_sale ichida qarz
                # daftariga faqat QOLGAN summa yoziladi.
                try:
                    paid_now = float(payload.get("paid_now") or 0)
                except (TypeError, ValueError):
                    paid_now = 0
                if paid_now < 0:
                    paid_now = 0

                try:
                    ok, err, result = record_webapp_sale(
                        items, payment_type, method_label=method_label,
                        customer_name=customer_name, phone=phone, print_receipt=print_receipt,
                        printer_name=printer_name, copies=copies, paid_now=paid_now)
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return

                if not ok:
                    self._send_json({"error": "sale_failed", "message": err}, 400)
                    return
                self._send_json({"ok": True, "total": result["total"],
                                  "receipt_text": result["receipt_text"],
                                  "print_ok": result.get("print_ok"),
                                  "print_error": result.get("print_error")})
                return

            if parsed.path == "/api/product/add":
                if not (is_admin or (match and match.get("can_manage_products"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                try:
                    ok, err, result = record_webapp_add_product(
                        payload.get("name"), payload.get("cost_price") or 0,
                        payload.get("price"), payload.get("qty") or 0,
                        payload.get("unit"), payload.get("barcode"),
                        name_font_size=payload.get("name_font_size"),
                        price_font_size=payload.get("price_font_size"),
                        barcode_scale=payload.get("barcode_scale"),
                        image_base64=payload.get("image_base64"),
                        ai_remove_bg=bool(payload.get("ai_remove_bg")))
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                if not ok:
                    self._send_json({"error": "add_failed", "message": err}, 400)
                    return
                _save_webapp_barcode_sizes(payload.get("name_font_size"), payload.get("price_font_size"),
                                            payload.get("barcode_scale"))
                self._send_json({"ok": True, **result})
                return

            if parsed.path == "/api/product/update":
                if not (is_admin or (match and match.get("can_manage_products"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                try:
                    ok, err = update_webapp_product(
                        payload.get("id"), payload.get("name"), payload.get("cost_price") or 0,
                        payload.get("price"), payload.get("qty") or 0,
                        payload.get("unit"), payload.get("barcode"),
                        image_base64=payload.get("image_base64"),
                        remove_image=bool(payload.get("remove_image")),
                        ai_remove_bg=bool(payload.get("ai_remove_bg")))
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                if not ok:
                    self._send_json({"error": "update_failed", "message": err}, 400)
                    return
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/product/delete":
                if not (is_admin or (match and match.get("can_manage_products"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                try:
                    ok, err = delete_webapp_product(payload.get("id"))
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                if not ok:
                    self._send_json({"error": "delete_failed", "message": err}, 400)
                    return
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/barcode/print":
                if not (is_admin or (match and match.get("can_manage_products"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                barcode = payload.get("barcode")
                name = payload.get("name") or ""
                price = payload.get("price") or 0
                printer_name = payload.get("printer_name") or None
                if not barcode:
                    self._send_json({"error": "bad_request", "message": "Shtrix kod yo'q."}, 400)
                    return
                try:
                    ok, err = print_webapp_barcode(
                        barcode, name, price, printer_name,
                        name_font_size=payload.get("name_font_size"),
                        price_font_size=payload.get("price_font_size"),
                        barcode_scale=payload.get("barcode_scale"),
                        copies=payload.get("copies") or 1)
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                _save_webapp_barcode_sizes(payload.get("name_font_size"), payload.get("price_font_size"),
                                            payload.get("barcode_scale"))
                self._send_json({"ok": ok, "message": None if ok else err})
                return

            if parsed.path == "/api/barcode/preview":
                if not (is_admin or (match and match.get("can_manage_products"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                barcode = payload.get("barcode")
                name = payload.get("name") or ""
                price = payload.get("price") or 0
                if not barcode:
                    self._send_json({"error": "bad_request", "message": "Shtrix kod yo'q."}, 400)
                    return
                try:
                    ok, err, img_b64 = render_webapp_barcode_preview(
                        barcode, name, price,
                        name_font_size=payload.get("name_font_size"),
                        price_font_size=payload.get("price_font_size"),
                        barcode_scale=payload.get("barcode_scale"))
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                if not ok:
                    self._send_json({"error": "preview_failed", "message": err}, 400)
                    return
                _save_webapp_barcode_sizes(payload.get("name_font_size"), payload.get("price_font_size"),
                                            payload.get("barcode_scale"))
                self._send_json({"ok": True, "barcode_image_base64": img_b64})
                return

            if parsed.path == "/api/usd_rate/save":
                try:
                    save_webapp_usd_rate(payload.get("rate"))
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/sale/delete":
                # MUHIM: sotuvni bekor qilish -- bazani o'zgartiradigan
                # (mahsulot qoldig'ini qaytaradigan) jiddiy amal, shuning
                # uchun savdo qilish huquqi bilan bir xil ruxsat talab
                # qilinadi.
                if not (is_admin or (match and match.get("can_make_sales"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                sale_id = payload.get("sale_id")
                try:
                    ok, err = delete_webapp_sale(sale_id)
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                if not ok:
                    self._send_json({"error": "delete_failed", "message": err}, 400)
                    return
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/receipt/reprint":
                # MUHIM: sotilgan mahsulot(lar) uchun chekni QAYTA chop
                # etish -- bazani o'zgartirmaydi, faqat printerga
                # yuboradi, shuning uchun savdo qilish huquqi kifoya.
                if not (is_admin or (match and match.get("can_make_sales"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                sale_batch = payload.get("sale_batch")
                printer_name = payload.get("printer_name") or None
                copies = payload.get("copies") or 1
                try:
                    ok, err = reprint_webapp_receipt(sale_batch, printer_name, copies)
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                self._send_json({"ok": ok, "message": None if ok else err})
                return

            if parsed.path == "/api/receipt/custom_print":
                # MUHIM (foydalanuvchi so'rovi bilan): "So'nggi sotuvlar"
                # ro'yxatidan BIR NECHTA (2 va undan ortiq) turli mahsulotni
                # (hattoki turli sotuvlardan bo'lsa ham) o'zi tanlab, ularni
                # BITTA yangi chekka birlashtirib chop etish uchun -- bazani
                # o'zgartirmaydi, faqat printerga yuboradi.
                if not (is_admin or (match and match.get("can_make_sales"))):
                    self._send_json({"error": "no_permission",
                                      "message": _tg_str(lang, "no_permission")}, 403)
                    return
                items = payload.get("items") or []
                printer_name = payload.get("printer_name") or None
                copies = payload.get("copies") or 1
                try:
                    ok, err = print_custom_webapp_receipt(items, printer_name, copies)
                except Exception as e:
                    self._send_json({"error": "server_error", "message": str(e)}, 500)
                    return
                self._send_json({"ok": ok, "message": None if ok else err})
                return

            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def _run_miniapp_http_server():
    import http.server
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", _MINIAPP_PORT), _miniapp_handler_factory())
        server.serve_forever()
    except Exception as e:
        _MINIAPP_STATE["error"] = f"Lokal server xatosi: {e}"


def _find_cloudflared_path():
    import shutil
    cloudflared_path = shutil.which("cloudflared")
    search_dirs = [os.getcwd()]
    try:
        if getattr(sys, "frozen", False):
            # PyInstaller --onefile qilib yig'ilgan exe'ning O'ZI joylashgan
            # papka (vaqtinchalik _MEI papkasi emas) -- cloudflared.exe shu
            # yerga (exe bilan bir joyga) qo'yilishi kutiladi.
            search_dirs.append(os.path.dirname(sys.executable))
        search_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    if not cloudflared_path:
        for d in search_dirs:
            for name in ("cloudflared.exe", "cloudflared"):
                candidate = os.path.join(d, name)
                if os.path.exists(candidate):
                    cloudflared_path = candidate
                    break
            if cloudflared_path:
                break
    return cloudflared_path


def _tunnel_health_watchdog(proc, stop_event, generation):
    """MUHIM (foydalanuvchi so'rovi bilan): internet BIROZGINA uzilib,
    keyin qaytganda, cloudflared.exe JARAYONI o'zi tugab/qulab
    QOLMASDAN, shunchaki "zombi" holatda -- ya'ni jarayon hali ham
    ishlab turgandek ko'rinadi (Task Manager'da bor), lekin tunnel
    ULANISHI ICHKARIDA o'lik/qotib qolgan bo'ladi. Bunday holatda
    faqat "jarayon tugashini kutish" (proc.wait()) YETARLI EMAS --
    chunki jarayonning o'zi umuman tugamaydi, foydalanuvchi buni
    Task Manager'dan qo'lda "End Task" qilishga majbur bo'lgan.

    Shuning uchun bu funksiya alohida oqim (thread)da ishlab, HAR necha
    soniyada TUNNEL MANZILINING O'ZIGA (o'zining ochgan trycloudflare.com
    manziliga) haqiqiy tarmoq so'rovi yuborib "tirikligini" tekshiradi --
    xuddi Telegram undan foydalanayotgandek. Agar ketma-ket bir necha
    marta javob bo'lmasa, jarayon MAJBURAN o'ldiriladi (proc.kill()) --
    shunda asosiy tsikl buni "tugadi" deb qabul qilib, AVTOMATIK ravishda
    yangi cloudflared jarayonini ishga tushiradi (foydalanuvchi hech
    narsa qilmasdan)."""
    import time
    import urllib.request
    check_interval = 15
    max_failures = 2
    failures = 0
    # Birinchi tekshiruvdan oldin tunnel manzili aniqlanishi uchun ozgina
    # kutamiz.
    time.sleep(check_interval)
    while not stop_event.is_set():
        if proc.poll() is not None:
            return
        url = _MINIAPP_STATE.get("url")
        if url:
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp.read(1)
                failures = 0
            except Exception:
                failures += 1
        else:
            failures += 1
        if failures >= max_failures:
            _MINIAPP_STATE["error"] = (
                "Mini App tunnel javob bermayapti (internet uzilib qolgan "
                "bo'lishi mumkin) -- avtomatik qayta ulanmoqda..."
            )
            try:
                proc.kill()
            except Exception:
                pass
            return
        for _ in range(check_interval):
            if stop_event.is_set() or proc.poll() is not None:
                return
            time.sleep(1)


def _start_cloudflared_tunnel():
    """MUHIM TUZATISH (foydalanuvchi so'rovi bilan -- Mini App "ba'zida
    ishlab, ba'zida ishlamay qolishi"): bepul cloudflared "quick tunnel"
    (trycloudflare.com) internetdagi vaqtinchalik, RASMIY UPTIME KAFOLATI
    BO'LMAGAN xizmat -- vaqti-vaqti bilan (internet uzilishi, Cloudflare
    tomonidagi vaqtinchalik nosozlik yoki jarayonning o'zi kutilmaganda
    to'xtab qolishi sababli) tunnel uzilib qolishi TABIIY holat. Avval bu
    funksiya FAQAT BIR MARTA ishga tushirilib, agar tunnel biror sababdan
    o'chib qolsa -- ORQASIDAN QAYTA ULAMAS edi (dastur qayta ishga
    tushirilmaguncha Mini App butunlay ishlamay qolar edi). Endi bu -- bir
    marta emas, DOIMIY ishlaydigan "qorovul" (watchdog) tsikli: tunnel
    jarayoni har qanday sababdan to'xtasa, avtomatik ravishda (kichik
    kutish bilan) QAYTA ishga tushiriladi va yangi manzil bilan Telegram
    menyu tugmasi ham avtomatik yangilanadi. MUHIM (2): jarayonning O'ZI
    tugashini kutishdan tashqari, alohida "sog'liqni tekshiruvchi" (_tunnel_
    health_watchdog) oqim ham ishga tushiriladi -- u internet uzilib
    qaytgandan keyin cloudflared "zombi" holatda qolib ketgan hollarni ham
    aniqlab, jarayonni majburan qayta ishga tushiradi (foydalanuvchi endi
    Task Manager'dan qo'lda "End Task" qilishi shart emas)."""
    import re
    import threading
    import time
    cloudflared_path = _find_cloudflared_path()
    if not cloudflared_path:
        _MINIAPP_STATE["cloudflared_missing"] = True
        _MINIAPP_STATE["error"] = (
            "cloudflared.exe topilmadi. Mini App ishlashi uchun uni yuklab, "
            "dastur papkasiga yoki PATH'ga qo'ying: "
            "https://github.com/cloudflare/cloudflared/releases (Windows uchun "
            "cloudflared-windows-amd64.exe faylini yuklab, nomini "
            "cloudflared.exe qilib dastur papkasiga joylashtiring)."
        )
        return

    # MUHIM TUZATISH: dastur --windowed (konsolsiz) qilib yig'ilgan bo'lsa
    # ham, subprocess.Popen orqali ishga tushirilgan cloudflared.exe (bu
    # konsol dasturi) Windows'da avtomatik ravishda O'ZINING qora konsol
    # oynasini ochib yuborar edi. Buni oldini olish uchun Windows'da
    # CREATE_NO_WINDOW bayrog'i (va startupinfo bilan SW_HIDE) beriladi.
    popen_kwargs = {}
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        popen_kwargs["creationflags"] = creationflags
        popen_kwargs["startupinfo"] = startupinfo

    url_pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
    restart_delay = 3
    generation = 0
    while True:
        generation += 1
        _MINIAPP_STATE["error"] = None
        try:
            proc = subprocess.Popen(
                [cloudflared_path, "tunnel", "--url", f"http://127.0.0.1:{_MINIAPP_PORT}"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                **popen_kwargs,
            )
        except Exception as e:
            _MINIAPP_STATE["error"] = f"cloudflared ishga tushmadi: {e}"
            time.sleep(restart_delay)
            continue

        got_url = False
        for line in proc.stdout:
            m = url_pattern.search(line)
            if m:
                url = m.group(0)
                if url != _MINIAPP_STATE.get("url"):
                    _MINIAPP_STATE["url"] = url
                    _MINIAPP_STATE["error"] = None
                    _apply_miniapp_menu_button(url)
                got_url = True
                break

        # MUHIM (qo'shimcha barqarorlik tuzatishi): yuqorida manzil
        # topilgach "break" bilan stdout'ni o'qishni to'xtatgan edik --
        # lekin cloudflared davomida ham log chiqarib turadi, va agar
        # buni O'QIB TURMASAK, operatsion tizimning quvur (pipe) buferi
        # to'lib, cloudflared O'ZI yozishda "osilib" qolishi (deadlock)
        # mumkin edi -- bu ham tunnelning vaqti-vaqti bilan "muzlab"
        # qolishiga sabab bo'lgan bo'lishi mumkin. Shuning uchun endi
        # qolgan chiqishini alohida oqimda doimiy o'qib (e'tiborsiz
        # qoldirib) tashlaymiz.
        if got_url:
            def _drain_stdout(p=proc):
                try:
                    for _ in p.stdout:
                        pass
                except Exception:
                    pass
            threading.Thread(target=_drain_stdout, daemon=True).start()

        # MUHIM: shu jarayon (generatsiya) uchun sog'liqni tekshiruvchi
        # oqimni ishga tushiramiz -- u internetni tekshirib, tunnel
        # "zombi" bo'lib qolsa, jarayonni majburan o'ldiradi.
        stop_health_event = threading.Event()
        if got_url:
            threading.Thread(
                target=_tunnel_health_watchdog,
                args=(proc, stop_health_event, generation),
                daemon=True,
            ).start()

        # MUHIM: yuqoridagi tsikldan "break" bilan chiqqandan keyin ham,
        # jarayonning O'ZINI o'ldirmaymiz -- tunnel fon rejimida davom
        # etaveradi. Bu yerda esa shu jarayon TUGASHINI (odatiy holda
        # o'z-o'zidan, YOKI sog'liqni tekshiruvchi uni majburan o'ldirsa)
        # kutamiz -- ikkala holatda ham avtomatik qayta ulanamiz.
        proc.wait()
        stop_health_event.set()
        _MINIAPP_STATE["url"] = None
        if not got_url:
            _MINIAPP_STATE["error"] = (
                "cloudflared tunnel manzil bermay to'xtadi -- qayta urinilmoqda... "
                "(internet aloqasini tekshiring)"
            )
        else:
            _MINIAPP_STATE["error"] = (
                "Mini App tunnel uzildi -- avtomatik qayta ulanmoqda..."
            )
        time.sleep(restart_delay)


_MENU_BUTTON_TEXT = {"uz": "🛒 Narxlar", "en": "🛒 Prices", "ru": "🛒 Цены"}


def _set_menu_button_for_chat(token, url, chat_id=None, lang="uz"):
    """Telegram chat menyusidagi ko'k "Narxlar"/"Prices"/"Цены" tugmasini,
    BERILGAN chat uchun (yoki chat_id=None bo'lsa -- HAMMA uchun umumiy
    "default" tugma sifatida) o'sha tildagi matn bilan o'rnatadi.

    MUHIM: Telegram'ning setChatMenuButton'i har bir chat uchun ALOHIDA
    o'rnatilishi mumkin -- shuning uchun har bir foydalanuvchi o'ziga xos
    tilida "Narxlar" so'zini ko'radi, chat_id berilmasa esa bu HAMMA
    (hali chat-specific tugmasi yo'q) foydalanuvchilar uchun standart
    bo'lib qoladi."""
    import json as _json
    text = _MENU_BUTTON_TEXT.get(lang, _MENU_BUTTON_TEXT["uz"])
    menu_button = {"type": "web_app", "text": text, "web_app": {"url": f"{url}/webapp"}}
    payload = {"menu_button": _json.dumps(menu_button)}
    if chat_id:
        payload["chat_id"] = chat_id
    return _telegram_api_call(token, "setChatMenuButton", payload)


def _apply_miniapp_menu_button(url):
    """Tunnel manzili aniqlanganda (yoki bot tokeni o'zgarganda) chaqiriladi.
    MUHIM O'ZGARISH: endi FAQAT "default" (umumiy) tugmani emas, balki HAR
    BIR allaqachon ruxsat berilgan foydalanuvchi (va admin) uchun, ULARNING
    o'z tanlagan tilidagi tugmani ham ALOHIDA-ALOHIDA o'rnatadi -- shu
    orqali "Narxlar" ko'k tugmasi ham foydalanuvchi tiliga mos chiqadi."""
    with _telegram_lock():
        settings = load_settings()
        token = (settings.get("telegram_bot_token") or "").strip()
        if not token:
            return
        settings["telegram_miniapp_url"] = url
        save_settings(settings)

    # 1) Umumiy (default) tugma -- hali tilini tanlamagan/ro'yxatdan
    # o'tmagan yangi foydalanuvchilar uchun (o'zbekcha bo'yicha).
    result = _set_menu_button_for_chat(token, url, chat_id=None, lang="uz")
    if result and result.get("ok"):
        _MINIAPP_STATE["menu_button_error"] = None
    else:
        desc = (result or {}).get("description") if isinstance(result, dict) else None
        _MINIAPP_STATE["menu_button_error"] = (
            f"Telegram tugmani sozlashni rad etdi: {desc or _LAST_TELEGRAM_ERROR or 'nomaʼlum xato'}"
        )

    # 2) Admin uchun, uning o'z tanlagan tilida.
    admin_chat_id = (settings.get("telegram_admin_chat_id") or "").strip()
    admin_lang = settings.get("telegram_admin_language") or "uz"
    if admin_chat_id:
        try:
            _set_menu_button_for_chat(token, url, chat_id=admin_chat_id, lang=admin_lang)
        except Exception:
            pass

    # 3) Har bir ruxsat berilgan foydalanuvchi uchun, ularning tanlagan
    # tilida.
    for u in (settings.get("telegram_approved_users") or []):
        cid = u.get("chat_id")
        lang = u.get("language") or "uz"
        if cid:
            try:
                _set_menu_button_for_chat(token, url, chat_id=cid, lang=lang)
            except Exception:
                pass


def get_miniapp_status():
    return dict(_MINIAPP_STATE)


def reapply_miniapp_menu_button():
    """Bot Token o'zgartirilganda (masalan yangi bot yaratilganda) chaqiriladi.
    MUHIM TUZATISH: avval tunnel manzili faqat BIR MARTA (birinchi bot uchun)
    sozlanardi -- keyinchalik boshqa botga o'tilsa, "🛒 Narxlar" tugmasi yangi
    bot uchun HECH QACHON sozlanmasdi. Endi tunnel allaqachon ochiq bo'lsa,
    joriy (yangi) token bilan menyu tugmasi qayta o'rnatiladi."""
    url = _MINIAPP_STATE.get("url")
    if url:
        _apply_miniapp_menu_button(url)


def start_miniapp_server():
    """Mini App uchun lokal serverni va cloudflared tunnelni fon rejimida
    ishga tushiradi. Xavfsiz -- bir necha marta chaqirilsa ham faqat bir
    marta ishga tushadi."""
    if _MINIAPP_STATE["started"]:
        return
    _MINIAPP_STATE["started"] = True
    import threading
    threading.Thread(target=_run_miniapp_http_server, daemon=True).start()
    threading.Thread(target=_start_cloudflared_tunnel, daemon=True).start()


_TELEGRAM_POLL_STATE = {"stop": False, "started": False}


def start_telegram_polling():
    if _TELEGRAM_POLL_STATE["started"]:
        return
    _TELEGRAM_POLL_STATE["started"] = True
    import threading
    t = threading.Thread(target=_telegram_poll_loop, args=(_TELEGRAM_POLL_STATE,), daemon=True)
    t.start()



# ---------------------------------------------------------------------------
# Til (i18n) -- dastur interfeysi uz/en/ru tillarida ko'rsatilishi mumkin.
# ---------------------------------------------------------------------------

TRANSLATIONS = {
    "en": {
        # --- 8-bosqich (navigatsiya panel yorliqlari) ---
        'Qarzdorlar': 'Debtors',
        'Hisobotlar': 'Reports',
        # --- 7-bosqich (to'lovni bekor qilish) ---
        "To'lovni bekor qilish": 'Undo payment',
        "Bu qarz hali to'lanmagan.": 'This debt has not been paid yet.',
        '"{name}" — {amount} so\'m uchun to\'lovni bekor qilib, qarzni yana "to\'lanmagan" holatiga qaytaramizmi?':
            'Undo the payment of {amount} so\'m for "{name}" and mark this debt as unpaid again?',
        # --- 6-bosqich (qarzdorlar holati) ---
        "To'langan": 'Paid',
        "To'lanmagan": 'Unpaid',
        # --- 5-bosqich (tarjima audit tuzatishlari) ---
        "Sotish narxi: {raw} so'm bo'ldi, {price} so'm ga yaxlitlandi ({pct:g}% foyda bilan)": "Sale price came to {raw} so'm, rounded to {price} so'm ({pct:g}% markup)",
        "Avval shtrix kodni kiriting yoki bo'sh qoldirib 'Saqlash'ni bosing (dastur o'zi kod yaratib, chop etish oynasini ochadi).": "Enter a barcode first, or leave it blank and click 'Save' (the app will generate a code and open the print window).",
        "Har bir sotuvda, ruxsat berilgan odamlarga avtomatik xabar yuboriladi.\nKimdir botga yozsa, sizga (admin) so'rov keladi.": 'An automatic message is sent to allowed people on every sale.\nIf someone messages the bot, a request comes to you (the admin).',
        "'{code}' shtrix koduga mos mahsulot yo'q.\n\nBu yangi mahsulotmi? 'Ha' desangiz, shu kod bilan\nyangi mahsulot qo'shish oynasi ochiladi.": "No product matches the barcode '{code}'.\n\nIs this a new product? If you choose 'Yes', a window to add\na new product with this code will open.",
        '"{name}" nomli mahsulot omborda allaqachon mavjud (qoldiq: {qty}).\n\nYangi mahsulot sifatida qo\'shish o\'rniga, ushbu miqdorni ({add_qty}) mavjud mahsulotga QO\'SHIB qo\'yaymi?': 'A product named "{name}" already exists in stock (remaining: {qty}).\n\nInstead of adding it as a new product, should this quantity ({add_qty}) be ADDED to the existing product?',
        '"{name}" nomli boshqa mahsulot allaqachon mavjud. Boshqa nom tanlang.': 'Another product named "{name}" already exists. Choose a different name.',
        "'{code}' shtrix koduga mos mahsulot topilmadi.\nMahsulotlar bo'limida shu kodni mahsulotga biriktiring.": "No product matches the barcode '{code}'.\nAssign this code to a product in the Products section.",
        "Haqiqatan ham butun savdo hisobotini (barcha summalar, tarix va yopilgan kunlarni) 0 ga tushirmoqchimisiz? Bu amalni ortga qaytarib bo'lmaydi.": 'Are you sure you want to reset the entire sales report (all totals, history and closed days) to 0? This action cannot be undone.',
        "Avval jadvaldan chekka qo'shmoqchi bo'lgan mahsulot(lar)ni tanlang.\n\nBir nechtasini birga tanlash uchun Ctrl (yoki Shift) tugmasini\nbosib turgan holda qatorlarni bosing.": 'First select the product(s) in the table you want to add to the receipt.\n\nTo select several at once, hold Ctrl (or Shift)\nwhile clicking the rows.',
        'Bu sotuvni o\'chirib, mahsulotni omborga qaytarasizmi?\n"{name}" — {qty}': 'Delete this sale and return the product to stock?\n"{name}" — {qty}',
        # --- 4-bosqich ---
        'Avtomatik chop etib bo\'lmadi ({err})': 'Couldn\'t print automatically ({err})',

        # --- 3-bosqich (jadval sarlavhalari) ---
        'Bugun hali sotuv qilinmagan, yopish uchun narsa yo\'q.': 'No sales have been made today yet, nothing to close.',
        'Holati': 'Status',
        'Mahsulot / izoh': 'Product / note',
        'Qoldiq': 'Remaining',
        'Summasi': 'Amount',
        'Telefon': 'Phone',
        'Xaridor': 'Customer',
        'Sana / vaqt': 'Date / time',

        # --- 2-bosqich qo'shimchalari ---
        'Avval tan narxini kiriting, so\'ng foizni kiriting.': 'First enter the cost price, then the percentage.',
        'Avval tan narxini to\'g\'ri kiriting.': 'First enter a valid cost price.',
        'Birligi': 'Unit',
        'Bot Token kiritilmagan.': 'Bot Token not entered.',
        'Bot ulandi': 'Bot connected',
        'Bu odamni ro\'yxatdan chiqarib tashlaymi?': 'Remove this person from the list?',
        'Dollar summasi va kursni to\'g\'ri kiriting (masalan 1.5 va 12000).': 'Enter a valid dollar amount and rate (e.g. 1.5 and 12000).',
        'Foyda foizi (%):': 'Profit margin (%):',
        'Hisoblandi': 'Calculated',
        'Hisoblash': 'Calculate',
        'Jami qarz': 'Total debt',
        'Kurs (so\'m/$):': 'Rate (so\'m/$):',
        'Mahsulot nomini kiriting.': 'Enter the product name.',
        'Masalan: kg/litr/metr tanlasangiz, miqdorga 0.9, 1.5 kabi kasr son ham kiritishingiz mumkin.': 'For example, if you choose kg/liter/meter, you can also enter a fraction like 0.9, 1.5 for quantity.',
        'Miqdorni to\'g\'ri kiriting.': 'Enter a valid quantity.',
        'Narx musbat son bo\'lishi kerak.': 'Price must be a positive number.',
        'Narx va miqdorni to\'g\'ri kiriting (masalan: 0.9).': 'Enter a valid price and quantity (e.g. 0.9).',
        'Narxni to\'g\'ri kiriting.': 'Enter a valid price.',
        'Nasiya': 'Credit',
        'Noma\'lum xato.': 'Unknown error.',
        'Ombordagi (odatdagi) narx': 'Warehouse (default) price',
        'Qiymatlar musbat bo\'lishi kerak.': 'Values must be positive.',
        'Rad etish': 'Reject',
        'Ruxsat berish': 'Approve',
        'Shtrix kod rasmini yaratib bolmadi': 'Couldn\'t generate the barcode image',
        'Sotish narxi — mijozga qo\'yiladigan narx (so\'m, 1 birlik uchun)': 'Sale price — the price charged to the customer (so\'m, per unit)',
        'Sotish narxi: {price} so\'m ({pct:g}% foyda bilan)': 'Sale price: {price} so\'m (with {pct:g}% profit)',
        'Sotish narxini hisoblash': 'Calculate sale price',
        'Summani to\'g\'ri kiriting.': 'Enter a valid amount.',
        'Tan narxi ($):': 'Cost price ($):',
        'Telefon raqamini kiriting.': 'Enter the phone number.',
        'Telegram sozlamalari saqlandi.': 'Telegram settings saved.',
        'Ulanmadi': 'Not connected',
        'Xaridor ism-familiyasini kiriting.': 'Enter the customer\'s full name.',
        'Xaridor ismini kiriting.': 'Enter the customer\'s name.',
        'Yangi miqdor': 'New quantity',
        'Yordamchi: dollardan so\'mga avtomatik hisoblash': 'Helper: automatic dollar-to-so\'m conversion',
        'masalan 1.5': 'e.g. 1.5',
        'masalan 12000': 'e.g. 12000',
        'masalan 20': 'e.g. 20',
        'olgan mahsulotlari': 'items taken',
        '— Yangi xaridor —': '— New customer —',

        # --- Yangi GUI (PySide6) satrlari ---
        '"{name}" mahsulotidan omborda yetarli miqdor yo\'q.': 'Not enough "{name}" in stock.',
        '"{name}" mahsulotini o\'chirmoqchimisiz?': 'Delete product "{name}"?',
        '"{name}" qarzini o\'chirmoqchimisiz?': 'Delete debt for "{name}"?',
        '"{name}" — {amount} so\'m to\'landi deb belgilaymi?': 'Mark "{name}" — {amount} so\'m as paid?',
        '\'openpyxl\' kutubxonasi o\'rnatilmagan.': 'The \'openpyxl\' library is not installed.',
        '(jami)': '(total)',
        'Avtomatik chop etib bo\'lmadi. Fayl saqlangan: {path} ({err})': 'Couldn\'t print automatically. File saved: {path} ({err})',
        'Avtomatik chop etib bo\'lmadi. Rasm saqlangan: {path} ({err})': 'Couldn\'t print automatically. Image saved: {path} ({err})',
        'Avval jadvaldan mahsulotni tanlang.': 'First select a product from the table.',
        'Avval jadvaldan qarzdorni tanlang.': 'First select a debtor from the table.',
        'Avval jadvaldan sotuvni tanlang.': 'First select a sale from the table.',
        'Avval savatdan mahsulotni tanlang.': 'First select an item from the cart.',
        'Bekor qilindi': 'Cancelled',
        'Bosh sahifa': 'Home',
        'Bu mahsulot omborda qolmagan.': 'This product is out of stock.',
        'Bu mahsulotda shtrix kod yo\'q.': 'This product has no barcode.',
        'Bu qarz allaqachon to\'langan.': 'This debt has already been paid.',
        'Bugungi foyda': 'Today\'s profit',
        'Bugungi kun allaqachon yopilgan.': 'Today has already been closed.',
        'Bugungi kun muvaffaqiyatli yopildi.': 'Today was closed successfully.',
        'Bugungi kunni yopmoqchimisiz? Bu amalni ortga qaytarib bo\'lmaydi.': 'Do you want to close today\'s day? This action cannot be undone.',
        'Bugungi savdo (nasiya)': 'Today\'s sales (credit)',
        'Bunday mahsulot allaqachon bor': 'This product already exists',
        'Chegirma': 'Discount',
        'Chek printerga yuborildi.': 'Receipt sent to printer.',
        'Dublikat mahsulot yaratilmadi. Xohlasangiz nomni o\'zgartirib qayta urinib ko\'ring.': 'No duplicate product was created. Change the name and try again if you like.',
        'Excel faylni saqlash': 'Save Excel file',
        'Excel\'ga eksport': 'Export to Excel',
        'Fayl saqlandi': 'File saved',
        'Foyda': 'Profit',
        'Grafik modul (QtCharts) mavjud emas.': 'Chart module (QtCharts) is not available.',
        'Hisobot 0 ga tushirildi.': 'Report reset to zero.',
        'Jami': 'Total',
        'Kam qolgan mahsulotlar': 'Low stock products',
        'Kod': 'Code',
        'Kun yopilishlari': 'Day closures',
        'Kunduzgi rejim': 'Light mode',
        'Kunlik foyda': 'Daily profit',
        'Kutilayotgan foyda': 'Expected profit',
        'Mahsulot ma\'lumotlari yangilandi.': 'Product details updated.',
        'Mahsulot miqdori yangilandi.': 'Product quantity updated.',
        'Mahsulot nomi bo\'yicha qidirish...': 'Search by product name...',
        'Mahsulot omborga qo\'shildi.': 'Product added to warehouse.',
        'Mahsulot qidirish...': 'Search product...',
        'Mahsulot qo\'shish': 'Add product',
        'Miqdor musbat son bo\'lishi kerak.': 'Quantity must be a positive number.',
        'Miqdor yangilandi.': 'Quantity updated.',
        'Miqdorni to\'g\'ri kiriting (masalan: 0.9).': 'Enter a valid quantity (e.g. 0.9).',
        'Naqd foyda': 'Cash profit',
        'Naqd savdo': 'Cash sales',
        'Nasiya foyda': 'Credit profit',
        'Nasiya savdo': 'Credit sales',
        'Nasiyaga savdo': 'Credit sale',
        'Nusxa saqlandi': 'Copy saved',
        'O\'chirildi': 'Deleted',
        'O\'chirish (omborga qaytarish)': 'Delete (return to stock)',
        'Olgan mahsulotlarini ko\'rish': 'View items taken',
        'Omborda faqat {qty} bor.': 'Only {qty} available in stock.',
        'Printerlar royxati olinmadi': 'Couldn\'t get the printer list',
        'Qarzdorlar daftari': 'Debt ledger',
        'Qo\'shildi': 'Added',
        'Saqlab bolmadi': 'Couldn\'t save',
        'Savat bo\'sh.': 'Cart is empty.',
        'Savdo': 'Sales',
        'Savdo tarixi': 'Sales history',
        'Shtrix kod printerga yuborildi ({n} ta nusxa).': 'Barcode sent to printer ({n} copies).',
        'Shtrix kodni chop etish': 'Print barcode',
        'Shtrix kodni saqlash': 'Save barcode',
        'Shtrix kodni skanerlang yoki kiriting...': 'Scan or enter barcode...',
        'Sotuv o\'chirildi, mahsulot omborga qaytarildi.': 'Sale deleted, product returned to stock.',
        'To\'landi': 'Paid',
        'To\'landi deb belgilash': 'Mark as paid',
        'Tungi rejim': 'Dark mode',
        'Yangilandi': 'Updated',
        'Yopilgan vaqti:': 'Closed at:',
        'jami': 'total',
        'mos mahsulot topilmadi': 'no matching product found',
        'naqd + nasiya': 'cash + credit',
        'naqd va nasiya': 'cash and credit',
        'naqd/karta': 'cash/card',
        'qarz to\'langanda': 'when debt is paid',
        'qarzga berilgan': 'given on credit',
        'qoshildi': 'added',
        'sabab noma\'lum': 'reason unknown',
        'so\'nggi {n} kun': 'last {n} days',
        'tan narxi bo\'yicha': 'by cost price',
        'to\'lanmagan': 'unpaid',
        '{n} ta': '{n} pcs',

        'dona': 'pcs',
        'Bugungi savdo (naqd)': "Today's sales (cash)",
        'Bugungi foyda (naqd)': "Today's profit (cash)",
        'Bugungi nasiya (qarzga)': "Today's sales (on credit)",
        'sof foyda': 'net profit',
        'sof foyda (to\'langan nasiyalar bilan)': 'net profit (including paid credit sales)',
        'Nasiya foydasi': 'Credit profit',
        'kutilayotgan (hali to\'lanmagan)': 'pending (not yet paid)',
        'foyda': 'profit',
        'nasiya foydasi (kutilayotgan)': 'credit profit (pending)',
        '{n} ta chek': '{n} receipts',
        'kutilayotgan foyda: {v} so\'m': 'expected profit: {v} so\'m',
        'Ombor qiymati': 'Inventory value',
        '{n} nomdagi mahsulot': '{n} products',
        'Qarzdorlik': 'Debt',
        '{n} kishi': '{n} people',
        'joriy holat': 'current status',
        'Kunduzgi': 'Light',
        'Tungi': 'Dark',
        'Ulanishni tekshirish': 'Test connection',
        '⚠️ Bot Token kiritilmagan.': "⚠️ Bot Token isn't entered.",
        'Tekshirilmoqda…': 'Checking…',
        '№': 'No.',
        'JAMI': 'TOTAL',
        'Naqd': 'Cash',
        'Sana': 'Date',
        'naqd': 'cash',
        'Davr:': 'Period:',
        'Narxi': 'Price',
        'Savat': 'Cart',
        'Summa': 'Amount',
        'Miqdor': 'Qty',
        'Sotish': 'Sell',
        'Yopish': 'Close',
        'nasiya': 'credit',
        'Hisobot': 'Report',
        'Miqdor:': 'Qty:',
        'Miqdori': 'Quantity',
        'Omborda': 'In stock',
        'Saqlash': 'Save',
        'Mahsulot': 'Product',
        'Miqdori:': 'Quantity:',
        "Qo'llash": 'Apply',
        "Qo'shish": 'Add',
        '  Sotuv  ': '  Sales  ',
        "O'chirish": 'Delete',
        'Tan narxi': 'Cost price',
        '  Asosiy  ': '  Home  ',
        "+ Qo'shish": '+ Add',
        'Bot Token:': 'Bot Token:',
        'Chop etish': 'Print',
        'Jami foyda': 'Total profit',
        'Jami savdo': 'Total sales',
        'NAQD SOTUV': 'CASH SALES',
        'Shtrix kod': 'Barcode',
        'Tahrirlash': 'Edit',
        '  Hisobot  ': '  Report  ',
        'Chek tayyor': 'Receipt ready',
        'Mahsulotlar': 'Products',
        '🚫 Rad etish': '🚫 Reject',
        'Bekor qilish': 'Cancel',
        "Jami: 0 so'm": "Total: 0 so'm",
        'Kunni yopish': 'Close the day',
        'Mahsulotlari': 'Items',
        "O'zgartirish": 'Change',
        'Qarz daftari': 'Debt ledger',
        'Sotish narxi': 'Selling price',
        'Sotuv qilish': 'Make a sale',
        'Bugungi holat': "Today's status",
        "Ma'lumot yo'q": 'No data',
        'Mahsulot nomi': 'Product name',
        'Olib tashlash': 'Remove',
        'Plastik karta': 'Card',
        'Chek chiqarish': 'Print receipt',
        'Chek printeri:': 'Receipt printer:',
        'Kengligi (mm):': 'Width (mm):',
        'Telefon raqami': 'Phone number',
        'Yopilgan vaqti': 'Closed at',
        '  Mahsulotlar  ': '  Products  ',
        'Kun tanlanmagan': 'No day selected',
        'NASIYA (QARZGA)': 'CREDIT (ON DEBT)',
        "O'lchov birligi": 'Unit',
        'Sotuvlar tarixi': 'Sales history',
        'Yopilgan kunlar': 'Closed days',
        '✅ Ruxsat berish': '✅ Approve',
        '  Qarz daftari  ': '  Debt ledger  ',
        'Balandligi (mm):': 'Height (mm):',
        "Qog'oz kengligi:": 'Paper width:',
        "Savatga qo'shish": 'Add to cart',
        'Savatni tozalash': 'Clear cart',
        "Yorliq o'lchami:": 'Label size:',
        "   DO'KON DAFTARI": '   STORE LEDGER',
        'Chiqarib tashlash': 'Remove',
        'Hisobotni tozalash': 'Reset report',
        'Mahsulot qidirish:': 'Search product:',
        'Ruxsat berilganlar': 'Approved',
        '  Sotuvlar tarixi  ': '  Sales history  ',
        '  Yopilgan kunlar  ': '  Closed days  ',
        'Ombordagi kamchilik': 'Low stock',
        "Qarz summasi (so'm)": "Debt amount (so'm)",
        'Boshqa joyga saqlash': 'Save elsewhere',
        "Eng ko'p sotilganlar": 'Best sellers',
        'Shtrix kod printeri:': 'Barcode printer:',
        'Telegram sozlamalari': 'Telegram settings',
        "Miqdorni o'zgartirish": 'Change quantity',
        "Qog'oz kengligi (mm):": 'Paper width (mm):',
        "To'landi / To'lanmadi": 'Paid / Unpaid',
        '⌁ Shtrix kod skaneri:': '⌁ Barcode scanner:',
        'Excelga eksport qilish': 'Export to Excel',
        "Kutilayotgan so'rovlar": 'Pending requests',
        'Shtrix kodni chiqarish': 'Print barcode',
        'Telegram xabarnomalari': 'Telegram notifications',
        "To'lov turini tanlang:": 'Choose payment method:',
        'Xaridor ism-familiyasi': 'Customer full name',
        "Jami qarzdorlik: 0 so'm": "Total debt: 0 so'm",
        'Kirim (mahsulot keldi):': 'Restock (item arrived):',
        'Olayotgan mahsulotlari:': 'Items being taken:',
        "Qarz daftariga qo'shish": 'Add to debt ledger',
        'Hisobotni 0 ga tushirish': 'Reset report to zero',
        'Nasiyaga (qarzga) berish': 'Give on credit',
        'Soni (nechta chiqarish):': 'Copies to print:',
        "Mening chat_id'im (admin):": 'My chat_id (admin):',
        'Narxni pasaytirish (chegirma)': 'Lower price (discount)',
        'Shtrix kod avtomatik yaratildi': 'Barcode generated automatically',
        'Qidirish (nom yoki shtrix kod):': 'Search (name or barcode):',
        "Hozircha kam qolgan mahsulot yo'q": 'No low-stock items yet',
        "Hozircha kutilayotgan so'rov yo'q": 'No pending requests yet',
        'Hozircha hech kimga ruxsat berilmagan': 'No one has been approved yet',
        'Nima mahsulot oldi / izoh (ixtiyoriy)': 'What they took / note (optional)',
        "Chapdagi ro'yxatdan bir kunni tanlang.": 'Select a day from the list on the left.',
        'Yangi (kelishilgan) narx, 1 dona uchun:': 'New (agreed) price, per unit:',
        "Tanlangan yozuvni o'chirish (ombor qaytariladi)": 'Delete selected record (stock restored)',
        "Bu qarzdor uchun mahsulot ro'yxati kiritilmagan.": 'No item list was entered for this debtor.',
        "Bu printerni eslab qol (keyingi safar so'ramasin)": "Remember this printer (don't ask next time)",
        "Bu yozuv uchun batafsil ro'yxat saqlanmagan, izoh:": 'No detailed list was saved for this record, note:',
        'Avval nasiyaga olgan xaridordan tanlang (ixtiyoriy)': 'Choose a previous credit customer (optional)',
        "(O'zgartirsangiz, keyingi chekdan boshlab qo'llanadi)": '(If changed, applies from the next receipt)',
        'Shtrix kodni skanerlang — mahsulot avtomatik topiladi': 'Scan the barcode — the item will be found automatically',
        "Kursor shu yerda bo'lsa, skanerlash avtomatik ishlaydi": 'If the cursor is here, scanning works automatically',
        'Chek chiqarish uchun bir yoki bir nechta qatorni tanlang ': 'Select one or more rows to print a receipt ',
        "Sotish narxi — siz mijozga qo'ygan narx (so'm, 1 birlik uchun)": "Selling price — the price you set for the customer (so'm, per unit)",
        "(Admin chat_id — so'rovlar SIZGA shu yerga kelishi uchun kerak)": '(Admin chat_id — needed so requests come to YOU here)',
        "Tan narxi — zavod/optomdan qancha turadi (so'm, 1 birlik uchun)": "Cost price — what it costs from the factory/wholesaler (so'm, per unit)",
        "Har bir yopilgan kunni bosib, o'sha kunning batafsil statistikasini ko'ring.": 'Click any closed day to see its detailed statistics.',
        'Masalan: kg/litr/metr tanlasangiz, miqdorga 0.9, 1.5 kabi\nkasr son ham kiritishingiz mumkin.': 'For example, if you choose kg/liter/meter, you can also enter\nfractional amounts like 0.9, 1.5.',
        'Diqqat': 'Notice',
        'Diqqat!': 'Notice!',
        'Xato': 'Error',
        'Saqlandi': 'Saved',
        'Tayyor': 'Done',
        'Topilmadi': 'Not found',
        'Yetarli emas': 'Not enough',
        'Bajarildi': 'Done',
        'Kun yopildi': 'Day closed',
        'Printer tanlanmagan': 'No printer selected',
        "Kerakli dastur yo'q": 'Required app missing',
        "Kerakli kutubxonalar yo'q": 'Required libraries missing',
        "Shtrix kod yo'q": 'No barcode',
        "So'nggi 30 kun": 'Last 30 days',
        "Elmans materials — Do'kon Daftari": 'Elmans materials — Store Ledger',
        "To'lov turi": 'Payment method',
        'Chek': 'Receipt',
        'Yangi shtrix kod': 'New barcode',
        'Nasiyaga berish': 'Give on credit',
        "Qarzdor qo'shish": 'Add debtor',
        'Yanvar': 'January',
        'Fevral': 'February',
        'Mart': 'March',
        'Aprel': 'April',
        'May': 'May',
        'Iyun': 'June',
        'Iyul': 'July',
        'Avgust': 'August',
        'Sentyabr': 'September',
        'Oktyabr': 'October',
        'Noyabr': 'November',
        'Dekabr': 'December',
        "Shtrix kod (skanerdan o'qiting yoki qo'lda kiriting). Bo'sh qoldirsangiz,\ndastur o'zi tasodifiy 13 xonali shtrix kod yaratib beradi.": 'Barcode (scan it or type it manually). If left empty,\nthe app will generate a random 13-digit barcode.',
        "Har bir sotuvda, ruxsat berilgan odamlarga avtomatik xabar\nyuboriladi. Kimdir botga yozsa, sizga (admin) so'rov keladi.": 'On every sale, an automatic message is sent to approved\npeople. If someone messages the bot, you (admin) get a request.',
        "Bu yerda belgilangan narx faqat shu sotuvga tegishli bo'ladi —\nmahsulotning ombordagi doimiy narxi o'zgarmaydi.": "The price set here applies only to this sale —\nthe product's regular price in stock does not change.",
        "(Yorliq qog'ozingizning haqiqiy o'lchamini tanlang — bosh harflar\nva narx kesilib qolmasligi uchun)": "(Choose your label paper's actual size — so the name\nand price don't get cut off)",
        "Bu tugma barcha savdo hisobotini (jami summa, tarix, grafik, yopilgan kunlar) 0 ga\ntushiradi. Mahsulotlar va qarz daftariga tegmaydi. Ortga qaytarib bo'lmaydi!": "This button resets the entire sales report (total amount, history, chart, closed days) to zero.\nIt doesn't affect products or the debt ledger. This cannot be undone!",
        'Chek chiqarish uchun bir yoki bir nechta qatorni tanlang (bir nechtasini birga tanlash uchun Ctrl yoki Shift tugmasini bosib turing).': 'Select one or more rows to print a receipt (hold Ctrl or Shift to select multiple).',
        # --- 9-bosqich (tema rejimi tugmasi) ---
        'Tema: Kunduzgi': 'Theme: Light',
        'Tema: Tungi': 'Theme: Dark',
        'Tema: Tizimga mos': 'Theme: System',
        'Bugungi foyda (nasiya)': "Today's profit (credit)",
        'qarz to\'langanda tushadi': 'received when debt is paid',
        # --- 10-bosqich (Telegram: til tanlash va narx so'rash) ---
        "Yangi so'rovchi avval botda tilini (o'zbek/ingliz/rus) tanlaydi, "
        "so'ng sizga so'rov keladi. Ruxsat berilgan odamga \"Narx so'rashga "
        "ruxsat berish\" tugmasini bossangiz, u botga mahsulot nomini yozib "
        "narxi va qoldig'ini so'rab bilasiz.":
            'A new requester first picks their language (Uzbek/English/Russian) in '
            'the bot, then a request comes to you. If you press "Allow price lookup" '
            'for an approved person, they can type a product name in the bot to '
            'check its price and remaining quantity.',
        "Narx so'rashni o'chirish": 'Disable price lookup',
        "Narx so'rashga ruxsat berish": 'Allow price lookup',
        # --- 11-bosqich (Telegram Mini App) ---
        'Mini App (bot ilovasi)': 'Mini App (bot application)',
        'Tekshirilmoqda...': 'Checking...',
        'cloudflared.exe topilmadi': 'cloudflared.exe not found',
        'Mini App tayyor': 'Mini App ready',
        'Bot menyusidagi "🛒 Narxlar" tugmasi orqali ochiladi': 'Opens via the "🛒 Prices" button in the bot menu',
        'Tunnel ochilmoqda, kuting...': 'Opening tunnel, please wait...',
        'Bot Token saqlansa avtomatik ishga tushadi.': 'Starts automatically once the Bot Token is saved.',
        # --- 12-bosqich (ombor qiymati formulasi) ---
        'sotish narxi bo\'yicha': 'by sale price',
        # --- 13-bosqich (Excel eksport: jami qatorlari) ---
        'Jami summa': 'Total amount',
        'Jami qarz (nasiya)': 'Total debt (credit)',
        'Kutilayotgan foyda (nasiya)': 'Expected profit (credit)',
        # --- 14-bosqich (Excel eksport: yangi ustunlar/jami qatori) ---
        'Birlik': 'Unit',
        "Tan narxi (so'm)": 'Cost price (so\'m)',
        "Narxi (so'm)": "Price (so'm)",
        "Chegirma (so'm)": "Discount (so'm)",
        "Summa (so'm)": "Amount (so'm)",
        "Foyda (so'm)": "Profit (so'm)",
        'NAQD — jami savdo': 'CASH — total sales',
        'NAQD — jami foyda': 'CASH — total profit',
        'NASIYA — jami savdo': 'CREDIT — total sales',
        'NASIYA — jami foyda': 'CREDIT — total profit',
        'UMUMIY JAMI:': 'GRAND TOTAL:',
        'UMUMIY FOYDA': 'TOTAL PROFIT',
        # --- 15-bosqich (qisman to'lov) ---
        "Hozir to'lanadigan summa (ixtiyoriy — xaridor bir qismini darhol to'lasa)":
            "Amount to be paid now (optional — if the customer pays part immediately)",
        'Qarzga qoladi': 'Remaining debt',
        'Qisman to\'lash': 'Partial payment',
        'Qarzdan qancha to\'landi?': 'How much was paid toward the debt?',
        'Qolgan qarz': 'Remaining debt',
        'To\'langan summa': 'Amount paid',
        'To\'lovni qarzdan ayirish': 'Deduct payment from debt',
        'To\'lov qarzdan ayirildi. Qolgan qarz: {amount} so\'m': 'Payment deducted. Remaining debt: {amount} UZS',
        "To'langan summani to'g'ri kiriting (0 dan Jami summagacha).":
            "Enter a valid amount paid (from 0 up to the total amount).",
        "Hozir to'lanadigan summani to'g'ri kiriting.": "Enter a valid amount to be paid now.",
        "To'langan summa manfiy bo'lishi mumkin emas.": "The amount paid cannot be negative.",
        "To'langan summa jami summadan ({total}) katta bo'lishi mumkin emas.":
            "The amount paid cannot exceed the total amount ({total}).",
        "{paid} to'landi, {debt} qoldi": "{paid} paid, {debt} remaining",
    },
    "ru": {
        # --- 8-bosqich (navigatsiya panel yorliqlari) ---
        'Qarzdorlar': 'Должники',
        'Hisobotlar': 'Отчёты',
        # --- 7-bosqich (to'lovni bekor qilish) ---
        "To'lovni bekor qilish": 'Отменить оплату',
        "Bu qarz hali to'lanmagan.": 'Этот долг ещё не оплачен.',
        '"{name}" — {amount} so\'m uchun to\'lovni bekor qilib, qarzni yana "to\'lanmagan" holatiga qaytaramizmi?':
            'Отменить оплату {amount} сум для "{name}" и снова отметить долг как неоплаченный?',
        # --- 6-bosqich (qarzdorlar holati) ---
        "To'langan": 'Оплачено',
        "To'lanmagan": 'Не оплачено',
        # --- 5-bosqich (tarjima audit tuzatishlari) ---
        "Sotish narxi: {raw} so'm bo'ldi, {price} so'm ga yaxlitlandi ({pct:g}% foyda bilan)": 'Цена продажи составила {raw} сум, округлена до {price} сум (наценка {pct:g}%)',
        "Avval shtrix kodni kiriting yoki bo'sh qoldirib 'Saqlash'ni bosing (dastur o'zi kod yaratib, chop etish oynasini ochadi).": 'Сначала введите штрихкод или оставьте поле пустым и нажмите «Сохранить» (приложение само создаст код и откроет окно печати).',
        "Har bir sotuvda, ruxsat berilgan odamlarga avtomatik xabar yuboriladi.\nKimdir botga yozsa, sizga (admin) so'rov keladi.": 'При каждой продаже разрешённым людям автоматически отправляется сообщение.\nЕсли кто-то напишет боту, вам (админу) придёт запрос.',
        "'{code}' shtrix koduga mos mahsulot yo'q.\n\nBu yangi mahsulotmi? 'Ha' desangiz, shu kod bilan\nyangi mahsulot qo'shish oynasi ochiladi.": "Товар со штрихкодом '{code}' не найден.\n\nЭто новый товар? Если выберете «Да», откроется окно\nдобавления нового товара с этим кодом.",
        '"{name}" nomli mahsulot omborda allaqachon mavjud (qoldiq: {qty}).\n\nYangi mahsulot sifatida qo\'shish o\'rniga, ushbu miqdorni ({add_qty}) mavjud mahsulotga QO\'SHIB qo\'yaymi?': 'Товар с названием "{name}" уже есть на складе (остаток: {qty}).\n\nВместо добавления как нового товара, добавить это количество ({add_qty}) к существующему товару?',
        '"{name}" nomli boshqa mahsulot allaqachon mavjud. Boshqa nom tanlang.': 'Другой товар с названием "{name}" уже существует. Выберите другое название.',
        "'{code}' shtrix koduga mos mahsulot topilmadi.\nMahsulotlar bo'limida shu kodni mahsulotga biriktiring.": "Товар со штрихкодом '{code}' не найден.\nПривяжите этот код к товару в разделе «Товары».",
        "Haqiqatan ham butun savdo hisobotini (barcha summalar, tarix va yopilgan kunlarni) 0 ga tushirmoqchimisiz? Bu amalni ortga qaytarib bo'lmaydi.": 'Вы действительно хотите обнулить весь отчёт по продажам (все суммы, историю и закрытые дни)? Это действие нельзя отменить.',
        "Avval jadvaldan chekka qo'shmoqchi bo'lgan mahsulot(lar)ni tanlang.\n\nBir nechtasini birga tanlash uchun Ctrl (yoki Shift) tugmasini\nbosib turgan holda qatorlarni bosing.": 'Сначала выберите в таблице товар(ы), которые нужно добавить в чек.\n\nЧтобы выбрать несколько сразу, удерживайте Ctrl (или Shift)\nи щёлкайте по строкам.',
        'Bu sotuvni o\'chirib, mahsulotni omborga qaytarasizmi?\n"{name}" — {qty}': 'Удалить эту продажу и вернуть товар на склад?\n"{name}" — {qty}',
        # --- 4-bosqich ---
        'Avtomatik chop etib bo\'lmadi ({err})': 'Не удалось напечатать автоматически ({err})',

        # --- 3-bosqich (jadval sarlavhalari) ---
        'Bugun hali sotuv qilinmagan, yopish uchun narsa yo\'q.': 'Сегодня продаж ещё не было, закрывать нечего.',
        'Holati': 'Статус',
        'Mahsulot / izoh': 'Товар / примечание',
        'Qoldiq': 'Остаток',
        'Summasi': 'Сумма',
        'Telefon': 'Телефон',
        'Xaridor': 'Клиент',
        'Sana / vaqt': 'Дата / время',

        # --- 2-bosqich qo'shimchalari ---
        'Avval tan narxini kiriting, so\'ng foizni kiriting.': 'Сначала введите себестоимость, затем процент.',
        'Avval tan narxini to\'g\'ri kiriting.': 'Сначала введите правильную себестоимость.',
        'Birligi': 'Единица',
        'Bot Token kiritilmagan.': 'Токен бота не введён.',
        'Bot ulandi': 'Бот подключён',
        'Bu odamni ro\'yxatdan chiqarib tashlaymi?': 'Удалить этого человека из списка?',
        'Dollar summasi va kursni to\'g\'ri kiriting (masalan 1.5 va 12000).': 'Введите правильную сумму в долларах и курс (например 1.5 и 12000).',
        'Foyda foizi (%):': 'Наценка (%):',
        'Hisoblandi': 'Рассчитано',
        'Hisoblash': 'Рассчитать',
        'Jami qarz': 'Общий долг',
        'Kurs (so\'m/$):': 'Курс (сум/$):',
        'Mahsulot nomini kiriting.': 'Введите название товара.',
        'Masalan: kg/litr/metr tanlasangiz, miqdorga 0.9, 1.5 kabi kasr son ham kiritishingiz mumkin.': 'Например, если вы выберете кг/литр/метр, в количество можно вводить и дробные числа, например 0.9, 1.5.',
        'Miqdorni to\'g\'ri kiriting.': 'Введите правильное количество.',
        'Narx musbat son bo\'lishi kerak.': 'Цена должна быть положительным числом.',
        'Narx va miqdorni to\'g\'ri kiriting (masalan: 0.9).': 'Введите правильную цену и количество (например: 0.9).',
        'Narxni to\'g\'ri kiriting.': 'Введите правильную цену.',
        'Nasiya': 'В долг',
        'Noma\'lum xato.': 'Неизвестная ошибка.',
        'Ombordagi (odatdagi) narx': 'Складская (обычная) цена',
        'Qiymatlar musbat bo\'lishi kerak.': 'Значения должны быть положительными.',
        'Rad etish': 'Отклонить',
        'Ruxsat berish': 'Разрешить',
        'Shtrix kod rasmini yaratib bolmadi': 'Не удалось создать изображение штрихкода',
        'Sotish narxi — mijozga qo\'yiladigan narx (so\'m, 1 birlik uchun)': 'Цена продажи — цена для клиента (сум, за единицу)',
        'Sotish narxi: {price} so\'m ({pct:g}% foyda bilan)': 'Цена продажи: {price} сум (с наценкой {pct:g}%)',
        'Sotish narxini hisoblash': 'Рассчитать цену продажи',
        'Summani to\'g\'ri kiriting.': 'Введите правильную сумму.',
        'Tan narxi ($):': 'Себестоимость ($):',
        'Telefon raqamini kiriting.': 'Введите номер телефона.',
        'Telegram sozlamalari saqlandi.': 'Настройки Telegram сохранены.',
        'Ulanmadi': 'Не подключено',
        'Xaridor ism-familiyasini kiriting.': 'Введите ФИО клиента.',
        'Xaridor ismini kiriting.': 'Введите имя клиента.',
        'Yangi miqdor': 'Новое количество',
        'Yordamchi: dollardan so\'mga avtomatik hisoblash': 'Помощник: автоматический пересчёт долларов в сумы',
        'masalan 1.5': 'например 1.5',
        'masalan 12000': 'например 12000',
        'masalan 20': 'например 20',
        'olgan mahsulotlari': 'взятые товары',
        '— Yangi xaridor —': '— Новый клиент —',

        # --- Yangi GUI (PySide6) satrlari ---
        '"{name}" mahsulotidan omborda yetarli miqdor yo\'q.': 'Недостаточно товара "{name}" на складе.',
        '"{name}" mahsulotini o\'chirmoqchimisiz?': 'Удалить товар "{name}"?',
        '"{name}" qarzini o\'chirmoqchimisiz?': 'Удалить долг "{name}"?',
        '"{name}" — {amount} so\'m to\'landi deb belgilaymi?': 'Отметить "{name}" — {amount} сум как оплаченный?',
        '\'openpyxl\' kutubxonasi o\'rnatilmagan.': 'Библиотека \'openpyxl\' не установлена.',
        '(jami)': '(итого)',
        'Avtomatik chop etib bo\'lmadi. Fayl saqlangan: {path} ({err})': 'Не удалось напечатать автоматически. Файл сохранён: {path} ({err})',
        'Avtomatik chop etib bo\'lmadi. Rasm saqlangan: {path} ({err})': 'Не удалось напечатать автоматически. Изображение сохранено: {path} ({err})',
        'Avval jadvaldan mahsulotni tanlang.': 'Сначала выберите товар из таблицы.',
        'Avval jadvaldan qarzdorni tanlang.': 'Сначала выберите должника из таблицы.',
        'Avval jadvaldan sotuvni tanlang.': 'Сначала выберите продажу из таблицы.',
        'Avval savatdan mahsulotni tanlang.': 'Сначала выберите товар в корзине.',
        'Bekor qilindi': 'Отменено',
        'Bosh sahifa': 'Главная',
        'Bu mahsulot omborda qolmagan.': 'Этого товара нет на складе.',
        'Bu mahsulotda shtrix kod yo\'q.': 'У этого товара нет штрихкода.',
        'Bu qarz allaqachon to\'langan.': 'Этот долг уже оплачен.',
        'Bugungi foyda': 'Прибыль за сегодня',
        'Bugungi kun allaqachon yopilgan.': 'Сегодняшний день уже закрыт.',
        'Bugungi kun muvaffaqiyatli yopildi.': 'Сегодняшний день успешно закрыт.',
        'Bugungi kunni yopmoqchimisiz? Bu amalni ortga qaytarib bo\'lmaydi.': 'Закрыть сегодняшний день? Это действие нельзя отменить.',
        'Bugungi savdo (nasiya)': 'Продажи сегодня (в долг)',
        'Bunday mahsulot allaqachon bor': 'Такой товар уже существует',
        'Chegirma': 'Скидка',
        'Chek printerga yuborildi.': 'Чек отправлен на печать.',
        'Dublikat mahsulot yaratilmadi. Xohlasangiz nomni o\'zgartirib qayta urinib ko\'ring.': 'Дубликат товара не создан. При желании измените название и попробуйте снова.',
        'Excel faylni saqlash': 'Сохранить файл Excel',
        'Excel\'ga eksport': 'Экспорт в Excel',
        'Fayl saqlandi': 'Файл сохранён',
        'Foyda': 'Прибыль',
        'Grafik modul (QtCharts) mavjud emas.': 'Модуль графиков (QtCharts) недоступен.',
        'Hisobot 0 ga tushirildi.': 'Отчёт сброшен до нуля.',
        'Jami': 'Итого',
        'Kam qolgan mahsulotlar': 'Товары с низким остатком',
        'Kod': 'Код',
        'Kun yopilishlari': 'Закрытые дни',
        'Kunduzgi rejim': 'Дневной режим',
        'Kunlik foyda': 'Дневная прибыль',
        'Kutilayotgan foyda': 'Ожидаемая прибыль',
        'Mahsulot ma\'lumotlari yangilandi.': 'Данные товара обновлены.',
        'Mahsulot miqdori yangilandi.': 'Количество товара обновлено.',
        'Mahsulot nomi bo\'yicha qidirish...': 'Поиск по названию товара...',
        'Mahsulot omborga qo\'shildi.': 'Товар добавлен на склад.',
        'Mahsulot qidirish...': 'Поиск товара...',
        'Mahsulot qo\'shish': 'Добавить товар',
        'Miqdor musbat son bo\'lishi kerak.': 'Количество должно быть положительным числом.',
        'Miqdor yangilandi.': 'Количество обновлено.',
        'Miqdorni to\'g\'ri kiriting (masalan: 0.9).': 'Введите правильное количество (например: 0.9).',
        'Naqd foyda': 'Прибыль наличными',
        'Naqd savdo': 'Продажи наличными',
        'Nasiya foyda': 'Прибыль в долг',
        'Nasiya savdo': 'Продажи в долг',
        'Nasiyaga savdo': 'Продажа в долг',
        'Nusxa saqlandi': 'Копия сохранена',
        'O\'chirildi': 'Удалено',
        'O\'chirish (omborga qaytarish)': 'Удалить (вернуть на склад)',
        'Olgan mahsulotlarini ko\'rish': 'Просмотреть взятые товары',
        'Omborda faqat {qty} bor.': 'На складе есть только {qty}.',
        'Printerlar royxati olinmadi': 'Не удалось получить список принтеров',
        'Qarzdorlar daftari': 'Книга должников',
        'Qo\'shildi': 'Добавлено',
        'Saqlab bolmadi': 'Не удалось сохранить',
        'Savat bo\'sh.': 'Корзина пуста.',
        'Savdo': 'Продажи',
        'Savdo tarixi': 'История продаж',
        'Shtrix kod printerga yuborildi ({n} ta nusxa).': 'Штрихкод отправлен на печать ({n} копий).',
        'Shtrix kodni chop etish': 'Печать штрихкода',
        'Shtrix kodni saqlash': 'Сохранить штрихкод',
        'Shtrix kodni skanerlang yoki kiriting...': 'Отсканируйте или введите штрихкод...',
        'Sotuv o\'chirildi, mahsulot omborga qaytarildi.': 'Продажа удалена, товар возвращён на склад.',
        'To\'landi': 'Оплачено',
        'To\'landi deb belgilash': 'Отметить как оплаченное',
        'Tungi rejim': 'Ночной режим',
        'Yangilandi': 'Обновлено',
        'Yopilgan vaqti:': 'Закрыто в:',
        'jami': 'итого',
        'mos mahsulot topilmadi': 'подходящий товар не найден',
        'naqd + nasiya': 'нал. + в долг',
        'naqd va nasiya': 'нал. и в долг',
        'naqd/karta': 'нал./карта',
        'qarz to\'langanda': 'при оплате долга',
        'qarzga berilgan': 'выдано в долг',
        'qoshildi': 'добавлено',
        'sabab noma\'lum': 'причина неизвестна',
        'so\'nggi {n} kun': 'последние {n} дней',
        'tan narxi bo\'yicha': 'по себестоимости',
        'to\'lanmagan': 'не оплачено',
        '{n} ta': '{n} шт.',

        'dona': 'шт',
        'Bugungi savdo (naqd)': 'Продажи сегодня (нал.)',
        'Bugungi foyda (naqd)': 'Прибыль сегодня (нал.)',
        'Bugungi nasiya (qarzga)': 'Продажи сегодня (в долг)',
        'sof foyda': 'чистая прибыль',
        'sof foyda (to\'langan nasiyalar bilan)': 'чистая прибыль (включая оплаченные долги)',
        'Nasiya foydasi': 'Прибыль с долга',
        'kutilayotgan (hali to\'lanmagan)': 'ожидается (ещё не оплачено)',
        'foyda': 'прибыль',
        'nasiya foydasi (kutilayotgan)': 'прибыль с долга (ожидается)',
        '{n} ta chek': '{n} чеков',
        'kutilayotgan foyda: {v} so\'m': 'ожидаемая прибыль: {v} сум',
        'Ombor qiymati': 'Стоимость склада',
        '{n} nomdagi mahsulot': '{n} товаров',
        'Qarzdorlik': 'Задолженность',
        '{n} kishi': '{n} человек',
        'joriy holat': 'текущее состояние',
        'Kunduzgi': 'Светлая',
        'Tungi': 'Тёмная',
        'Ulanishni tekshirish': 'Проверить соединение',
        '⚠️ Bot Token kiritilmagan.': '⚠️ Bot Token не введён.',
        'Tekshirilmoqda…': 'Проверяется…',
        '№': '№',
        'JAMI': 'ИТОГО',
        'Naqd': 'Наличные',
        'Sana': 'Дата',
        'naqd': 'наличные',
        'Davr:': 'Период:',
        'Narxi': 'Цена',
        'Savat': 'Корзина',
        'Summa': 'Сумма',
        'Miqdor': 'Кол-во',
        'Sotish': 'Продать',
        'Yopish': 'Закрыть',
        'nasiya': 'в долг',
        'Hisobot': 'Отчёт',
        'Miqdor:': 'Кол-во:',
        'Miqdori': 'Количество',
        'Omborda': 'На складе',
        'Saqlash': 'Сохранить',
        'Mahsulot': 'Товар',
        'Miqdori:': 'Количество:',
        "Qo'llash": 'Применить',
        "Qo'shish": 'Добавить',
        '  Sotuv  ': '  Продажи  ',
        "O'chirish": 'Удалить',
        'Tan narxi': 'Себестоимость',
        '  Asosiy  ': '  Главная  ',
        "+ Qo'shish": '+ Добавить',
        'Bot Token:': 'Bot Token:',
        'Chop etish': 'Печать',
        'Jami foyda': 'Общая прибыль',
        'Jami savdo': 'Общие продажи',
        'NAQD SOTUV': 'ПРОДАЖИ НАЛИЧНЫМИ',
        'Shtrix kod': 'Штрихкод',
        'Tahrirlash': 'Изменить',
        '  Hisobot  ': '  Отчёт  ',
        'Chek tayyor': 'Чек готов',
        'Mahsulotlar': 'Товары',
        '🚫 Rad etish': '🚫 Отклонить',
        'Bekor qilish': 'Отмена',
        "Jami: 0 so'm": "Итого: 0 so'm",
        'Kunni yopish': 'Закрыть день',
        'Mahsulotlari': 'Товары',
        "O'zgartirish": 'Изменить',
        'Qarz daftari': 'Долговая книга',
        'Sotish narxi': 'Цена продажи',
        'Sotuv qilish': 'Оформить продажу',
        'Bugungi holat': 'Статус на сегодня',
        "Ma'lumot yo'q": 'Нет данных',
        'Mahsulot nomi': 'Название товара',
        'Olib tashlash': 'Убрать',
        'Plastik karta': 'Карта',
        'Chek chiqarish': 'Печать чека',
        'Chek printeri:': 'Принтер чеков:',
        'Kengligi (mm):': 'Ширина (мм):',
        'Telefon raqami': 'Номер телефона',
        'Yopilgan vaqti': 'Закрыто в',
        '  Mahsulotlar  ': '  Товары  ',
        'Kun tanlanmagan': 'День не выбран',
        'NASIYA (QARZGA)': 'В ДОЛГ',
        "O'lchov birligi": 'Единица измерения',
        'Sotuvlar tarixi': 'История продаж',
        'Yopilgan kunlar': 'Закрытые дни',
        '✅ Ruxsat berish': '✅ Разрешить',
        '  Qarz daftari  ': '  Долговая книга  ',
        'Balandligi (mm):': 'Высота (мм):',
        "Qog'oz kengligi:": 'Ширина бумаги:',
        "Savatga qo'shish": 'Добавить в корзину',
        'Savatni tozalash': 'Очистить корзину',
        "Yorliq o'lchami:": 'Размер этикетки:',
        "   DO'KON DAFTARI": '   ЖУРНАЛ МАГАЗИНА',
        'Chiqarib tashlash': 'Удалить',
        'Hisobotni tozalash': 'Сбросить отчёт',
        'Mahsulot qidirish:': 'Поиск товара:',
        'Ruxsat berilganlar': 'Разрешённые',
        '  Sotuvlar tarixi  ': '  История продаж  ',
        '  Yopilgan kunlar  ': '  Закрытые дни  ',
        'Ombordagi kamchilik': 'Нехватка на складе',
        "Qarz summasi (so'm)": "Сумма долга (so'm)",
        'Boshqa joyga saqlash': 'Сохранить в другом месте',
        "Eng ko'p sotilganlar": 'Хиты продаж',
        'Shtrix kod printeri:': 'Принтер этикеток:',
        'Telegram sozlamalari': 'Настройки Telegram',
        "Miqdorni o'zgartirish": 'Изменить количество',
        "Qog'oz kengligi (mm):": 'Ширина бумаги (мм):',
        "To'landi / To'lanmadi": 'Оплачено / Не оплачено',
        '⌁ Shtrix kod skaneri:': '⌁ Сканер штрихкода:',
        'Excelga eksport qilish': 'Экспорт в Excel',
        "Kutilayotgan so'rovlar": 'Ожидающие запросы',
        'Shtrix kodni chiqarish': 'Печать штрихкода',
        'Telegram xabarnomalari': 'Уведомления Telegram',
        "To'lov turini tanlang:": 'Выберите способ оплаты:',
        'Xaridor ism-familiyasi': 'ФИО покупателя',
        "Jami qarzdorlik: 0 so'm": "Общий долг: 0 so'm",
        'Kirim (mahsulot keldi):': 'Приход (товар поступил):',
        'Olayotgan mahsulotlari:': 'Забираемые товары:',
        "Qarz daftariga qo'shish": 'Добавить в долговую книгу',
        'Hisobotni 0 ga tushirish': 'Обнулить отчёт',
        'Nasiyaga (qarzga) berish': 'Отдать в долг',
        'Soni (nechta chiqarish):': 'Количество копий:',
        "Mening chat_id'im (admin):": 'Мой chat_id (админ):',
        'Narxni pasaytirish (chegirma)': 'Снизить цену (скидка)',
        'Shtrix kod avtomatik yaratildi': 'Штрихкод сгенерирован автоматически',
        'Qidirish (nom yoki shtrix kod):': 'Поиск (название или штрихкод):',
        "Hozircha kam qolgan mahsulot yo'q": 'Пока нет товаров с низким остатком',
        "Hozircha kutilayotgan so'rov yo'q": 'Пока нет ожидающих запросов',
        'Hozircha hech kimga ruxsat berilmagan': 'Пока никому не разрешено',
        'Nima mahsulot oldi / izoh (ixtiyoriy)': 'Что взял(а) / примечание (необязательно)',
        "Chapdagi ro'yxatdan bir kunni tanlang.": 'Выберите день из списка слева.',
        'Yangi (kelishilgan) narx, 1 dona uchun:': 'Новая (согласованная) цена за единицу:',
        "Tanlangan yozuvni o'chirish (ombor qaytariladi)": 'Удалить запись (товар вернётся на склад)',
        "Bu qarzdor uchun mahsulot ro'yxati kiritilmagan.": 'Список товаров для этого должника не указан.',
        "Bu printerni eslab qol (keyingi safar so'ramasin)": 'Запомнить этот принтер (не спрашивать в следующий раз)',
        "Bu yozuv uchun batafsil ro'yxat saqlanmagan, izoh:": 'Подробный список для этой записи не сохранён, примечание:',
        'Avval nasiyaga olgan xaridordan tanlang (ixtiyoriy)': 'Выберите прежнего покупателя в долг (необязательно)',
        "(O'zgartirsangiz, keyingi chekdan boshlab qo'llanadi)": '(Если изменить, применится со следующего чека)',
        'Shtrix kodni skanerlang — mahsulot avtomatik topiladi': 'Отсканируйте штрихкод — товар найдётся автоматически',
        "Kursor shu yerda bo'lsa, skanerlash avtomatik ishlaydi": 'Если курсор здесь, сканирование работает автоматически',
        'Chek chiqarish uchun bir yoki bir nechta qatorni tanlang ': 'Выберите одну или несколько строк для печати чека ',
        "Sotish narxi — siz mijozga qo'ygan narx (so'm, 1 birlik uchun)": "Цена продажи — цена для клиента (so'm, за единицу)",
        "(Admin chat_id — so'rovlar SIZGA shu yerga kelishi uchun kerak)": '(Admin chat_id — нужен, чтобы запросы приходили ВАМ сюда)',
        "Tan narxi — zavod/optomdan qancha turadi (so'm, 1 birlik uchun)": "Себестоимость — сколько стоит у поставщика (so'm, за единицу)",
        "Har bir yopilgan kunni bosib, o'sha kunning batafsil statistikasini ko'ring.": 'Нажмите на закрытый день, чтобы увидеть подробную статистику.',
        'Masalan: kg/litr/metr tanlasangiz, miqdorga 0.9, 1.5 kabi\nkasr son ham kiritishingiz mumkin.': 'Например, если выбрать кг/литр/метр, можно вводить\nдробные значения, например 0.9, 1.5.',
        'Diqqat': 'Внимание',
        'Diqqat!': 'Внимание!',
        'Xato': 'Ошибка',
        'Saqlandi': 'Сохранено',
        'Tayyor': 'Готово',
        'Topilmadi': 'Не найдено',
        'Yetarli emas': 'Недостаточно',
        'Bajarildi': 'Выполнено',
        'Kun yopildi': 'День закрыт',
        'Printer tanlanmagan': 'Принтер не выбран',
        "Kerakli dastur yo'q": 'Нужная программа отсутствует',
        "Kerakli kutubxonalar yo'q": 'Нужные библиотеки отсутствуют',
        "Shtrix kod yo'q": 'Нет штрихкода',
        "So'nggi 30 kun": 'Последние 30 дней',
        "Elmans materials — Do'kon Daftari": 'Elmans materials — Журнал магазина',
        "To'lov turi": 'Способ оплаты',
        'Chek': 'Чек',
        'Yangi shtrix kod': 'Новый штрихкод',
        'Nasiyaga berish': 'Отдать в долг',
        "Qarzdor qo'shish": 'Добавить должника',
        'Yanvar': 'Январь',
        'Fevral': 'Февраль',
        'Mart': 'Март',
        'Aprel': 'Апрель',
        'May': 'Май',
        'Iyun': 'Июнь',
        'Iyul': 'Июль',
        'Avgust': 'Август',
        'Sentyabr': 'Сентябрь',
        'Oktyabr': 'Октябрь',
        'Noyabr': 'Ноябрь',
        'Dekabr': 'Декабрь',
        "Shtrix kod (skanerdan o'qiting yoki qo'lda kiriting). Bo'sh qoldirsangiz,\ndastur o'zi tasodifiy 13 xonali shtrix kod yaratib beradi.": 'Штрихкод (отсканируйте или введите вручную). Если оставить пустым,\nприложение сгенерирует случайный 13-значный штрихкод.',
        "Har bir sotuvda, ruxsat berilgan odamlarga avtomatik xabar\nyuboriladi. Kimdir botga yozsa, sizga (admin) so'rov keladi.": 'При каждой продаже автоматическое сообщение отправляется\nразрешённым людям. Если кто-то напишет боту, вам (админу) придёт запрос.',
        "Bu yerda belgilangan narx faqat shu sotuvga tegishli bo'ladi —\nmahsulotning ombordagi doimiy narxi o'zgarmaydi.": 'Указанная здесь цена относится только к этой продаже —\nобычная цена товара на складе не меняется.',
        "(Yorliq qog'ozingizning haqiqiy o'lchamini tanlang — bosh harflar\nva narx kesilib qolmasligi uchun)": '(Выберите реальный размер этикетки — чтобы название\nи цена не обрезались)',
        "Bu tugma barcha savdo hisobotini (jami summa, tarix, grafik, yopilgan kunlar) 0 ga\ntushiradi. Mahsulotlar va qarz daftariga tegmaydi. Ortga qaytarib bo'lmaydi!": 'Эта кнопка обнуляет весь отчёт по продажам (общую сумму, историю, график, закрытые дни).\nТовары и долговую книгу это не затрагивает. Отменить нельзя!',
        'Chek chiqarish uchun bir yoki bir nechta qatorni tanlang (bir nechtasini birga tanlash uchun Ctrl yoki Shift tugmasini bosib turing).': 'Выберите одну или несколько строк для печати чека (удерживайте Ctrl или Shift для множественного выбора).',
        # --- 9-bosqich (tema rejimi tugmasi) ---
        'Tema: Kunduzgi': 'Тема: Светлая',
        'Tema: Tungi': 'Тема: Тёмная',
        'Tema: Tizimga mos': 'Тема: Системная',
        'Bugungi foyda (nasiya)': 'Прибыль сегодня (в кредит)',
        'qarz to\'langanda tushadi': 'поступит при оплате долга',
        # --- 10-bosqich (Telegram: til tanlash va narx so'rash) ---
        "Yangi so'rovchi avval botda tilini (o'zbek/ingliz/rus) tanlaydi, "
        "so'ng sizga so'rov keladi. Ruxsat berilgan odamga \"Narx so'rashga "
        "ruxsat berish\" tugmasini bossangiz, u botga mahsulot nomini yozib "
        "narxi va qoldig'ini so'rab bilasiz.":
            'Новый пользователь сначала выбирает язык (узбекский/английский/русский) '
            'в боте, затем вам приходит запрос. Если вы нажмёте "Разрешить запрос цены" '
            'для одобренного пользователя, он сможет написать боту название товара и '
            'узнать его цену и остаток.',
        "Narx so'rashni o'chirish": 'Отключить запрос цены',
        "Narx so'rashga ruxsat berish": 'Разрешить запрос цены',
        # --- 11-bosqich (Telegram Mini App) ---
        'Mini App (bot ilovasi)': 'Мини-приложение (в боте)',
        'Tekshirilmoqda...': 'Проверка...',
        'cloudflared.exe topilmadi': 'cloudflared.exe не найден',
        'Mini App tayyor': 'Мини-приложение готово',
        'Bot menyusidagi "🛒 Narxlar" tugmasi orqali ochiladi': 'Открывается через кнопку "🛒 Цены" в меню бота',
        'Tunnel ochilmoqda, kuting...': 'Открытие туннеля, подождите...',
        'Bot Token saqlansa avtomatik ishga tushadi.': 'Запускается автоматически после сохранения Bot Token.',
        # --- 12-bosqich (ombor qiymati formulasi) ---
        'sotish narxi bo\'yicha': 'по цене продажи',
        # --- 13-bosqich (Excel eksport: jami qatorlari) ---
        'Jami summa': 'Общая сумма',
        'Jami qarz (nasiya)': 'Общий долг (в кредит)',
        'Kutilayotgan foyda (nasiya)': 'Ожидаемая прибыль (в кредит)',
        # --- 14-bosqich (Excel eksport: yangi ustunlar/jami qatori) ---
        'Birlik': 'Единица',
        "Tan narxi (so'm)": 'Себестоимость (сум)',
        "Narxi (so'm)": 'Цена (сум)',
        "Chegirma (so'm)": 'Скидка (сум)',
        "Summa (so'm)": 'Сумма (сум)',
        "Foyda (so'm)": 'Прибыль (сум)',
        'NAQD — jami savdo': 'НАЛИЧНЫЕ — общие продажи',
        'NAQD — jami foyda': 'НАЛИЧНЫЕ — общая прибыль',
        'NASIYA — jami savdo': 'КРЕДИТ — общие продажи',
        'NASIYA — jami foyda': 'КРЕДИТ — общая прибыль',
        'UMUMIY JAMI:': 'ИТОГО:',
        'UMUMIY FOYDA': 'ОБЩАЯ ПРИБЫЛЬ',
        # --- 15-bosqich (qisman to'lov) ---
        "Hozir to'lanadigan summa (ixtiyoriy — xaridor bir qismini darhol to'lasa)":
            "Сумма к оплате сейчас (необязательно — если покупатель сразу платит часть)",
        'Qarzga qoladi': 'Остаток долга',
        'Qisman to\'lash': 'Частичная оплата',
        'Qarzdan qancha to\'landi?': 'Сколько оплачено в счёт долга?',
        'Qolgan qarz': 'Остаток долга',
        'To\'langan summa': 'Оплаченная сумма',
        'To\'lovni qarzdan ayirish': 'Вычесть оплату из долга',
        'To\'lov qarzdan ayirildi. Qolgan qarz: {amount} so\'m': 'Оплата вычтена. Остаток долга: {amount} сум',
        "To'langan summani to'g'ri kiriting (0 dan Jami summagacha).":
            "Введите правильную сумму оплаты (от 0 до общей суммы).",
        "Hozir to'lanadigan summani to'g'ri kiriting.": "Введите правильную сумму, оплачиваемую сейчас.",
        "To'langan summa manfiy bo'lishi mumkin emas.": "Оплаченная сумма не может быть отрицательной.",
        "To'langan summa jami summadan ({total}) katta bo'lishi mumkin emas.":
            "Оплаченная сумма не может превышать общую сумму ({total}).",
        "{paid} to'landi, {debt} qoldi": "{paid} оплачено, {debt} осталось",
    },
}

LANG = "uz"


def tr(text):
    if not text or LANG == "uz":
        return text
    return TRANSLATIONS.get(LANG, {}).get(text, text)


def set_language(code):
    global LANG
    if code not in ("uz", "en", "ru"):
        code = "uz"
    LANG = code
    with _telegram_lock():
        settings = load_settings()
        settings["language"] = code
        save_settings(settings)

LANG = "uz"
_settings_at_start = load_settings()
_lang_initial = _settings_at_start.get("language", "uz")
if _lang_initial in ("uz", "en", "ru"):
    LANG = _lang_initial
