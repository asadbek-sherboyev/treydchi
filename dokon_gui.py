#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import sys
import os
import re
import datetime
import random
import calendar
import math

from PySide6.QtCore import (Qt, QAbstractTableModel, QModelIndex, QTimer, QSize, QRect, QRectF, QPointF,
                             QItemSelectionModel, QThread, Signal, QPropertyAnimation, QEasingCurve, QEvent,
                             QVariantAnimation, QParallelAnimationGroup, QPoint, QElapsedTimer, QObject)
from PySide6.QtGui import (QIcon, QPixmap, QColor, QPainter, QFont, QLinearGradient, QConicalGradient, QGradient, QBrush, QPen,
                             QPainterPath, QCursor, QPalette)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QFileDialog, QHeaderView, QAbstractItemView, QSizePolicy, QFrame,
    QDialog, QButtonGroup, QStackedWidget, QTextEdit, QScrollArea, QGraphicsDropShadowEffect,
    QTableView, QToolTip, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QCheckBox,
    QGraphicsOpacityEffect, QPushButton, QTableWidgetItem,
)

from qfluentwidgets import (
    FluentIcon,
    TableWidget, CheckBox,
    TableView, PushButton, PrimaryPushButton, TransparentPushButton, PillPushButton,
    LineEdit, SearchLineEdit, ComboBox, SpinBox,
    TitleLabel, SubtitleLabel, BodyLabel, StrongBodyLabel, CaptionLabel,
    SimpleCardWidget,
    InfoBar, InfoBarPosition, MessageBox,
    setTheme, Theme, setThemeColor, isDarkTheme, qconfig,
)

import dokon_backend as be

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QSplineSeries, QAreaSeries, QValueAxis
    _CHARTS_AVAILABLE = True
except Exception:
    _CHARTS_AVAILABLE = False


APP_ORG = "Treydchi"
APP_NAME = "Treydchi"
ACCENT_COLOR = "#F0641E"


MAIN_QSS = """
QLabel#totalLabel { font-size: 18px; font-weight: 700; color: %(accent)s; }
""" % {"accent": ACCENT_COLOR}


def detect_system_dark_mode():
    """Operatsion tizimning JORIY Dark/Light rejimini aniqlaydi.

    MUHIM: bu funksiya "Tizimga mos (avto)" tema rejimi uchun qo'shildi --
    foydalanuvchi shikoyat qilgani: Windows tizim darajasida "Dark mode"da
    bo'lsa-yu, dastur "Kunduzgi" temada ochilsa (yoki aksincha), ikkalasi
    bir-biriga mos kelmay qolar edi. Endi tema "Tizimga mos" rejimida
    bo'lganda, dastur shu funksiya orqali WINDOWS/macOS/Linux'ning haqiqiy
    joriy rejimini o'qib, o'zini avtomatik o'sha rejimga moslaydi.

    Qaytaradi: True (tungi/dark), False (kunduzgi/light) yoki None
    (aniqlab bo'lmadi -- masalan noma'lum platforma)."""
    # TEZLIK: avval macOS/Linux'da har 3 soniyada GUI oqimida tashqi
    # jarayon (defaults/gsettings) ishga tushirilar edi -- bu yozish
    # paytida "kechikish"ga sabab bo'lardi. Endi Qt'ning o'zidan (bir zumda)
    # o'qiladi; faqat aniqlab bo'lmasa, eski usulga tushiladi.
    if sys.platform != "win32":
        try:
            from PySide6.QtGui import QGuiApplication
            scheme = QGuiApplication.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return True
            if scheme == Qt.ColorScheme.Light:
                return False
        except Exception:
            pass
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            try:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return value == 0
            finally:
                winreg.CloseKey(key)
        elif sys.platform == "darwin":
            import subprocess
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=2)
            return "dark" in (result.stdout or "").strip().lower()
        else:
            import subprocess
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True, timeout=2)
            return "dark" in (result.stdout or "").strip().lower()
    except Exception:
        return None


def debounced(parent, slot, ms=250):
    """Qidiruv maydoniga har harf yozilganda emas, yozish TO'XTAGANIDAN
    keyin (ms millisekunddan so'ng) bir marta ishlaydigan slot qaytaradi.
    Shu bilan har harfda bazadan qayta yuklash va jadvalni qayta chizish
    yo'qoladi va yozish tez bo'ladi."""
    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.setInterval(ms)
    timer.timeout.connect(slot)
    return lambda *_args: timer.start()


def theme_bg_hex():
    """Joriy tema (dark/light) uchun aniq fon rangi.

    MUHIM TUZATISH: qfluentwidgets'ning setTheme() chaqiruvi faqat o'zining
    ichki komponentlariga (SimpleCardWidget, TableView va h.k.) mos QSS
    beradi -- lekin oddiy QWidget (bizning MainWindow kabi) fon rangi haligacha
    operatsion tizim palitrasidan (macOS'da System Appearance) meros olinadi.
    Natijada: agar Mac tizim darajasida "Dark Mode"da bo'lsa-yu, dastur ichida
    "Kunduzgi" (Light) temani tanlasangiz, oyna foni baribir qora bo'lib
    qolar edi. Buni oldini olish uchun MainWindow'ning fonini har doim shu
    funksiya qaytargan aniq rang bilan o'zimiz belgilaymiz (tizim palitrasiga
    qaramasdan)."""
    return "#202124" if isDarkTheme() else "#f5f6f8"


def apply_window_background(widget):
    """Berilgan top-level widget uchun temaga mos ANIQ fon rangini majburan
    o'rnatadi (macOS'dagi tizim Dark/Light rejimidan mustaqil ravishda)."""
    widget.setObjectName("themedRoot")
    widget.setAutoFillBackground(True)
    widget.setStyleSheet(f"#themedRoot {{ background-color: {theme_bg_hex()}; }}")


class ImageZoomOverlay(QWidget):
    """MUHIM (foydalanuvchi so'rovi bilan): mahsulot jadvalidagi kichik
    rasmga (thumbnail) bosilganda, rasmni KATTALASHTIRIB, qorong'u fon
    ustida ko'rsatadi. Rasmning o'zidan TASHQARI istalgan joyga bosilsa,
    chiroyli so'nish animatsiyasi bilan yopiladi; ochilganda ham yumshoq
    paydo bo'lish animatsiyasi bor."""

    def __init__(self, host_window, pixmap):
        super().__init__(host_window)
        self._host_window = host_window
        self.setStyleSheet("background-color: rgba(0, 0, 0, 165);")
        self.setGeometry(host_window.rect())

        self.image_label = QLabel(self)
        max_w = max(200, int(host_window.width() * 0.8))
        max_h = max(200, int(host_window.height() * 0.8))
        scaled = pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.setStyleSheet(
            "background: white; border-radius: 14px; padding: 10px;")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.adjustSize()
        self.image_label.move(
            (self.width() - self.image_label.width()) // 2,
            (self.height() - self.image_label.height()) // 2)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)

        host_window.installEventFilter(self)
        self.show()
        self.raise_()

        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def eventFilter(self, obj, event):
        if obj is self._host_window and event.type() == QEvent.Resize:
            self.setGeometry(self._host_window.rect())
            self.image_label.move(
                (self.width() - self.image_label.width()) // 2,
                (self.height() - self.image_label.height()) // 2)
        return False

    def mousePressEvent(self, event):
        # Rasmning O'ZIGA emas, atrofidagi qorong'u fonga bosilgandagina
        # yopiladi -- rasmning ustiga bosish esa hech narsa qilmaydi.
        if not self.image_label.geometry().contains(event.pos()):
            self._close_animated()

    def _close_animated(self):
        try:
            self._host_window.removeEventFilter(self)
        except Exception:
            pass
        anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        anim.setDuration(150)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self.deleteLater)
        anim.start()
        self._closing_anim = anim  # animatsiya tugaguncha "tirik" saqlanishi uchun


class ThemedDialog(QDialog):
    """Barcha dialog oynalar shundan meros oladi. MUHIM TUZATISH: oddiy
    QDialog fon rangini operatsion tizim palitrasidan (macOS Dark Mode)
    meros oladi, shuning uchun dastur ichida Kunduzgi tema tanlangan bo'lsa
    ham, agar Mac tizim darajasida Dark Mode'da bo'lsa, dialog foni baribir
    qora bo'lib qolar edi. apply_window_background() shu muammoni tuzatadi."""

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_window_background(self)

    def showEvent(self, event):
        super().showEvent(event)
        # Dialog yumshoq paydo bo'ladi (bir marta, 160 ms).
        if getattr(self, "_faded_in", False):
            return
        self._faded_in = True
        try:
            self.setWindowOpacity(0.0)
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(160)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(lambda: self.setWindowOpacity(1.0))
            anim.start()
            self._fade_anim = anim
        except Exception:
            try:
                self.setWindowOpacity(1.0)
            except Exception:
                pass


def make_scrollable(page_widget, margins=(24, 20, 24, 24), spacing=14):
    """Sahifa uchun QScrollArea o'rnatadi va QVBoxLayout qaytaradi (ichiga
    tarkib qo'shish uchun). MUHIM TUZATISH: standart QScrollArea/viewport
    o'zining ICHKI fonini (QPalette::Base) operatsion tizim palitrasidan
    chizadi -- bu bizning maxsus temamizga (dark/light) mos kelmay, tungi
    rejimda "qora dog'" ko'rinishidagi nomuvofiqlikka olib kelardi. Shuning
    uchun scroll area, uning viewport'i va ichidagi konteyner butunlay
    shaffof (transparent) qilib belgilanadi -- shunda orqadagi asosiy oyna
    foni (apply_window_background bilan boshqariladigan) muammosiz ko'rinadi."""
    scroll = QScrollArea(page_widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    container = QWidget()
    container.setStyleSheet("background: transparent;")
    scroll.setWidget(container)
    scroll.viewport().setStyleSheet("background: transparent;")

    outer = QVBoxLayout(container)
    outer.setContentsMargins(*margins)
    outer.setSpacing(spacing)

    page_layout = QVBoxLayout(page_widget)
    page_layout.setContentsMargins(0, 0, 0, 0)
    page_layout.addWidget(scroll)
    return outer


def fix_table_hover_highlight(table):
    """Jadval (TableView) uchun sichqoncha ustidan o'tganda/bosilganda
    paydo bo'ladigan NOTO'G'RI ko'rinishni tuzatadi.

    MUHIM TUZATISH: qfluentwidgets.TableView butun qatorni yumshoq,
    shaffof rangda belgilaydi (o'zining custom delegate'i orqali) -- lekin
    bundan TASHQARI, Qt'ning standart uslubi "joriy katakcha"ni (current
    cell, ya'ni sichqoncha bosgan/ustidan turgan aniq bir katakcha) alohida
    QPalette.Highlight rangida (endi bu rang -- dasturning ACCENT rangi,
    to'q sariq) TO'LIQ bo'yab qo'yar edi. Natijada foydalanuvchi
    ta'kidlaganidek: bitta katakcha boshqalaridan farqli, kattaroq va
    yorqin sariq bo'lib "sakrab" ko'rinardi. Bu funksiya native
    Highlight/HighlightedText ranglarini shaffof qilib, faqat
    qfluentwidgets'ning o'zi chizadigan (butun qatorni bir xilda
    belgilaydigan) uslub qoladi."""
    from PySide6.QtGui import QPalette
    pal = table.palette()
    pal.setColor(QPalette.Highlight, Qt.transparent)
    pal.setColor(QPalette.HighlightedText, pal.color(QPalette.Text))
    pal.setColor(QPalette.Inactive, QPalette.Highlight, Qt.transparent)
    pal.setColor(QPalette.Inactive, QPalette.HighlightedText, pal.color(QPalette.Text))
    table.setPalette(pal)


# =============================================================================
# "Liquid glass" statistikaviy kartochka — QPainter bilan qo'lda chizilgan
# (gradient fon + yuqorida shaffof "shisha" yaltirash chizig'i), shunda
# ranglar HECH QACHON xira/yuvilib ketmaydi va SimpleCardWidget'ning o'zi
# tema ustiga qo'yadigan shaffof qatlami matnni "ko'rinmas" qilib qo'ymaydi.
# =============================================================================

def _mix_color(a, b, t):
    """Ikki rangni t (0..1) nisbatda aralashtiradi."""
    t = max(0.0, min(1.0, float(t)))
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t),
                  int(a.alpha() + (b.alpha() - a.alpha()) * t))


_NEON_PAIRS = {
    "#F0641E": ("#FF9A1F", "#FF2D95"),   # to'q sariq -> pushti
    "#2ECC71": ("#2ECC71", "#00E5FF"),   # yashil -> ko'k-havorang
    "#7C5CFC": ("#8A6BFF", "#00E0FF"),   # binafsha -> havorang
    "#E5484D": ("#FF3B5C", "#FFC83D"),   # qizil -> sariq
}


def neon_pair(accent):
    """Kartochka rangi bilan BIRLASHIB ketmaydigan, ajralib turadigan ikki
    rangli neon (gradient) juftligini qaytaradi."""
    if not accent:
        return QColor("#5AA9FF"), QColor("#B26BFF")
    pair = _NEON_PAIRS.get(str(accent).upper())
    if pair:
        return QColor(pair[0]), QColor(pair[1])
    base = QColor(accent)
    second = QColor.fromHsl((base.hue() + 150) % 360, 255, 150)
    return base.lighter(115), second


_LIFT = 8


class GlowHalo(QWidget):
    """Kartochka ORQASIDA turadigan, ikki rangli (gradient) neon nur. Kartochka
    bilan bir xil ota-vidjet ichida, uning ostida joylashadi."""

    M = 30

    def __init__(self, parent, c1, c2):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._c1 = QColor(c1)
        self._c2 = QColor(c2)
        self._t = 0.0
        self._angle = 0.0

    def set_t(self, t):
        self._t = float(t)
        self.update()

    def set_angle(self, a):
        self._angle = float(a)
        self.update()

    def paintEvent(self, event):
        if self._t <= 0.002:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        m = self.M
        up = _LIFT * self._t
        inner = QRectF(m, m + _LIFT - up, self.width() - 2 * m, self.height() - 2 * m - _LIFT)
        for i in range(m, 0, -1):
            k = 1.0 - i / float(m)
            alpha = int(80 * self._t * (k ** 2.2))
            if alpha <= 0:
                continue
            r = inner.adjusted(-i, -i, i, i)
            grad = QConicalGradient(r.center(), -self._angle)
            a = QColor(self._c1)
            a.setAlpha(alpha)
            b = QColor(self._c2)
            b.setAlpha(alpha)
            grad.setColorAt(0.0, a)
            grad.setColorAt(0.5, b)
            grad.setColorAt(1.0, a)
            p.setPen(QPen(QBrush(grad), 1.3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 14.0 + i, 14.0 + i)
        p.end()


class HoverGlow(QObject):
    """Sichqoncha vidjet ustiga borganda uning atrofida yumshoq "neon"
    nur (accent rangda) silliq paydo bo'ladi, ketganda silliq so'nadi."""

    def __init__(self, widget, color=None, radius=24, alpha=180):
        super().__init__(widget)
        self._w = widget
        self._color = QColor(color or ACCENT_COLOR)
        self._color.setAlpha(alpha)
        self._radius = radius
        self._eff = None
        self._anim = None
        self._t = 0.0
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Enter:
            self._show()
        elif t in (QEvent.Leave, QEvent.Hide):
            self._hide()
        return False

    def _show(self):
        try:
            if self._eff is None:
                eff = QGraphicsDropShadowEffect(self._w)
                col = QColor(self._color)
                col.setAlpha(0)
                eff.setColor(col)
                eff.setOffset(0, 0)
                eff.setBlurRadius(float(self._radius))
                self._w.setGraphicsEffect(eff)
                self._eff = eff
                self._t = 0.0
            self._animate(1.0, None)
        except Exception:
            pass

    def _hide(self):
        if self._eff is None:
            return
        try:
            self._animate(0.0, self._remove)
        except Exception:
            self._remove()

    def _animate(self, end, done):
        if self._anim is not None:
            self._anim.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(240)
        anim.setStartValue(float(getattr(self, "_t", 0.0)))
        anim.setEndValue(float(end))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._on_t)
        if done is not None:
            anim.finished.connect(done)
        anim.start()
        self._anim = anim

    def _on_t(self, v):
        self._t = float(v)
        if self._eff is not None:
            col = QColor(self._color)
            col.setAlpha(int(self._color.alpha() * self._t))
            self._eff.setColor(col)

    def _remove(self):
        if self._eff is not None:
            try:
                self._w.setGraphicsEffect(None)
            except Exception:
                pass
            self._eff = None


class GlassCard(QFrame):
    """Rangli statistikaviy kartochka -- FLAT (tekis) dizayn. `accent`
    berilsa (masalan "#F0641E"), fon shu rangning bir xil (tekis) rangi
    bilan chiziladi va matn OQ rangda bo'ladi. `accent=None` bo'lsa, joriy
    temaga (och/tungi) mos neytral fon va ANIQ, har doim ko'rinadigan matn
    rangi ishlatiladi.

    MUHIM: ilgari bu yerda "liquid glass" (shishasimon, yaltiroq) effekti
    bor edi (gradient fon + yuqorida shaffof yaltirash chizig'i) -- foydala
    nuvchi so'rovi bo'yicha bu effekt olib tashlandi, endi kartochka oddiy,
    bir xil (flat) rangda chiziladi."""

    def __init__(self, accent=None, parent=None):
        super().__init__(parent)
        self.accent = accent
        self.setMinimumHeight(100)
        self.setAttribute(Qt.WA_StyledBackground, False)
        # Hover effekti: kartochka biroz tepaga ko'tariladi va orqasidan
        # accent rangda "neon" nur chiqadi.
        self._hovering = False
        self._lift_t = 0.0
        self._base_pos = None
        self._base_margins = None
        self._halo = None
        self._neon = neon_pair(accent)
        self._lift_anim = QVariantAnimation(self)
        self._lift_anim.setDuration(260)
        self._lift_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._lift_anim.valueChanged.connect(self._on_lift)
        self._lift_anim.finished.connect(self._on_lift_finished)
        self._angle = 0.0
        self._spin = QVariantAnimation(self)
        self._spin.setStartValue(0.0)
        self._spin.setEndValue(360.0)
        self._spin.setDuration(2000)
        self._spin.setLoopCount(-1)
        self._spin.setEasingCurve(QEasingCurve.Linear)
        self._spin.valueChanged.connect(self._on_spin)
        self._poll = QTimer(self)
        self._poll.setInterval(60)
        self._poll.timeout.connect(self._check_cursor)

    def enterEvent(self, event):
        super().enterEvent(event)
        self._begin_hover()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._reset_hover()

    def _begin_hover(self):
        if self._hovering:
            return
        try:
            self._hovering = True
            parent = self.parentWidget()
            if parent is None:
                self._hovering = False
                return
            if self._base_pos is None:
                self._base_pos = self.pos()
            self.raise_()
            if self._halo is not None:
                M0 = GlowHalo.M
                self._halo.setGeometry(self.geometry().adjusted(-M0, -M0, M0, M0))
            if self._halo is None:
                c1, c2 = neon_pair(self.accent)
                self._neon = (c1, c2)
                halo = GlowHalo(parent, c1, c2)
                halo.setGeometry(self.geometry().adjusted(-GlowHalo.M, -GlowHalo.M, GlowHalo.M, GlowHalo.M))
                halo.stackUnder(self)
                halo.show()
                self._halo = halo
            self._animate_lift(1.0)
            self._poll.start()
        except Exception:
            self._reset_hover()

    def _on_spin(self, v):
        self._angle = float(v)
        if self._halo is not None:
            self._halo.set_angle(self._angle)
        self.update()

    def _animate_lift(self, end):
        if end > 0.5:
            if self._spin.state() != QVariantAnimation.State.Running:
                self._spin.start()
        self._lift_anim.stop()
        self._lift_anim.setStartValue(float(self._lift_t))
        self._lift_anim.setEndValue(float(end))
        self._lift_anim.start()

    def _on_lift(self, v):
        self._lift_t = float(v)
        self._apply_margins()
        if self._halo is not None:
            self._halo.set_t(self._lift_t)
        self.update()

    def _apply_margins(self):
        lay = self.layout()
        if lay is None:
            return
        if self._base_margins is None:
            self._base_margins = lay.contentsMargins()
        m0 = self._base_margins
        up = int(round(_LIFT * self._lift_t))
        lay.setContentsMargins(m0.left(), m0.top() + _LIFT - up, m0.right(), m0.bottom() + up)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_margins()

    def _body_rect(self):
        up = _LIFT * self._lift_t
        return QRectF(0.5, _LIFT - up + 0.5, self.width() - 1.0, self.height() - _LIFT - 1.0)

    def _on_lift_finished(self):
        if not self._hovering and self._lift_t <= 0.001:
            self._reset_hover()

    def _check_cursor(self):
        parent = self.parentWidget()
        if parent is None or self._base_pos is None:
            self._end_hover()
            return
        rect = QRect(parent.mapToGlobal(self._base_pos), self.size())
        if not rect.contains(QCursor.pos()):
            self._end_hover()

    def _end_hover(self):
        self._hovering = False
        self._poll.stop()
        self._animate_lift(0.0)

    def _reset_hover(self):
        self._hovering = False
        self._poll.stop()
        self._lift_anim.stop()
        self._spin.stop()
        self._lift_t = 0.0
        self._apply_margins()
        self._base_pos = None
        if self._halo is not None:
            self._halo.hide()
            self._halo.deleteLater()
            self._halo = None
        self.update()

    def _colors(self):
        dark = isDarkTheme()
        if self.accent:
            fill = QColor(self.accent)
            text_color = QColor("white")
            sub_color = QColor(255, 255, 255, 225)
        else:
            if dark:
                fill = QColor(50, 52, 58)
                text_color = QColor(240, 241, 243)
                sub_color = QColor(190, 194, 200)
            else:
                fill = QColor(248, 249, 250)
                text_color = QColor(27, 31, 35)
                sub_color = QColor(91, 101, 112)
        return fill, text_color, sub_color

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self._body_rect()
        radius = 14.0

        fill, _text, _sub = self._colors()

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(fill))
        painter.drawPath(path)

        # Yupqa tashqi konturi (border) — biroz aniqlik berish uchun.
        border_color = QColor(255, 255, 255, 30) if self.accent else \
            (QColor(255, 255, 255, 18) if isDarkTheme() else QColor(0, 0, 0, 15))
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        # Hover: chetida ikki rangli yorqin neon chiziq
        if self._lift_t > 0.01:
            c1, c2 = self._neon
            a = QColor(c1)
            a.setAlpha(int(170 * self._lift_t))
            b = QColor(c2)
            b.setAlpha(int(170 * self._lift_t))
            grad = QConicalGradient(rect.center(), -self._angle)
            grad.setColorAt(0.0, a)
            grad.setColorAt(0.5, b)
            grad.setColorAt(1.0, a)
            painter.setPen(QPen(QBrush(grad), 2.0))
            painter.drawPath(path)

        super().paintEvent(event)


_COUNT_LAST = {}
_COUNT_PAT = re.compile(r"^(-?[\d ]*\d)(.*)$")


def _animate_count(label, text, key):
    """Kartochkadagi raqamni oldingi qiymatdan yangisiga silliq "sanab"
    o'tkazadi (birinchi marta -- 0 dan). Qiymat o'zgarmagan bo'lsa,
    animatsiya bo'lmaydi."""
    m = _COUNT_PAT.match(text or "")
    if not m:
        return
    try:
        target = float(m.group(1).replace(" ", ""))
    except ValueError:
        return
    suffix = m.group(2)
    start = _COUNT_LAST.get(key, 0.0)
    _COUNT_LAST[key] = target
    if abs(start - target) < 0.5:
        return
    label.setText(be.fmt_money(start) + suffix)
    anim = QVariantAnimation(label)
    anim.setDuration(650)
    anim.setStartValue(float(start))
    anim.setEndValue(float(target))
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.valueChanged.connect(lambda v: label.setText(be.fmt_money(v) + suffix))
    anim.finished.connect(lambda: label.setText(text))
    anim.start()
    label._count_anim = anim


def make_stat_card(title, value, sub, accent=None, anim_key=None):
    """Bosh sahifa/hisobotdagi rangli statistikaviy kartochka."""
    card = GlassCard(accent=accent)
    _, text_color, sub_color = card._colors()

    v = QVBoxLayout(card)
    v.setContentsMargins(16, 14, 16, 14)
    v.setSpacing(3)

    title_lbl = QLabel(title.upper())
    title_lbl.setStyleSheet(f"font-size:11px; font-weight:700; color:{sub_color.name()}; "
                              f"background:transparent;")
    value_lbl = QLabel(value)
    value_lbl.setStyleSheet(f"font-size:20px; font-weight:800; color:{text_color.name()}; "
                              f"font-family:{be.FONT_MONO_NAME}; background:transparent;")
    sub_lbl = QLabel(sub or "")
    sub_lbl.setStyleSheet(f"font-size:11px; color:{sub_color.name()}; background:transparent;")

    v.addWidget(title_lbl)
    v.addWidget(value_lbl)
    v.addWidget(sub_lbl)
    if anim_key:
        _animate_count(value_lbl, value, anim_key)
    return card


# =============================================================================
# QAbstractTableModel asosidagi jadval modellari
# =============================================================================

def _square_thumbnail_pixmap(full_path, size):
    """Berilgan fayldan aniq KVADRAT (size x size) pixmap yasaydi --
    MUHIM TUZATISH (foydalanuvchi so'rovi bilan): ilgari
    QPixmap.scaled(..., Qt.KeepAspectRatioByExpanding) ishlatilgan edi,
    lekin bu usul natijada aniq kvadrat pixmap QAYTARMAYDI (agar manba
    rasm kvadrat bo'lmasa, natija ham to'rtburchak bo'lib qoladi) --
    shuning uchun jadval katagida rasm CHAP TOMONGA surilib, faqat bir
    qismi (masalan ingichka chiziq) ko'rinib qolar edi. Endi avval
    rasmning MARKAZIDAN kvadrat qism kesib olinadi (qanday nisbatda
    bo'lishidan qat'iy nazar), so'ng aniq so'ralgan o'lchamga
    moslashtiriladi -- natija har doim to'g'ri markazlashgan, aniq
    kvadrat rasm bo'ladi."""
    pixmap = QPixmap(full_path)
    if pixmap.isNull():
        return None
    w, h = pixmap.width(), pixmap.height()
    side = min(w, h)
    x = (w - side) // 2
    y = (h - side) // 2
    cropped = pixmap.copy(x, y, side, side)
    return cropped.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


class BaseTableModel(QAbstractTableModel):
    def __init__(self, headers, rows=None, parent=None):
        super().__init__(parent)
        # MUHIM: asl (uz) sarlavha kalitlari alohida saqlanadi, chunki til
        # o'zgarganda ularni be.tr() bilan qaytadan tarjima qilish kerak --
        # oldin sarlavhalar faqat konstruktorda bir marta o'rnatilib, til
        # almashtirilganda hech qachon yangilanmasdi.
        self._header_keys = headers
        self._headers = [be.tr(h) for h in headers]
        self._rows = rows or []

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._headers[section]
        return str(section + 1)

    def set_rows(self, rows):
        # TEZLIK: ma'lumot o'zgarmagan bo'lsa (masalan har 4 soniyada
        # avtomatik yangilashda), jadvalni qayta qurmaymiz -- bu qayta
        # chizish va "qotish"ning oldini oladi.
        if (not getattr(self, "_force_reset", False) and rows is not self._rows
                and rows == self._rows):
            return
        self._force_reset = False
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def retranslate(self):
        """Jadval sarlavhalarini joriy tilga qayta tarjima qiladi."""
        self._force_reset = True
        self._headers = [be.tr(h) for h in self._header_keys]
        if self.columnCount() > 0:
            self.headerDataChanged.emit(Qt.Horizontal, 0, self.columnCount() - 1)

    def row_at(self, row_index):
        if 0 <= row_index < len(self._rows):
            return self._rows[row_index]
        return None


class ProductsTableModel(BaseTableModel):
    # MUHIM (foydalanuvchi so'rovi bilan): mahsulotlar jadvaliga rasm
    # (thumbnail) ustuni qo'shildi -- birinchi (nomsiz) ustun.
    def __init__(self, parent=None):
        super().__init__(["", "Mahsulot nomi", "Shtrix kod", "Tan narxi", "Sotish narxi", "Miqdori"], parent=parent)
        # MUHIM TUZATISH (foydalanuvchi so'rovi bilan): ilgari HAR safar
        # jadval qayta chizilganda (masalan skrol qilinganda) DecorationRole
        # so'ralib, rasm faylini diskdan qayta o'qib, qayta kesib, qayta
        # kichraytirar edi -- bu ko'p qatorli ro'yxatda skrol paytida
        # kompyuterni "qotib-qotib o'tadigan" (lag) qilib qo'yardi. Endi har
        # bir rasm faqat BIR MARTA tayyorlanadi va shu lug'atda (fayl
        # o'zgarish vaqti bilan birga) saqlanadi -- keyingi so'rovlarda
        # qayta ishlov berilmasdan, tayyor holda qaytariladi. Fayl
        # yangilansa (o'zgarish vaqti boshqacha bo'lsa), avtomatik qayta
        # hisoblanadi.
        self._thumb_cache = {}

    def _get_thumbnail(self, image_path):
        if not image_path:
            return None
        full_path = be.get_product_image_full_path(image_path)
        if not full_path:
            return None
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            return None
        cached = self._thumb_cache.get(full_path)
        if cached and cached[0] == mtime:
            return cached[1]
        pixmap = _square_thumbnail_pixmap(full_path, 52)
        if pixmap is not None:
            self._thumb_cache[full_path] = (mtime, pixmap)
        return pixmap

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        pid, name, cost_price, price, qty, unit, barcode, image_path = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 1:
                return name
            if col == 2:
                return barcode or "—"
            if col == 3:
                return f"{be.fmt_money(cost_price)} / {unit}"
            if col == 4:
                return f"{be.fmt_money(price)} / {unit}"
            if col == 5:
                return be.fmt_qty(qty, unit)
        if role == Qt.DecorationRole and col == 0:
            # MUHIM (foydalanuvchi so'rovi bilan): rasm avvalgidan KATTAROQ
            # (52px) va aniq markazlashgan kvadrat qilib ko'rsatiladi --
            # qatorlar ham shunga mos balandroq. Tezlik uchun natija
            # keshlanadi (_get_thumbnail), aks holda skrolda "qotib-qotib
            # o'tish" (lag) yuzaga kelardi.
            return self._get_thumbnail(image_path)
        if role == Qt.TextAlignmentRole and col in (3, 4, 5):
            return Qt.AlignRight | Qt.AlignVCenter
        return None

    def product_id_at(self, row):
        row_data = self.row_at(row)
        return row_data[0] if row_data else None


class CartTableModel(BaseTableModel):
    def __init__(self, parent=None):
        super().__init__(["Mahsulot", "Miqdor", "Narxi", "Summa"], parent=parent)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return item["name"]
            if col == 1:
                return be.fmt_qty(item["qty"], item["unit"])
            if col == 2:
                text = be.fmt_money(item["price"])
                if abs(item["price"] - item.get("list_price", item["price"])) > 1e-9:
                    text += " *"
                return text
            if col == 3:
                return be.fmt_money(item["total"])
        if role == Qt.TextAlignmentRole and col in (1, 2, 3):
            return Qt.AlignRight | Qt.AlignVCenter
        return None


class SalesHistoryTableModel(BaseTableModel):
    def __init__(self, parent=None):
        super().__init__(
            ["Sana / vaqt", "Mahsulot", "Miqdor", "Narxi", "Chegirma", "Summa", "Foyda", "To'lov turi"],
            parent=parent)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        (sid, created_at, date, name, qty, unit, price, list_price, total, profit, ptype, method, pid,
         sale_batch) = row
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return created_at or date
            if col == 1:
                return name
            if col == 2:
                return be.fmt_qty(qty, unit)
            if col == 3:
                return be.fmt_money(price)
            if col == 4:
                discount_total = (list_price - price) * qty if list_price and list_price > price else 0
                return f"-{be.fmt_money(discount_total)}" if discount_total > 0.5 else "—"
            if col == 5:
                return be.fmt_money(total)
            if col == 6:
                return be.fmt_money(profit)
            if col == 7:
                return method or (be.tr("Naqd") if ptype == "naqd" else be.tr("Nasiya"))
        if role == Qt.TextAlignmentRole and col in (2, 3, 4, 5, 6, 7):
            return Qt.AlignRight | Qt.AlignVCenter
        return None

    def sale_id_at(self, row):
        row_data = self.row_at(row)
        return row_data[0] if row_data else None


class DebtsTableModel(BaseTableModel):
    # MUHIM TUZATISH (foydalanuvchi so'rovi bilan -- "to'g'ri hisob-kitob
    # qilmayapti"): avval "Summasi" ustuni FAQAT qolgan qarzni (debts.
    # amount) ko'rsatardi -- bu izohdagi "...qoldi" bilan AYNAN bir xil
    # raqam bo'lib, xaridor qisman to'lagan bo'lsa ham, "Summasi" xuddi
    # to'lov umuman bo'lmagandek ko'rinardi (masalan Summasi=140000,
    # izoh="20000 to'landi, 140000 qoldi" -- 160000lik savdoning qayerga
    # yo'qolib qolgani ko'rinmaydi). Endi "Summasi" ustuni -- izohda
    # to'lov borligi aniqlansa -- TO'LIQ savdo summasini (to'langan +
    # qolgan) ko'rsatadi, shunda qator ichida sonlar mantiqan mos keladi.
    # E'TIBOR: bazadagi debts.amount hamon FAQAT qolgan qarzni saqlaydi
    # (dashboard'dagi "jami qarz" kabi boshqa hisob-kitoblar to'g'ri
    # ishlashi uchun) -- bu faqat KO'RSATISH uchun qo'shimcha hisoblash.
    _NOTE_SPLIT_PAT = re.compile(r"^([\d\s]+)\s*to'landi,\s*([\d\s]+)\s*qoldi$")

    def __init__(self, parent=None):
        super().__init__(["Xaridor", "Telefon", "Summasi", "Mahsulot / izoh", "Sana", "Holati"], parent=parent)

    @classmethod
    def _display_total(cls, amount, note):
        m = cls._NOTE_SPLIT_PAT.match(note or "")
        if not m:
            return amount
        try:
            paid_val = float(m.group(1).replace(" ", ""))
        except ValueError:
            return amount
        return amount + paid_val

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        did, name, phone, amount, note, date, paid = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return name
            if col == 1:
                return phone or ""
            if col == 2:
                return be.fmt_money(self._display_total(amount, note))
            if col == 3:
                return note or ""
            if col == 4:
                return date
            if col == 5:
                return be.tr("To'langan") if paid else be.tr("To'lanmagan")
        if role == Qt.ForegroundRole and col == 5:
            return QColor("#2ECC71") if paid else QColor("#E5484D")
        if role == Qt.TextAlignmentRole and col == 2:
            return Qt.AlignRight | Qt.AlignVCenter
        return None

    def debt_id_at(self, row):
        row_data = self.row_at(row)
        return row_data[0] if row_data else None


class ClosuresTableModel(BaseTableModel):
    def __init__(self, parent=None):
        # MUHIM TUZATISH: foydalanuvchi aslida hafta kuni nomini emas,
        # ODDIY SANANI xohlagan ekan -- faqat "Yopilgan vaqti" (closed_at
        # timestamp) ustuni kerak emas edi. Shuning uchun "Kun" ustuni
        # yana oddiy sanani ko'rsatadi, "Yopilgan vaqti" ustuni esa butunlay
        # olib tashlandi.
        super().__init__(["Sana", "Jami savdo", "Jami foyda"], parent=parent)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        cid, date, closed_at, s_naqd, p_naqd, s_nasiya, p_nasiya = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return date
            if col == 1:
                return be.fmt_money(s_naqd + s_nasiya)
            if col == 2:
                return be.fmt_money(p_naqd + p_nasiya)
        if role == Qt.TextAlignmentRole and col in (1, 2):
            return Qt.AlignRight | Qt.AlignVCenter
        return None

    def closure_at(self, row):
        return self.row_at(row)


class _DebtNoteColorDelegate(QStyledItemDelegate):
    """Qarzdorlar jadvalidagi 'Mahsulot / izoh' ustunida
    "X to'landi, Y qoldi" formatidagi matnni ikki xil rangda chizadi:
    to'langan qismi -- yashil, qolgan qarz qismi -- qizil.
    Boshqa formatdagi izohlar (masalan "Nasiyaga savdo") odatdagidek
    (bir rangda) chiziladi.

    MUHIM TUZATISH: bu ustunga alohida delegate o'rnatilgani sababli
    (setItemDelegateForColumn) jadval kutubxonasi (qfluentwidgets
    TableView) o'zining sichqoncha ustidan o'tganda/tanlanganda qatorni
    "oqartirib" bo'yaydigan fon chizish logikasi bu ustunda ISHLAMAY
    qolgan edi -- chunki o'sha logika asl (table.delegate) delegate
    ichida joylashgan, biz esa uni butunlay almashtirgan edik. Endi
    _paint_row_background() o'sha ASL delegate hali ham kuzatib
    turadigan hover/bosilgan/tanlangan qator holatini (table.delegate.
    hoverRow/pressedRow/selectedRows) o'qib, AYNAN SHU FONNI qo'lda
    qayta chizadi -- shunda bu ustun ham boshqa ustunlar kabi
    "oqarib" ko'rinadi."""

    _PAT = re.compile(r"^(.*\bto'landi)(,\s*)(.*\bqoldi)$")
    _PAID_COLOR = QColor("#2ECC71")
    _DEBT_COLOR = QColor("#E5484D")

    def __init__(self, table):
        super().__init__(table)
        self._table = table

    def _paint_row_background(self, painter, option, index):
        orig = getattr(self._table, "delegate", None)
        if orig is None or not hasattr(orig, "_drawBackground"):
            return
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipping(True)
        painter.setClipRect(option.rect)

        bg_opt = QStyleOptionViewItem(option)
        bg_rect = QRect(option.rect)
        margin = getattr(orig, "margin", 2)
        bg_rect.adjust(0, margin, 0, -margin)
        bg_opt.rect = bg_rect

        row = index.row()
        selected_rows = getattr(orig, "selectedRows", set())
        is_hover = getattr(orig, "hoverRow", -1) == row
        is_pressed = getattr(orig, "pressedRow", -1) == row
        is_alternate = row % 2 == 0 and self._table.alternatingRowColors()
        dark = isDarkTheme()
        c = 255 if dark else 0
        alpha = 0
        if row not in selected_rows:
            if is_pressed:
                alpha = 9 if dark else 6
            elif is_hover:
                alpha = 12
            elif is_alternate:
                alpha = 5
        else:
            if is_pressed:
                alpha = 15 if dark else 9
            elif is_hover:
                alpha = 25
            else:
                alpha = 17

        bg_role = index.data(Qt.BackgroundRole)
        painter.setBrush(bg_role if bg_role else QColor(c, c, c, alpha))
        orig._drawBackground(painter, bg_opt, index)
        painter.restore()

    @staticmethod
    def _is_paid_row(index):
        """Shu qatordagi qarz 'to'landi' deb belgilanganmi -- DebtsTableModel
        qatori (did, name, phone, amount, note, date, paid) formatida."""
        model = index.model()
        row_at = getattr(model, "row_at", None)
        if row_at is None:
            return False
        row_data = row_at(index.row())
        if not row_data or len(row_data) < 7:
            return False
        return bool(row_data[6])

    def paint(self, painter, option, index):
        text = index.data(Qt.DisplayRole)
        m = self._PAT.match(text) if isinstance(text, str) else None

        self._paint_row_background(painter, option, index)

        if not m:
            # MUHIM (foydalanuvchi so'rovi bilan): oddiy (rangsiz) izohlarda
            # -- masalan "Nasiyaga savdo" -- chiziq TORTILMAYDI, qarz
            # to'langan bo'lsa ham. Chiziq FAQAT rangli (yashil/qizil,
            # "X to'landi, Y qoldi" formatidagi) izohlarda chiziladi.
            super().paint(painter, option, index)
            return

        # MUHIM (foydalanuvchi so'rovi bilan): qarz "To'landi" deb
        # belgilansa, izohdagi yashil/qizil matn ustidan (o'rtasidan)
        # chiziq tortiladi -- "hal qilingan" ekanini ko'rsatish uchun.
        # "To'lanmagan"ga qaytarilsa, chiziq darhol yo'qoladi (chunki
        # data() shu paytda qayta chaqiriladi va paid=0 bo'ladi).
        is_paid = self._is_paid_row(index)

        paid_part, sep, debt_part = m.group(1), m.group(2), m.group(3)

        painter.save()
        fm = painter.fontMetrics()
        margin = 4
        rect = option.rect.adjusted(margin, 0, -margin, 0)
        x = rect.left()
        y = rect.top()
        h = rect.height()
        right_limit = rect.right()
        start_x = x

        sep_color = option.palette.color(QPalette.Text)

        paid_w = min(fm.horizontalAdvance(paid_part), max(0, right_limit - x))
        painter.setPen(self._PAID_COLOR)
        painter.drawText(QRect(x, y, paid_w, h), Qt.AlignLeft | Qt.AlignVCenter, paid_part)
        x += paid_w

        sep_w = min(fm.horizontalAdvance(sep), max(0, right_limit - x))
        painter.setPen(sep_color)
        painter.drawText(QRect(x, y, sep_w, h), Qt.AlignLeft | Qt.AlignVCenter, sep)
        x += sep_w

        debt_w = max(0, right_limit - x)
        painter.setPen(self._DEBT_COLOR)
        painter.drawText(QRect(x, y, debt_w, h), Qt.AlignLeft | Qt.AlignVCenter, debt_part)
        end_x = x + min(fm.horizontalAdvance(debt_part), debt_w)

        if is_paid:
            mid_y = y + h // 2
            pen = QPen(sep_color)
            pen.setWidthF(1.4)
            painter.setPen(pen)
            painter.drawLine(start_x, mid_y, end_x, mid_y)

        painter.restore()


class LowStockTableModel(BaseTableModel):
    def __init__(self, parent=None):
        super().__init__(["Mahsulot nomi", "Qoldiq"], parent=parent)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        name, qty, unit = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return name
            if col == 1:
                return be.fmt_qty(qty, unit)
        if role == Qt.ForegroundRole:
            return QColor("#E5484D")
        if role == Qt.TextAlignmentRole and col == 1:
            return Qt.AlignRight | Qt.AlignVCenter
        return None


# =============================================================================
# Kichik yordamchi funksiyalar
# =============================================================================

def info_success(parent, title, content):
    InfoBar.success(title=title, content=content, orient=Qt.Horizontal, isClosable=True,
                     position=InfoBarPosition.TOP, duration=3500, parent=parent)


def info_error(parent, title, content):
    InfoBar.error(title=title, content=content, orient=Qt.Horizontal, isClosable=True,
                   position=InfoBarPosition.TOP, duration=4500, parent=parent)


def info_warning(parent, title, content):
    InfoBar.warning(title=title, content=content, orient=Qt.Horizontal, isClosable=True,
                     position=InfoBarPosition.TOP, duration=4000, parent=parent)


def confirm(parent, title, content):
    box = MessageBox(title, content, parent)
    return box.exec()


# =============================================================================
# ProductDialog — mahsulot qo'shish/tahrirlash
#   + Dollar->so'm avtomatik konvertatsiya (tan narxi uchun)
#   + Foiz qo'shib sotish narxini avtomatik hisoblash
#   + Shtrix kodni darhol chiqarish tugmasi
# =============================================================================

class _BgRemovalWorker(QThread):
    """MUHIM TUZATISH (foydalanuvchi so'rovi bilan): "AI: fonni olib
    tashlash" jarayoni (rembg) -- ayniqsa BIRINCHI marta, model
    internetdan yuklanayotganda -- bir necha o'nlab soniya (hatto
    daqiqalar) davom etishi mumkin. Ilgari bu jarayon to'g'ridan-to'g'ri
    asosiy (GUI) oqimda ishga tushirilgani sababli, shu vaqt davomida
    butun dastur oynasi muzlab, Windows "Not Responding" deb ko'rsatar
    edi. Endi bu og'ir hisoblash ALOHIDA OQIMDA (background thread)
    bajariladi -- dastur oynasi shu vaqt ichida ham to'liq tirik va
    javob beradigan bo'lib qoladi."""
    finished_ok = Signal(str)
    finished_fail = Signal(str)  # "no_rembg" yoki xato matni

    def __init__(self, source_path):
        super().__init__()
        self.source_path = source_path

    def run(self):
        try:
            from rembg import remove as rembg_remove
        except Exception:
            self.finished_fail.emit("no_rembg")
            return
        try:
            from PIL import Image
            import io
            import tempfile
            with open(self.source_path, "rb") as f:
                raw = f.read()
            out_bytes = rembg_remove(raw)
            cut = Image.open(io.BytesIO(out_bytes)).convert("RGBA")

            # Faqat mahsulot turgan (shaffof bo'lmagan) qismini topib,
            # atrofidagi ortiqcha bo'sh joyni kesib tashlaymiz.
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

            # Oq fonga qo'yamiz (alpha-mask orqali).
            white_flat = Image.new("RGB", cut.size, (255, 255, 255))
            white_flat.paste(cut, mask=cut.split()[-1])

            # Markazlashtirib, KVADRAT (oq) tuvalga joylashtiramiz.
            side = max(white_flat.size)
            square = Image.new("RGB", (side, side), (255, 255, 255))
            offset = ((side - white_flat.width) // 2, (side - white_flat.height) // 2)
            square.paste(white_flat, offset)

            max_side = 900
            if side > max_side:
                square = square.resize((max_side, max_side), Image.LANCZOS)

            fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            square.save(tmp_path, "JPEG", quality=90)
            self.finished_ok.emit(tmp_path)
        except Exception as e:
            self.finished_fail.emit(str(e))


class _TelegramBgWorker(QThread):
    """MUHIM TUZATISH (foydalanuvchi so'rovi bilan -- 'Saqlash' yoki
    'Ulanishni tekshirish' bosilganda dastur 'Not Responding' bo'lib
    qolayotgan edi): Telegram serveriga tarmoq so'rovi yuboradigan
    amallar (bot bilan bog'lanishni tekshirish, Mini App menyu
    tugmasini qayta sozlash, xabar yuborish) ilgari to'g'ridan-to'g'ri
    GUI oqimida (tugma bosilgan zahoti) bajarilardi. Agar internet yoki
    Telegram serveriga ulanish sekin bo'lsa -- har bir so'rov 15
    soniyagacha kutishi mumkin, ba'zida ketma-ket bir nechta so'rov
    yuboriladi -- butun oyna shu vaqt davomida muzlab, Windows "Not
    Responding" deb ko'rsatardi. Endi bu amallar ALOHIDA OQIMDA
    bajariladi -- oyna doim tirik va javob beradigan bo'lib qoladi
    (xuddi _BgRemovalWorker'dagi kabi)."""
    finished = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as e:
            result = e
        self.finished.emit(result)


class ProductDialog(ThemedDialog):
    @staticmethod
    def _fmt_num_for_edit(v):
        """Raqamli maydonlarga boshlang'ich matn qo'yishda ishlatiladi.
        MUHIM TUZATISH (foydalanuvchi so'rovi bilan): ilgari str(100.0)
        kabi qiymatlar tahrirlash maydonida "100.0" bo'lib chiqib,
        ko'rinishni chalkashtirar edi. Endi butun songa teng bo'lgan
        floatlar uchun ORTIQCHA ".0" OLIB TASHLANADI (masalan 100.0 ->
        "100"), lekin haqiqiy kasr qismi bo'lsa (masalan 0.123) u
        to'liq saqlanadi (masalan "0.123")."""
        if v is None or v == "":
            return ""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return str(v)
        if f == int(f):
            return str(int(f))
        # Ortiqcha o'nlik nollarni kesib tashlaymiz (masalan 1.50000 -> 1.5),
        # lekin haqiqiy kasr qiymatini yo'qotmaymiz.
        text = ("%f" % f).rstrip("0").rstrip(".")
        return text if text else "0"

    def __init__(self, parent=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle(be.tr("Mahsulot"))
        self.setMinimumWidth(460)
        self.result_data = None

        name0, cost0, price0, qty0, unit0, barcode0, image_path0 = initial or ("", "", "", "", "dona", "", None)

        # MUHIM (foydalanuvchi so'rovi bilan): mahsulot rasmi bilan
        # bog'liq holat -- self._image_action: "keep" (hech narsa
        # o'zgarmadi), "set" (yangi fayl tanlandi, self._new_image_path'da),
        # yoki "remove" (rasm olib tashlandi).
        self._image_action = "keep"
        self._new_image_path = None
        self._existing_image_path = image_path0

        # MUHIM TUZATISH (foydalanuvchi so'rovi bilan): oyna ekranga
        # sig'may, Windows taskbar orqasiga o'tib qolayotgan edi. Endi
        # butun kontent QScrollArea ichiga o'raladi (Saqlash/Bekor qilish
        # tugmalari esa PASTDA, scroll'dan TASHQARIDA, doim ko'rinadigan
        # holda qoladi), va dialogning maksimal balandligi ekran
        # o'lchamiga qarab cheklanadi -- shu bilan taskbar orqasiga hech
        # qachon o'tib ketmaydi.
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        # MUHIM TUZATISH (foydalanuvchi so'rovi bilan): gorizontal skrol
        # umuman OLIB TASHLANDI -- faqat vertikal skrol qoladi. Ichkaridagi
        # tor (masalan dollar/foiz) maydonlar endi setFixedWidth O'RNIGA
        # setMaximumWidth bilan belgilangan (pastda), shu bilan ular kerak
        # bo'lganda siqilib, konteynerga sig'ib ketadi -- gorizontal
        # skrolga hech qachon ehtiyoj qolmaydi.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget(self)
        content.setStyleSheet("background: transparent;")
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 12)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel(be.tr("Mahsulot nomi")))
        self.name_edit = LineEdit(self)
        self.name_edit.setText(str(name0))
        layout.addWidget(self.name_edit)

        # MUHIM (foydalanuvchi so'rovi bilan): har bir mahsulot uchun
        # rasm qo'shish -- fayldan tanlab qo'yish, oldindan ko'rish
        # (preview) va olib tashlash imkoniyati bilan.
        # MUHIM TUZATISH: rasm konteyneri endi PASTDA emas, YON TARAFDA
        # (gorizontal joylashuvda) turadi va KVADRAT shaklga ega.
        layout.addWidget(StrongBodyLabel(be.tr("Mahsulot rasmi (ixtiyoriy)")))
        image_row = QHBoxLayout()
        image_row.setSpacing(12)
        self.image_preview = QLabel(self)
        self.image_preview.setFixedSize(120, 120)
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setStyleSheet(
            "border: 1px solid rgba(128,128,128,0.35); border-radius: 8px;")
        image_row.addWidget(self.image_preview)

        image_btn_col = QVBoxLayout()
        image_btn_col.setSpacing(6)
        pick_image_btn = PushButton(be.tr("Rasm tanlash"), self)
        pick_image_btn.clicked.connect(self._pick_image)
        pick_image_btn.setAutoDefault(False)
        pick_image_btn.setDefault(False)
        image_btn_col.addWidget(pick_image_btn)
        self.remove_image_btn = PushButton(be.tr("Rasmni olib tashlash"), self)
        self.remove_image_btn.clicked.connect(self._remove_image)
        self.remove_image_btn.setAutoDefault(False)
        self.remove_image_btn.setDefault(False)
        image_btn_col.addWidget(self.remove_image_btn)
        # MUHIM (foydalanuvchi so'rovi bilan): "avtomatik kvadrat qilib
        # kesish + oq fonga qo'yish" ixtiyoriy -- faqat shu belgi
        # (checkbox) BOSILGAN bo'lsa ishlaydi, bosilmasa rasm o'zgarishsiz
        # (asl holida) saqlanadi.
        self.auto_crop_check = QCheckBox(be.tr("AI: fonni olib tashlash"), self)
        self.auto_crop_check.setChecked(False)
        self.auto_crop_check.setToolTip(be.tr(
            "Yoqilsa: sun'iy intellekt (rembg) mahsulotni orqa fondan "
            "avtomatik ajratib oladi, oq fonga qo'yadi va markazlashtirib "
            "kvadrat shaklda saqlaydi. Birinchi marta ishlatilganda model "
            "internetdan yuklanishi va bir necha soniya vaqt ketishi "
            "mumkin. Bosilmasa, rasm o'zgarishsiz (asl fon bilan) "
            "saqlanadi."))
        image_btn_col.addWidget(self.auto_crop_check)
        image_btn_col.addStretch(1)
        image_row.addLayout(image_btn_col)
        image_row.addStretch(1)
        layout.addLayout(image_row)
        self._refresh_image_preview()

        layout.addWidget(CaptionLabel(be.tr(
            "Shtrix kod (skanerdan o'qiting yoki qo'lda kiriting). Bo'sh qoldirsangiz,\n"
            "dastur o'zi tasodifiy 13 xonali shtrix kod yaratib beradi.")))
        self.barcode_edit = LineEdit(self)
        self.barcode_edit.setText(str(barcode0 or ""))
        # MUHIM TUZATISH: shtrix kod skaneri kod o'qigandan so'ng avtomatik
        # Enter tugmasini "bosib" yuboradi. Ilgari bu Enter QDialog'ning
        # ichki mexanizmi orqali "Saqlash" tugmasini (u autoDefault=True
        # bo'lgani uchun) ishga tushirib, narx/miqdor kiritilmasdan turib
        # mahsulotni saqlab/chop etib yuborardi. Endi Enter shtrix kod
        # maydonida bosilganda hech narsa saqlanmaydi -- faqat fokus
        # keyingi maydonga o'tadi.
        # MUHIM TUZATISH: fokus ilgari to'g'ridan-to'g'ri "Tan narxi"
        # maydoniga o'tkazilgan edi -- lekin sahifa tartibida "Miqdori"
        # maydoni shtrix kod bilan tan narxi ORASIDA joylashgan, shuning
        # uchun u chetlab o'tilib qolar edi. Endi fokus to'g'ri tartibda,
        # avval "Miqdori" maydoniga o'tadi.
        self.barcode_edit.returnPressed.connect(self._focus_qty_after_scan)
        layout.addWidget(self.barcode_edit)
        # MUHIM TUZATISH: ilgari "Shtrix kodni chiqarish" tugmasi shtrix kod
        # maydonining O'NG TOMONIDA, bir qatorda turardi -- LineEdit
        # cho'zilgani (stretch=1) sababli tugmaga juda kam joy qolib,
        # tugma yozuvi ("Shtrix kodni chiqarish") kesilib, to'liq
        # ko'rinmas edi. Endi bu tugma shtrix kod konteynerining PASTIGA,
        # alohida qatorga o'tkazildi -- shu bilan matn har doim to'liq
        # ko'rinadi.
        print_barcode_row = QHBoxLayout()
        print_barcode_btn = PushButton(be.tr("Shtrix kodni chiqarish"), self)
        print_barcode_btn.clicked.connect(self._print_barcode_now)
        print_barcode_btn.setAutoDefault(False)
        print_barcode_btn.setDefault(False)
        print_barcode_row.addWidget(print_barcode_btn)
        print_barcode_row.addStretch(1)
        layout.addLayout(print_barcode_row)

        row = QHBoxLayout()
        col1 = QVBoxLayout()
        col1.addWidget(BodyLabel(be.tr("O'lchov birligi")))
        self.unit_combo = ComboBox(self)
        self.unit_combo.addItems(be.UNITS)
        if unit0 in be.UNITS:
            self.unit_combo.setCurrentText(unit0)
        col1.addWidget(self.unit_combo)
        row.addLayout(col1)

        col2 = QVBoxLayout()
        col2.addWidget(BodyLabel(be.tr("Miqdori")))
        self.qty_edit = LineEdit(self)
        self.qty_edit.setText(self._fmt_num_for_edit(qty0))
        col2.addWidget(self.qty_edit)
        row.addLayout(col2)
        layout.addLayout(row)

        # --- Tan narxi (so'm) + Dollardan avtomatik hisoblash ---
        layout.addWidget(CaptionLabel(be.tr("Tan narxi — zavod/optomdan qancha turadi (so'm, 1 birlik uchun)")))
        self.cost_edit = LineEdit(self)
        self.cost_edit.setText(self._fmt_num_for_edit(cost0))
        layout.addWidget(self.cost_edit)

        usd_card = SimpleCardWidget(self)
        usd_layout = QVBoxLayout(usd_card)
        usd_layout.setContentsMargins(12, 10, 12, 10)
        usd_layout.setSpacing(6)
        usd_layout.addWidget(CaptionLabel(be.tr("Yordamchi: dollardan so'mga avtomatik hisoblash")))
        usd_row = QHBoxLayout()
        usd_row.addWidget(BodyLabel(be.tr("Tan narxi ($):")))
        self.usd_cost_edit = LineEdit(self)
        self.usd_cost_edit.setMaximumWidth(90)
        self.usd_cost_edit.setPlaceholderText(be.tr("masalan 1.5"))
        usd_row.addWidget(self.usd_cost_edit)
        usd_row.addWidget(BodyLabel(be.tr("Kurs (so'm/$):")))
        self.usd_rate_edit = LineEdit(self)
        self.usd_rate_edit.setMaximumWidth(90)
        self.usd_rate_edit.setPlaceholderText(be.tr("masalan 12000"))
        settings = be.load_settings()
        last_rate = settings.get("last_usd_rate")
        if last_rate:
            self.usd_rate_edit.setText(str(last_rate))
        usd_row.addWidget(self.usd_rate_edit)
        usd_apply_btn = PushButton(be.tr("Hisoblash"), self)
        usd_apply_btn.clicked.connect(self._apply_usd_conversion)
        usd_apply_btn.setAutoDefault(False)
        usd_apply_btn.setDefault(False)
        usd_row.addWidget(usd_apply_btn)
        usd_row.addStretch(1)
        usd_layout.addLayout(usd_row)
        layout.addWidget(usd_card)

        # --- Sotish narxi (so'm) + Foiz qo'shish yordamchisi ---
        layout.addWidget(CaptionLabel(be.tr("Sotish narxi — mijozga qo'yiladigan narx (so'm, 1 birlik uchun)")))
        self.price_edit = LineEdit(self)
        self.price_edit.setText(self._fmt_num_for_edit(price0))
        layout.addWidget(self.price_edit)

        pct_card = SimpleCardWidget(self)
        pct_layout = QHBoxLayout(pct_card)
        pct_layout.setContentsMargins(12, 10, 12, 10)
        pct_layout.addWidget(BodyLabel(be.tr("Foyda foizi (%):")))
        self.markup_edit = LineEdit(self)
        self.markup_edit.setMaximumWidth(80)
        self.markup_edit.setPlaceholderText(be.tr("masalan 20"))
        pct_layout.addWidget(self.markup_edit)
        markup_btn = PushButton(be.tr("Sotish narxini hisoblash"), self)
        markup_btn.clicked.connect(self._apply_markup)
        markup_btn.setAutoDefault(False)
        markup_btn.setDefault(False)
        pct_layout.addWidget(markup_btn)
        pct_layout.addStretch(1)
        layout.addWidget(pct_card)

        layout.addWidget(CaptionLabel(be.tr(
            "Masalan: kg/litr/metr tanlasangiz, miqdorga 0.9, 1.5 kabi kasr son ham kiritishingiz mumkin.")))

        # MUHIM TUZATISH: scroll qilinadigan kontent shu yerda tugaydi.
        # Saqlash/Bekor qilish tugmalari endi scroll ICHIDA emas -- doim
        # ko'rinadigan bo'lishi uchun scroll'dan TASHQARIGA, alohida
        # qatorga chiqarildi.
        outer_layout.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(24, 10, 24, 16)
        save_btn = PrimaryPushButton(be.tr("Saqlash"), self)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = PushButton(be.tr("Bekor qilish"), self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        outer_layout.addLayout(btn_row)

        # MUHIM TUZATISH (foydalanuvchi so'rovi bilan): dialog Windows
        # taskbar orqasiga o'tib ketmasligi uchun maksimal balandlik
        # ekranning bo'sh (taskbar'siz) maydoniga qarab cheklanadi.
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            max_h = max(360, avail.height() - 60)
            self.setMaximumHeight(max_h)
            self.resize(self.width(), min(max_h, 640))

        self.name_edit.setFocus()

    def _refresh_image_preview(self):
        """Rasm holatiga qarab (yangi tanlangan / mavjud / yo'q) preview
        rasmini yangilaydi va "olib tashlash" tugmasini ko'rsatadi/
        yashiradi."""
        path = None
        if self._image_action == "set" and self._new_image_path:
            path = self._new_image_path
        elif self._image_action == "keep" and self._existing_image_path:
            path = be.get_product_image_full_path(self._existing_image_path)
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                size = self.image_preview.width() or 120
                self.image_preview.setPixmap(
                    pixmap.scaled(size, size,
                                  Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.remove_image_btn.setVisible(True)
                return
        self.image_preview.clear()
        self.image_preview.setText(be.tr("Rasm yo'q"))
        self.remove_image_btn.setVisible(self._image_action != "remove" and bool(self._existing_image_path))

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, be.tr("Mahsulot rasmini tanlang"), "",
            "Rasmlar (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        # MUHIM (foydalanuvchi so'rovi bilan): "AI: fonni olib tashlash"
        # belgisi BOSILGAN bo'lsagina rasmdagi mahsulot sun'iy intellekt
        # (rembg) yordamida orqa fondan AVTOMATIK AJRATIB OLINADI. Bu
        # jarayon (ayniqsa birinchi marta) bir necha soniya/o'nlab soniya
        # davom etishi mumkin -- shuning uchun MUHIM TUZATISH: bu ALOHIDA
        # OQIMDA (_BgRemovalWorker) bajariladi, dastur oynasi shu vaqt
        # ichida ham "Not Responding" bo'lib qolmaydi. Belgi bosilmasa,
        # rasm darhol, o'zgarishsiz ishlatiladi.
        if self.auto_crop_check.isChecked():
            # Rasmni darhol (asl holida) preview qilamiz, keyin AI
            # tugagach almashtiramiz -- foydalanuvchi kutish paytida ham
            # nimadir tanlanganini ko'rib turadi.
            self._image_action = "set"
            self._new_image_path = path
            self._refresh_image_preview()

            self.auto_crop_check.setEnabled(False)
            self.image_preview.setText(be.tr("AI ishlamoqda...\n(birinchi marta model\nyuklanishi mumkin)"))
            self.image_preview.setPixmap(QPixmap())

            self._bg_worker = _BgRemovalWorker(path)
            self._bg_worker.finished_ok.connect(
                lambda tmp_path, orig=path: self._on_bg_removal_ok(orig, tmp_path))
            self._bg_worker.finished_fail.connect(
                lambda err, orig=path: self._on_bg_removal_fail(orig, err))
            self._bg_worker.start()
            return
        self._image_action = "set"
        self._new_image_path = path
        self._refresh_image_preview()

    def _on_bg_removal_ok(self, original_path, processed_path):
        self.auto_crop_check.setEnabled(True)
        # Foydalanuvchi shu orada boshqa rasm tanlamagan bo'lsa, natijani qo'llaymiz.
        if self._image_action == "set" and self._new_image_path == original_path:
            self._new_image_path = processed_path
            self._refresh_image_preview()

    def _on_bg_removal_fail(self, original_path, error_kind):
        self.auto_crop_check.setEnabled(True)
        if error_kind == "no_rembg":
            info_warning(self, be.tr("Diqqat"),
                         be.tr("Sun'iy intellekt (rembg) kutubxonasi bu o'rnatishda "
                               "mavjud emas. Rasm shunchaki kvadrat qilib kesib "
                               "saqlanadi, fon o'zgarmaydi."))
        else:
            info_error(self, be.tr("Xato"),
                      f"{be.tr('Fonni avtomatik olib tashlab bolmadi')}: {error_kind}")
        if self._image_action == "set" and self._new_image_path == original_path:
            fallback = self._plain_square_crop(original_path)
            if fallback:
                self._new_image_path = fallback
            self._refresh_image_preview()

    def _plain_square_crop(self, path):
        """Zaxira (fallback) usul: rembg ishlamasa yoki mavjud bo'lmasa,
        rasmni shunchaki markazdan kvadrat shaklda kesadi (fon
        o'zgarishsiz qoladi)."""
        if not getattr(be, "_PIL_AVAILABLE", False):
            return None
        try:
            from PIL import Image
            import tempfile
            img = Image.open(path).convert("RGB")
            w, h = img.size
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            img = img.crop((left, top, left + side, top + side))
            fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            img.save(tmp_path, "JPEG", quality=90)
            return tmp_path
        except Exception:
            return None

    def _remove_image(self):
        self._image_action = "remove"
        self._new_image_path = None
        self._refresh_image_preview()

    def _focus_qty_after_scan(self):
        """Shtrix kod skanerlangandan (yoki qo'lda Enter bosilgandan) so'ng
        fokusni "Miqdori" maydoniga o'tkazadi va undagi matnni to'liq
        belgilaydi -- shu bilan foydalanuvchi darhol miqdorni yozishni
        boshlashi mumkin, eski qiymatni o'chirib o'tirmasdan."""
        self.qty_edit.setFocus()
        self.qty_edit.selectAll()

    def _apply_usd_conversion(self):
        try:
            usd_amount = float(self.usd_cost_edit.text())
            rate = float(self.usd_rate_edit.text())
        except ValueError:
            info_error(self, be.tr("Xato"), be.tr("Dollar summasi va kursni to'g'ri kiriting (masalan 1.5 va 12000)."))
            return
        if usd_amount <= 0 or rate <= 0:
            info_error(self, be.tr("Xato"), be.tr("Qiymatlar musbat bo'lishi kerak."))
            return
        cost_som = round(usd_amount * rate)
        self.cost_edit.setText(str(cost_som))
        with be.settings_lock():
            settings = be.load_settings()
            settings["last_usd_rate"] = rate
            be.save_settings(settings)
        info_success(self, be.tr("Hisoblandi"), f"{be.tr('Tan narxi')}: {be.fmt_money(cost_som)} so'm")

    def _apply_markup(self):
        try:
            cost_price = float(self.cost_edit.text())
            pct = float(self.markup_edit.text())
        except ValueError:
            info_error(self, be.tr("Xato"), be.tr("Avval tan narxini kiriting, so'ng foizni kiriting."))
            return
        if cost_price <= 0:
            info_error(self, be.tr("Xato"), be.tr("Avval tan narxini to'g'ri kiriting."))
            return
        raw_price = cost_price * (1 + pct / 100.0)
        # MUHIM O'ZGARISH (foydalanuvchi so'rovi bilan): hisoblangan sotish
        # narxi endi eng yaqin 500 so'mgacha, HAR DOIM YUQORIGA qarab
        # yaxlitlanadi (ceiling) -- oldingi "eng yaqinga" (round) qoidasi
        # o'rniga. Masalan: 32167 -> 32500 (32000'ga emas), 32523 -> 33000.
        new_price = math.ceil(raw_price / 500.0) * 500
        self.price_edit.setText(str(int(new_price)))
        raw_rounded = round(raw_price)
        # MUHIM: foydalanuvchi so'ragani bo'yicha, endi HAR DOIM ikkalasi
        # ham ko'rsatiladi -- avval aniq hisoblangan (yaxlitlanmagan) summa,
        # keyin 500 so'mgacha yaxlitlangan summa.
        info_success(self, be.tr("Hisoblandi"),
                     be.tr("Sotish narxi: {raw} so'm bo'ldi, {price} so'm ga yaxlitlandi "
                           "({pct:g}% foyda bilan)").format(
                         raw=be.fmt_money(raw_rounded), price=be.fmt_money(new_price), pct=pct))

    def _print_barcode_now(self):
        code = self.barcode_edit.text().strip()
        if not code:
            info_warning(self, be.tr("Diqqat"),
                         be.tr("Avval shtrix kodni kiriting yoki bo'sh qoldirib 'Saqlash'ni bosing "
                               "(dastur o'zi kod yaratib, chop etish oynasini ochadi)."))
            return
        name = self.name_edit.text().strip() or be.tr("Mahsulot")
        try:
            price = float(self.price_edit.text())
        except ValueError:
            price = 0.0
        try:
            image = be.build_barcode_label_image(code, name, price)
        except Exception as e:
            info_error(self, be.tr("Xato"), f"{be.tr('Shtrix kod rasmini yaratib bolmadi')}: {e}")
            return
        path = be.save_barcode_label(image, code)
        BarcodeLabelDialog(self, path, code, name, price).exec()

    def _on_save(self):
        name = self.name_edit.text().strip()
        if not name:
            info_error(self, be.tr("Xato"), be.tr("Mahsulot nomini kiriting."))
            return
        try:
            cost_price = float(self.cost_edit.text()) if self.cost_edit.text().strip() else 0.0
            price = float(self.price_edit.text())
            qty = float(self.qty_edit.text())
        except ValueError:
            info_error(self, be.tr("Xato"), be.tr("Narx va miqdorni to'g'ri kiriting (masalan: 0.9)."))
            return
        if not all(math.isfinite(v) for v in (cost_price, price, qty)) or price <= 0 or cost_price < 0 or qty < 0:
            info_error(self, be.tr("Xato"), be.tr("Narx va miqdorni to'g'ri kiriting (masalan: 0.9)."))
            return

        barcode = self.barcode_edit.text().strip() or None
        unit = self.unit_combo.currentText() or "dona"
        auto_generated = False
        if not barcode:
            conn = be.get_conn()
            existing = {row[0] for row in conn.execute(
                "SELECT barcode FROM products WHERE barcode IS NOT NULL")}
            conn.close()
            barcode = be.generate_random_barcode(existing)
            auto_generated = True

        # MUHIM (foydalanuvchi so'rovi bilan): natijaga rasm bilan bog'liq
        # amal ham qo'shildi -- "keep" (hech narsa qilinmaydi), "set"
        # (yangi_rasm_yoli bo'yicha saqlanadi), "remove" (rasm o'chiriladi).
        self.result_data = (name, cost_price, price, qty, unit, barcode, auto_generated,
                            self._image_action, self._new_image_path)
        self.accept()


class PaymentMethodDialog(ThemedDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(be.tr("To'lov turi"))
        self.method = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(StrongBodyLabel(be.tr("To'lov turini tanlang:")))
        row = QHBoxLayout()
        cash_btn = PrimaryPushButton(be.tr("Naqd"), self)
        cash_btn.clicked.connect(lambda: self._choose(be.tr("Naqd")))
        card_btn = PushButton(be.tr("Plastik karta"), self)
        card_btn.clicked.connect(lambda: self._choose(be.tr("Plastik karta")))
        row.addWidget(cash_btn)
        row.addWidget(card_btn)
        layout.addLayout(row)

    def _choose(self, method):
        self.method = method
        self.accept()


class BarcodeChoiceDialog(ThemedDialog):
    """Ba'zan zavod/ta'minotchidan turli nomdagi mahsulotlar bir xil shtrix
    kod bilan kelib qoladi (masalan bir xil qadoqlash liniyasi). Bunday
    holatda shtrix kod skanerlanganda BAZADA O'SHA KODGA MOS BIR NECHTA
    mahsulot topilsa, dastur qaysi birini savatga qo'shishni O'ZI hal
    qilmaydi -- foydalanuvchiga shu oyna orqali tanlov beradi."""

    def __init__(self, parent, rows):
        super().__init__(parent)
        self.setWindowTitle(be.tr("Mahsulotni tanlang"))
        self.chosen_row = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addWidget(StrongBodyLabel(
            be.tr("Bu shtrix kodga bir nechta mahsulot mos keladi — qaysi birini tanlaysiz?")))
        for row in rows:
            pid, name, cost_price, price, qty, unit, barcode, image_path = row
            btn = PushButton(f"{name}  —  {be.fmt_money(price)} so'm  ({be.fmt_qty(qty, unit)})", self)
            btn.clicked.connect(lambda _=None, r=row: self._choose(r))
            layout.addWidget(btn)
        cancel_btn = PushButton(be.tr("Bekor qilish"), self)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

    def _choose(self, row):
        self.chosen_row = row
        self.accept()


class EditQtyDialog(ThemedDialog):
    def __init__(self, parent, name, unit, current_qty):
        super().__init__(parent)
        self.setWindowTitle(be.tr("Miqdorni o'zgartirish"))
        self.new_qty = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addWidget(StrongBodyLabel(name))
        layout.addWidget(BodyLabel(f"{be.tr('Yangi miqdor')} ({unit}):"))
        self.qty_edit = LineEdit(self)
        self.qty_edit.setText(be.fmt_qty(current_qty, "").split()[0])
        layout.addWidget(self.qty_edit)
        btn_row = QHBoxLayout()
        save_btn = PrimaryPushButton(be.tr("Saqlash"), self)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = PushButton(be.tr("Bekor qilish"), self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        self.qty_edit.setFocus()

    def _on_save(self):
        try:
            self.new_qty = float(self.qty_edit.text())
        except ValueError:
            info_error(self, be.tr("Xato"), be.tr("Miqdorni to'g'ri kiriting."))
            return
        if not math.isfinite(self.new_qty) or self.new_qty < 0:
            self.new_qty = None
            info_error(self, be.tr("Xato"), be.tr("Miqdorni to'g'ri kiriting."))
            return
        self.accept()


class DiscountDialog(ThemedDialog):
    def __init__(self, parent, name, list_price, current_price, unit="dona"):
        super().__init__(parent)
        self.setWindowTitle(be.tr("Narxni pasaytirish (chegirma)"))
        self.new_price = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addWidget(StrongBodyLabel(name))
        layout.addWidget(CaptionLabel(f"{be.tr('Ombordagi (odatdagi) narx')}: {be.fmt_money(list_price)} so'm"))
        layout.addWidget(CaptionLabel(be.tr(
            "Bu yerda belgilangan narx faqat shu sotuvga tegishli bo'ladi —\n"
            "mahsulotning ombordagi doimiy narxi o'zgarmaydi.")))
        # MUHIM TUZATISH: bu yozuv ilgari HAR DOIM "1 dona uchun" deb
        # qattiq yozilgan edi -- garchi hisob-kitobning o'zi (item["qty"]
        # * item["price"]) har doim to'g'ri, HAQIQIY birlikka (metr/kg/
        # litr/dona) mos ishlagan bo'lsa ham, shu yozuv mahsulotning
        # o'lchov birligidan qat'i nazar doim "dona" deb ko'rsatib,
        # foydalanuvchini chalg'itardi. Endi mahsulotning HAQIQIY o'lchov
        # birligi ko'rsatiladi (masalan "1 metr uchun", "1 kg uchun").
        layout.addWidget(BodyLabel(be.tr("Yangi (kelishilgan) narx, 1 {unit} uchun:").format(unit=unit)))
        self.price_edit = LineEdit(self)
        self.price_edit.setText(be.fmt_qty(current_price, "").split()[0])
        layout.addWidget(self.price_edit)
        btn_row = QHBoxLayout()
        apply_btn = PrimaryPushButton(be.tr("Qo'llash"), self)
        apply_btn.clicked.connect(self._on_apply)
        cancel_btn = PushButton(be.tr("Bekor qilish"), self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        self.price_edit.setFocus()
        self.price_edit.selectAll()

    def _on_apply(self):
        try:
            price = float(self.price_edit.text())
        except ValueError:
            info_error(self, be.tr("Xato"), be.tr("Narxni to'g'ri kiriting."))
            return
        if price <= 0:
            info_error(self, be.tr("Xato"), be.tr("Narx musbat son bo'lishi kerak."))
            return
        self.new_price = price
        self.accept()


class CreditDialog(ThemedDialog):
    def __init__(self, parent, items, total):
        super().__init__(parent)
        self.setWindowTitle(be.tr("Nasiyaga berish"))
        self.setMinimumWidth(420)
        self.customer_name = None
        self.phone = None
        self.total = total
        self.paid_now = 0.0

        conn = be.get_conn()
        customers = conn.execute(
            "SELECT DISTINCT customer_name, COALESCE(phone,'') FROM debts "
            "WHERE customer_name IS NOT NULL AND customer_name != '' ORDER BY customer_name").fetchall()
        conn.close()
        self._customers = {f"{n} — {p}" if p else n: (n, p) for n, p in customers}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        if self._customers:
            layout.addWidget(BodyLabel(be.tr("Avval nasiyaga olgan xaridordan tanlang (ixtiyoriy)")))
            self.picker = ComboBox(self)
            self.picker.addItem(be.tr("— Yangi xaridor —"))
            self.picker.addItems(list(self._customers.keys()))
            self.picker.currentTextChanged.connect(self._on_pick_customer)
            layout.addWidget(self.picker)

        layout.addWidget(StrongBodyLabel(be.tr("Xaridor ism-familiyasi")))
        self.name_edit = LineEdit(self)
        layout.addWidget(self.name_edit)

        layout.addWidget(StrongBodyLabel(be.tr("Telefon raqami (ixtiyoriy)")))
        self.phone_edit = LineEdit(self)
        layout.addWidget(self.phone_edit)

        layout.addWidget(StrongBodyLabel(be.tr("Olayotgan mahsulotlari:")))
        items_text = "\n".join(
            f"• {i['name']}  —  {be.fmt_qty(i['qty'], i['unit'])}  ({be.fmt_money(i['total'])} so'm)"
            for i in items)
        items_lbl = BodyLabel(items_text)
        items_lbl.setWordWrap(True)
        layout.addWidget(items_lbl)

        total_lbl = QLabel(f"{be.tr('Jami summa')}: {be.fmt_money(total)} so'm")
        total_lbl.setStyleSheet("font-size:15px; font-weight:700;")
        layout.addWidget(total_lbl)

        # MUHIM (foydalanuvchi so'rovi bilan -- "qisman to'lov"): ba'zan
        # xaridor jami summaning bir qismini DARHOL (naqd/karta) to'laydi,
        # qolganini keyinroq keltirib berishga va'da beradi. Bu maydon
        # orqali o'sha hozir olingan summa kiritiladi -- 0 qoldirilsa,
        # xuddi ilgarigidek, HAMMASI qarzga yoziladi.
        layout.addWidget(StrongBodyLabel(
            be.tr("Hozir to'lanadigan summa (ixtiyoriy — xaridor bir qismini darhol to'lasa)")))
        self.paid_now_edit = LineEdit(self)
        self.paid_now_edit.setText("0")
        self.paid_now_edit.textChanged.connect(self._update_remaining_label)
        layout.addWidget(self.paid_now_edit)

        self.remaining_lbl = QLabel(f"{be.tr('Qarzga qoladi')}: {be.fmt_money(total)} so'm")
        self.remaining_lbl.setStyleSheet("font-size:16px; font-weight:700; color:#E5484D;")
        layout.addWidget(self.remaining_lbl)

        btn_row = QHBoxLayout()
        save_btn = PrimaryPushButton(be.tr("Qarz daftariga qo'shish"), self)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = PushButton(be.tr("Bekor qilish"), self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_pick_customer(self, key):
        if key in self._customers:
            name, phone = self._customers[key]
            self.name_edit.setText(name)
            self.phone_edit.setText(phone)
        else:
            self.name_edit.clear()
            self.phone_edit.clear()

    def _update_remaining_label(self):
        try:
            paid = float((self.paid_now_edit.text() or "0").replace(" ", ""))
        except ValueError:
            paid = None
        if paid is None or paid < 0 or paid > self.total + 1e-9:
            self.remaining_lbl.setText(be.tr("To'langan summani to'g'ri kiriting (0 dan Jami summagacha)."))
            self.remaining_lbl.setStyleSheet("font-size:14px; font-weight:600; color:#E5484D;")
            return
        remaining = self.total - paid
        self.remaining_lbl.setStyleSheet("font-size:16px; font-weight:700; color:#E5484D;")
        self.remaining_lbl.setText(f"{be.tr('Qarzga qoladi')}: {be.fmt_money(remaining)} so'm")

    def _on_save(self):
        name = self.name_edit.text().strip()
        phone = self.phone_edit.text().strip()
        if not name:
            info_error(self, be.tr("Xato"), be.tr("Xaridor ism-familiyasini kiriting."))
            return
        try:
            paid_now = float((self.paid_now_edit.text() or "0").replace(" ", ""))
        except ValueError:
            info_error(self, be.tr("Xato"), be.tr("Hozir to'lanadigan summani to'g'ri kiriting."))
            return
        if paid_now < 0:
            info_error(self, be.tr("Xato"), be.tr("To'langan summa manfiy bo'lishi mumkin emas."))
            return
        if paid_now > self.total + 1e-9:
            info_error(self, be.tr("Xato"),
                       be.tr("To'langan summa jami summadan ({total}) katta bo'lishi mumkin emas.").format(
                           total=be.fmt_money(self.total)))
            return
        # MUHIM (foydalanuvchi so'rovi bilan): telefon raqami endi IXTIYORIY --
        # ba'zi xaridorlarning telefon raqamini bilmasligi mumkin, shuning
        # uchun bo'sh qoldirilsa ham nasiyaga savdo qilish davom etadi.
        self.customer_name = name
        self.phone = phone or None
        self.paid_now = paid_now
        self.accept()


class DebtItemsDialog(ThemedDialog):
    def __init__(self, parent, customer_name, items, note):
        super().__init__(parent)
        self.setWindowTitle(f"{customer_name} — {be.tr('olgan mahsulotlari')}")
        self.setMinimumSize(420, 320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(SubtitleLabel(customer_name))

        if items:
            class _SimpleModel(QAbstractTableModel):
                def __init__(self, rows):
                    super().__init__()
                    self._rows = rows

                def rowCount(self, p=QModelIndex()):
                    return len(self._rows)

                def columnCount(self, p=QModelIndex()):
                    return 3

                def headerData(self, section, orientation, role=Qt.DisplayRole):
                    if role == Qt.DisplayRole and orientation == Qt.Horizontal:
                        return [be.tr("Mahsulot nomi"), be.tr("Miqdori"), be.tr("Birligi")][section]
                    return None

                def data(self, index, role=Qt.DisplayRole):
                    if role == Qt.DisplayRole:
                        return self._rows[index.row()][index.column()]
                    return None

            table = TableView(self)
            table.setModel(_SimpleModel([(name, be.fmt_qty(qty, "").split()[0], unit) for name, qty, unit in items]))
            # MUHIM: uzun mahsulot nomlari kesilib qolmasligi uchun faqat
            # nomi ustuni Stretch (qolgan joyni oladi), miqdor/birlik ustunlari
            # esa o'z kontentiga mos kichik kenglikda bo'ladi.
            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            table.setTextElideMode(Qt.ElideNone)
            table.setWordWrap(True)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            # Suzuvchi (floating) skroll chizig'i jadval kontenti ustiga
            # chiqib ketmasligi uchun o'ng tomondan joy ajratib qo'yamiz.
            table.setViewportMargins(0, 0, 14, 0)
            fix_table_hover_highlight(table)
            layout.addWidget(table)
        elif note:
            layout.addWidget(CaptionLabel(be.tr("Bu yozuv uchun batafsil ro'yxat saqlanmagan, izoh:")))
            note_lbl = BodyLabel(note)
            note_lbl.setWordWrap(True)
            layout.addWidget(note_lbl)
        else:
            layout.addWidget(BodyLabel(be.tr("Bu qarzdor uchun mahsulot ro'yxati kiritilmagan.")))

        close_btn = PrimaryPushButton(be.tr("Yopish"), self)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignLeft)


class ReceiptDialog(ThemedDialog):
    def __init__(self, parent, receipt_text, file_path):
        super().__init__(parent)
        self.setWindowTitle(be.tr("Chek"))
        self.setFixedWidth(380)
        self.file_path = file_path

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(StrongBodyLabel(be.tr("Chek tayyor")))

        text_widget = QTextEdit(self)
        text_widget.setReadOnly(True)
        text_widget.setPlainText(receipt_text)
        text_widget.setFont(QFont(be.FONT_MONO_NAME, 9))
        text_widget.setFixedSize(340, 340)
        text_widget.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(text_widget)

        layout.addWidget(CaptionLabel(f"{be.tr('Fayl saqlandi')}: {file_path}"))

        printers = be.list_printers()
        self.printer_combo = None
        if printers:
            row = QHBoxLayout()
            row.addWidget(BodyLabel(be.tr("Chek printeri:")))
            self.printer_combo = ComboBox(self)
            self.printer_combo.addItems(printers)
            settings = be.load_settings()
            remembered = settings.get("receipt_printer")
            if remembered in printers:
                self.printer_combo.setCurrentText(remembered)
            row.addWidget(self.printer_combo)
            layout.addLayout(row)
        else:
            _perr = be._LAST_PRINTER_ERROR or be.tr("sabab noma'lum")
            layout.addWidget(CaptionLabel(f"({be.tr('Printerlar royxati olinmadi')}: {_perr})"))

        btn_row = QHBoxLayout()
        print_btn = PrimaryPushButton(be.tr("Chop etish"), self)
        print_btn.clicked.connect(self._on_print)
        close_btn = PushButton(be.tr("Yopish"), self)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(print_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_print(self):
        printer_name = self.printer_combo.currentText() if self.printer_combo else None
        ok, err = be.print_receipt_file(self.file_path, printer_name)
        if printer_name:
            with be.settings_lock():
                settings = be.load_settings()
                settings["receipt_printer"] = printer_name
                be.save_settings(settings)
        if ok:
            info_success(self, be.tr("Chop etish"), be.tr("Chek printerga yuborildi."))
        else:
            # MUHIM: fayl yo'li allaqachon dialog ichida alohida ko'rsatilgan
            # (yuqoridagi caption'da), shuning uchun bu yerda uni qaytadan
            # takrorlamaymiz -- aks holda uzun yo'l InfoBar bildirishnomasini
            # kesib, matn ko'rinmay qolishiga sabab bo'lardi.
            info_warning(self, be.tr("Chop etish"),
                          be.tr("Avtomatik chop etib bo'lmadi ({err})").format(err=err))


class BarcodeLabelDialog(ThemedDialog):
    """Shtrix kod oynasi. MUHIM: shtrix kod rasmi yuqori piksel zichligida
    (chop etish uchun) yaratiladi, shuning uchun ekranda ko'rsatishdan oldin
    kichik, sobit o'lchamga (max 320px kenglik) qadar mutanosib ravishda
    kichraytiriladi -- aks holda oyna nazoratsiz kattalashib ketardi."""

    PREVIEW_MAX_WIDTH = 320

    def __init__(self, parent, image_path, code, product_name, price):
        super().__init__(parent)
        self.setWindowTitle(be.tr("Shtrix kod"))
        # MUHIM TUZATISH: 380px eni ba'zi tillarda (masalan ruscha
        # "Boshqa joyga saqlash" tarjimasi) 3 ta tugmani bitta qatorga
        # sig'dira olmay, tugma matnining boshi/oxiri kesilib qolar edi.
        # Shuning uchun oyna kengroq qilindi va tugmalar 2 qatorga
        # bo'lindi (pastda ko'ring).
        self.setFixedWidth(420)
        self.image_path = image_path
        self.code = code
        self.product_name = product_name
        self.price = price
        # MUHIM: yozuvlarni (nomi/narxi/shtrix kodning o'zi) ALOHIDA-
        # ALOHIDA kattalashtirish/kichraytirish uchun joriy o'lchamlar --
        # foydalanuvchi aniq so'ragan imkoniyat. MUHIM TUZATISH: bir marta
        # o'lcham tanlansa, KEYINGI safar shtrix kod oynasi ochilganda ham
        # o'sha o'lcham eslab qolinishi kerak -- shuning uchun boshlang'ich
        # qiymatlar endi qattiq kodlangan (23/25/100) emas, balki
        # sozlamalardan (oxirgi ishlatilgan) o'qiladi.
        _settings = be.load_settings()
        self.name_font_size = _settings.get("barcode_label_name_size", 23)
        self.price_font_size = _settings.get("barcode_label_price_size", 25)
        self.barcode_scale = _settings.get("barcode_label_scale", 100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(StrongBodyLabel(be.tr("Shtrix kod")))
        layout.addWidget(BodyLabel(f"{product_name}  —  {be.fmt_money(price)} so'm"))

        img_label = QLabel(self)
        self.img_label = img_label
        pixmap = QPixmap(image_path)
        if not pixmap.isNull() and pixmap.width() > self.PREVIEW_MAX_WIDTH:
            pixmap = pixmap.scaledToWidth(self.PREVIEW_MAX_WIDTH, Qt.SmoothTransformation)
        img_label.setPixmap(pixmap)
        img_label.setFixedSize(self.PREVIEW_MAX_WIDTH + 20, pixmap.height() + 20)
        img_label.setAlignment(Qt.AlignCenter)
        img_label.setStyleSheet("background: white; border-radius: 8px; padding: 10px;")
        layout.addWidget(img_label, alignment=Qt.AlignHCenter)

        layout.addWidget(CaptionLabel(f"{be.tr('Kod')}: {code}"))
        layout.addWidget(CaptionLabel(f"{be.tr('Fayl saqlandi')}: {image_path}"))

        # --- Yozuvlarni alohida kattalashtirish/kichraytirish ---
        # MUHIM TUZATISH: avval ikkita spinbox bitta qatorga (label bilan
        # birga) sig'dirilgan edi -- 420px kenglikda bu raqamning o'zi
        # ko'rinmay, faqat yuqori/pastga o'q tugmalari ko'rinib qolar edi.
        # Endi har biri O'Z QATORIDA, YETARLICHA KENG (110px) qilib
        # joylashtirilgan -- shu bilan raqam har doim to'liq ko'rinadi.
        # MUHIM TUZATISH: 110px ham yetarli emas ekan -- SpinBox'ning ichki
        # yuqori/pastga tugmalari ko'p joy egallagani uchun 2-3 xonali son
        # (masalan "100") to'liq ko'rinmay, faqat bitta raqam ko'rinar edi.
        # Endi ancha kengroq (160px) qilindi.
        SPIN_WIDTH = 160

        name_row = QHBoxLayout()
        name_row.addWidget(BodyLabel(be.tr("Nomi shrifti:")))
        name_row.addStretch(1)
        self.name_size_spin = SpinBox(self)
        self.name_size_spin.setRange(10, 60)
        self.name_size_spin.setValue(self.name_font_size)
        self.name_size_spin.setFixedWidth(SPIN_WIDTH)
        self.name_size_spin.valueChanged.connect(self._on_style_changed)
        name_row.addWidget(self.name_size_spin)
        layout.addLayout(name_row)

        price_row = QHBoxLayout()
        price_row.addWidget(BodyLabel(be.tr("Narx shrifti:")))
        price_row.addStretch(1)
        self.price_size_spin = SpinBox(self)
        self.price_size_spin.setRange(10, 60)
        self.price_size_spin.setValue(self.price_font_size)
        self.price_size_spin.setFixedWidth(SPIN_WIDTH)
        self.price_size_spin.valueChanged.connect(self._on_style_changed)
        price_row.addWidget(self.price_size_spin)
        layout.addLayout(price_row)

        barcode_scale_row = QHBoxLayout()
        barcode_scale_row.addWidget(BodyLabel(be.tr("Shtrix kod o'lchami (%):")))
        barcode_scale_row.addStretch(1)
        self.barcode_scale_spin = SpinBox(self)
        self.barcode_scale_spin.setRange(50, 250)
        self.barcode_scale_spin.setSingleStep(10)
        self.barcode_scale_spin.setValue(self.barcode_scale)
        self.barcode_scale_spin.setFixedWidth(SPIN_WIDTH)
        self.barcode_scale_spin.valueChanged.connect(self._on_style_changed)
        barcode_scale_row.addWidget(self.barcode_scale_spin)
        layout.addLayout(barcode_scale_row)

        # Oyna ochilganda, DARHOL oldingi safar eslab qolingan o'lchamlar
        # bilan yorliqni qayta chizamiz (chunki tashqaridan berilgan
        # image_path standart o'lchamda yaratilgan bo'lishi mumkin).
        self._on_style_changed()

        printers = be.list_printers()
        self.printer_combo = None
        if printers:
            row = QHBoxLayout()
            row.addWidget(BodyLabel(be.tr("Shtrix kod printeri:")))
            self.printer_combo = ComboBox(self)
            self.printer_combo.addItems(printers)
            settings = be.load_settings()
            remembered = settings.get("barcode_printer")
            if remembered in printers:
                self.printer_combo.setCurrentText(remembered)
            row.addWidget(self.printer_combo)
            layout.addLayout(row)

        qty_row = QHBoxLayout()
        qty_row.addWidget(BodyLabel(be.tr("Soni (nechta chiqarish):")))
        self.copies_edit = LineEdit(self)
        self.copies_edit.setText("1")
        self.copies_edit.setFixedWidth(60)
        qty_row.addWidget(self.copies_edit)
        qty_row.addStretch(1)
        layout.addLayout(qty_row)

        print_btn = PrimaryPushButton(be.tr("Chop etish"), self)
        print_btn.clicked.connect(self._on_print)
        layout.addWidget(print_btn)

        btn_row = QHBoxLayout()
        save_btn = PushButton(be.tr("Boshqa joyga saqlash"), self)
        save_btn.clicked.connect(self._on_save_as)
        close_btn = PushButton(be.tr("Yopish"), self)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn, 1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_style_changed(self, _value=None):
        """Nomi/narx shrifti yoki shtrix kod o'lchami o'zgartirilganda,
        yorliq rasmini YANGI o'lchamlar bilan qayta yaratadi, diskka
        qayta saqlaydi (chop etish shu YANGI faylni ishlatishi uchun)
        va oynadagi ko'rinishni (preview) yangilaydi."""
        self.name_font_size = self.name_size_spin.value()
        self.price_font_size = self.price_size_spin.value()
        self.barcode_scale = self.barcode_scale_spin.value()
        # MUHIM TUZATISH: tanlangan o'lchamlar sozlamalarga saqlanadi --
        # shunda KEYINGI safar shtrix kod oynasi ochilganda, o'lchamlar
        # standart (23/25/100) ga emas, balki OXIRGI marta tanlangan
        # qiymatlarga qaytadi.
        try:
            with be.settings_lock():
                _settings = be.load_settings()
                _settings["barcode_label_name_size"] = self.name_font_size
                _settings["barcode_label_price_size"] = self.price_font_size
                _settings["barcode_label_scale"] = self.barcode_scale
                be.save_settings(_settings)
        except Exception:
            pass
        try:
            image = be.build_barcode_label_image(
                self.code, self.product_name, self.price,
                name_font_size=self.name_font_size,
                price_font_size=self.price_font_size,
                barcode_scale=self.barcode_scale / 100.0)
            self.image_path = be.save_barcode_label(image, self.code)
        except Exception as e:
            info_error(self, be.tr("Xato"), f"{be.tr('Shtrix kod rasmini yaratib bolmadi')}: {e}")
            return
        pixmap = QPixmap(self.image_path)
        if not pixmap.isNull() and pixmap.width() > self.PREVIEW_MAX_WIDTH:
            pixmap = pixmap.scaledToWidth(self.PREVIEW_MAX_WIDTH, Qt.SmoothTransformation)
        self.img_label.setPixmap(pixmap)
        self.img_label.setFixedSize(self.PREVIEW_MAX_WIDTH + 20, pixmap.height() + 20)

    def _on_print(self):
        try:
            copies = max(1, int(float(self.copies_edit.text())))
        except ValueError:
            copies = 1
        printer_name = self.printer_combo.currentText() if self.printer_combo else None
        with be.settings_lock():
            settings = be.load_settings()
        label_size = tuple(settings.get("barcode_label_size", [58, 38]))
        # MUHIM TUZATISH: avval har nusxa uchun be.print_barcode_label_file()
        # alohida chaqirilar edi (har safar alohida print-job ochib) -- bu
        # ba'zi shtrix kod printerlarida nusxalar orasida to'xtab-to'xtab,
        # sekin chop etishga sabab bo'lardi. Endi barcha nusxalar BITTA
        # chaqiruvda (copies=copies), bitta uzluksiz topshiriq sifatida
        # yuboriladi -- printer tez va tekis ishlaydi.
        ok, err = be.print_barcode_label_file(self.image_path, printer_name, label_size, copies=copies)
        if printer_name:
            with be.settings_lock():
                settings = be.load_settings()
                settings["barcode_printer"] = printer_name
                be.save_settings(settings)
        if ok:
            info_success(self, be.tr("Chop etish"),
                         be.tr("Shtrix kod printerga yuborildi ({n} ta nusxa).").format(n=copies))
        else:
            # (Rasm fayli yo'li allaqachon dialog ichida ko'rsatilgan.)
            info_warning(self, be.tr("Chop etish"),
                          be.tr("Avtomatik chop etib bo'lmadi ({err})").format(err=err))

    def _on_save_as(self):
        dest, _ = QFileDialog.getSaveFileName(self, be.tr("Shtrix kodni saqlash"),
                                                os.path.basename(self.image_path), "PNG rasm (*.png)")
        if not dest:
            return
        try:
            import shutil
            shutil.copyfile(self.image_path, dest)
            info_success(self, be.tr("Saqlandi"), f"{be.tr('Nusxa saqlandi')}: {dest}")
        except Exception as e:
            info_error(self, be.tr("Xato"), f"{be.tr('Saqlab bolmadi')}: {e}")


def telegram_pixmap(size=48):
    """Telegram uslubidagi logotip: ko'k doira ichida oq qog'oz samolyot
    (rasm faylisiz, kod bilan chiziladi -- har qanday masshtabda aniq)."""
    dpr = 2.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0.0, QColor("#37AEE2"))
    grad.setColorAt(1.0, QColor("#1E96C8"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawEllipse(QRectF(0, 0, size, size))
    k = size / 48.0
    def P(x, y):
        return QPointF((x - 1.5) * k, y * k)
    # asosiy qanot (yuqori-chap -> o'ng uchi -> pastki o'ng -> ichki burma)
    body = QPainterPath()
    body.moveTo(P(9.5, 23.6))
    body.lineTo(P(36.5, 12.4))
    body.lineTo(P(32.2, 35.6))
    body.lineTo(P(23.6, 29.4))
    body.lineTo(P(20.2, 25.6))
    body.lineTo(P(31.0, 17.6))
    body.lineTo(P(17.6, 24.8))
    body.closeSubpath()
    p.setBrush(QColor("white"))
    p.drawPath(body)
    # pastki "dum" qismi (biroz xiraroq oq)
    tail = QPainterPath()
    tail.moveTo(P(20.2, 25.6))
    tail.lineTo(P(23.6, 29.4))
    tail.lineTo(P(20.6, 32.6))
    tail.closeSubpath()
    p.setBrush(QColor(200, 218, 234))
    p.drawPath(tail)
    p.end()
    return pm


def telegram_icon(size=48):
    return QIcon(telegram_pixmap(size))


class TelegramSettingsDialog(ThemedDialog):
    CARD_HEIGHT = 116

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(be.tr("Telegram sozlamalari"))
        # MUHIM TUZATISH: foydalanuvchi bu oynani ixcham, O'ZGARMAS
        # (o'lchami almashtirilmaydigan) qilishni so'radi. Tarkib
        # ko'payib ketsa ham (Mini App holati, ro'yxatlar), oyna hajmi
        # doim shu FIKS o'lchamda qoladi -- ortiqcha tarkib esa ichki
        # skrol (pastda) orqali ko'riladi, "Yopish" tugmasi esa doim
        # pastda, ko'rinadigan joyda qoladi.
        self.setFixedSize(880, 780)
        self.setWindowIcon(telegram_icon(64))

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 12)
        layout.setSpacing(12)
        head_row = QHBoxLayout()
        head_row.setSpacing(14)
        self.tg_logo = QLabel(self)
        self.tg_logo.setPixmap(telegram_pixmap(52))
        self.tg_logo.setFixedSize(52, 52)
        self.tg_logo.setStyleSheet("background: transparent;")
        head_row.addWidget(self.tg_logo, 0, Qt.AlignTop)
        head_col = QVBoxLayout()
        head_col.setSpacing(2)
        head_col.addWidget(SubtitleLabel(be.tr("Telegram xabarnomalari")))
        _hint = CaptionLabel(be.tr(
            "Har bir sotuvda, ruxsat berilgan odamlarga avtomatik xabar yuboriladi.\n"
            "Kimdir botga yozsa, sizga (admin) so'rov keladi."))
        _hint.setWordWrap(True)
        head_col.addWidget(_hint)
        head_row.addLayout(head_col, 1)
        layout.addLayout(head_row)
        # MUHIM TUZATISH: foydalanuvchi so'ragani bo'yicha, bu yerda
        # oldin turgan uzun tushuntirish matni ("Yangi so'rovchi avval
        # botda tilini...") butunlay olib tashlandi -- oyna ixcham
        # bo'lishi uchun.

        settings = be.load_settings()
        form = QVBoxLayout()
        form.setSpacing(6)
        self.token_edit = LineEdit(self)
        self.token_edit.setText(settings.get("telegram_bot_token", ""))
        self.token_edit.setEchoMode(LineEdit.Password)
        # MUHIM TUZATISH: QFormLayout.addRow() ga oddiy matn (str) berilsa,
        # Qt o'zi avtomatik oddiy QLabel yaratadi va u dastur temasiga mos
        # ravishda rang olmaydi -- shuning uchun ba'zan (masalan Kunduzgi/
        # White rejimda) yozuv fon rangi bilan bir xil bo'lib, ko'rinmay
        # qolar edi. Buning o'rniga har doim temaga moslashuvchi BodyLabel
        # ishlatilyapti.
        self.token_edit.setPlaceholderText("123456789:AA...")
        self.token_edit.setClearButtonEnabled(True)
        self.token_edit.setMinimumHeight(36)
        form.addWidget(StrongBodyLabel("Bot Token"))
        form.addWidget(self.token_edit)
        self.admin_edit = LineEdit(self)
        self.admin_edit.setText(settings.get("telegram_admin_chat_id", ""))
        self.admin_edit.setPlaceholderText("123456789")
        self.admin_edit.setClearButtonEnabled(True)
        self.admin_edit.setMinimumHeight(36)
        form.addSpacing(4)
        form.addWidget(StrongBodyLabel(be.tr("Mening chat_id'im (admin):")))
        form.addWidget(self.admin_edit)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        save_btn = PrimaryPushButton(FluentIcon.SAVE, be.tr("Saqlash"), self)
        save_btn.clicked.connect(self._save_settings)
        test_btn = PushButton(FluentIcon.SYNC, be.tr("Ulanishni tekshirish"), self)
        test_btn.clicked.connect(self._test_connection)
        # MUHIM TUZATISH: tugmalarga qat'iy Preferred o'lcham siyosati
        # berilyapti va qator oxiriga bo'sh joy (stretch) qo'shilyapti --
        # shu bilan tugmalar dialog kengligini to'ldirib, cho'zilib/
        # kattayib ketmaydi, faqat o'z matniga mos o'lchamda qoladi.
        save_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        test_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(test_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.status_label = CaptionLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # --- Mini App (bot ichidagi "Ilova") holati ---
        self.miniapp_title = StrongBodyLabel(be.tr("Mini App (bot ilovasi)"))
        layout.addSpacing(6)
        layout.addWidget(self.miniapp_title)
        _mini_card = SimpleCardWidget(self)
        _mini_lay = QVBoxLayout(_mini_card)
        _mini_lay.setContentsMargins(14, 10, 14, 10)
        self.miniapp_status_label = CaptionLabel(be.tr("Tekshirilmoqda..."))
        self.miniapp_status_label.setWordWrap(True)
        _mini_lay.addWidget(self.miniapp_status_label)
        layout.addWidget(_mini_card)
        self._refresh_miniapp_status()

        self.pending_title = StrongBodyLabel(be.tr("Kutilayotgan so'rovlar"))
        layout.addWidget(self.pending_title)
        self.pending_table = self._make_perm_table(2)
        self.pending_empty = CaptionLabel(be.tr("Hozircha kutilayotgan so'rov yo'q"))
        layout.addWidget(self.pending_table)
        layout.addWidget(self.pending_empty)

        self.approved_title = StrongBodyLabel(be.tr("Ruxsat berilganlar"))
        layout.addWidget(self.approved_title)
        self.approved_table = self._make_perm_table(6)
        self.approved_empty = CaptionLabel(be.tr("Hozircha hech kimga ruxsat berilmagan"))
        layout.addWidget(self.approved_table)
        layout.addWidget(self.approved_empty)
        layout.addStretch(1)
        self._lists_sig = None

        scroll.setWidget(content)
        outer_layout.addWidget(scroll, 1)

        # MUHIM TUZATISH: "Yopish" tugmasi endi skrol ICHIDA emas, balki
        # tashqi (outer_layout) qatorda joylashgan -- shu sababli tarkib
        # qanchalik uzun bo'lmasin, oyna balandligi qanday bo'lmasin, bu
        # tugma HAR DOIM pastda, ko'rinadigan joyda qoladi.
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(20, 10, 20, 16)
        close_btn = PushButton(be.tr("Yopish"), self)
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn, alignment=Qt.AlignLeft)
        bottom_row.addStretch(1)
        outer_layout.addLayout(bottom_row)

        self._refresh_lists()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_lists)
        self._timer.timeout.connect(self._refresh_miniapp_status)
        self._timer.start(4000)

    def _make_list_scroll(self, inner_layout):
        """Har bir ro'yxat (kutilayotgan/ruxsat berilgan) uchun bir xil
        o'lchamdagi, o'zining skroliga ega konteyner yaratadi -- MUHIM
        TUZATISH: ilgari bu ro'yxatlar juda kichik/torgina bo'lib
        ko'rinar edi va skroli yo'q edi."""
        # MUHIM TUZATISH: layout'ga aniq Qt.AlignTop berilmasa, yagona
        # (masalan "Hozircha ...yo'q") widget ScrollArea konteynerining
        # butun balandligini egallab, matn o'rtada osilib qolgan ko'rinishda
        # chizilar edi. Endi barcha elementlar tepadan boshlab joylashadi.
        inner_layout.setAlignment(Qt.AlignTop)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(96)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        container.setLayout(inner_layout)
        scroll.setWidget(container)
        scroll.viewport().setStyleSheet("background: transparent;")
        return scroll

    def retranslate(self):
        self.setWindowTitle(be.tr("Telegram sozlamalari"))
        self.miniapp_title.setText(be.tr("Mini App (bot ilovasi)"))
        self.pending_title.setText(be.tr("Kutilayotgan so'rovlar"))
        self.approved_title.setText(be.tr("Ruxsat berilganlar"))
        self._lists_sig = None
        self._refresh_lists()
        self._refresh_miniapp_status()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _save_settings(self):
        token = self.token_edit.text().strip()
        admin_chat_id = self.admin_edit.text().strip()
        # BUG TUZATISH: bu yerda o'qish+yozish ilgari QULFSIZ bajarilar
        # edi -- aynan shu payt Telegram fon oqimi (bot polling) ham
        # sozlamalar.json faylini o'qib-yozib turgani uchun, ba'zida
        # bu yerda saqlangan token/admin ID keyinroq fon oqimining ESKI
        # nusxa asosidagi yozuvi bilan "yutib yuborilib" yo'qolib
        # qolardi. Endi butun o'qish+o'zgartirish+yozish bitta umumiy
        # qulf ostida, bo'linmas tarzda bajariladi.
        with be.settings_lock():
            settings = be.load_settings()
            old_token = (settings.get("telegram_bot_token") or "").strip()
            old_admin_chat_id = (settings.get("telegram_admin_chat_id") or "").strip()
            old_admin_lang = settings.get("telegram_admin_language") or "uz"
            settings["telegram_bot_token"] = token
            settings["telegram_admin_chat_id"] = admin_chat_id
            if admin_chat_id != old_admin_chat_id:
                # MUHIM: admin chat_id o'chirilganda yoki BOSHQA odamga
                # almashtirilganda, avvalgi ("telegram_admin_language")
                # tanlovi ENDI ESKI admin-ga tegishli -- agar shu kalitni
                # tozalamasak, keyinroq YANGI admin belgilanganda, unga
                # xato ravishda ESKI odamning tili qo'llanib qolardi.
                settings.pop("telegram_admin_language", None)
            be.save_settings(settings)
        be.start_telegram_polling()
        be.start_miniapp_server()

        info_success(self, be.tr("Saqlandi"), be.tr("Telegram sozlamalari saqlandi."))
        self.status_label.setText(f"⏳ {be.tr('Tekshirilmoqda...')}")

        token_changed = token != old_token
        admin_newly_set = bool(admin_chat_id) and admin_chat_id != old_admin_chat_id

        # MUHIM TUZATISH (foydalanuvchi so'rovi -- "birinchi marta admin
        # tayinlanganda, botdan til tanlash so'ralganda sekin/javob bermay
        # qolyapti"): ilgari bu yerda BIR NECHTA mustaqil fon oqimi
        # (notify_admin_removed, notify_new_telegram_admin,
        # reapply_miniapp_menu_button + getMe tekshiruvi) BARCHASI BIR
        # VAQTDA, BIR-BIRIGA PARALEL ishga tushirilardi. be.reapply_
        # miniapp_menu_button() esa -- HAR BIR ruxsat berilgan foydalanuvchi
        # (+ admin + umumiy "default") uchun ALOHIDA-ALOHIDA Telegram
        # so'rovi yuboradi -- bu OG'IR ish aynan o'sha payt (admin yangi
        # tayinlanib, botdan "Siz administrator etib belgilandingiz" xabari
        # va til tanlash tugmalarini olayotgan payt) bilan ustma-ust tushib,
        # Telegram serveriga ketayotgan so'rovlar orasida "navbat" hosil
        # qilardi -- shuning uchun admin tugmani bossa ham javob sekin
        # kelardi (ba'zida esa dastur ham shu tirbandlik ichida javob
        # bermay qolardi). Endi BARCHA tarmoq amallari BITTA fon oqimida,
        # KETMA-KET bajariladi -- ENG AVVAL (tezkor, admin uchun eng muhim)
        # xabar va til-tanlash tugmalari yuboriladi, FAQAT SHUNDAN KEYIN
        # (sekinroq bo'lishi mumkin bo'lgan) menyu tugmalarini hammaga
        # qayta sozlash boshlanadi -- va bu ham FAQAT haqiqatan kerak
        # bo'lganda (Token o'zgarganda yoki admin YANGI tayinlanganda),
        # oddiy saqlashda bekorga o'nlab so'rov yubormaslik uchun.
        def _do_save_network_work(_token=token, _old_admin=old_admin_chat_id,
                                   _old_lang=old_admin_lang, _admin=admin_chat_id,
                                   _admin_removed=(admin_chat_id != old_admin_chat_id),
                                   _admin_newly_set=admin_newly_set,
                                   _token_changed=token_changed):
            if _token and _old_admin and _admin_removed:
                try:
                    be.notify_admin_removed(_token, _old_admin, _old_lang)
                except Exception:
                    pass
            if _token and _admin_newly_set:
                try:
                    be.notify_new_telegram_admin(_token, _admin)
                except Exception:
                    pass
            if _token and (_token_changed or _admin_newly_set):
                try:
                    be.reapply_miniapp_menu_button()
                except Exception:
                    pass
            if _token:
                return be._telegram_api_call(_token, "getMe")
            return None

        self._save_worker = _TelegramBgWorker(_do_save_network_work, self)
        self._save_worker.finished.connect(self._on_save_network_done)
        self._save_worker.start()

    def _on_save_network_done(self, result):
        if isinstance(result, Exception):
            self.status_label.setText(f"❌ {be.tr('Xato')}: {result}")
        elif result and result.get("ok"):
            username = (result.get("result") or {}).get("username", "?")
            self.status_label.setText(f"✅ {be.tr('Bot ulandi')}: @{username}")
        elif result is None:
            self.status_label.setText("")
        else:
            err = be._LAST_TELEGRAM_ERROR or be.tr("Noma'lum xato.")
            self.status_label.setText(f"❌ {be.tr('Ulanmadi')}: {err}")
        self._refresh_miniapp_status()

    def _test_connection(self):
        token = self.token_edit.text().strip()
        if not token:
            self.status_label.setText(f"⚠️ {be.tr('Bot Token kiritilmagan.')}")
            return
        # MUHIM TUZATISH (foydalanuvchi so'rovi -- "Ulanishni tekshirish"
        # bosilganda dastur "Not Responding" bo'lib qolayotgan edi):
        # be._telegram_api_call() Telegram serveriga tarmoq so'rovi
        # yuboradi (15 soniyagacha kutishi mumkin). Ilgari bu chaqiruv
        # GUI oqimida to'g'ridan-to'g'ri bajarilib, oynani shu vaqt
        # davomida muzlatib qo'yardi. Endi ALOHIDA oqimda (_TelegramBgWorker)
        # bajariladi, natija tayyor bo'lgach signal orqali GUI yangilanadi.
        self.status_label.setText(f"⏳ {be.tr('Tekshirilmoqda...')}")
        self._test_worker = _TelegramBgWorker(
            lambda _t=token: be._telegram_api_call(_t, "getMe"), self)
        self._test_worker.finished.connect(self._on_test_connection_done)
        self._test_worker.start()

    def _on_test_connection_done(self, result):
        if isinstance(result, Exception):
            self.status_label.setText(f"❌ {be.tr('Xato')}: {result}")
        elif result and result.get("ok"):
            username = (result.get("result") or {}).get("username", "?")
            self.status_label.setText(f"✅ {be.tr('Bot ulandi')}: @{username}")
        else:
            err = be._LAST_TELEGRAM_ERROR or be.tr("Noma'lum xato.")
            self.status_label.setText(f"❌ {be.tr('Ulanmadi')}: {err}")

    def _refresh_miniapp_status(self):
        status = be.get_miniapp_status()
        if status.get("cloudflared_missing"):
            self.miniapp_status_label.setText(f"⚠️ {be.tr('cloudflared.exe topilmadi')}")
        elif status.get("menu_button_error"):
            self.miniapp_status_label.setText(f"❌ {status['menu_button_error']}")
        elif status.get("url"):
            hint = be.tr('Bot menyusidagi "🛒 Narxlar" tugmasi orqali ochiladi')
            self.miniapp_status_label.setText(
                f"✅ {be.tr('Mini App tayyor')}: {status['url']}/webapp\n({hint})")
        elif status.get("error"):
            self.miniapp_status_label.setText(f"❌ {status['error']}")
        elif status.get("started"):
            self.miniapp_status_label.setText(f"⏳ {be.tr('Tunnel ochilmoqda, kuting...')}")
        else:
            self.miniapp_status_label.setText(f"⏳ {be.tr('Bot Token saqlansa avtomatik ishga tushadi.')}")

    ROW_H = 48

    def _make_perm_table(self, cols):
        t = TableWidget(self)
        t.setColumnCount(cols)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setFocusPolicy(Qt.NoFocus)
        t.verticalHeader().hide()
        t.verticalHeader().setDefaultSectionSize(self.ROW_H)
        t.setBorderVisible(True)
        t.setBorderRadius(10)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hh = t.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        widths = {2: {1: 250}, 6: {1: 96, 2: 96, 3: 104, 4: 100, 5: 160}}[cols]
        for c, w in widths.items():
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
            t.setColumnWidth(c, w)
        t.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        t.setTextElideMode(Qt.ElideRight)
        return t

    @staticmethod
    def _plain_user_label(user):
        """Faqat foydalanuvchining o'zi: ism, @username, ID (ruxsat
        belgilari va stikerlarsiz)."""
        d = {k: v for k, v in user.items() if not str(k).startswith("can_") and k != "language"}
        return be._telegram_user_label(d)

    @staticmethod
    def _empty_item(text):
        it = QTableWidgetItem(text)
        it.setTextAlignment(Qt.AlignCenter)
        it.setFlags(Qt.NoItemFlags)
        return it

    @staticmethod
    def _centered(widget):
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.addWidget(widget, 0, Qt.AlignCenter)
        return box

    def _relayout_tables(self):
        """Qt katakdagi vidjetlarni (checkbox/tugma) yangi qatorlar uchun
        darhol emas, keyinroq joylashtiradi -- shu sababli "Ruxsat berish"dan
        keyin ular qiyshiq turardi. Qatorlar balandligini aniq belgilab,
        joylashuvni majburan yangilaymiz."""
        for t in (self.pending_table, self.approved_table):
            for r in range(t.rowCount()):
                t.setRowHeight(r, self.ROW_H)
            t.doItemsLayout()
            t.viewport().update()
        QTimer.singleShot(0, self._relayout_later)

    def _relayout_later(self):
        try:
            for t in (self.pending_table, self.approved_table):
                t.doItemsLayout()
                t.viewport().update()
        except RuntimeError:
            pass

    def _fit_table(self, table, rows):
        h = table.horizontalHeader().height() or 36
        table.setFixedHeight(h + 3 * self.ROW_H + 4)

    def _refresh_lists(self):
        settings = be.load_settings()
        pending = settings.get("telegram_pending_requests") or []
        approved = settings.get("telegram_approved_users") or []
        sig = repr((pending, approved))
        if sig == getattr(self, "_lists_sig", None):
            return
        self._lists_sig = sig

        # --- Kutilayotgan so'rovlar jadvali ---
        t = self.pending_table
        t.clearContents()
        t.setRowCount(len(pending))
        t.setHorizontalHeaderLabels([be.tr("Foydalanuvchi"), be.tr("Amal")])
        t.setRowCount(max(len(pending), 1))
        self.pending_empty.setVisible(False)
        t.setVisible(True)
        t.clearSpans()
        if not pending:
            t.setRowCount(1)
            t.setSpan(0, 0, 1, 2)
            t.setItem(0, 0, self._empty_item(be.tr("Hozircha kutilayotgan so'rov yo'q")))
        for r, user in enumerate(pending):
            item = QTableWidgetItem(self._plain_user_label(user))
            t.setItem(r, 0, item)
            approve_btn = PrimaryPushButton(be.tr("Ruxsat berish"))
            approve_btn.clicked.connect(lambda _=None, u=user: self._approve(u))
            reject_btn = PushButton(be.tr("Rad etish"))
            reject_btn.clicked.connect(lambda _=None, u=user: self._reject(u))
            box = QWidget()
            box.setStyleSheet("background: transparent;")
            hl = QHBoxLayout(box)
            hl.setContentsMargins(6, 0, 6, 0)
            hl.setSpacing(8)
            approve_btn.setFixedHeight(32)
            reject_btn.setFixedHeight(32)
            hl.addWidget(approve_btn, 0, Qt.AlignVCenter)
            hl.addWidget(reject_btn, 0, Qt.AlignVCenter)
            t.setCellWidget(r, 1, box)
        self._fit_table(t, max(len(pending), 1))
        self._relayout_tables()

        # --- Ruxsat berilganlar jadvali ---
        t = self.approved_table
        t.clearContents()
        t.setRowCount(len(approved))
        t.setHorizontalHeaderLabels([
            be.tr("Foydalanuvchi"), be.tr("Narx"), be.tr("Savdo"),
            be.tr("Mahsulot"), be.tr("Hisobot"), ""])
        self.approved_empty.setVisible(False)
        t.setVisible(True)
        t.clearSpans()
        if not approved:
            t.setRowCount(1)
            t.setSpan(0, 0, 1, 6)
            t.setItem(0, 0, self._empty_item(be.tr("Hozircha hech kimga ruxsat berilmagan")))
        perms = (
            ("can_query_products", self._toggle_query_permission, "Narx so'rashga ruxsat berish"),
            ("can_make_sales", self._toggle_sale_permission, "Savdo qilishga ruxsat berish"),
            ("can_manage_products", self._toggle_manage_permission, "Mahsulot qo'shishga ruxsat berish"),
            ("can_view_reports", self._toggle_reports_permission, "Hisobotlarga ruxsat berish"),
        )
        for r, user in enumerate(approved):
            t.setItem(r, 0, QTableWidgetItem(self._plain_user_label(user)))
            for c, (key, handler, tip) in enumerate(perms, start=1):
                cur = bool(user.get(key))
                cb = CheckBox()
                cb.setChecked(cur)
                cb.setToolTip(be.tr(tip))
                cb.clicked.connect(lambda _=None, u=user, cur=cur, h=handler: h(u, cur))
                t.setCellWidget(r, c, self._centered(cb))
            remove_btn = PushButton(be.tr("Chiqarib tashlash"))
            remove_btn.setFixedHeight(32)
            remove_btn.clicked.connect(lambda _=None, u=user: self._remove(u))
            t.setCellWidget(r, 5, self._centered(remove_btn))
        self._fit_table(t, max(len(approved), 1))
        self._relayout_tables()

    def _toggle_query_permission(self, user, currently_allowed):
        be.set_telegram_product_query_permission(user["chat_id"], not currently_allowed)
        self._refresh_lists()

    def _toggle_sale_permission(self, user, currently_allowed):
        be.set_telegram_sale_permission(user["chat_id"], not currently_allowed)
        self._refresh_lists()

    def _toggle_manage_permission(self, user, currently_allowed):
        be.set_telegram_manage_products_permission(user["chat_id"], not currently_allowed)
        self._refresh_lists()

    def _toggle_reports_permission(self, user, currently_allowed):
        be.set_telegram_reports_permission(user["chat_id"], not currently_allowed)
        self._refresh_lists()

    def _approve(self, user):
        # MUHIM TUZATISH (foydalanuvchi so'rovi -- "oddiy foydalanuvchiga
        # ham tuzatildimi?"): be.approve_telegram_user() sozlamalarni
        # saqlash (tez, tarmoqsiz) qismi -- shuning uchun bu qism darhol,
        # GUI oqimida bajariladi, ro'yxat esa shu zahoti yangilanadi.
        # Ruxsat berilgan foydalanuvchi uchun ko'k "Narxlar" tugmasini
        # o'rnatish esa (finalize_approved_menu_button) Telegram serveriga
        # TARMOQ so'rovi -- bu ilgari GUI oqimida to'g'ridan-to'g'ri
        # bajarilib, "Ruxsat berish" tugmasi bosilganda dasturni bir necha
        # soniyaga muzlatib qo'yishi mumkin edi (xuddi Saqlash/Ulanishni
        # tekshirish tugmalaridagi kabi). Endi bu qism ALOHIDA oqimda
        # (_TelegramBgWorker) bajariladi.
        full_user = be.approve_telegram_user(user["chat_id"])
        self._refresh_lists()
        self._notify_async(full_user, True)

        self._approve_workers = getattr(self, "_approve_workers", [])
        worker = _TelegramBgWorker(lambda _u=full_user: be.finalize_approved_menu_button(_u), self)
        self._approve_workers.append(worker)

        def _on_done(_result, _w=worker):
            try:
                self._approve_workers.remove(_w)
            except ValueError:
                pass

        worker.finished.connect(_on_done)
        worker.start()

    def _reject(self, user):
        full_user = be.reject_telegram_user(user["chat_id"])
        self._refresh_lists()
        self._notify_async(full_user, False)

    def _remove(self, user):
        # BUG TUZATISH (dastur qulab tushishi -- 0xC0000005): confirm()
        # ("Bu odamni chiqarib tashlaymi?") o'zining ICHKI (nested) Qt
        # tsiklini ochadi -- shu payt ushbu oynaning 4 soniyalik avtomatik
        # yangilanish taymeri (self._timer) HAM ishlay olardi, u esa
        # _refresh_lists() orqali AYNAN shu tugma turgan kartochkani
        # (self.approved_container) butunlay qayta quradi/o'chiradi --
        # ya'ni tugmaning o'z signalini qayta ishlab turgan payt, o'zi
        # turgan vidjet ostidan yulib olinardi. Bu klassik PyQt qulashi
        # ("use-after-free"), Python xatosi sifatida umuman ko'rinmaydi --
        # dastur to'g'ridan-to'g'ri (native darajada) yopilib qoladi. Endi
        # confirm() ko'rsatilib turgan vaqtda taymer TO'XTATILADI, so'ng
        # (natijasi qanday bo'lishidan qat'i nazar) qayta ishga tushiriladi.
        self._timer.stop()
        try:
            _confirm_text = be.tr("Bu odamni ro'yxatdan chiqarib tashlaymi?")
            do_remove = confirm(self, be.tr("Chiqarib tashlash"),
                                 f"{self._plain_user_label(user)}\n\n{_confirm_text}")
        finally:
            self._timer.start(4000)
        if do_remove:
            removed = be.remove_telegram_user(user["chat_id"])
            self._refresh_lists()
            settings = be.load_settings()
            token = (settings.get("telegram_bot_token") or "").strip()
            if token and removed:
                import threading
                threading.Thread(target=be._notify_telegram_removal, args=(token, removed), daemon=True).start()

    def _notify_async(self, user, approved):
        if not user:
            return
        import threading

        def _run():
            settings = be.load_settings()
            token = (settings.get("telegram_bot_token") or "").strip()
            admin_chat_id = (settings.get("telegram_admin_chat_id") or "").strip()
            if token:
                be._notify_telegram_decision(token, admin_chat_id, user, approved, via_app=True)

        threading.Thread(target=_run, daemon=True).start()


# =============================================================================
# DashboardPage
# =============================================================================

class DashboardPage(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        # MUHIM TUZATISH: foydalanuvchi so'rovi bo'yicha bosh sahifadagi
        # katta (tashqi) skroll olib tashlandi -- endi sahifa oddiy
        # QVBoxLayout bilan chiziladi, tarkib doim bitta ekranga sig'adigan
        # qilib ixchamlashtirildi (pastda "Kam qolgan mahsulotlar" jadvali
        # ham kichraytirildi).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 24)
        outer.setSpacing(16)

        self.title_lbl = TitleLabel(be.tr("Bosh sahifa"))
        outer.addWidget(self.title_lbl)

        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(14)
        outer.addLayout(self.cards_grid)

        # MUHIM: foydalanuvchi so'rovi bo'yicha "Kam qolgan mahsulotlar"
        # konteyneri kattalashtirildi (ichki bo'shliqlar va jadval balandligi
        # oshirildi, sarlavha shrifti kattalashtirildi).
        low_stock_card = SimpleCardWidget(self)
        low_stock_layout = QVBoxLayout(low_stock_card)
        low_stock_layout.setContentsMargins(20, 18, 20, 20)
        low_stock_layout.setSpacing(10)
        self.low_stock_title = StrongBodyLabel(be.tr("Kam qolgan mahsulotlar"))
        # MUHIM TUZATISH: rangsiz setStyleSheet("font-size: 17px;") o'rniga
        # QFont pixel o'lchami orqali kattalashtiriladi -- shunda
        # StrongBodyLabel'ning tema-moslashuvchan matn rangi buzilmaydi
        # (aks holda kunduzgi rejimda sarlavha ko'rinmay qolardi).
        _lst_font = self.low_stock_title.font()
        _lst_font.setPixelSize(17)
        self.low_stock_title.setFont(_lst_font)
        low_stock_layout.addWidget(self.low_stock_title)
        self.low_stock_model = LowStockTableModel()
        self.low_stock_table = TableView(self)
        self.low_stock_table.setModel(self.low_stock_model)
        self.low_stock_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.low_stock_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.low_stock_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.low_stock_table.setViewportMargins(0, 0, 14, 0)
        # MUHIM TUZATISH: endi bu jadval SAHIFANING O'ZI skroll qilinmasdan
        # (tashqi katta skrolsiz), konteyner ichidagi qolgan bo'sh joyni
        # to'liq TO'LDIRIB, dastur pastigacha cho'ziladi (qattiq balandlik
        # chegarasi olib tashlandi, faqat minimal balandlik qoldirildi).
        # qfluentwidgets.TableView o'zining ichki SmoothScrollDelegate'i
        # tufayli sichqoncha g'ildiragi bilan skroll qilinganda avtomatik
        # SILLIQ (smooth/animatsiyali) ishlaydi.
        self.low_stock_table.setMinimumHeight(150)
        fix_table_hover_highlight(self.low_stock_table)
        low_stock_layout.addWidget(self.low_stock_table, 1)
        outer.addWidget(low_stock_card, 1)

        # MUHIM: "Kunni yopish" tugmasi ATAYLAB olib tashlandi -- kun endi
        # to'liq AVTOMATIK ravishda yarim tunda (00:00) yopiladi (hatto
        # dastur o'sha payt ochilmagan bo'lsa ham, keyingi safar ochilganda
        # orqada qolgan kunlar avtomatik yopiladi). Foydalanuvchi buni qo'lda
        # bosishi shart emas.

        self.refresh()

    def retranslate(self):
        self.title_lbl.setText(be.tr("Bosh sahifa"))
        self.low_stock_title.setText(be.tr("Kam qolgan mahsulotlar"))
        self.low_stock_model.retranslate()
        self.refresh()

    def _clear_grid(self):
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def refresh(self):
        self._clear_grid()
        today = be.today_str()
        conn = be.get_conn()
        # MUHIM: faqat hali biror "kun yopilishi"ga bog'lanmagan (closure_id
        # IS NULL) sotuvlar hisoblanadi -- shunda kun yopilgandan so'ng
        # "Bugungi" ko'rsatkichlar darhol 0 ga tushadi (asl tkinter
        # versiyasidagi xatti-harakat bilan bir xil).
        # MUHIM (foydalanuvchi so'rovi bilan): nasiyaga savdo qilinganda
        # xaridor hozir bir qismini (paid_now) darhol to'lasa, o'sha qism
        # endi "Bugungi savdo (naqd)"ga, qolgani "nasiya"ga hisoblanadi
        # (be.get_naqd_nasiya_totals orqali -- haqiqiy kassadagi pul
        # bilan mos kelishi uchun; foyda hisob-kitobi o'zgarmaydi).
        sales_naqd, profit_naqd, sales_nasiya, profit_nasiya = be.get_naqd_nasiya_totals(
            today, closure_open_only=True)
        # MUHIM TUZATISH: avval bu yerda tan narxi (cost_price*qty) bo'yicha
        # hisoblangan, lekin "Hisobot" sahifasidagi xuddi shu "Ombor qiymati"
        # ko'rsatkichi SOTISH NARXI (price*qty) bo'yicha hisoblanadi edi --
        # ikki sahifada turli formula ishlatilgani chalkashlik keltirib
        # chiqargan. Endi ikkalasi ham sotish narxi bo'yicha hisoblanadi.
        warehouse_value = conn.execute(
            "SELECT COALESCE(SUM(price*qty),0) FROM products").fetchone()[0]
        debt_total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM debts WHERE paid=0").fetchone()[0]
        low_stock_rows = conn.execute(
            "SELECT name, qty, unit FROM products WHERE qty <= 5 ORDER BY qty ASC").fetchall()
        conn.close()

        # MUHIM O'ZGARISH (foydalanuvchi so'rovi bilan): alohida "Bugungi
        # foyda (nasiya)" kartochkasi OLIB TASHLANDI. Endi, biror nasiya
        # (qarz) BUGUN to'langan bo'lsa, o'sha qarzni yaratgan sotuvning
        # HAQIQIY foydasi (sale_batch orqali sales jadvalidan olinadi)
        # to'g'ridan-to'g'ri "Foyda" kartochkasiga (avvalgi nomi "Foyda
        # (naqd)") qo'shib ko'rsatiladi -- qarz to'langan zahoti foyda
        # shu yerda ko'rinadi, alohida oyna kerak emas.
        rolled_over_profit = be.get_todays_rolled_over_nasiya_profit()
        foyda_total = profit_naqd + rolled_over_profit
        # MUHIM O'ZGARISH: "kutilayotgan foyda" endi HALI TO'LANMAGAN
        # (paid=0) nasiya sotuvlar bo'yicha hisoblanadi -- aks holda, qarz
        # bugun to'langan bo'lsa, uning foydasi HAM shu yerda ("kutilayotgan"
        # sifatida), HAM yuqoridagi "Foyda" kartochkasida (haqiqiy sifatida)
        # ko'rinib, ikki marta hisoblanib qolar edi.
        pending_nasiya_profit = be.get_pending_nasiya_profit_for_date(today)

        cards = [
            (be.tr("Bugungi savdo (naqd)"), f"{be.fmt_money(sales_naqd)} so'm", be.tr("naqd/karta"), ACCENT_COLOR),
            (be.tr("Foyda"), f"{be.fmt_money(foyda_total)} so'm", be.tr("sof foyda (to'langan nasiyalar bilan)"), "#2ECC71"),
            (be.tr("Bugungi nasiya (qarzga)"), f"{be.fmt_money(sales_nasiya)} so'm",
             be.tr("kutilayotgan foyda: {v} so'm").format(v=be.fmt_money(pending_nasiya_profit)), "#7C5CFC"),
            (be.tr("Ombor qiymati"), f"{be.fmt_money(warehouse_value)} so'm", be.tr("sotish narxi bo'yicha"), None),
            (be.tr("Qarzdorlik"), f"{be.fmt_money(debt_total)} so'm", be.tr("to'lanmagan"), "#E5484D"),
        ]
        for idx, (title, value, sub, accent) in enumerate(cards):
            card = make_stat_card(title, value, sub, accent=accent, anim_key=("dash", idx))
            self.cards_grid.addWidget(card, idx // 3, idx % 3)

        self.low_stock_model.set_rows(low_stock_rows)

    def _do_close_day(self, manual=True):
        today = be.today_str()
        conn = be.get_conn()
        already = conn.execute("SELECT id FROM day_closures WHERE date=?", (today,)).fetchone()
        conn.close()

        # be.close_day_for_date() sotuvlarni "closure_id" bilan belgilaydi,
        # shu bilan ular darhol "Bugungi ochiq savdo" hisobidan chiqadi va
        # Bosh sahifadagi ko'rsatkichlar 0 ga tushadi. Kun allaqachon
        # yopilgan bo'lsa-yu, shundan keyin yangi savdo/to'lov bo'lgan
        # bo'lsa, ular mavjud yopilishga qo'shiladi.
        closure_id = be.close_day_for_date(today, allow_empty=False)
        if closure_id is None:
            if manual:
                if already:
                    info_warning(self, be.tr("Diqqat"), be.tr("Bugungi kun allaqachon yopilgan."))
                else:
                    info_warning(self, be.tr("Diqqat"), be.tr("Bugun hali sotuv qilinmagan, yopish uchun narsa yo'q."))
            return

        if manual:
            info_success(self, be.tr("Kun yopildi"), be.tr("Bugungi kun muvaffaqiyatli yopildi."))
        self.refresh()
        if hasattr(self.main_window, "closures_page"):
            self.main_window.closures_page.refresh()


# =============================================================================
# ProductsPage
# =============================================================================

class ProductsPage(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 24)
        outer.setSpacing(14)

        self.title_lbl = TitleLabel(be.tr("Mahsulotlar"))
        outer.addWidget(self.title_lbl)

        # --- Kirim (mahsulot keldi) -- shtrix kod skanerlab tezda miqdor qo'shish ---
        restock_card = SimpleCardWidget(self)
        restock_card.setStyleSheet("SimpleCardWidget { border: 1px solid #F0641E; }")
        restock_row = QHBoxLayout(restock_card)
        restock_row.setContentsMargins(14, 10, 14, 10)
        self.restock_label = StrongBodyLabel(be.tr("Kirim (mahsulot keldi):"))
        self.restock_label.setStyleSheet("color:#F0641E;")
        restock_row.addWidget(self.restock_label)
        self.restock_qty_label = BodyLabel(be.tr("Miqdor:"))
        restock_row.addWidget(self.restock_qty_label)
        self.restock_qty_edit = LineEdit(self)
        self.restock_qty_edit.setText("1")
        self.restock_qty_edit.setFixedWidth(60)
        restock_row.addWidget(self.restock_qty_edit)
        self.restock_barcode_edit = LineEdit(self)
        self.restock_barcode_edit.setPlaceholderText(be.tr("Shtrix kodni skanerlang yoki kiriting..."))
        self.restock_barcode_edit.setFixedWidth(220)
        self.restock_barcode_edit.returnPressed.connect(self.on_restock_scan)
        restock_row.addWidget(self.restock_barcode_edit)
        self.restock_status = CaptionLabel(be.tr("Shtrix kodni skanerlang — mahsulot avtomatik topiladi"))
        restock_row.addWidget(self.restock_status, 1)
        outer.addWidget(restock_card)

        top_row = QHBoxLayout()
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText(be.tr("Mahsulot qidirish..."))
        # MUHIM (foydalanuvchi so'rovi bilan): shtrix kod bu maydonga
        # skanerlanganda (yoki nomi yozilganda) ENDI HECH QANDAY tanlash
        # oynasi CHIQMAYDI -- faqat mos keladigan barcha mahsulotlar
        # jadvalda ro'yxat sifatida ko'rsatiladi (bir xil shtrix kodli
        # bir nechta mahsulot bo'lsa, ularning hammasi ro'yxatda ko'rinadi).
        self.search_edit.textChanged.connect(debounced(self, self.refresh))
        top_row.addWidget(self.search_edit, 1)
        self.add_btn = PrimaryPushButton(be.tr("Mahsulot qo'shish"), self)
        self.add_btn.clicked.connect(self.add_product)
        top_row.addWidget(self.add_btn)
        outer.addLayout(top_row)

        self.model = ProductsTableModel()
        self.table = TableView(self)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # MUHIM (foydalanuvchi so'rovi bilan): birinchi ustun -- mahsulot
        # rasmi (thumbnail) -- boshqa ustunlar kabi cho'zilib ketmasligi
        # uchun FIXED va tor qilib qo'yiladi, qator balandligi esa rasm
        # sig'ishi uchun oshiriladi.
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 68)
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setViewportMargins(0, 0, 14, 0)
        fix_table_hover_highlight(self.table)
        # MUHIM (foydalanuvchi so'rovi bilan): rasm ustuniga bosilganda,
        # rasmni kattalashtirib ko'rsatish (animatsiya bilan).
        self.table.clicked.connect(self._on_table_clicked)
        outer.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.edit_btn = PushButton(be.tr("Tahrirlash"), self)
        self.edit_btn.clicked.connect(self.edit_product)
        self.qty_btn = PushButton(be.tr("Miqdorni o'zgartirish"), self)
        self.qty_btn.clicked.connect(self.edit_qty)
        self.barcode_btn = PushButton(be.tr("Shtrix kodni chop etish"), self)
        self.barcode_btn.clicked.connect(self.print_barcode)
        self.delete_btn = PushButton(be.tr("O'chirish"), self)
        self.delete_btn.clicked.connect(self.delete_product)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.qty_btn)
        btn_row.addWidget(self.barcode_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        self.refresh()

        # MUHIM TUZATISH: foydalanuvchi Mini App orqali (telefondan) mahsulot
        # qo'shsa/o'chirsa/tahrirlasa, bazaga TO'G'RIDAN-TO'G'RI (alohida
        # oqim/thread orqali) yoziladi -- lekin kompyuterdagi bu sahifa
        # avvalroq yuklab olingan RO'YXATNI xotirada saqlab turadi va uni
        # o'zi qayta so'ramaguncha yangilamaydi. Natijada, masalan, telefondan
        # o'chirilgan mahsulot kompyuterda hali ham "bor" bo'lib ko'rinar edi.
        # Shuning uchun bu sahifa HAR 4 SONIYADA (agar aynan shu sahifa
        # hozir ko'rinib turgan bo'lsa) o'zini avtomatik yangilab turadi.
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh_if_visible)
        self._auto_refresh_timer.start(4000)

    def _auto_refresh_if_visible(self):
        # Foydalanuvchi qidiruv maydoniga yozayotgan bo'lsa, yozishga
        # xalal bermaslik uchun avtomatik yangilash o'tkazib yuboriladi.
        if self.isVisible() and not self.search_edit.hasFocus():
            self.refresh()

    def retranslate(self):
        self.title_lbl.setText(be.tr("Mahsulotlar"))
        self.restock_label.setText(be.tr("Kirim (mahsulot keldi):"))
        self.restock_qty_label.setText(be.tr("Miqdor:"))
        self.restock_barcode_edit.setPlaceholderText(be.tr("Shtrix kodni skanerlang yoki kiriting..."))
        self.restock_status.setText(be.tr("Shtrix kodni skanerlang — mahsulot avtomatik topiladi"))
        self.search_edit.setPlaceholderText(be.tr("Mahsulot qidirish..."))
        self.add_btn.setText(be.tr("Mahsulot qo'shish"))
        self.edit_btn.setText(be.tr("Tahrirlash"))
        self.qty_btn.setText(be.tr("Miqdorni o'zgartirish"))
        self.barcode_btn.setText(be.tr("Shtrix kodni chop etish"))
        self.delete_btn.setText(be.tr("O'chirish"))
        self.model.retranslate()
        self.refresh()

    def _refresh_sales_page(self):
        if hasattr(self.main_window, "sales_page"):
            self.main_window.sales_page.refresh_products()

    def on_restock_scan(self):
        code = self.restock_barcode_edit.text().strip()
        self.restock_barcode_edit.clear()
        if not code:
            return
        try:
            add_qty = float(self.restock_qty_edit.text())
        except ValueError:
            add_qty = 1.0
        if add_qty <= 0:
            add_qty = 1.0

        conn = be.get_conn()
        matches = conn.execute(
            "SELECT id, name, cost_price, price, qty, unit, barcode, image_path FROM products WHERE barcode=?",
            (code,)).fetchall()
        conn.close()

        if not matches:
            self.restock_status.setText(f"'{code}' — {be.tr('mos mahsulot topilmadi')}")
            if confirm(self, be.tr("Topilmadi"),
                       be.tr("'{code}' shtrix koduga mos mahsulot yo'q.\n\n"
                             "Bu yangi mahsulotmi? 'Ha' desangiz, shu kod bilan\n"
                             "yangi mahsulot qo'shish oynasi ochiladi.").format(code=code)):
                dlg = ProductDialog(self, initial=("", "", "", str(add_qty), "dona", code, None))
                if dlg.exec() == QDialog.Accepted and dlg.result_data:
                    (name, cost_price, price, qty, unit, barcode, _auto,
                     image_action, new_image_path) = dlg.result_data
                    conn = be.get_conn()
                    conn.execute(
                        "INSERT INTO products (name, cost_price, price, qty, unit, barcode) VALUES (?,?,?,?,?,?)",
                        (name, cost_price, price, qty, unit, barcode))
                    conn.commit()
                    new_pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.close()
                    if image_action == "set" and new_image_path:
                        try:
                            be.save_product_image_from_file(new_pid, new_image_path)
                        except Exception:
                            pass
                    self.refresh()
                    self._refresh_sales_page()
                    if hasattr(self.main_window, "dashboard_page"):
                        self.main_window.dashboard_page.refresh()
            self.restock_barcode_edit.setFocus()
            return

        if len(matches) == 1:
            row = matches[0]
        else:
            # MUHIM TUZATISH: ilgari bir xil shtrix kodga bir nechta
            # mahsulot mos kelsa, dastur ULARDAN QAYSINI BAZA QAYTARSA
            # O'SHANI (tasodifiy/birinchi) tanlab, faqat o'shaning
            # miqdorini oshirar edi -- foydalanuvchiga tanlov berilmasdi.
            # Endi savatdagi shtrix kod maydoni bilan BIR XIL: bir nechta
            # mos mahsulot topilsa, "Mahsulotni tanlang" oynasi chiqadi.
            dlg = BarcodeChoiceDialog(self, matches)
            if dlg.exec() != QDialog.Accepted or not dlg.chosen_row:
                self.restock_barcode_edit.setFocus()
                return
            row = dlg.chosen_row

        pid, name, cost_price, price, qty, unit, barcode, image_path = row
        new_qty = qty + add_qty
        conn = be.get_conn()
        conn.execute("UPDATE products SET qty=? WHERE id=?", (new_qty, pid))
        conn.commit()
        conn.close()

        self.restock_status.setText(
            f"✓ {name}: +{be.fmt_qty(add_qty, unit)} {be.tr('qoshildi')} "
            f"({be.tr('jami')}: {be.fmt_qty(new_qty, unit)})")
        self.refresh()
        self._refresh_sales_page()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()
        self.restock_barcode_edit.setFocus()

    def refresh(self):
        # MUHIM TUZATISH (foydalanuvchi so'rovi bilan): ilgari refresh()
        # HAR DOIM tanlovni tozalar edi -- bu esa sahifa har 4 soniyada
        # o'zini avtomatik yangilab turgani (_auto_refresh_timer, Mini App
        # bilan sinxronlash uchun) bilan qo'shilib, foydalanuvchi mahsulot
        # tanlab "Tahrirlash"ni bosishga ulgurmasdan tanlov o'chib
        # ketardi -- shu sabab "tahrirlash ishlamayapti" va "avval
        # mahsulotni tanlang" xatosi chiqardi. Endi joriy tanlangan
        # mahsulotning ID'si eslab qolinadi va ro'yxat qayta yuklangandan
        # keyin, agar o'sha mahsulot hali mavjud bo'lsa, u QAYTA
        # tanlanadi -- faqat haqiqatan o'chirilgan/topilmay qolgan bo'lsa
        # tanlov tozalanadi.
        selected_pid = None
        idxs = self.table.selectionModel().selectedRows()
        if idxs:
            old_row = self.model.row_at(idxs[0].row())
            if old_row:
                selected_pid = old_row[0]

        query = (self.search_edit.text() or "").strip().lower()
        conn = be.get_conn()
        rows = conn.execute(
            "SELECT id, name, cost_price, price, qty, unit, barcode, image_path FROM products ORDER BY name").fetchall()
        conn.close()
        if query:
            rows = [r for r in rows if query in r[1].lower() or (r[6] and query in r[6].lower())]
        self.model.set_rows(rows)

        if selected_pid is not None:
            for i, r in enumerate(rows):
                if r[0] == selected_pid:
                    new_index = self.model.index(i, 0)
                    self.table.setCurrentIndex(new_index)
                    self.table.selectionModel().select(
                        new_index,
                        QItemSelectionModel.Select | QItemSelectionModel.Rows)
                    return

        # Avvalgi tanlangan mahsulot endi mavjud emas (yoki hech narsa
        # tanlanmagan edi) -- tanlovni tozalaymiz.
        self.table.clearSelection()
        self.table.setCurrentIndex(QModelIndex())

    def _selected_product(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            info_warning(self, be.tr("Diqqat"), be.tr("Avval jadvaldan mahsulotni tanlang."))
            return None
        return self.model.row_at(idxs[0].row())

    def _on_table_clicked(self, index):
        # MUHIM (foydalanuvchi so'rovi bilan): faqat rasm ustuniga (0)
        # bosilganda, mavjud rasm bo'lsa, uni kattalashtirib ko'rsatamiz.
        if not index.isValid() or index.column() != 0:
            return
        row = self.model.row_at(index.row())
        if not row:
            return
        image_path = row[7]
        full_path = be.get_product_image_full_path(image_path)
        if not full_path:
            return
        pixmap = QPixmap(full_path)
        if pixmap.isNull():
            return
        host = self.window()
        self._zoom_overlay = ImageZoomOverlay(host, pixmap)

    def add_product(self):
        dlg = ProductDialog(self)
        if dlg.exec() != QDialog.Accepted or not dlg.result_data:
            return
        (name, cost_price, price, qty, unit, barcode, auto_generated,
         image_action, new_image_path) = dlg.result_data

        existing = be.find_product_by_name(name)
        if existing:
            eid, ename, ecost, eprice, eqty, eunit, ebarcode = existing
            if confirm(self, be.tr("Bunday mahsulot allaqachon bor"),
                       be.tr("\"{name}\" nomli mahsulot omborda allaqachon mavjud (qoldiq: {qty}).\n\n"
                             "Yangi mahsulot sifatida qo'shish o'rniga, ushbu miqdorni ({add_qty}) "
                             "mavjud mahsulotga QO'SHIB qo'yaymi?").format(
                                 name=ename, qty=be.fmt_qty(eqty, eunit), add_qty=be.fmt_qty(qty, unit))):
                conn = be.get_conn()
                conn.execute("UPDATE products SET qty = qty + ? WHERE id=?", (qty, eid))
                conn.commit()
                conn.close()
                if image_action == "set" and new_image_path:
                    try:
                        be.save_product_image_from_file(eid, new_image_path)
                    except Exception:
                        pass
                elif image_action == "remove":
                    try:
                        be.delete_product_image(eid)
                    except Exception:
                        pass
                info_success(self, be.tr("Yangilandi"), be.tr("Mahsulot miqdori yangilandi."))
                self.refresh()
                self._refresh_sales_page()
                if hasattr(self.main_window, "dashboard_page"):
                    self.main_window.dashboard_page.refresh()
                return
            else:
                info_warning(self, be.tr("Bekor qilindi"),
                              be.tr("Dublikat mahsulot yaratilmadi. Xohlasangiz nomni o'zgartirib qayta urinib ko'ring."))
                return

        conn = be.get_conn()
        conn.execute(
            "INSERT INTO products (name, cost_price, price, qty, unit, barcode) VALUES (?,?,?,?,?,?)",
            (name, cost_price, price, qty, unit, barcode))
        conn.commit()
        new_pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        if image_action == "set" and new_image_path:
            try:
                be.save_product_image_from_file(new_pid, new_image_path)
            except Exception:
                pass
        info_success(self, be.tr("Qo'shildi"), be.tr("Mahsulot omborga qo'shildi."))
        self.refresh()
        self._refresh_sales_page()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()

        if auto_generated:
            try:
                image = be.build_barcode_label_image(barcode, name, price)
                path = be.save_barcode_label(image, barcode)
                BarcodeLabelDialog(self, path, barcode, name, price).exec()
            except Exception:
                pass

    def edit_product(self):
        row = self._selected_product()
        if not row:
            return
        pid, name, cost_price, price, qty, unit, barcode, image_path = row
        dlg = ProductDialog(self, initial=(name, cost_price, price, qty, unit, barcode, image_path))
        if dlg.exec() != QDialog.Accepted or not dlg.result_data:
            return
        (new_name, new_cost, new_price, new_qty, new_unit, new_barcode, _auto,
         image_action, new_image_path) = dlg.result_data

        dup = be.find_product_by_name(new_name, exclude_id=pid)
        if dup:
            info_error(self, be.tr("Xato"),
                       be.tr("\"{name}\" nomli boshqa mahsulot allaqachon mavjud. "
                             "Boshqa nom tanlang.").format(name=dup[1]))
            return

        conn = be.get_conn()
        conn.execute(
            "UPDATE products SET name=?, cost_price=?, price=?, qty=?, unit=?, barcode=? WHERE id=?",
            (new_name, new_cost, new_price, new_qty, new_unit, new_barcode, pid))
        conn.commit()
        conn.close()
        # MUHIM (foydalanuvchi so'rovi bilan): mahsulot rasmini
        # yangilash/o'chirish.
        if image_action == "set" and new_image_path:
            try:
                be.save_product_image_from_file(pid, new_image_path)
            except Exception:
                pass
        elif image_action == "remove":
            try:
                be.delete_product_image(pid)
            except Exception:
                pass
        info_success(self, be.tr("Saqlandi"), be.tr("Mahsulot ma'lumotlari yangilandi."))
        self.refresh()
        self._refresh_sales_page()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()

    def edit_qty(self):
        row = self._selected_product()
        if not row:
            return
        pid, name, cost_price, price, qty, unit, barcode, image_path = row
        dlg = EditQtyDialog(self, name, unit, qty)
        if dlg.exec() != QDialog.Accepted or dlg.new_qty is None:
            return
        conn = be.get_conn()
        conn.execute("UPDATE products SET qty=? WHERE id=?", (dlg.new_qty, pid))
        conn.commit()
        conn.close()
        info_success(self, be.tr("Saqlandi"), be.tr("Miqdor yangilandi."))
        self.refresh()
        self._refresh_sales_page()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()

    def print_barcode(self):
        row = self._selected_product()
        if not row:
            return
        pid, name, cost_price, price, qty, unit, barcode, image_path = row
        if not barcode:
            info_warning(self, be.tr("Diqqat"), be.tr("Bu mahsulotda shtrix kod yo'q."))
            return
        try:
            image = be.build_barcode_label_image(barcode, name, price)
        except Exception as e:
            info_error(self, be.tr("Xato"), f"{e}")
            return
        path = be.save_barcode_label(image, barcode)
        BarcodeLabelDialog(self, path, barcode, name, price).exec()

    def delete_product(self):
        row = self._selected_product()
        if not row:
            return
        pid, name, cost_price, price, qty, unit, barcode, image_path = row
        if not confirm(self, be.tr("O'chirish"),
                        be.tr("\"{name}\" mahsulotini o'chirmoqchimisiz?").format(name=name)):
            return
        # MUHIM: mahsulot o'chirilishidan OLDIN rasm faylini o'chiramiz --
        # bazadan o'chirilgach image_path'ni topib bo'lmay qoladi.
        try:
            be.delete_product_image(pid)
        except Exception:
            pass
        conn = be.get_conn()
        conn.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        self.refresh()
        self._refresh_sales_page()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()


# =============================================================================
# SalesPage
# =============================================================================

class SalesPage(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.cart = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 24)
        outer.setSpacing(16)

        left = QVBoxLayout()
        self.title_lbl = TitleLabel(be.tr("Savdo"))
        left.addWidget(self.title_lbl)

        # --- Shtrix kod skaneri -- alohida, ajratib turuvchi qator (Enter bosilganda
        # darhol savatga tushadi). Qidirish maydonidan ataylab ajratilgan, chunki
        # skaner ham matn kiritadi va ular chalkashib ketmasligi kerak. ---
        scan_card = SimpleCardWidget(self)
        scan_card.setStyleSheet("SimpleCardWidget { border: 1px solid #F0641E; }")
        scan_row = QHBoxLayout(scan_card)
        scan_row.setContentsMargins(14, 10, 14, 10)
        self.scan_label = StrongBodyLabel(be.tr("⌁ Shtrix kod skaneri:"))
        self.scan_label.setStyleSheet("color:#F0641E;")
        scan_row.addWidget(self.scan_label)
        self.barcode_edit = LineEdit(self)
        self.barcode_edit.setFixedWidth(220)
        self.barcode_edit.returnPressed.connect(self._on_barcode_enter)
        scan_row.addWidget(self.barcode_edit)
        self.scan_hint = CaptionLabel(be.tr("Kursor shu yerda bo'lsa, skanerlash avtomatik ishlaydi"))
        scan_row.addWidget(self.scan_hint, 1)
        left.addWidget(scan_card)

        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText(be.tr("Mahsulot qidirish..."))
        self.search_edit.textChanged.connect(debounced(self, self._on_search_changed))
        left.addWidget(self.search_edit)

        self.products_model = ProductsTableModel()
        self.products_table = TableView(self)
        self.products_table.setModel(self.products_model)
        # MUHIM TUZATISH: ilgari BARCHA ustunlar (shu jumladan "Mahsulot
        # nomi") baravar Stretch qilingan edi -- shuning uchun uzun nomlar
        # qisqa ustunlar (Shtrix kod, Tan narxi va h.k.) bilan bir xil
        # kenglikda bo'lib, "..." bilan kesilib qolardi. Endi faqat
        # "Mahsulot nomi" ustuni (0) qolgan bo'sh joyni egallaydi, qolganlari
        # o'z mazmuniga mos ixcham kenglikda turadi.
        # MUHIM TUZATISH (tezlik): "Savdo" sahifasiga o'tganda 1-2 soniya
        # kutish kerak bo'lardi. Sababi: QHeaderView.ResizeToContents va
        # vertikal sarlavhadagi ResizeToContents rejimi doimiy ravishda
        # ISHLAB TURADI -- ya'ni sahifa har safar ko'rinadigan bo'lganda,
        # o'lchami o'zgarganda yoki model yangilanganda, Qt HAR BIR
        # katakning matn o'lchamini qaytadan hisoblab chiqadi (yuzlab
        # mahsulot bo'lsa, bu sezilarli sekinlashuvga olib keladi). Endi
        # bu hisoblash faqat mahsulotlar ro'yxati yangilanganda (qidiruv
        # o'zgarganda) BIR MARTA amalga oshiriladi (_refit_products_table),
        # so'ng ustunlar Interactive/Fixed rejimga o'tkaziladi -- shunda
        # sahifaga oddiy o'tish (navigatsiya) hech qanday qayta hisoblash
        # talab qilmaydi va darhol ochiladi.
        products_header = self.products_table.horizontalHeader()
        # MUHIM (foydalanuvchi so'rovi bilan): endi 0-ustun -- mahsulot
        # rasmi (thumbnail), shuning uchun cho'ziladigan ustun endi 1
        # ("Mahsulot nomi") bo'ladi, 0-ustun esa tor va FIXED.
        products_header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.products_table.setColumnWidth(0, 68)
        products_header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (2, 3, 4, 5):
            products_header.setSectionResizeMode(col, QHeaderView.Interactive)
        self.products_table.setWordWrap(True)
        self.products_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.products_table.verticalHeader().setDefaultSectionSize(64)
        self.products_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.products_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.products_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.products_table.doubleClicked.connect(lambda _i: self.add_to_cart())
        self.products_table.setViewportMargins(0, 0, 14, 0)
        fix_table_hover_highlight(self.products_table)
        # MUHIM (foydalanuvchi so'rovi bilan): rasm ustuniga bosilganda,
        # rasmni kattalashtirib ko'rsatish (animatsiya bilan).
        self.products_table.clicked.connect(self._on_products_table_clicked)
        left.addWidget(self.products_table, 1)

        add_row = QHBoxLayout()
        self.qty_label = BodyLabel(be.tr("Miqdori:"))
        add_row.addWidget(self.qty_label)
        # MUHIM: foydalanuvchi so'rovi bilan -- savatga qo'shishdan OLDIN
        # kiritiladigan miqdorni ham "-"/"+"  tugmalari bilan tez
        # o'zgartirish mumkin bo'lsin (savatdagi kabi).
        self.qty_minus_btn = PushButton("➖", self)
        self.qty_minus_btn.setFixedWidth(36)
        self.qty_minus_btn.clicked.connect(self._decrement_qty_edit)
        add_row.addWidget(self.qty_minus_btn)
        self.qty_edit = LineEdit(self)
        self.qty_edit.setText("1")
        self.qty_edit.setFixedWidth(70)
        add_row.addWidget(self.qty_edit)
        self.qty_plus_btn = PushButton("➕", self)
        self.qty_plus_btn.setFixedWidth(36)
        self.qty_plus_btn.clicked.connect(self._increment_qty_edit)
        add_row.addWidget(self.qty_plus_btn)
        self.unit_hint_lbl = CaptionLabel("dona")
        add_row.addWidget(self.unit_hint_lbl)
        add_row.addStretch(1)
        self.add_btn = PrimaryPushButton(be.tr("Savatga qo'shish"), self)
        self.add_btn.clicked.connect(self.add_to_cart)
        add_row.addWidget(self.add_btn)
        left.addLayout(add_row)

        self.products_table.selectionModel().selectionChanged.connect(self._on_select_product)

        outer.addLayout(left, 3)

        right = QVBoxLayout()
        self.cart_title = StrongBodyLabel(be.tr("Savat"))
        right.addWidget(self.cart_title)

        self.cart_model = CartTableModel()
        self.cart_table = TableView(self)
        self.cart_table.setModel(self.cart_model)
        # MUHIM TUZATISH: ilgari barcha ustunlar (shu jumladan "Mahsulot"
        # nomi) QHeaderView.Stretch bilan TENG bo'lib cho'zilar edi --
        # natijada 4 ustunga teng bo'lingan joyning atigi 1/4 qismi
        # "Mahsulot" nomiga tegar, uzun nomlar "..." bilan kesilib qolardi.
        # Endi "Mahsulot" ustuni (0) qolgan BO'SH joyni TO'LIQ egallaydi
        # (Stretch), boshqa ustunlar (Miqdor/Narxi/Summa) esa faqat o'z
        # kontentiga mos, ixcham kenglikda turadi -- shunda mahsulot nomi
        # uchun iloji boricha ko'proq joy qoladi va u to'liq ko'rinadi.
        # MUHIM TUZATISH (tezlik): savat kichik bo'lgani uchun bu yerda
        # ta'sir kamroq, ammo bir xillik va umumiy tezlik uchun bu jadval
        # ham products_table bilan bir xil Interactive/Fixed rejimga
        # o'tkazildi (qarang: yuqoridagi products_table sharhi).
        cart_header = self.cart_table.horizontalHeader()
        cart_header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            cart_header.setSectionResizeMode(col, QHeaderView.Interactive)
        # MUHIM: nom juda uzun bo'lsa ham (Stretch ustunga sig'masa),
        # matn "..." bilan kesilib qolmasin deb, qator ichida ikkinchi
        # qatorga o'tkaziladi (word wrap) va qator balandligi shu matnga
        # mos ravishda avtomatik kattalashadi.
        self.cart_table.setWordWrap(True)
        self.cart_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.cart_table.verticalHeader().setDefaultSectionSize(40)
        self.cart_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.cart_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart_table.setViewportMargins(0, 0, 14, 0)
        fix_table_hover_highlight(self.cart_table)
        right.addWidget(self.cart_table, 1)

        cart_btn_row = QHBoxLayout()
        # MUHIM: foydalanuvchi so'rovi bilan -- savatdagi tanlangan
        # mahsulotning miqdorini tez o'zgartirish uchun "+"/"-" tugmalari
        # qo'shildi (Mini App'dagi savat bilan bir xil qulaylik).
        self.dec_qty_btn = PushButton("➖", self)
        self.dec_qty_btn.setFixedWidth(44)
        self.dec_qty_btn.clicked.connect(self.decrease_cart_qty)
        self.inc_qty_btn = PushButton("➕", self)
        self.inc_qty_btn.setFixedWidth(44)
        self.inc_qty_btn.clicked.connect(self.increase_cart_qty)
        self.discount_btn = PushButton(be.tr("Chegirma"), self)
        self.discount_btn.clicked.connect(self.apply_discount)
        self.remove_btn = PushButton(be.tr("Olib tashlash"), self)
        self.remove_btn.clicked.connect(self.remove_from_cart)
        cart_btn_row.addWidget(self.dec_qty_btn)
        cart_btn_row.addWidget(self.inc_qty_btn)
        cart_btn_row.addWidget(self.discount_btn)
        cart_btn_row.addWidget(self.remove_btn)
        right.addLayout(cart_btn_row)

        self.total_lbl = QLabel(be.tr("Jami: 0 so'm"))
        self.total_lbl.setObjectName("totalLabel")
        right.addWidget(self.total_lbl)

        self.sell_btn = PrimaryPushButton(be.tr("Sotish"), self)
        self.sell_btn.clicked.connect(self.finalize_sale)
        right.addWidget(self.sell_btn)
        self.credit_btn = PushButton(be.tr("Nasiyaga berish"), self)
        self.credit_btn.clicked.connect(self.finalize_credit)
        right.addWidget(self.credit_btn)
        self.clear_btn = PushButton(be.tr("Savatni tozalash"), self)
        self.clear_btn.clicked.connect(self.clear_cart)
        right.addWidget(self.clear_btn)

        outer.addLayout(right, 2)

        self.refresh_products()

    def retranslate(self):
        self.title_lbl.setText(be.tr("Savdo"))
        self.scan_label.setText(be.tr("⌁ Shtrix kod skaneri:"))
        self.scan_hint.setText(be.tr("Kursor shu yerda bo'lsa, skanerlash avtomatik ishlaydi"))
        self.search_edit.setPlaceholderText(be.tr("Mahsulot qidirish..."))
        self.qty_label.setText(be.tr("Miqdori:"))
        self.add_btn.setText(be.tr("Savatga qo'shish"))
        self.cart_title.setText(be.tr("Savat"))
        self.discount_btn.setText(be.tr("Chegirma"))
        self.remove_btn.setText(be.tr("Olib tashlash"))
        self.sell_btn.setText(be.tr("Sotish"))
        self.credit_btn.setText(be.tr("Nasiyaga berish"))
        self.clear_btn.setText(be.tr("Savatni tozalash"))
        self.products_model.retranslate()
        self.cart_model.retranslate()
        self._update_total()

    def refresh_products(self):
        query = (self.search_edit.text() or "").strip().lower()
        conn = be.get_conn()
        rows = conn.execute(
            "SELECT id, name, cost_price, price, qty, unit, barcode, image_path FROM products ORDER BY name").fetchall()
        conn.close()
        if query:
            rows = [r for r in rows if query in r[1].lower() or (r[6] and query in r[6].lower())]
        self.products_model.set_rows(rows)
        self.products_table.clearSelection()
        # MUHIM TUZATISH (tezlik): ustun kengliklari faqat shu yerda --
        # ro'yxat haqiqatan yangilanganda -- bir marta hisoblanadi (aks
        # holda doimiy Interactive rejim ularni o'zgartirmaydi). Shu bilan
        # sahifaga oddiy o'tishda (navigatsiyada) hech qanday qayta
        # hisoblash bo'lmaydi, sahifa darhol ochiladi.
        self.products_table.resizeColumnsToContents()
        self.products_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.products_table.setColumnWidth(0, 68)
        self.products_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

    def _on_search_changed(self):
        self.refresh_products()

    def _on_products_table_clicked(self, index):
        # MUHIM (foydalanuvchi so'rovi bilan): faqat rasm ustuniga (0)
        # bosilganda, mavjud rasm bo'lsa, uni kattalashtirib ko'rsatamiz.
        if not index.isValid() or index.column() != 0:
            return
        row = self.products_model.row_at(index.row())
        if not row:
            return
        image_path = row[7]
        full_path = be.get_product_image_full_path(image_path)
        if not full_path:
            return
        pixmap = QPixmap(full_path)
        if pixmap.isNull():
            return
        host = self.window()
        self._zoom_overlay = ImageZoomOverlay(host, pixmap)

    def _on_select_product(self, *_args):
        idxs = self.products_table.selectionModel().selectedRows()
        if not idxs:
            return
        row = self.products_model.row_at(idxs[0].row())
        if row:
            self.unit_hint_lbl.setText(row[5])
            self.qty_edit.setText("1")

    def _on_barcode_enter(self):
        code = (self.barcode_edit.text() or "").strip()
        self.barcode_edit.clear()
        if not code:
            return
        # MUHIM TUZATISH: ilgari bu yerda qty=1 QATTIQ YOZILGAN edi -- ya'ni
        # "Miqdori:" maydoniga necha yozilishidan qat'i nazar, shtrix kod
        # skanerlanganda HAR DOIM 1 dona qo'shilardi. Endi xuddi qo'lda
        # "Savatga qo'shish" bosilganidek, "Miqdori:" maydonidagi qiymat
        # o'qiladi -- bu barcha birliklar (dona, kg, litr, metr) uchun bir
        # xil ishlaydi, chunki miqdor har doim oddiy o'nlik son sifatida
        # saqlanadi.
        try:
            qty = float(self.qty_edit.text())
        except ValueError:
            qty = 1
        if qty <= 0:
            qty = 1
        conn = be.get_conn()
        matches = conn.execute(
            "SELECT id, name, cost_price, price, qty, unit, barcode, image_path FROM products WHERE barcode=?",
            (code,)).fetchall()
        conn.close()
        if not matches:
            info_warning(self, be.tr("Topilmadi"),
                         be.tr("'{code}' shtrix koduga mos mahsulot topilmadi.\n"
                               "Mahsulotlar bo'limida shu kodni mahsulotga biriktiring.").format(code=code))
        elif len(matches) == 1:
            self._add_product_row(matches[0], qty=qty)
            self.refresh_products()
        else:
            # MUHIM: ba'zan zavod/ta'minotchidan har xil nomdagi mahsulotlar
            # bir xil shtrix kod bilan keladi -- bunday holatda dastur
            # o'zicha birortasini tanlab qo'ymaydi, foydalanuvchiga tanlov
            # oynasini ko'rsatadi.
            dlg = BarcodeChoiceDialog(self, matches)
            if dlg.exec() == QDialog.Accepted and dlg.chosen_row:
                self._add_product_row(dlg.chosen_row, qty=qty)
                self.refresh_products()
        self.barcode_edit.setFocus()

    def add_to_cart(self):
        idxs = self.products_table.selectionModel().selectedRows()
        if not idxs:
            info_warning(self, be.tr("Diqqat"), be.tr("Avval jadvaldan mahsulotni tanlang."))
            return
        try:
            qty = float(self.qty_edit.text())
        except ValueError:
            info_error(self, be.tr("Xato"), be.tr("Miqdorni to'g'ri kiriting (masalan: 0.9)."))
            return
        if qty <= 0:
            info_error(self, be.tr("Xato"), be.tr("Miqdor musbat son bo'lishi kerak."))
            return
        row = self.products_model.row_at(idxs[0].row())
        self._add_product_row(row, qty=qty)

    def _add_product_row(self, row, qty=1):
        pid, name, cost_price, price, avail_qty, unit, barcode, image_path = row
        if avail_qty <= 0:
            info_warning(self, be.tr("Diqqat"), be.tr("Bu mahsulot omborda qolmagan."))
            return
        for item in self.cart:
            if item["product_id"] == pid:
                if item["qty"] + qty > avail_qty + 1e-9:
                    info_warning(self, be.tr("Yetarli emas"),
                                 be.tr("Omborda faqat {qty} bor.").format(qty=be.fmt_qty(avail_qty, unit)))
                    return
                item["qty"] += qty
                item["total"] = item["qty"] * item["price"]
                self._refresh_cart_model()
                return
        if qty > avail_qty + 1e-9:
            info_warning(self, be.tr("Yetarli emas"),
                         be.tr("Omborda faqat {qty} bor.").format(qty=be.fmt_qty(avail_qty, unit)))
            return
        self.cart.append({
            "product_id": pid, "name": name, "unit": unit, "qty": qty,
            "cost_price": cost_price, "price": price, "list_price": price,
            "total": qty * price,
        })
        self._refresh_cart_model()

    def _refresh_cart_model(self, keep_selected_row=None):
        self.cart_model.set_rows(self.cart)
        # MUHIM TUZATISH (tezlik): savat kichik bo'lgani uchun bu yerda
        # bir martalik qayta o'lchash arzon -- ustunlar Interactive rejimda
        # qolgani uchun sahifaga oddiy o'tishda qayta hisoblanmaydi.
        self.cart_table.resizeColumnsToContents()
        self.cart_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._update_total()
        # MUHIM TUZATISH: model qayta o'rnatilganda (set_rows -> reset)
        # QTableView'ning tanlangan qatori avtomatik TOZALANIB ketadi --
        # shuning uchun "+"/"-"/chegirma tugmalarini KETMA-KET (bir necha
        # marta) bosganda, ikkinchi bosishda "avval mahsulotni tanlang"
        # degan xato chiqar edi. Endi qaysi qator tanlangan bo'lsa,
        # yangilashdan KEYIN ham o'sha qator (yoki savat qisqarib qolgan
        # bo'lsa -- eng yaqin qolgan qator) qayta tanlanadi.
        if keep_selected_row is not None and self.cart:
            row_to_select = min(keep_selected_row, len(self.cart) - 1)
            self.cart_table.selectRow(row_to_select)

    def _update_total(self):
        total = sum(i["total"] for i in self.cart)
        self.total_lbl.setText(f"{be.tr('Jami')}: {be.fmt_money(total)} so'm")

    def _selected_cart_item(self):
        idxs = self.cart_table.selectionModel().selectedRows()
        if not idxs:
            info_warning(self, be.tr("Diqqat"), be.tr("Avval savatdan mahsulotni tanlang."))
            return None
        return idxs[0].row()

    def apply_discount(self):
        row_idx = self._selected_cart_item()
        if row_idx is None:
            return
        item = self.cart[row_idx]
        dlg = DiscountDialog(self, item["name"], item["list_price"], item["price"], unit=item.get("unit") or "dona")
        if dlg.exec() != QDialog.Accepted or dlg.new_price is None:
            return
        item["price"] = dlg.new_price
        item["total"] = item["qty"] * item["price"]
        self._refresh_cart_model(keep_selected_row=row_idx)

    def remove_from_cart(self):
        row_idx = self._selected_cart_item()
        if row_idx is None:
            return
        self.cart.pop(row_idx)
        self._refresh_cart_model()

    def _increment_qty_edit(self):
        try:
            cur = float(self.qty_edit.text())
        except ValueError:
            cur = 0
        cur = max(0, cur) + 1
        self.qty_edit.setText(be.fmt_qty(cur, "").strip())

    def _decrement_qty_edit(self):
        try:
            cur = float(self.qty_edit.text())
        except ValueError:
            cur = 1
        cur = max(1, cur - 1)
        self.qty_edit.setText(be.fmt_qty(cur, "").strip())

    def increase_cart_qty(self):
        row_idx = self._selected_cart_item()
        if row_idx is None:
            return
        item = self.cart[row_idx]
        conn = be.get_conn()
        row = conn.execute("SELECT qty FROM products WHERE id=?", (item["product_id"],)).fetchone()
        conn.close()
        avail_qty = row[0] if row else 0
        if item["qty"] + 1 > avail_qty + 1e-9:
            info_warning(self, be.tr("Yetarli emas"),
                         be.tr("Omborda faqat {qty} bor.").format(
                             qty=be.fmt_qty(avail_qty, item.get("unit") or "dona")))
            return
        item["qty"] += 1
        item["total"] = item["qty"] * item["price"]
        self._refresh_cart_model(keep_selected_row=row_idx)

    def decrease_cart_qty(self):
        row_idx = self._selected_cart_item()
        if row_idx is None:
            return
        item = self.cart[row_idx]
        item["qty"] -= 1
        removed = item["qty"] <= 1e-9
        if removed:
            self.cart.pop(row_idx)
        else:
            item["total"] = item["qty"] * item["price"]
        self._refresh_cart_model(keep_selected_row=row_idx)

    def clear_cart(self):
        self.cart = []
        self._refresh_cart_model()

    def _validate_cart(self):
        if not self.cart:
            info_warning(self, be.tr("Diqqat"), be.tr("Savat bo'sh."))
            return False
        conn = be.get_conn()
        for item in self.cart:
            avail = conn.execute("SELECT qty FROM products WHERE id=?", (item["product_id"],)).fetchone()
            if not avail or avail[0] < item["qty"]:
                conn.close()
                info_error(self, be.tr("Xato"),
                           be.tr("\"{name}\" mahsulotidan omborda yetarli miqdor yo'q.").format(name=item["name"]))
                return False
        conn.close()
        return True

    def _commit_sale(self, payment_type, method_label=None, customer_name=None, phone=None, paid_now=0):
        ok, err, info = be.commit_sale_transaction(
            self.cart, payment_type, method_label=method_label,
            customer_name=customer_name, phone=phone, paid_now=paid_now)
        if not ok:
            info_error(self, be.tr("Xato"), be.tr(err) if err else be.tr("Amalga oshmadi."))
            self.refresh_products()
            return
        sale_batch = info["sale_batch"]
        total = info["total"]
        total_profit = info["total_profit"]
        paid_now = info["paid_now"]

        receipt_text = be.build_receipt_text(self.cart, total, payment_type,
                                              customer_name=customer_name, phone=phone,
                                              method_label=method_label, paid_now=paid_now)
        receipt_path = be.save_receipt_file(receipt_text)

        try:
            be.send_sale_notifications(self.cart, total, total_profit, payment_type,
                                        method_label=method_label, customer_name=customer_name,
                                        sale_batch=sale_batch)
        except Exception:
            pass

        self.clear_cart()
        self.refresh_products()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()
        if hasattr(self.main_window, "history_page"):
            self.main_window.history_page.refresh()
        if hasattr(self.main_window, "debts_page"):
            self.main_window.debts_page.refresh()

        ReceiptDialog(self, receipt_text, receipt_path).exec()

    def finalize_sale(self):
        if not self._validate_cart():
            return
        dlg = PaymentMethodDialog(self)
        if dlg.exec() != QDialog.Accepted or not dlg.method:
            return
        self._commit_sale("naqd", method_label=dlg.method)

    def finalize_credit(self):
        if not self._validate_cart():
            return
        total = sum(i["total"] for i in self.cart)
        dlg = CreditDialog(self, self.cart, total)
        if dlg.exec() != QDialog.Accepted or not dlg.customer_name:
            return
        # MUHIM (foydalanuvchi so'rovi bilan): "Qisman to'lov" alohida
        # to'lov turi/yorliq sifatida ISHLATILMAYDI -- qisman to'langan
        # bo'lsa ham, "Savdo tarixi"da hamon oddiy "Nasiya" deb ko'rinadi
        # (ilgarigidek). To'langan/qolgan summa haqidagi ma'lumot esa
        # Qarzdorlar daftaridagi izohda ko'rsatiladi (_commit_sale ichida).
        self._commit_sale("nasiya", customer_name=dlg.customer_name,
                           phone=dlg.phone, paid_now=dlg.paid_now)


# =============================================================================
# DebtsPage
# =============================================================================

class PartialPaymentDialog(ThemedDialog):
    """Qarzdor qarzining bir qismini to'lasa -- shu summani qarzdan ayirish."""

    def __init__(self, parent, customer_name, amount):
        super().__init__(parent)
        self.amount = amount
        self.pay_amount = None
        self.setWindowTitle(be.tr("Qisman to'lash"))
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel(customer_name))
        self.debt_lbl = QLabel(f"{be.tr('Qolgan qarz')}: {be.fmt_money(amount)} so'm")
        self.debt_lbl.setStyleSheet("font-size:15px; font-weight:600;")
        layout.addWidget(self.debt_lbl)
        layout.addWidget(StrongBodyLabel(be.tr("Qarzdan qancha to'landi?")))
        self.pay_edit = LineEdit(self)
        self.pay_edit.setPlaceholderText(be.tr("To'langan summa"))
        self.pay_edit.textChanged.connect(self._update_label)
        layout.addWidget(self.pay_edit)
        self.after_lbl = QLabel("")
        self.after_lbl.setStyleSheet("font-size:16px; font-weight:700; color:#E5484D;")
        layout.addWidget(self.after_lbl)
        btn_row = QHBoxLayout()
        save_btn = PrimaryPushButton(be.tr("To'lovni qarzdan ayirish"), self)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = PushButton(be.tr("Bekor qilish"), self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _parse(self):
        try:
            v = float((self.pay_edit.text() or "").replace(" ", "").replace(",", "."))
        except ValueError:
            return None
        if not math.isfinite(v) or v <= 0 or v > self.amount + 1e-9:
            return None
        return v

    def _update_label(self):
        v = self._parse()
        if v is None:
            self.after_lbl.setText(be.tr("To'langan summani to'g'ri kiriting (0 dan Jami summagacha)."))
            self.after_lbl.setStyleSheet("font-size:13px; font-weight:600; color:#E5484D;")
            return
        self.after_lbl.setStyleSheet("font-size:16px; font-weight:700; color:#E5484D;")
        self.after_lbl.setText(f"{be.tr('Qarzga qoladi')}: {be.fmt_money(self.amount - v)} so'm")

    def _on_save(self):
        v = self._parse()
        if v is None:
            info_error(self, be.tr("Xato"), be.tr("To'langan summani to'g'ri kiriting (0 dan Jami summagacha)."))
            return
        self.pay_amount = v
        self.accept()


class DebtsPage(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 24)
        outer.setSpacing(14)

        self.title_lbl = TitleLabel(be.tr("Qarzdorlar daftari"))
        outer.addWidget(self.title_lbl)

        top_row = QHBoxLayout()
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText(be.tr("Qarzdorni qidirish (ism yoki telefon)..."))
        self.search_edit.textChanged.connect(debounced(self, self.refresh))
        top_row.addWidget(self.search_edit, 1)
        outer.addLayout(top_row)

        self.model = DebtsTableModel()
        self.table = TableView(self)
        self.table.setModel(self.model)
        # MUHIM TUZATISH (foydalanuvchi so'rovi bilan): ustun kengligini
        # sof "content"ga (ResizeToContents+Stretch) qo'yish "Mahsulot /
        # izoh" ustuniga QOLGAN BARCHA bo'sh joyni bitta ustunga tashlab
        # qo'ydi -- natijada u matndan keyin katta bo'sh joy bilan
        # g'ayritabiiy kattalashib ko'rindi. Endi kengliklar to'liq QO'LDA
        # (_layout_columns orqali) boshqariladi: avval har bir ustun o'z
        # matniga mos MINIMAL kenglikni oladi, so'ng har qanday ORTIQCHA
        # bo'sh joy BARCHA ustunlar orasida ularning nisbiy kengligiga
        # PROPORSIONAL taqsimlanadi -- shu bilan bitta ustun yolg'iz
        # kattalashib ketmaydi, lekin hech qanday matn ham kesilmaydi.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        self.table.setWordWrap(True)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.doubleClicked.connect(lambda _i: self.view_items())
        self.table.setViewportMargins(0, 0, 14, 0)
        fix_table_hover_highlight(self.table)
        # "X to'landi, Y qoldi" formatidagi izohni ikki xil rangda
        # chizadigan delegate -- to'langan qismi yashil, qolgan qarzi qizil.
        self._note_delegate = _DebtNoteColorDelegate(self.table)
        self.table.setItemDelegateForColumn(3, self._note_delegate)
        outer.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.paid_btn = PushButton(be.tr("To'landi deb belgilash"), self)
        self.paid_btn.clicked.connect(self.mark_paid)
        # MUHIM: agar xatolik bilan "To'landi" tugmasi bosilib qolsa, buni
        # ortga qaytarish (qarzni yana "to'lanmagan" holatiga qaytarish)
        # imkoniyati bo'lishi uchun qo'shildi.
        self.unpaid_btn = PushButton(be.tr("To'lovni bekor qilish"), self)
        self.unpaid_btn.clicked.connect(self.unmark_paid)
        # Qarzdor qarzining FAQAT bir qismini to'lasa -- shu summa qarzdan
        # ayiriladi, qolgani qarz bo'lib qoladi.
        self.partial_btn = PushButton(be.tr("Qisman to'lash"), self)
        self.partial_btn.clicked.connect(self.pay_partial)
        self.items_btn = PushButton(be.tr("Olgan mahsulotlarini ko'rish"), self)
        self.items_btn.clicked.connect(self.view_items)
        self.delete_btn = PushButton(be.tr("O'chirish"), self)
        self.delete_btn.clicked.connect(self.delete_debt)
        btn_row.addWidget(self.paid_btn)
        btn_row.addWidget(self.partial_btn)
        btn_row.addWidget(self.unpaid_btn)
        btn_row.addWidget(self.items_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        self.refresh()

    def _layout_columns(self):
        """Ustun kengliklarini qo'lda hisoblaydi: avval har biri o'z
        matniga (yoki sarlavhasiga, qaysi kengroq bo'lsa) mos MINIMAL
        kenglikni oladi, so'ng ortiqcha bo'sh joy bo'lsa, u BARCHA
        ustunlar orasida ularning nisbiy kengligiga proporsional
        taqsimlanadi -- shu bilan bitta ustun (masalan "Mahsulot /
        izoh") yolg'iz butun bo'sh joyni yutib yubormaydi."""
        col_count = self.model.columnCount()
        for col in range(col_count):
            self.table.resizeColumnToContents(col)
        # "Mahsulot / izoh" ustuni juda uzun bitta izoh bo'lsa ham
        # cheksiz kattalashib ketmasligi uchun yuqori chegara.
        if self.table.columnWidth(3) > 480:
            self.table.setColumnWidth(3, 480)
        widths = [self.table.columnWidth(c) for c in range(col_count)]
        total_needed = sum(widths)
        avail = self.table.viewport().width()
        extra = avail - total_needed
        if extra > 0 and total_needed > 0:
            for col in range(col_count):
                add = int(extra * (widths[col] / total_needed))
                self.table.setColumnWidth(col, widths[col] + add)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_columns()

    def retranslate(self):
        self.title_lbl.setText(be.tr("Qarzdorlar daftari"))
        self.search_edit.setPlaceholderText(be.tr("Qarzdorni qidirish (ism yoki telefon)..."))
        self.paid_btn.setText(be.tr("To'landi deb belgilash"))
        self.partial_btn.setText(be.tr("Qisman to'lash"))
        self.unpaid_btn.setText(be.tr("To'lovni bekor qilish"))
        self.items_btn.setText(be.tr("Olgan mahsulotlarini ko'rish"))
        self.delete_btn.setText(be.tr("O'chirish"))
        self.model.retranslate()
        self.refresh()

    def refresh(self):
        conn = be.get_conn()
        rows = conn.execute(
            "SELECT id, customer_name, phone, amount, note, date, paid FROM debts "
            "ORDER BY paid ASC, date DESC").fetchall()
        conn.close()
        # MUHIM: qidiruv qatoriga yozilgan matn bo'yicha, xaridor ismi
        # yoki telefon raqami ichidan qidiriladi (katta-kichik harflarga
        # va bo'sh joylarga sezgir emas) -- shu orqali qarzdorlar
        # daftari uzun bo'lsa ham kerakli odamni tezda topish mumkin.
        query = (self.search_edit.text() or "").strip().lower()
        if query:
            rows = [r for r in rows
                    if query in (r[1] or "").lower() or query in (r[2] or "").lower()]
        self.model.set_rows(rows)
        self.table.clearSelection()
        # Ustun kengliklarini (content + proporsional taqsimlangan
        # ortiqcha joy) va qator balandliklarini (wordWrap uchun) har
        # safar model o'zgarganda qayta hisoblaymiz.
        self._layout_columns()
        self.table.resizeRowsToContents()

    def _selected_debt(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            info_warning(self, be.tr("Diqqat"), be.tr("Avval jadvaldan qarzdorni tanlang."))
            return None
        return self.model.row_at(idxs[0].row())



    def mark_paid(self):
        row = self._selected_debt()
        if not row:
            return
        did, name, phone, amount, note, date, paid = row
        if paid:
            info_warning(self, be.tr("Diqqat"), be.tr("Bu qarz allaqachon to'langan."))
            return
        if not confirm(self, be.tr("To'landi"),
                        be.tr("\"{name}\" — {amount} so'm to'landi deb belgilaymi?").format(
                            name=name, amount=be.fmt_money(amount))):
            return
        ok, err = be.mark_debt_paid(did)
        if not ok:
            info_error(self, be.tr("Xato"), err or be.tr("Amalga oshmadi."))
            return
        self.refresh()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()

    def pay_partial(self):
        row = self._selected_debt()
        if not row:
            return
        did, name, phone, amount, note, date, paid = row
        if paid:
            info_warning(self, be.tr("Diqqat"), be.tr("Bu qarz allaqachon to'langan."))
            return
        dlg = PartialPaymentDialog(self, name, amount)
        if dlg.exec() != QDialog.Accepted or dlg.pay_amount is None:
            return
        ok, err, remaining = be.pay_debt_partial(did, dlg.pay_amount)
        if not ok:
            info_error(self, be.tr("Xato"), err or be.tr("Amalga oshmadi."))
            return
        info_success(self, be.tr("Bajarildi"),
                     be.tr("To'lov qarzdan ayirildi. Qolgan qarz: {amount} so'm").format(
                         amount=be.fmt_money(remaining or 0)))
        self.refresh()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()

    def unmark_paid(self):
        """Xatolik bilan 'To'landi' deb belgilangan qarzni yana
        'to'lanmagan' holatiga qaytaradi."""
        row = self._selected_debt()
        if not row:
            return
        did, name, phone, amount, note, date, paid = row
        if not paid:
            info_warning(self, be.tr("Diqqat"), be.tr("Bu qarz hali to'lanmagan."))
            return
        if not confirm(self, be.tr("To'lovni bekor qilish"),
                        be.tr("\"{name}\" — {amount} so'm uchun to'lovni bekor qilib, "
                              "qarzni yana \"to'lanmagan\" holatiga qaytaramizmi?").format(
                            name=name, amount=be.fmt_money(amount))):
            return
        conn = be.get_conn()
        conn.execute("UPDATE debts SET paid=0, paid_date=NULL WHERE id=?", (did,))
        conn.execute("DELETE FROM debt_payments WHERE debt_id=? AND is_final=1", (did,))
        conn.commit()
        conn.close()
        self.refresh()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()

    def view_items(self):
        row = self._selected_debt()
        if not row:
            return
        did, name, phone, amount, note, date, paid = row
        conn = be.get_conn()
        items = conn.execute(
            "SELECT product_name, qty, unit FROM debt_items WHERE debt_id=?", (did,)).fetchall()
        conn.close()
        DebtItemsDialog(self, name, items, note).exec()

    def delete_debt(self):
        row = self._selected_debt()
        if not row:
            return
        did, name, phone, amount, note, date, paid = row
        if not confirm(self, be.tr("O'chirish"),
                        be.tr("\"{name}\" qarzini o'chirmoqchimisiz?").format(name=name)):
            return
        conn = be.get_conn()
        conn.execute("DELETE FROM debts WHERE id=?", (did,))
        conn.commit()
        conn.close()
        self.refresh()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()


# =============================================================================
# ReportPage
# =============================================================================

class ReportPage(QWidget):
    """Hisobot sahifasi -- asl tkinter versiyasidagi bilan bir xil tarkibda:
    davr tanlash (so'nggi 30 kun / oy bo'yicha), naqd/nasiya bo'yicha alohida
    kartochkalar, KUNLIK SAVDO va KUNLIK FOYDA (naqd + nasiya, 2 rangli chiziq)
    grafiklari, eng ko'p sotilgan 5 mahsulot ro'yxati, va "Hisobotni 0 ga
    tushirish" xavfli-zona tugmasi."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._period_map = {}

        outer = make_scrollable(self, margins=(24, 20, 24, 24), spacing=14)

        top_row = QHBoxLayout()
        self.title_lbl = TitleLabel(be.tr("Hisobot"))
        top_row.addWidget(self.title_lbl)
        top_row.addStretch(1)
        self.period_label_lbl = BodyLabel(be.tr("Davr:"))
        top_row.addWidget(self.period_label_lbl)
        self.period_combo = ComboBox(self)
        self.period_combo.currentIndexChanged.connect(self.refresh)
        top_row.addWidget(self.period_combo)
        outer.addLayout(top_row)

        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(14)
        outer.addLayout(self.cards_grid)

        charts_row = QHBoxLayout()
        left_col = QVBoxLayout()
        self.revenue_title = StrongBodyLabel("")
        left_col.addWidget(self.revenue_title)
        if _CHARTS_AVAILABLE:
            self.revenue_chart = QChart()
            self.revenue_chart.legend().hide()
            self.revenue_chart_view = QChartView(self.revenue_chart)
            self.revenue_chart_view.setMinimumHeight(220)
            # MUHIM: QChartView'ning o'zi ham standart oq fon chizadi --
            # buni shaffof qilib, faqat QChart.setBackgroundBrush() (temaga
            # mos rang) ko'rinishini ta'minlaymiz.
            self.revenue_chart_view.setStyleSheet("background: transparent; border: none;")
            # MUHIM: sichqoncha grafik chizig'i ustidan o'tganda "hovered"
            # signali ishlashi uchun sichqoncha kuzatuvi yoqilishi kerak.
            self.revenue_chart_view.setMouseTracking(True)
            self.revenue_chart_view.setRenderHint(QPainter.Antialiasing, True)
            left_col.addWidget(self.revenue_chart_view)
        else:
            self.revenue_chart_view = None
            left_col.addWidget(CaptionLabel(be.tr("Grafik modul (QtCharts) mavjud emas.")))

        self.profit_title = StrongBodyLabel("")
        left_col.addWidget(self.profit_title)
        legend_row = QHBoxLayout()
        # MUHIM TUZATISH: ilgari "■" belgilari oddiy CaptionLabel bo'lib,
        # ranglari joriy temaning matn rangidan meros olar edi -- shuning
        # uchun ular hamma vaqt kulrang/oq bo'lib ko'rinar, naqd (to'q
        # sariq) va nasiya (qizil) ranglari umuman ko'rinmas edi. Endi HTML
        # <span> orqali grafikdagi chiziq rangi bilan bir xil rang beriladi.
        self.naqd_legend_lbl = CaptionLabel(self)
        self.nasiya_legend_lbl = CaptionLabel(self)
        self._update_legend_labels()
        legend_row.addWidget(self.naqd_legend_lbl)
        legend_row.addWidget(self.nasiya_legend_lbl)
        legend_row.addStretch(1)
        left_col.addLayout(legend_row)
        if _CHARTS_AVAILABLE:
            self.profit_chart = QChart()
            self.profit_chart.legend().hide()
            self.profit_chart_view = QChartView(self.profit_chart)
            self.profit_chart_view.setMinimumHeight(200)
            self.profit_chart_view.setStyleSheet("background: transparent; border: none;")
            self.profit_chart_view.setMouseTracking(True)
            self.profit_chart_view.setRenderHint(QPainter.Antialiasing, True)
            left_col.addWidget(self.profit_chart_view)
        else:
            self.profit_chart_view = None
        charts_row.addLayout(left_col, 3)

        right_col = QVBoxLayout()
        top_card = SimpleCardWidget(self)
        top_card_layout = QVBoxLayout(top_card)
        self.top_title = StrongBodyLabel(be.tr("Eng ko'p sotilganlar"))
        top_card_layout.addWidget(self.top_title)
        self.top_products_layout = QVBoxLayout()
        top_card_layout.addLayout(self.top_products_layout)
        top_card_layout.addStretch(1)
        right_col.addWidget(top_card)
        charts_row.addLayout(right_col, 1)
        outer.addLayout(charts_row)

        danger_card = SimpleCardWidget(self)
        danger_card.setStyleSheet("SimpleCardWidget { border: 1px solid #E5484D; }")
        danger_layout = QVBoxLayout(danger_card)
        self.danger_title = StrongBodyLabel(be.tr("Hisobotni tozalash"))
        self.danger_title.setStyleSheet("color:#E5484D;")
        danger_layout.addWidget(self.danger_title)
        self.danger_desc = CaptionLabel(be.tr(
            "Bu tugma barcha savdo hisobotini (jami summa, tarix, grafik, yopilgan kunlar) 0 ga\n"
            "tushiradi. Mahsulotlar va qarz daftariga tegmaydi. Ortga qaytarib bo'lmaydi!"))
        danger_layout.addWidget(self.danger_desc)
        self.reset_btn = PushButton(be.tr("Hisobotni 0 ga tushirish"), self)
        self.reset_btn.setStyleSheet("PushButton { color: #E5484D; }")
        self.reset_btn.clicked.connect(self.reset_report)
        danger_layout.addWidget(self.reset_btn, alignment=Qt.AlignLeft)
        outer.addWidget(danger_card)

        self._build_period_options()
        self.refresh()

    def retranslate(self):
        self.title_lbl.setText(be.tr("Hisobot"))
        self.period_label_lbl.setText(be.tr("Davr:"))
        self.top_title.setText(be.tr("Eng ko'p sotilganlar"))
        self.danger_title.setText(be.tr("Hisobotni tozalash"))
        self.danger_desc.setText(be.tr(
            "Bu tugma barcha savdo hisobotini (jami summa, tarix, grafik, yopilgan kunlar) 0 ga\n"
            "tushiradi. Mahsulotlar va qarz daftariga tegmaydi. Ortga qaytarib bo'lmaydi!"))
        self.reset_btn.setText(be.tr("Hisobotni 0 ga tushirish"))
        self._update_legend_labels()
        self._build_period_options()
        self.refresh()

    def _update_legend_labels(self):
        """Kunlik foyda grafigidagi naqd/nasiya rang belgilarini (■) grafik
        chiziqlari bilan bir xil rangda, HTML orqali chizadi -- shunda
        ranglar temadan qat'i nazar har doim aniq ko'rinadi."""
        self.naqd_legend_lbl.setText(f'<span style="color:{ACCENT_COLOR};">■</span> {be.tr("foyda")}')
        self.nasiya_legend_lbl.setText(f'<span style="color:#E5484D;">■</span> {be.tr("nasiya foydasi (kutilayotgan)")}')

    def _build_period_options(self):
        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        self._period_map = {be.tr("So'nggi 30 kun"): None}
        options = [be.tr("So'nggi 30 kun")]
        today = datetime.date.today()
        y, m = today.year, today.month

        months_back = 12
        try:
            conn0 = be.get_conn()
            earliest = conn0.execute("SELECT MIN(date) FROM sales").fetchone()[0]
            conn0.close()
        except Exception:
            earliest = None
        if earliest:
            try:
                ey, em = int(earliest[:4]), int(earliest[5:7])
                diff = (y - ey) * 12 + (m - em) + 1
                months_back = max(months_back, diff)
            except Exception:
                pass
        months_back = min(months_back, 120)

        for i in range(months_back):
            mm = m - i
            yy = y
            while mm <= 0:
                mm += 12
                yy -= 1
            label = f"{be.tr(be.UZ_MONTHS[mm - 1])} {yy}"
            options.append(label)
            self._period_map[label] = f"{yy:04d}-{mm:02d}"

        self.period_combo.addItems(options)
        self.period_combo.setCurrentIndex(0)
        self.period_combo.blockSignals(False)

    def _clear_grid(self):
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _clear_top_products(self):
        while self.top_products_layout.count():
            item = self.top_products_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def reset_report(self):
        if not confirm(self, be.tr("Diqqat!"),
                        be.tr("Haqiqatan ham butun savdo hisobotini (barcha summalar, tarix va yopilgan "
                              "kunlarni) 0 ga tushirmoqchimisiz? Bu amalni ortga qaytarib bo'lmaydi.")):
            return
        conn = be.get_conn()
        conn.execute("DELETE FROM sales")
        conn.execute("DELETE FROM day_closures")
        conn.execute("DELETE FROM debt_payments")
        conn.commit()
        conn.close()
        info_success(self, be.tr("Bajarildi"), be.tr("Hisobot 0 ga tushirildi."))
        self.refresh()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()
        if hasattr(self.main_window, "closures_page"):
            self.main_window.closures_page.refresh()
        if hasattr(self.main_window, "history_page"):
            self.main_window.history_page.refresh()

    def refresh(self):
        self._clear_grid()
        self._clear_top_products()
        conn = be.get_conn()

        period_key = self._period_map.get(self.period_combo.currentText())

        if period_key is None:
            naqd_profit, naqd_count = conn.execute(
                "SELECT COALESCE(SUM(profit),0), COUNT(*) "
                "FROM sales WHERE payment_type='naqd'").fetchone()
            _nasiya_profit_raw, nasiya_count = conn.execute(
                "SELECT COALESCE(SUM(profit),0), COUNT(*) "
                "FROM sales WHERE payment_type='nasiya'").fetchone()
            # MUHIM (foydalanuvchi so'rovi bilan -- "to'langani naqdga
            # qo'shilsinmi?"): nasiyaga savdo qilinganda xaridor hozir bir
            # qismini (paid_now) darhol to'lagan bo'lsa, o'sha qism endi
            # "Naqd savdo"ga, qolgani "Nasiya savdo"ga hisoblanadi (foyda
            # o'zgarmaydi -- pastda alohida hisoblanadi).
            naqd_total, _np, nasiya_total, _ns = be.get_naqd_nasiya_totals_where("WHERE 1=1", ())
            # MUHIM O'ZGARISH: nasiya foydasi endi TO'LANGAN/TO'LANMAGAN
            # holatiga qarab ikkiga bo'linadi -- to'langan qismi "Foyda"ga
            # (naqd bilan birga), to'lanmagani "Nasiya foydasi"
            # (kutilayotgan) kartochkasiga chiqadi (Bosh sahifadagi bilan
            # bir xil mantiq).
            paid_nasiya_profit, nasiya_profit = be.get_realized_and_pending_nasiya_profit()
            naqd_profit = naqd_profit + paid_nasiya_profit
            day_list = [datetime.date.today() - datetime.timedelta(days=i)
                        for i in range(be.REPORT_DAYS - 1, -1, -1)]
            period_label = be.tr("so'nggi {n} kun").format(n=be.REPORT_DAYS)
            card_suffix = be.tr("(jami)")
            # MUHIM TUZATISH: "Eng ko'p sotilganlar" ilgari PULGA (summaga)
            # qarab saralanardi -- ya'ni qimmat, lekin kam sotilgan
            # mahsulot ro'yxat boshida chiqib ketardi. Foydalanuvchi
            # so'ragani bo'yicha, endi bu ro'yxat SOTILGAN MIQDORGA
            # (necha dona/kg/litr sotilganiga) qarab saralanadi.
            top_sql = ("SELECT product_name, unit, SUM(qty) as q, SUM(total) as t FROM sales "
                       "GROUP BY product_name ORDER BY q DESC LIMIT 5")
            top_params = ()
        else:
            yy, mm = int(period_key[:4]), int(period_key[5:7])
            last_day = calendar.monthrange(yy, mm)[1]
            start_iso = datetime.date(yy, mm, 1).isoformat()
            end_iso = datetime.date(yy, mm, last_day).isoformat()

            naqd_profit, naqd_count = conn.execute(
                "SELECT COALESCE(SUM(profit),0), COUNT(*) "
                "FROM sales WHERE payment_type='naqd' AND date BETWEEN ? AND ?",
                (start_iso, end_iso)).fetchone()
            _nasiya_profit_raw, nasiya_count = conn.execute(
                "SELECT COALESCE(SUM(profit),0), COUNT(*) "
                "FROM sales WHERE payment_type='nasiya' AND date BETWEEN ? AND ?",
                (start_iso, end_iso)).fetchone()
            # MUHIM (foydalanuvchi so'rovi bilan -- "to'langani naqdga
            # qo'shilsinmi?"): shu oy uchun ham xuddi shunday -- hozir
            # to'langan qism "Naqd savdo"ga, qolgani "Nasiya savdo"ga.
            naqd_total, _np, nasiya_total, _ns = be.get_naqd_nasiya_totals_where(
                "WHERE date BETWEEN ? AND ?", (start_iso, end_iso))
            paid_nasiya_profit, nasiya_profit = be.get_realized_and_pending_nasiya_profit(start_iso, end_iso)
            naqd_profit = naqd_profit + paid_nasiya_profit
            day_list = [datetime.date(yy, mm, d) for d in range(1, last_day + 1)]
            period_label = f"{be.tr(be.UZ_MONTHS[mm - 1])} {yy}"
            card_suffix = f"({period_label})"
            top_sql = ("SELECT product_name, unit, SUM(qty) as q, SUM(total) as t FROM sales "
                       "WHERE date BETWEEN ? AND ? GROUP BY product_name ORDER BY q DESC LIMIT 5")
            top_params = (start_iso, end_iso)

        self.revenue_title.setText(f"{be.tr('Savdo')} — {period_label}")
        self.profit_title.setText(f"{be.tr('Kunlik foyda')} — {period_label} ({be.tr('naqd va nasiya')})")

        inv_value = conn.execute("SELECT COALESCE(SUM(price*qty),0) FROM products").fetchone()[0]
        debt_total = conn.execute("SELECT COALESCE(SUM(amount),0) FROM debts WHERE paid=0").fetchone()[0]

        # MUHIM O'ZGARISH (foydalanuvchi so'rovi bilan): "Naqd foyda" endi
        # shunchaki "Foyda" deb ataladi va TO'LANGAN nasiya foydasini ham
        # o'z ichiga oladi (yuqorida naqd_profit'ga qo'shildi). "Nasiya
        # foyda" esa "Nasiya foydasi" (kutilayotgan/hali to'lanmagan) deb
        # ataladi va faqat hali to'lanmagan qismini ko'rsatadi.
        cards = [
            (f"{be.tr('Naqd savdo')} {card_suffix}", f"{be.fmt_money(naqd_total)} so'm",
             be.tr("{n} ta chek").format(n=naqd_count), ACCENT_COLOR),
            (f"{be.tr('Foyda')} {card_suffix}", f"{be.fmt_money(naqd_profit)} so'm",
             be.tr("sof foyda (to'langan nasiyalar bilan)"), "#2ECC71"),
            (f"{be.tr('Nasiya savdo')} {card_suffix}", f"{be.fmt_money(nasiya_total)} so'm",
             be.tr("{n} ta").format(n=nasiya_count), "#7C5CFC"),
            (f"{be.tr('Nasiya foydasi')} {card_suffix}", f"{be.fmt_money(nasiya_profit)} so'm",
             be.tr("kutilayotgan (hali to'lanmagan)"), None),
            (be.tr("Ombor qiymati"), f"{be.fmt_money(inv_value)} so'm", be.tr("joriy holat"), None),
            (be.tr("Qarzdorlik"), f"{be.fmt_money(debt_total)} so'm", be.tr("joriy holat"),
             "#E5484D" if debt_total else None),
        ]
        for idx, (title, value, sub, accent) in enumerate(cards):
            card = make_stat_card(title, value, sub, accent=accent, anim_key=("report", idx))
            self.cards_grid.addWidget(card, idx // 3, idx % 3)

        day_labels = []
        revenue_vals = []
        naqd_profit_vals = []
        nasiya_profit_vals = []
        for d in day_list:
            iso = d.isoformat()
            total = conn.execute("SELECT COALESCE(SUM(total),0) FROM sales WHERE date=?", (iso,)).fetchone()[0]
            # MUHIM O'ZGARISH (foydalanuvchi so'rovi bilan): grafikdagi har
            # bir kun endi O'ZGARMAS (statik) -- ya'ni bir kun nasiyaga
            # sotilgan mahsulotning foydasi, u KEYINROQ to'lansa ham, doim
            # O'SHA sotuv sanasidagi "nasiya foydasi" chizig'ida ko'rsatiladi
            # va boshqa kunga (to'langan kunga) "ko'chib" ketmaydi. Bu orqali
            # qarzdor "To'landi" deb belgilanganda o'tgan kunlar grafigi
            # pasayib/o'zgarib qolmaydi. (Eslatma: Hisobot sahifasi tepasidagi
            # kartochkalar bundan mustasno -- ular hali ham to'langan/hali
            # to'lanmagan foydani alohida ko'rsatishda davom etadi.)
            pn = conn.execute(
                "SELECT COALESCE(SUM(profit),0) FROM sales WHERE date=? AND payment_type='naqd'",
                (iso,)).fetchone()[0]
            pc = conn.execute(
                "SELECT COALESCE(SUM(profit),0) FROM sales WHERE date=? AND payment_type='nasiya'",
                (iso,)).fetchone()[0]
            day_labels.append(d.strftime("%d.%m"))
            revenue_vals.append(total)
            naqd_profit_vals.append(pn)
            nasiya_profit_vals.append(pc)

        top_products = conn.execute(top_sql, top_params).fetchall()
        conn.close()

        if not top_products:
            self.top_products_layout.addWidget(CaptionLabel(be.tr("Ma'lumot yo'q")))
        else:
            # MUHIM TUZATISH: endi birinchi navbatda SOTILGAN MIQDOR
            # ko'rsatiladi (masalan "12.5 kg" yoki "34 dona"), summa esa
            # qavs ichida qo'shimcha ma'lumot sifatida qoladi.
            for i, (name, unit, qty, total) in enumerate(top_products, 1):
                qty_text = be.fmt_qty(qty, unit) if hasattr(be, "fmt_qty") else f"{qty} {unit or ''}".strip()
                row_lbl = BodyLabel(f"{i}. {name}   —   {qty_text}   ({be.fmt_money(total)} so'm)")
                row_lbl.setWordWrap(True)
                self.top_products_layout.addWidget(row_lbl)

        if self.revenue_chart_view is not None:
            # MUHIM (foydalanuvchi so'rovi bilan): FAQAT savdo (jami savdo)
            # grafigi -- qalinroq, yumshoq (tekis) chiziq, har kungi
            # nuqtalar (kun+summa) va chiziq ostida soya (gradient)
            # bilan chiroyliroq ko'rinishda chiziladi.
            self._draw_line_chart(self.revenue_chart, day_labels, [(ACCENT_COLOR, revenue_vals)],
                                   smooth_fancy=True)
        if self.profit_chart_view is not None:
            # MUHIM (foydalanuvchi so'rovi bilan): foyda grafigi ham
            # silliq, qalinroq chiziq bilan chiziladi, LEKIN endi soya
            # (gradient fon) chizilmaydi -- faqat savdo grafigida qoladi.
            self._draw_line_chart(self.profit_chart, day_labels,
                                   [(ACCENT_COLOR, naqd_profit_vals), ("#E5484D", nasiya_profit_vals)],
                                   smooth_fancy=True, show_shadow=False)

    @staticmethod
    def _smooth_curve_points(vals, samples_per_segment=12):
        """Kunlik qiymatlar ro'yxatini (masalan 30 ta son) Catmull-Rom
        formulasi yordamida zich (har bir kun oralig'ida bir nechta
        oraliq nuqta bilan) TEKIS egri chiziqqa aylantiradi. Asl kunlik
        qiymatlar butun x-koordinatalarda ANIQ saqlanadi (interpolatsiya
        formulasi t=0 bo'lganda har doim asl nuqtani beradi), faqat ular
        orasidagi o'tish yumshoq/yumaloq bo'ladi -- shu bilan keskin
        "uchburchak" ko'rinishidagi qirralar yo'qoladi."""
        n = len(vals)

        def get(i):
            i = max(0, min(n - 1, i))
            return vals[i]

        points = []
        for i in range(n - 1):
            p0, p1, p2, p3 = get(i - 1), get(i), get(i + 1), get(i + 2)
            for s in range(samples_per_segment):
                t = s / samples_per_segment
                t2 = t * t
                t3 = t2 * t
                y = 0.5 * ((2 * p1)
                           + (-p0 + p2) * t
                           + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                           + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
                points.append((i + t, y))
        points.append((n - 1, vals[-1]))
        return points

    def _draw_line_chart(self, chart, day_labels, series_defs, smooth_fancy=False, show_shadow=True):
        # MUHIM TUZATISH: grafiklarning orqa foni ilgari doim OQ bo'lib
        # qolar edi (QChart standart foni), tungi (dark) temada bu "oq
        # tirqish" kabi ko'rinib, ko'zga yoqimsiz va nomutanosib edi. Endi
        # fon, katak chiziqlari va o'q yorliqlari rangi joriy temaga
        # (isDarkTheme()) qarab avtomatik moslashtiriladi.
        dark = isDarkTheme()
        bg_color = QColor(37, 39, 45) if dark else QColor(255, 255, 255)
        label_color = QColor(225, 227, 230) if dark else QColor(45, 49, 54)
        grid_color = QColor(255, 255, 255, 35) if dark else QColor(0, 0, 0, 28)

        chart.setBackgroundBrush(QBrush(bg_color))
        chart.setBackgroundPen(QPen(Qt.NoPen))
        chart.setBackgroundRoundness(10)
        chart.setPlotAreaBackgroundBrush(QBrush(bg_color))
        chart.setPlotAreaBackgroundVisible(True)

        chart.removeAllSeries()
        for axis in chart.axes():
            chart.removeAxis(axis)
        n = len(day_labels)
        if n == 0:
            return
        all_vals = [v for _, vals in series_defs for v in vals]
        max_val = max(all_vals, default=1) or 1
        for color, vals in series_defs:
            # MUHIM (foydalanuvchi so'rovi bilan, faqat "savdo" grafigi
            # uchun -- smooth_fancy=True): oddiy to'g'ri chiziqlar (QLine
            # Series) o'rniga YUMSHOQ, tekis egri chiziq (QSplineSeries)
            # ishlatiladi ("uchburchak" ko'rinishdagi keskin burchaklar
            # o'rniga silliq ko'tarilish/tushish), chiziq QALINROQ qilinadi,
            # har bir kun uchun aniq NUQTA (marker) doim ko'rinadi, va
            # chiziq ostida yuqoridan pastga so'nib boruvchi soya (gradient
            # fon) qo'shiladi.
            # MUHIM (foydalanuvchi so'rovi bilan): QSplineSeries kam
            # nuqtali (kunlik) ma'lumotda ba'zan hamon "uchburchak"ga
            # o'xshab keskin burchak bilan chiqardi. Endi buning o'rniga
            # nuqtalar orasiga Catmull-Rom formulasi bilan qo'shimcha
            # (interpolatsiya qilingan) nuqtalar qo'shib, chindan ham
            # TEKIS/yumaloq (qirrasiz) egri chiziq hosil qilinadi --
            # asl kunlik qiymatlar (butun x'larda) aniq saqlanadi, faqat
            # ular orasidagi o'tish yumshoq bo'ladi.
            series = QLineSeries()
            series.setColor(QColor(color))
            pen = QPen(QColor(color))
            pen.setWidthF(3.2 if smooth_fancy else 2.0)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            series.setPen(pen)
            if smooth_fancy and len(vals) >= 2:
                for x, y in self._smooth_curve_points(vals):
                    series.append(x, max(0.0, y))
            else:
                for i, v in enumerate(vals):
                    series.append(i, v)
            if smooth_fancy:
                # MUHIM (foydalanuvchi so'rovi bilan): nuqta belgilar
                # (marker) endi ko'rsatilmaydi -- faqat silliq chiziq.
                series.setPointsVisible(False)
            if smooth_fancy and show_shadow:
                # MUHIM (foydalanuvchi so'rovi bilan): oldingi gradient
                # chiziqqa yaqin joyda tez so'nib, ba'zi joylarda (ayniqsa
                # cho'qqining tepasida) soya deyarli ko'rinmay qolardi.
                # Endi soya chiziq ostida deyarli TO'LIQ va bir maromda
                # (faqat eng pastki qismida ozgina so'nadi) chiziladi.
                # (Foyda grafigida esa soya umuman chizilmaydi -- foydalanuvchi
                # so'rovi bilan olib tashlandi.)
                area_top = QColor(color)
                area_top.setAlpha(205)
                area_mid = QColor(color)
                area_mid.setAlpha(150)
                area_low = QColor(color)
                area_low.setAlpha(60)
                area_bottom = QColor(color)
                area_bottom.setAlpha(0)
                gradient = QLinearGradient(0, 0, 0, 1)
                gradient.setColorAt(0.0, area_top)
                gradient.setColorAt(0.55, area_mid)
                gradient.setColorAt(0.85, area_low)
                gradient.setColorAt(1.0, area_bottom)
                gradient.setCoordinateMode(QGradient.ObjectBoundingMode)
                area = QAreaSeries(series)
                area.setBrush(QBrush(gradient))
                area.setPen(QPen(Qt.NoPen))
                chart.addSeries(area)
            chart.addSeries(series)
            # MUHIM: foydalanuvchi so'rovi bo'yicha qo'shildi -- sichqonchani
            # grafik chizig'i ustiga olib borganda, o'sha nuqtadagi aniq
            # sana va summa tooltip (bulutcha) orqali ko'rsatiladi.
            series.hovered.connect(
                lambda point, state, dl=day_labels: self._on_chart_point_hover(point, state, dl))
            # MUHIM (foydalanuvchi so'rovi bilan): grafikdagi nuqtalar endi
            # BOSILADIGAN ham -- ustiga bosilganda ham (hover shart emas,
            # masalan sichqoncha harakatlanmasdan to'g'ridan-to'g'ri
            # bosilganda ham) o'sha kundagi sana va summa tooltip sifatida
            # ko'rsatiladi.
            series.clicked.connect(
                lambda point, dl=day_labels: self._on_chart_point_hover(point, True, dl))
        axis_x = QValueAxis()
        axis_x.setRange(0, max(n - 1, 1))
        axis_x.setLabelFormat("%d")
        axis_x.setLabelsColor(label_color)
        axis_x.setGridLineColor(grid_color)
        axis_x.setLinePenColor(grid_color)
        axis_y = QValueAxis()
        axis_y.setRange(0, max_val * 1.15)
        axis_y.setLabelsColor(label_color)
        axis_y.setGridLineColor(grid_color)
        axis_y.setLinePenColor(grid_color)
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        for s in chart.series():
            s.attachAxis(axis_x)
            s.attachAxis(axis_y)

    def _on_chart_point_hover(self, point, state, day_labels):
        """Grafik chizig'i ustidan sichqoncha o'tganda (yoki chiqib
        ketganda) shu nuqtadagi sana va summani tooltip sifatida
        ko'rsatadi/yashiradi."""
        if not state:
            QToolTip.hideText()
            return
        idx = int(round(point.x()))
        idx = max(0, min(idx, len(day_labels) - 1)) if day_labels else 0
        label = day_labels[idx] if day_labels else ""
        QToolTip.showText(QCursor.pos(), f"{label}: {be.fmt_money(point.y())} so'm")


# =============================================================================
# ClosuresPage
# =============================================================================

class ClosuresPage(QWidget):
    """Yopilgan kunlar sahifasi. Chapda ro'yxat, o'ngda tanlangan kunning
    batafsil statistikasi (naqd/nasiya savdo va foyda) -- asl tkinter
    versiyasidagi kabi."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._closures = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 24)
        outer.setSpacing(10)

        self.title_lbl = TitleLabel(be.tr("Kun yopilishlari"))
        outer.addWidget(self.title_lbl)
        self.hint_lbl = CaptionLabel(be.tr("Har bir yopilgan kunni bosib, o'sha kunning batafsil statistikasini ko'ring."))
        outer.addWidget(self.hint_lbl)

        body = QHBoxLayout()
        self.model = ClosuresTableModel()
        self.table = TableView(self)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.selectionModel().selectionChanged.connect(self._on_select)
        self.table.setViewportMargins(0, 0, 14, 0)
        fix_table_hover_highlight(self.table)
        body.addWidget(self.table, 3)

        self.detail_card = SimpleCardWidget(self)
        self.detail_card.setFixedWidth(300)
        self.detail_layout = QVBoxLayout(self.detail_card)
        self.detail_layout.setContentsMargins(16, 16, 16, 16)
        body.addWidget(self.detail_card, 2)

        outer.addLayout(body, 1)

        self._render_empty_detail()
        self.refresh()

    def retranslate(self):
        self.title_lbl.setText(be.tr("Kun yopilishlari"))
        self.hint_lbl.setText(be.tr("Har bir yopilgan kunni bosib, o'sha kunning batafsil statistikasini ko'ring."))
        self.model.retranslate()
        self.refresh()
        self._render_empty_detail()

    def _clear_layout_recursive(self, layout):
        """QVBoxLayout/QHBoxLayout ichidagi barcha widget'larni, jumladan
        ICHKI layoutlar (masalan _stat_row orqali qo'shilgan QHBoxLayout)
        ichidagilarni ham rekursiv ravishda o'chiradi.

        MUHIM TUZATISH: eski _clear_detail faqat to'g'ridan-to'g'ri
        qo'shilgan widget'larni o'chirar edi -- lekin _stat_row() har bir
        qatorni alohida QHBoxLayout sifatida qo'shadi (addLayout orqali),
        va oddiy `item.widget()` bunday ichki layout elementlari uchun None
        qaytaradi, shuning uchun ularning ICHIDAGI label'lar HECH QACHON
        o'chirilmasdan, ekranda eskirgan (bir kunning ma'lumotlari boshqa
        kunning ma'lumotlari ustiga) bir-birining ustiga chiqib qolgan
        matn ko'rinishida qolib ketardi."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
            else:
                child_layout = item.layout()
                if child_layout:
                    self._clear_layout_recursive(child_layout)

    def _clear_detail(self):
        self._clear_layout_recursive(self.detail_layout)

    def _render_empty_detail(self):
        self._clear_detail()
        self.detail_layout.addWidget(StrongBodyLabel(be.tr("Kun tanlanmagan")))
        self.detail_layout.addWidget(CaptionLabel(be.tr("Chapdagi ro'yxatdan bir kunni tanlang.")))
        self.detail_layout.addStretch(1)

    def _stat_row(self, label, value, color=None):
        # MUHIM TUZATISH: ilgari val_lbl.setStyleSheet(...) chaqirilar edi
        # -- bu BodyLabel'ning (qfluentwidgets) o'zining ICHKI, tema
        # (kunduzgi/tungi)ga qarab avtomatik moslashadigan matn rangi
        # qoidasini BUTUNLAY o'chirib qo'yar edi (chunki setStyleSheet()
        # widget'ning butun stil satrini almashtiradi, faqat qo'shimcha
        # qilmaydi). `color` berilmagan hollarda (masalan oddiy "Savdo"
        # qatorlari) natijada yozuv HECH QANDAY rangsiz qolib, kunduzgi
        # (och) rejimda oq fonga singib, KO'RINMAY qolardi. Endi shrift
        # qalinligi/oilasi to'g'ridan-to'g'ri QFont orqali o'rnatiladi --
        # bu labelning ichki (tema-moslashuvchan) rang qoidasiga tegmaydi.
        # Faqat aniq `color` berilganda (masalan yashil/qizil foyda summasi)
        # stylesheet orqali rang qo'shiladi -- bu holatlar allaqachon har
        # ikkala temada ham o'qiladigan aniq ranglar bo'lgani uchun xavfsiz.
        row = QHBoxLayout()
        lbl = CaptionLabel(label)
        row.addWidget(lbl)
        row.addStretch(1)
        val_lbl = BodyLabel(value)
        val_font = QFont(be.FONT_MONO_NAME)
        val_font.setBold(True)
        val_lbl.setFont(val_font)
        if color:
            val_lbl.setStyleSheet(f"color:{color};")
        row.addWidget(val_lbl)
        self.detail_layout.addLayout(row)

    def _on_select(self, *_args):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            self._render_empty_detail()
            return
        closure = self.model.closure_at(idxs[0].row())
        if not closure:
            self._render_empty_detail()
            return
        (cid, date, closed_at, s_naqd, p_naqd, s_nasiya, p_nasiya) = closure

        self._clear_detail()
        # MUHIM TUZATISH: bu yerda oddiy sana ko'rsatiladi (hafta kuni
        # nomi emas); "Yopilgan vaqti" qatori esa endi kerak emasligi
        # sababli olib tashlandi.
        self.detail_layout.addWidget(SubtitleLabel(date))

        line1 = QFrame(self)
        line1.setFrameShape(QFrame.HLine)
        self.detail_layout.addWidget(line1)

        naqd_lbl = CaptionLabel(be.tr("NAQD SOTUV"))
        naqd_lbl.setStyleSheet(f"color:{ACCENT_COLOR}; font-weight:700;")
        self.detail_layout.addWidget(naqd_lbl)
        self._stat_row(be.tr("Savdo"), f"{be.fmt_money(s_naqd)} so'm")
        self._stat_row(be.tr("Foyda"), f"{be.fmt_money(p_naqd)} so'm", color="#2ECC71")

        line2 = QFrame(self)
        line2.setFrameShape(QFrame.HLine)
        self.detail_layout.addWidget(line2)

        nasiya_lbl = CaptionLabel(be.tr("NASIYA (QARZGA)"))
        nasiya_lbl.setStyleSheet("color:#E5484D; font-weight:700;")
        self.detail_layout.addWidget(nasiya_lbl)
        self._stat_row(be.tr("Savdo"), f"{be.fmt_money(s_nasiya)} so'm")
        self._stat_row(be.tr("Kutilayotgan foyda"), f"{be.fmt_money(p_nasiya)} so'm", color="#E5484D")

        line3 = QFrame(self)
        line3.setFrameShape(QFrame.HLine)
        self.detail_layout.addWidget(line3)

        jami_lbl = CaptionLabel(be.tr("JAMI"))
        # MUHIM TUZATISH: rangsiz setStyleSheet() o'rniga QFont orqali
        # qalinlashtiriladi -- shunda CaptionLabel'ning tema-moslashuvchan
        # rangi buzilmaydi (aks holda kunduzgi rejimda ko'rinmay qolardi).
        _jami_font = jami_lbl.font()
        _jami_font.setBold(True)
        jami_lbl.setFont(_jami_font)
        self.detail_layout.addWidget(jami_lbl)
        self._stat_row(be.tr("Savdo"), f"{be.fmt_money(s_naqd + s_nasiya)} so'm")
        self._stat_row(be.tr("Foyda"), f"{be.fmt_money(p_naqd + p_nasiya)} so'm")
        self.detail_layout.addStretch(1)

    def refresh(self):
        conn = be.get_conn()
        rows = conn.execute(
            "SELECT id, date, closed_at, sales_naqd, profit_naqd, sales_nasiya, profit_nasiya "
            "FROM day_closures ORDER BY date DESC").fetchall()
        conn.close()
        self.model.set_rows(rows)
        self.table.clearSelection()
        self._render_empty_detail()


# =============================================================================
# HistoryPage
# =============================================================================

class _FullRowHighlightDelegate(QStyledItemDelegate):
    """Butun qatorni bir xil, tekis rangda bo'yaydigan yengil delegate.

    MUHIM TUZATISH: standart Qt uslubi (native style) faqat "joriy"
    (current/focused) katakchani to'liq ACCENT rangda bo'yab, o'sha
    qatordagi qolgan katakchalarni bo'yamay qoldirar edi -- natijada
    foydalanuvchi ta'kidlaganidek, faqat bitta katakcha boshqalaridan
    ajralib, kattaroq/g'alati ko'rinardi. Bu delegate esa HAR BIR
    katakchani, agar uning QATORI tanlangan yoki sichqoncha o'sha qator
    ustida bo'lsa, avval o'zi bir xil rangda to'liq bo'yaydi (native
    "State_Selected" bo'yashni o'chirib qo'yib), so'ng matnni ustiga
    chizadi -- shunda butun qator bir xil, tekis rangda ko'rinadi."""

    def __init__(self, table):
        super().__init__(table)
        self.hover_row = -1

    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hover = (index.row() == self.hover_row)
        # MUHIM TUZATISH: "int(option.state)" PySide6'da xato berar ekan
        # (QStyle.State — StateFlag turi, int()'ga aylanmaydi). Shuning
        # uchun bevosita QFlags operatorlari (&, ~) orqali, natijani YANGI
        # o'zgaruvchiga QAYTA O'ZLASHTIRIB (in-place "&=" emas) tozalanadi
        # -- bu Shiboken6 flag turlari uchun ishonchli usul.
        new_state = option.state & ~QStyle.State_Selected
        new_state = new_state & ~QStyle.State_HasFocus
        option.state = new_state

        painter.save()
        if is_selected:
            painter.fillRect(option.rect, QColor(ACCENT_COLOR))
        elif is_hover:
            c = QColor(ACCENT_COLOR)
            c.setAlpha(35)
            painter.fillRect(option.rect, c)
        painter.restore()

        if is_selected:
            option.palette.setColor(QPalette.Text, QColor("white"))

        super().paint(painter, option, index)


class MultiSelectTableView(QTableView):
    """Oddiy QTableView, lekin Shift+bosish xatti-yurishini o'zgartiradi:
    standart Qt xatti-harakatida Shift+bosish OXIRGI tanlangan qatordan
    hozir bosilgan qatorgacha bo'lgan ORALIQNI tanlaydi. Foydalanuvchi
    buni xohlamadi — Shift bosib turgan holda qaysi qatorni bossa, FAQAT
    o'sha bitta qator qo'shilishini (xuddi Ctrl/Cmd kabi) so'radi. Shu
    sababli Shift modifikatorini alohida ushlab, Ctrl bilan bir xil
    (individual belgilash/almashtirish) xatti-harakatga aylantiramiz.

    MUHIM: bu jadval ATAYLAB qfluentwidgets.TableView'dan emas, oddiy
    QTableView'dan meros oladi -- chunki qfluentwidgets.TableView o'zining
    ichki "selectedRows" keshini Qt'ning haqiqiy tanlov modelidan alohida
    saqlaydi va model qayta yuklanganda (beginResetModel/endResetModel)
    bu ikkisi sinxrondan chiqib, Ctrl+bosganda qo'shni qatorni ham tanlab
    yuborish kabi xatolarga olib kelgan edi. "Bitta katakcha kattaroq
    bo'lib ko'rinishi" muammosi esa endi yuqoridagi
    _FullRowHighlightDelegate orqali, tanlov mexanizmiga tegmasdan
    hal qilinadi."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_delegate = _FullRowHighlightDelegate(self)
        self.setItemDelegate(self._hover_delegate)
        self.setMouseTracking(True)
        # MUHIM TUZATISH (qo'shimcha ehtiyot chorasi): Windows'ning ko'k
        # fokus to'rtburchagi faqat jadval KLAVIATURA FOKUSIGA ega bo'lganda
        # chiziladi. Bu jadvalda klaviatura orqali navigatsiya qilish shart
        # emas (qatorlar sichqoncha bilan tanlanadi), shuning uchun fokusni
        # butunlay o'chirib qo'yamiz -- shunda ko'k to'rtburchak umuman
        # paydo bo'lmaydi.
        self.setFocusPolicy(Qt.NoFocus)

    def _update_hover_row(self, row):
        if self._hover_delegate.hover_row != row:
            self._hover_delegate.hover_row = row
            self.viewport().update()

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.pos())
        self._update_hover_row(index.row() if index.isValid() else -1)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._update_hover_row(-1)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and (event.modifiers() & Qt.ShiftModifier) \
                and not (event.modifiers() & Qt.ControlModifier):
            index = self.indexAt(event.pos())
            if index.isValid():
                selection_model = self.selectionModel()
                if selection_model.isRowSelected(index.row(), self.rootIndex()):
                    selection_model.select(
                        index, QItemSelectionModel.Deselect | QItemSelectionModel.Rows)
                else:
                    selection_model.select(
                        index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                self.setCurrentIndex(index)
            return
        super().mousePressEvent(event)


class HistoryPage(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 24)
        outer.setSpacing(14)

        self.title_lbl = TitleLabel(be.tr("Savdo tarixi"))
        outer.addWidget(self.title_lbl)

        top_row = QHBoxLayout()
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText(be.tr("Mahsulot nomi bo'yicha qidirish..."))
        self.search_edit.textChanged.connect(debounced(self, self.refresh))
        top_row.addWidget(self.search_edit, 1)
        self.export_btn = PushButton(be.tr("Excel'ga eksport"), self)
        self.export_btn.clicked.connect(self.export_excel)
        top_row.addWidget(self.export_btn)
        outer.addLayout(top_row)

        self.model = SalesHistoryTableModel()
        # MUHIM: qfluentwidgets'ning TableView'i o'zining ichki
        # "selectedRows" keshini Qt'ning haqiqiy tanlov modelidan alohida
        # saqlaydi va model qayta yuklanganda (beginResetModel/endResetModel)
        # bu ikkisi sinxrondan chiqib, Ctrl+bosganda qo'shni qatorni ham
        # tanlab yuborish kabi xatolarga olib kelardi. Shu sababli bu jadval
        # uchun oddiy PySide6 QTableView ishlatiladi — u to'g'ridan-to'g'ri
        # Qt'ning o'z tanlov modeliga tayanadi, shuning uchun bunday
        # nomuvofiqlik bo'lmaydi. Fluent-ga o'xshash ko'rinish saqlab qolish
        # uchun quyida stylesheet qo'llaniladi.
        self.table = MultiSelectTableView(self)
        self.table.setModel(self.model)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setMinimumSectionSize(150)
        header.setHighlightSections(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # MUHIM: Ctrl/Shift bilan bir nechta qatorni birga tanlab, ularning
        # umumiy chekini qayta chiqarish mumkin bo'lishi uchun.
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        # MUHIM TUZATISH: ilgari native "selection-background-color" QSS
        # xossasi FAQAT joriy (current) katakchani to'liq bo'yab, o'sha
        # qatordagi qolgan katakchalarni bo'yamay qoldirar edi -- natijada
        # bitta katakcha boshqalaridan ajralib, kattaroq/g'alati ko'rinardi.
        # Endi butun qatorni bir xil rangda bo'yash MultiSelectTableView
        # ichidagi _FullRowHighlightDelegate zimmasida (yuqorida ta'riflangan),
        # shuning uchun bu yerda "selection-background-color" xossasi olib
        # tashlandi -- faqat chegara/panjara ko'rinishi saqlab qolindi.
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setStyleSheet(f"""
            QTableView {{
                border: 1px solid rgba(127,127,127,60);
                border-radius: 6px;
                gridline-color: rgba(127,127,127,40);
            }}
            QTableView::item {{
                padding: 2px 6px;
            }}
            QHeaderView::section {{
                padding: 6px;
                border: none;
                border-bottom: 1px solid rgba(127,127,127,60);
                font-weight: 600;
            }}
        """)
        # MUHIM TUZATISH: bu jadval (MultiSelectTableView) ATAYLAB oddiy
        # QTableView'dan meros olgani uchun (Ctrl+bosish xatosidan qochish
        # uchun), u qfluentwidgets'ning avtomatik tema-moslashuvchan matn
        # rangidan FOYDALANMAYDI -- balki operatsion tizim/standart Qt
        # palitrasidagi rangni ishlatadi. Bu esa ba'zi kompyuterlarda
        # kunduzgi rejimda matn ranги fon bilan deyarli bir xil (yoki
        # ko'rinmas) bo'lib qolishiga sabab bo'lardi. Endi matn rangi
        # to'g'ridan-to'g'ri joriy temaga (isDarkTheme()) qarab, ANIQ
        # o'rnatiladi -- va tema almashtirilganda ham (refresh() orqali)
        # qayta qo'llaniladi.
        self._apply_table_text_colors()
        outer.addWidget(self.table, 1)

        self.hint_lbl = CaptionLabel(be.tr(
            "Chek chiqarish uchun bir yoki bir nechta qatorni tanlang (bir nechtasini birga tanlash "
            "uchun Ctrl yoki Shift tugmasini bosib turing)."))
        outer.addWidget(self.hint_lbl)

        btn_row = QHBoxLayout()
        self.reprint_btn = PushButton(be.tr("Chek chiqarish"), self)
        self.reprint_btn.clicked.connect(self.reprint_receipt)
        btn_row.addWidget(self.reprint_btn)
        self.delete_btn = PushButton(be.tr("O'chirish (omborga qaytarish)"), self)
        self.delete_btn.clicked.connect(self.delete_sale)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        self.refresh()

    def retranslate(self):
        self.title_lbl.setText(be.tr("Savdo tarixi"))
        self.search_edit.setPlaceholderText(be.tr("Mahsulot nomi bo'yicha qidirish..."))
        self.export_btn.setText(be.tr("Excel'ga eksport"))
        self.hint_lbl.setText(be.tr(
            "Chek chiqarish uchun bir yoki bir nechta qatorni tanlang (bir nechtasini birga tanlash "
            "uchun Ctrl yoki Shift tugmasini bosib turing)."))
        self.reprint_btn.setText(be.tr("Chek chiqarish"))
        self.delete_btn.setText(be.tr("O'chirish (omborga qaytarish)"))
        self.model.retranslate()
        self.refresh()

    def reprint_receipt(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            info_warning(self, be.tr("Diqqat"),
                         be.tr("Avval jadvaldan chekka qo'shmoqchi bo'lgan mahsulot(lar)ni tanlang.\n\n"
                               "Bir nechtasini birga tanlash uchun Ctrl (yoki Shift) tugmasini\n"
                               "bosib turgan holda qatorlarni bosing."))
            return
        selected_rows = [self.model.row_at(i.row()) for i in idxs]
        selected_rows = [r for r in selected_rows if r]
        if not selected_rows:
            return

        items = []
        batches = set()
        for row in selected_rows:
            (sid, created_at, date, name, qty, unit, price, list_price, total, profit, ptype, method, pid,
             sale_batch) = row
            items.append({"name": name, "qty": qty, "unit": unit, "price": price, "total": total})
            batches.add(sale_batch)
        grand_total = sum(i["total"] for i in items)
        first = selected_rows[0]
        ptype = first[10]
        method = first[11] or (be.tr("Naqd") if ptype == "naqd" else be.tr("Nasiya"))

        # MUHIM (foydalanuvchi so'rovi bilan): agar tanlangan qatorlar
        # aslida BIR TO'LIQ nasiya sotuv partiyasi (sale_batch) bo'lsa va
        # xaridor o'sha partiyaning bir qismini oldindan to'lagan bo'lsa,
        # qayta chek chiqarilganda ham "Hozir to'landi / Qarz (qoldiq)"
        # qatorlari ASL chekdagidek to'g'ri ko'rsatiladi. Ilgari bu
        # ma'lumot reprint paytida yo'qolib qolardi.
        paid_now = 0
        if ptype == "nasiya" and len(batches) == 1:
            (batch,) = tuple(batches)
            if batch:
                conn = be.get_conn()
                batch_total_row = conn.execute(
                    "SELECT COALESCE(SUM(total),0) FROM sales WHERE sale_batch=?", (batch,)).fetchone()
                debt_row = conn.execute(
                    "SELECT amount FROM debts WHERE sale_batch=?", (batch,)).fetchone()
                conn.close()
                batch_total = batch_total_row[0] if batch_total_row else 0
                # Faqat TANLANGAN qatorlar o'sha partiyaning HAMMASI
                # bo'lsagina (grand_total butun partiya summasiga teng
                # bo'lsa) ishonchli hisoblanadi -- aks holda (foydalanuvchi
                # partiyadan faqat bir qismini tanlagan bo'lsa) hech narsa
                # taxmin qilinmaydi.
                if debt_row and abs(batch_total - grand_total) < 1e-6:
                    remaining = debt_row[0]
                    paid_now = max(batch_total - remaining, 0)

        receipt_text = be.build_receipt_text(items, grand_total, payment_type=ptype, method_label=method,
                                              paid_now=paid_now)
        path = be.save_receipt_file(receipt_text)
        ReceiptDialog(self, receipt_text, path).exec()

    def _apply_table_text_colors(self):
        """Jadval matn rangini joriy temaga (qora/oq) qarab ANIQ o'rnatadi
        -- yuqorida tushuntirilganidek, bu raw QTableView OS/standart Qt
        palitrasiga tayanmasligi uchun."""
        pal = self.table.palette()
        dark = isDarkTheme()
        text_color = QColor(230, 232, 235) if dark else QColor(20, 22, 26)
        pal.setColor(QPalette.Text, text_color)
        pal.setColor(QPalette.WindowText, text_color)
        pal.setColor(QPalette.Inactive, QPalette.Text, text_color)
        pal.setColor(QPalette.Inactive, QPalette.WindowText, text_color)
        self.table.setPalette(pal)

    def refresh(self):
        self._apply_table_text_colors()
        query = (self.search_edit.text() or "").strip().lower()
        conn = be.get_conn()
        rows = conn.execute(
            "SELECT id, created_at, date, product_name, qty, unit, price, list_price, total, profit, "
            "payment_type, payment_method, product_id, sale_batch FROM sales "
            "ORDER BY created_at DESC").fetchall()
        conn.close()
        if query:
            rows = [r for r in rows if query in r[3].lower()]
        self.model.set_rows(rows)
        self.table.clearSelection()
        # MUHIM: Shift bilan tanlashda noto'g'ri (ortiqcha) qatorlar
        # tanlanib ketmasligi uchun eski "joriy katak" (currentIndex)
        # ko'rsatkichini ham to'liq tozalaymiz -- aks holda Shift+bosish
        # eskirgan boshlang'ich nuqtadan hisoblab, kutilmagan qatorlarni
        # ham tanlab yuborishi mumkin edi.
        self.table.setCurrentIndex(QModelIndex())

    def delete_sale(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            info_warning(self, be.tr("Diqqat"), be.tr("Avval jadvaldan sotuvni tanlang."))
            return
        row = self.model.row_at(idxs[0].row())
        (sid, created_at, date, name, qty, unit, price, list_price, total, profit, ptype, method, pid,
         _sale_batch) = row

        if not confirm(self, be.tr("O'chirish"),
                        be.tr("Bu sotuvni o'chirib, mahsulotni omborga qaytarasizmi?\n"
                              "\"{name}\" — {qty}").format(name=name, qty=be.fmt_qty(qty, unit))):
            return

        ok, err = be.delete_webapp_sale(sid)
        if not ok:
            info_error(self, be.tr("Xato"), err or be.tr("Amalga oshmadi."))
            return

        info_success(self, be.tr("O'chirildi"), be.tr("Sotuv o'chirildi, mahsulot omborga qaytarildi."))
        self.refresh()
        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.refresh()
        if hasattr(self.main_window, "products_page"):
            self.main_window.products_page.refresh()
        if hasattr(self.main_window, "sales_page"):
            self.main_window.sales_page.refresh_products()

    def export_excel(self):
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
        except ImportError:
            info_error(self, be.tr("Xato"), be.tr("'openpyxl' kutubxonasi o'rnatilmagan."))
            return
        dest, _ = QFileDialog.getSaveFileName(self, be.tr("Excel faylni saqlash"),
                                                "savdo_tarixi.xlsx", "Excel (*.xlsx)")
        if not dest:
            return

        # MUHIM: eksport uchun cost_price (tan narxi) ham kerak, u hozirgi
        # ekrandagi jadval modelida yo'q -- shuning uchun bazadan alohida,
        # lekin xuddi ekrandagi bilan bir xil qidiruv filtri va tartibda
        # o'qiladi (WYSIWYG: ekranda nima ko'rinsa, eksportda ham o'sha).
        query = (self.search_edit.text() or "").strip().lower()
        conn = be.get_conn()
        db_rows = conn.execute(
            "SELECT created_at, date, product_name, qty, unit, cost_price, price, list_price, "
            "total, profit, payment_type, payment_method FROM sales ORDER BY created_at DESC").fetchall()
        conn.close()
        if query:
            db_rows = [r for r in db_rows if query in (r[2] or "").lower()]

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = be.tr("Savdo tarixi")

        headers = [be.tr("Sana / vaqt"), be.tr("Mahsulot"), be.tr("Miqdor"), be.tr("Birlik"),
                   be.tr("Tan narxi (so'm)"), be.tr("Narxi (so'm)"), be.tr("Chegirma (so'm)"),
                   be.tr("Summa (so'm)"), be.tr("Foyda (so'm)"), be.tr("To'lov turi")]
        ws.append(headers)

        # Sarlavha qatori: qora fon + oq qalin yozuv (so'ralgan ko'rinish).
        header_fill = PatternFill(start_color="FF1F1F1F", end_color="FF1F1F1F", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFFFF")
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.freeze_panes = "A2"

        naqd_total = naqd_profit = 0
        nasiya_total = nasiya_profit = 0

        for created_at, date, name, qty, unit, cost_price, price, list_price, total, profit, ptype, method in db_rows:
            discount_total = (list_price - price) * qty if list_price and list_price > price else 0
            method_label = method or (be.tr("Naqd") if ptype == "naqd" else be.tr("Nasiya"))
            ws.append([
                created_at or date,
                name,
                qty,
                unit,
                cost_price,
                price,
                discount_total if discount_total > 0.5 else 0,
                total,
                profit,
                method_label,
            ])
            if ptype == "naqd":
                naqd_total += total or 0
                naqd_profit += profit or 0
            else:
                nasiya_total += total or 0
                nasiya_profit += profit or 0

        # Tan narxi/narx/chegirma/summa/foyda ustunlarini son sifatida, ming
        # ajratgich bilan formatlash (Excel'ning o'zida hisoblash uchun).
        for r in range(2, ws.max_row + 1):
            for c in (5, 6, 7, 8, 9):
                ws.cell(row=r, column=c).number_format = '#,##0'

        # MUHIM TUZATISH: "Foyda (so'm)" ustunidagi sonlar avtomatik ravishda
        # o'ngga tekislanadi, "To'lov turi" esa chapga -- ikkalasi orasida
        # bo'shliq qolmay, matn songa "yopishib" qolgandek ko'rinar edi.
        # Endi "To'lov turi" ustuni O'RTAGA tekislangan, shu bilan ikki
        # ustun orasida vizual bo'shliq paydo bo'ladi.
        for r in range(2, ws.max_row + 1):
            ws.cell(row=r, column=10).alignment = Alignment(horizontal="center", vertical="center")

        total_sum = naqd_total + nasiya_total
        total_profit = naqd_profit + nasiya_profit

        # --- Pastda yakuniy jamlar: NAQD va NASIYA alohida-alohida (savdo
        # va foyda), so'ng UMUMIY JAMI va UMUMIY FOYDA. ---
        ws.append([])
        ws.append([])
        summary_first_row = ws.max_row + 1
        summary_rows = [
            (be.tr("NAQD — jami savdo"), naqd_total, be.tr("NAQD — jami foyda"), naqd_profit),
            (be.tr("NASIYA — jami savdo"), nasiya_total, be.tr("NASIYA — jami foyda"), nasiya_profit),
            (be.tr("UMUMIY JAMI:"), total_sum, be.tr("UMUMIY FOYDA"), total_profit),
        ]
        thin = Side(style="thin", color="FF999999")
        box_border = Border(left=thin, right=thin, top=thin, bottom=thin)
        for label1, value1, label2, value2 in summary_rows:
            ws.append(["", "", label1, value1, label2, value2])
            r = ws.max_row
            for c in (3, 4, 5, 6):
                cell = ws.cell(row=r, column=c)
                cell.font = Font(bold=True)
                cell.border = box_border
                if c in (4, 6):
                    cell.number_format = '#,##0'

        # --- Ustun kengliklari: sana va mahsulot nomi TO'LIQ ko'rinishi
        # uchun mazmunga qarab avtomatik kengaytiriladi (qirqilmasin). ---
        min_widths = [18, 28, 10, 10, 14, 14, 14, 14, 14, 14]
        for col_idx, min_w in enumerate(min_widths, start=1):
            col_letter = get_column_letter(col_idx)
            max_len = min_w
            for r in range(1, ws.max_row + 1):
                val = ws.cell(row=r, column=col_idx).value
                if val is not None:
                    max_len = max(max_len, len(str(val)) + 2)
            ws.column_dimensions[col_letter].width = min(max_len, 60)

        try:
            wb.save(dest)
            info_success(self, be.tr("Saqlandi"), f"{dest}")
        except Exception as e:
            info_error(self, be.tr("Xato"), f"{e}")


# =============================================================================
# MainWindow — yuqorida navigatsiya paneli (asl tkinter versiyasidagi kabi),
# til/tema tugmalari header'da, QStackedWidget sahifalarni almashtiradi.
# =============================================================================

NAV_ITEMS = [
    ("dashboard", "Bosh sahifa", FluentIcon.HOME),
    ("products", "Mahsulotlar", FluentIcon.TAG),
    ("sales", "Savdo", FluentIcon.SHOPPING_CART),
    ("debts", "Qarzdorlar", FluentIcon.PEOPLE),
    ("report", "Hisobotlar", FluentIcon.PIE_SINGLE),
    ("closures", "Kun yopilishlari", FluentIcon.CALENDAR),
    ("history", "Savdo tarixi", FluentIcon.HISTORY),
]


class NavPill(QPushButton):
    """Yuqoridagi navigatsiya tugmasi: o'zi chizadi (ikonka + matn), tanlanganda
    matn rangi silliq oqaradi, sichqoncha ustiga borganda yengil ko'tariladi va
    atrofida neon nur paydo bo'ladi. Tanlangan tugma orqasidagi rangli "pill"
    ni NavIndicator siljitib keladi."""

    ICON = 16

    def __init__(self, fluent_icon, text, parent=None):
        super().__init__(text, parent)
        self._fl_icon = fluent_icon
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(38)
        font = QFont(self.font())
        font.setPixelSize(14)
        font.setWeight(QFont.Weight.DemiBold)
        self.setFont(font)
        self._sel = 0.0
        self._hov = 0.0
        self._sel_anim = QVariantAnimation(self)
        self._sel_anim.setDuration(320)
        self._sel_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._sel_anim.valueChanged.connect(self._set_sel)
        self._hov_anim = QVariantAnimation(self)
        self._hov_anim.setDuration(200)
        self._hov_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hov_anim.valueChanged.connect(self._set_hov)
        self.toggled.connect(self._on_toggled)
        self._glow = HoverGlow(self, neon_pair(ACCENT_COLOR)[1], radius=20, alpha=190)

    def setText(self, text):
        super().setText(text)
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        w = 16 + self.ICON + 8 + self.fontMetrics().horizontalAdvance(self.text()) + 18
        return QSize(w, 38)

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_selected_immediate(self, selected):
        self._sel_anim.stop()
        self._sel = 1.0 if selected else 0.0
        self.update()

    def _set_sel(self, v):
        self._sel = float(v)
        self.update()

    def _set_hov(self, v):
        self._hov = float(v)
        self.update()

    def _animate(self, anim, end):
        anim.stop()
        current = self._sel if anim is self._sel_anim else self._hov
        anim.setStartValue(float(current))
        anim.setEndValue(float(end))
        anim.start()

    def _on_toggled(self, checked):
        self._animate(self._sel_anim, 1.0 if checked else 0.0)

    def enterEvent(self, event):
        super().enterEvent(event)
        self._animate(self._hov_anim, 1.0)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._animate(self._hov_anim, 0.0)

    def _draw_icon(self, painter, rect, sel):
        theme = Theme.DARK if (sel >= 0.5 or isDarkTheme()) else Theme.LIGHT
        try:
            self._fl_icon.render(painter, rect, theme)
            return
        except Exception:
            pass
        try:
            self._fl_icon.icon(theme).paint(painter, rect.toRect())
        except Exception:
            pass

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        dark = isDarkTheme()
        accent = QColor(ACCENT_COLOR)
        sel, hov = self._sel, self._hov
        rect = QRectF(self.rect()).adjusted(1.5, 3.5, -1.5, -1.5)
        rect.translate(0, -2.5 * hov)
        radius = rect.height() / 2.0

        # Oddiy (tanlanmagan) fon -- tanlanganda so'nadi
        p.setOpacity(1.0 - 0.92 * sel)
        if dark:
            bg, line = QColor(255, 255, 255, 14 + int(12 * hov)), QColor(255, 255, 255, 30)
        else:
            bg, line = QColor(0, 0, 0, 8 + int(10 * hov)), QColor(0, 0, 0, 28)
        p.setPen(QPen(line, 1))
        p.setBrush(bg)
        p.drawRoundedRect(rect, radius, radius)

        # Neon kontur (hover)
        if hov > 0.01:
            n1, n2 = neon_pair(ACCENT_COLOR)
            n1.setAlpha(int(240 * hov))
            n2.setAlpha(int(240 * hov))
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(0.0, n1)
            grad.setColorAt(1.0, n2)
            fill = QColor(accent)
            fill.setAlpha(int(30 * hov))
            p.setPen(QPen(QBrush(grad), 1.8))
            p.setBrush(fill)
            p.drawRoundedRect(rect, radius, radius)

        # Ikonka va matn
        p.setOpacity(1.0)
        idle_text = QColor(226, 229, 234) if dark else QColor(38, 42, 50)
        text_color = _mix_color(idle_text, QColor(255, 255, 255), min(1.0, sel * 1.4))
        if hov > 0.01 and sel < 0.5:
            text_color = _mix_color(text_color, accent.lighter(115) if dark else accent.darker(110), hov * 0.55)
        text = self.text()
        tw = self.fontMetrics().horizontalAdvance(text)
        total = self.ICON + 8 + tw
        x = rect.left() + (rect.width() - total) / 2.0
        cy = rect.center().y()
        self._draw_icon(p, QRectF(x, cy - self.ICON / 2.0, self.ICON, self.ICON), sel)
        p.setFont(self.font())
        p.setPen(text_color)
        p.drawText(QRectF(x + self.ICON + 8, rect.top(), tw + 6, rect.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()


class NavIndicator(QWidget):
    """Tanlangan navigatsiya tugmasi orqasidagi rangli "pill" (neon nur bilan).
    Boshqa tugmaga o'tganda geometriyasi silliq siljiydi."""

    PAD = 6

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pad = self.PAD
        inner = QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)
        accent = QColor(ACCENT_COLOR)
        # tashqi nur
        for i in range(pad):
            col = QColor(accent)
            col.setAlpha(int(70 * (1.0 - i / float(pad)) ** 2))
            p.setPen(QPen(col, 1.2))
            p.setBrush(Qt.NoBrush)
            r = inner.adjusted(-i, -i, i, i)
            p.drawRoundedRect(r, r.height() / 2.0, r.height() / 2.0)
        grad = QLinearGradient(inner.topLeft(), inner.bottomRight())
        grad.setColorAt(0.0, accent.lighter(112))
        grad.setColorAt(1.0, accent)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(inner, inner.height() / 2.0, inner.height() / 2.0)
        p.end()


class NavBar(QWidget):
    """Navigatsiya tugmalari joylashgan panel + silliq siljiydigan indikator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        pad = NavIndicator.PAD
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(pad, pad, pad, pad)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self.indicator = NavIndicator(self)
        self.indicator.lower()
        self.indicator.hide()
        self._current = None
        self._anim = None

    def add_button(self, btn):
        self._layout.insertWidget(self._layout.count() - 1, btn)
        self.indicator.lower()

    def _target(self, btn):
        pad = NavIndicator.PAD
        return btn.geometry().adjusted(-pad, -pad, pad, pad)

    def select(self, btn, animate=True):
        self._current = btn
        if btn is None:
            return
        target = self._target(btn)
        if (not animate) or (not self.isVisible()) or (not self.indicator.isVisible()):
            if self._anim is not None:
                self._anim.stop()
            self.indicator.setGeometry(target)
            self.indicator.show()
            self.indicator.lower()
            return
        if self._anim is not None:
            self._anim.stop()
        anim = QPropertyAnimation(self.indicator, b"geometry", self)
        anim.setDuration(420)
        anim.setStartValue(self.indicator.geometry())
        anim.setEndValue(target)
        curve = QEasingCurve(QEasingCurve.OutBack)
        curve.setOvershoot(0.55)
        anim.setEasingCurve(curve)
        anim.start()
        self._anim = anim

    def sync(self):
        """Tugmalar joyi/o'lchami o'zgargan bo'lsa (til, oyna kengligi),
        indikatorni animatsiyasiz tanlangan tugma ustiga qo'yadi."""
        if self._current is None:
            return
        if self._anim is not None and self._anim.state() == self._anim.State.Running:
            return
        self.indicator.setGeometry(self._target(self._current))
        self.indicator.show()
        self.indicator.lower()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.sync)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.sync)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)
        if os.path.exists(be.ICON_PATH):
            self.setWindowIcon(QIcon(be.ICON_PATH))
        # MUHIM: joriy tema rejimi ("light" / "dark" / "auto") saqlanadi --
        # "auto" bo'lsa, dastur operatsion tizim (Windows/macOS/Linux)
        # Dark/Light rejimiga har doim mos keladi (pastdagi
        # _check_system_theme_sync() orqali doimiy tekshirib turiladi).
        self._theme_mode = be.load_settings().get("theme", "auto")
        apply_window_background(self)
        self._apply_windows11_effect()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Header: sarlavha + top navigatsiya + til/tema tugmalari ---
        header = QFrame(self)
        header.setObjectName("headerBar")
        header.setStyleSheet(
            "#headerBar { background: transparent; border-bottom: 1px solid rgba(127,127,127,60); }")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 14, 14, 4)
        header_layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.setContentsMargins(6, 0, 6, 0)

        # MUHIM TUZATISH (2-marta kattalashtirildi): oldingi kattalashtirish
        # (32px->48px logotip, 26px->34px shrift) yetarlicha sezilmagan edi.
        # Endi logotip YANADA kattaroq (64x64) va "Treydchi" yozuvi UCHUN
        # ikkala usul BIRGA qo'llaniladi -- ham setStyleSheet() (font-size),
        # ham to'g'ridan-to'g'ri setFont() bilan aniq piksel o'lchamli QFont
        # obyekti majburan o'rnatiladi. Buning sababi: TitleLabel
        # (qfluentwidgets) o'z konstruktorida allaqachon o'ziga xos QFont
        # o'rnatib qo'yadi -- shu ikkalasini birga qo'llash orqali, qaysi
        # birortasi ustunlik qilishidan qat'i nazar, yozuv HAQIQATDA katta
        # ko'rinishi kafolatlanadi.
        # MUHIM TUZATISH: header'dagi kichik logotip past aniqlikdagi icon.ico
        # fayli tufayli kattalashtirilganda loyqa/dag'al ko'rinar edi va
        # foydalanuvchi buni umuman OLIB TASHLASHNI so'radi -- shuning uchun
        # bu yerda logotip endi ko'rsatilmaydi, faqat "Treydchi" yozuvi qoladi
        # (u chap chetdan boshlanadi, logotip turgan joyni egallaydi).
        self.app_title_lbl = TitleLabel(APP_NAME)
        _title_font = QFont(self.app_title_lbl.font())
        _title_font.setPixelSize(42)
        _title_font.setBold(True)
        _title_font.setWeight(QFont.Black)
        self.app_title_lbl.setFont(_title_font)
        self.app_title_lbl.setStyleSheet(f"font-size: 42px; font-weight: 800; color: {ACCENT_COLOR};")
        top_row.addWidget(self.app_title_lbl)
        top_row.addStretch(1)

        self.lang_combo = ComboBox(self)
        self.lang_combo.addItems(["O'zbekcha", "English", "Русский"])
        lang_map = {"uz": 0, "en": 1, "ru": 2}
        self.lang_combo.setCurrentIndex(lang_map.get(be.LANG, 0))
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        top_row.addWidget(self.lang_combo)

        self.theme_btn = PushButton(self)
        self._update_theme_btn_text()
        self.theme_btn.clicked.connect(self._cycle_theme)
        top_row.addWidget(self.theme_btn)

        self.telegram_btn = PushButton(telegram_icon(32), be.tr("Telegram sozlamalari"), self)
        self.telegram_btn.setIconSize(QSize(20, 20))
        self.telegram_btn.clicked.connect(self._open_telegram_settings)
        top_row.addWidget(self.telegram_btn)

        header_layout.addLayout(top_row)

        self.nav_bar = NavBar(self)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        for i, (key, label, icon) in enumerate(NAV_ITEMS):
            btn = NavPill(icon, be.tr(label), self.nav_bar)
            self.nav_bar.add_button(btn)
            btn.setChecked(i == 0)
            if i == 0:
                btn.set_selected_immediate(True)
            btn.clicked.connect(lambda _=None, k=key: self._switch_page(k))
            self.nav_group.addButton(btn)
            self.nav_buttons[key] = btn
        self.nav_bar.select(self.nav_buttons[NAV_ITEMS[0][0]], animate=False)
        header_layout.addWidget(self.nav_bar)
        # Yuqoridagi kichik tugmalarga ham hover nuri
        for _w in (self.lang_combo, self.theme_btn, self.telegram_btn):
            HoverGlow(_w, neon_pair(ACCENT_COLOR)[1], radius=18, alpha=170)

        root.addWidget(header)

        # --- Sahifalar ---
        self.stack = QStackedWidget(self)
        root.addWidget(self.stack, 1)

        # MUHIM: dastur ochilganda, agar u ma'lum vaqt yopiq turgan bo'lsa-yu,
        # shu orada yarim tun (00:00) o'tib ketgan bo'lsa, orqada qolgan
        # kunlar shu yerda avtomatik yopiladi -- shunday qilib avtomatik
        # yopish dastur doim ishlab turishini talab qilmaydi.
        try:
            be.auto_close_missed_days()
        except Exception:
            pass

        self.dashboard_page = DashboardPage(self)
        self.products_page = ProductsPage(self)
        self.sales_page = SalesPage(self)
        self.debts_page = DebtsPage(self)
        self.report_page = ReportPage(self)
        self.closures_page = ClosuresPage(self)
        self.history_page = HistoryPage(self)

        self.pages = {
            "dashboard": self.dashboard_page,
            "products": self.products_page,
            "sales": self.sales_page,
            "debts": self.debts_page,
            "report": self.report_page,
            "closures": self.closures_page,
            "history": self.history_page,
        }
        for key, _label, _icon in NAV_ITEMS:
            self.stack.addWidget(self.pages[key])

        self._switch_page("dashboard")

        # --- Yarim tunda (00:00) avtomatik kunni yopish ---
        self._last_auto_close_check_date = be.today_str()
        self._midnight_timer = QTimer(self)
        self._midnight_timer.timeout.connect(self._check_midnight_auto_close)
        self._midnight_timer.start(30 * 1000)

        # --- "Tizimga mos (avto)" tema rejimida, operatsion tizim Dark/Light
        # rejimini muntazam tekshirib, mos kelmasa dasturni avtomatik
        # moslashtiradi (masalan, Windows'da tizim tungi rejimga o'tsa). ---
        self._theme_sync_timer = QTimer(self)
        self._theme_sync_timer.timeout.connect(self._check_system_theme_sync)
        self._theme_sync_timer.start(3 * 1000)

        # --- Telegram polling boshqarish (agar token sozlangan bo'lsa) ---
        try:
            be.start_telegram_polling()
            be.start_miniapp_server()
        except Exception:
            pass

    # ---- navigatsiya ----
    def _switch_page(self, key):
        page = self.pages.get(key)
        if page is None:
            return
        changed = self.stack.currentWidget() is not page
        self.stack.setCurrentWidget(page)
        if hasattr(page, "refresh"):
            page.refresh()
        if changed:
            self._animate_page_in(page)
        btn = self.nav_buttons.get(key)
        if btn and not btn.isChecked():
            btn.setChecked(True)
        if btn:
            self.nav_bar.select(btn, animate=changed)

    def _animate_page_in(self, page):
        """Sahifa almashganda yumshoq paydo bo'lish (fade) + yengil pastdan
        yuqoriga siljish (slide), 240 ms. Effekt tugagach olib tashlanadi
        (aks holda jadvallar sekin chizilardi)."""
        if not self.isVisible():
            return
        try:
            self._finish_page_anim()
            effect = QGraphicsOpacityEffect(page)
            effect.setOpacity(0.0)
            page.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, b"opacity", page)
            fade.setDuration(240)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(QEasingCurve.OutCubic)
            base = page.pos()
            slide = QPropertyAnimation(page, b"pos", page)
            slide.setDuration(240)
            slide.setStartValue(QPoint(base.x(), base.y() + 14))
            slide.setEndValue(base)
            slide.setEasingCurve(QEasingCurve.OutCubic)
            group = QParallelAnimationGroup(page)
            group.addAnimation(fade)
            group.addAnimation(slide)
            group.finished.connect(self._finish_page_anim)
            self._page_anim = group
            self._page_anim_page = page
            self._page_anim_base = base
            group.start()
        except Exception:
            self._finish_page_anim()

    def _finish_page_anim(self):
        group = getattr(self, "_page_anim", None)
        page = getattr(self, "_page_anim_page", None)
        self._page_anim = None
        self._page_anim_page = None
        if group is not None:
            try:
                group.stop()
            except Exception:
                pass
        if page is not None:
            try:
                page.setGraphicsEffect(None)
                base = getattr(self, "_page_anim_base", None)
                if base is not None:
                    page.move(base)
            except Exception:
                pass

    def _crossfade(self, change_fn, ms=430):
        """Tema/til o'zgarganda "qotib" almashish o'rniga: joriy ko'rinishning
        surati oynaning ustiga qo'yiladi, ostida o'zgarish bajariladi, so'ng
        surat silliq so'nib, yangi ko'rinish paydo bo'ladi."""
        if not self.isVisible():
            change_fn()
            return
        try:
            old = getattr(self, "_xfade_overlay", None)
            if old is not None:
                old.hide()
                old.deleteLater()
                self._xfade_overlay = None
            overlay = QLabel(self)
            overlay.setPixmap(self.grab())
            overlay.setGeometry(self.rect())
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            effect = QGraphicsOpacityEffect(overlay)
            effect.setOpacity(1.0)
            overlay.setGraphicsEffect(effect)
            overlay.show()
            overlay.raise_()
        except Exception:
            change_fn()
            return
        self._xfade_overlay = overlay
        try:
            change_fn()
        except Exception:
            overlay.hide()
            overlay.deleteLater()
            self._xfade_overlay = None
            raise
        overlay.raise_()
        anim = QPropertyAnimation(effect, b"opacity", overlay)
        anim.setDuration(ms)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InOutCubic)

        def _done():
            overlay.hide()
            overlay.deleteLater()
            if getattr(self, "_xfade_overlay", None) is overlay:
                self._xfade_overlay = None

        anim.finished.connect(_done)
        anim.start()
        self._xfade_anim = anim

    # ---- til ----
    def _on_language_changed(self, index):
        codes = ["uz", "en", "ru"]
        code = codes[index] if 0 <= index < len(codes) else "uz"

        def _apply():
            be.set_language(code)
            self._retranslate_all()

        self._crossfade(_apply)

    def _retranslate_all(self):
        self.app_title_lbl.setText(APP_NAME)
        self.telegram_btn.setText(be.tr("Telegram sozlamalari"))
        self._update_theme_btn_text()
        for i, (key, label, icon) in enumerate(NAV_ITEMS):
            self.nav_buttons[key].setText(be.tr(label))
        for page in self.pages.values():
            if hasattr(page, "retranslate"):
                page.retranslate()
        QTimer.singleShot(0, self.nav_bar.sync)

    # ---- tema ----
    # MUHIM: endi UCHTA tema rejimi bor -- "Kunduzgi", "Tungi" va "Tizimga
    # mos (avto)". Tugmani bosish ularni ketma-ket almashtiradi. "Tizimga
    # mos" rejimida dastur operatsion tizimning haqiqiy Dark/Light holatini
    # o'qib, o'zini shunga moslaydi -- va tizim rejimi keyinchalik
    # o'zgarsa ham (masalan Windows kechqurun avtomatik tungi rejimga
    # o'tsa), _check_system_theme_sync() orqali kuzatib, qayta moslashtirib
    # turadi. Bu foydalanuvchi bildirgan "dastur bilan Windows rejimi
    # bir-biriga mos kelmayapti" muammosini butunlay hal qiladi.
    def _update_theme_btn_text(self):
        labels = {
            "light": be.tr("Tema: Kunduzgi"),
            "dark": be.tr("Tema: Tungi"),
            "auto": be.tr("Tema: Tizimga mos"),
        }
        self.theme_btn.setText(labels.get(self._theme_mode, labels["auto"]))

    def _cycle_theme(self):
        order = ["light", "dark", "auto"]
        idx = order.index(self._theme_mode) if self._theme_mode in order else 2
        new_mode = order[(idx + 1) % len(order)]
        self._set_theme_mode(new_mode, save=True)

    def _set_theme_mode(self, mode, save=True):
        self._crossfade(lambda: self._set_theme_mode_impl(mode, save))

    def _set_theme_mode_impl(self, mode, save=True):
        self._theme_mode = mode
        if mode == "auto":
            dark = detect_system_dark_mode()
            if dark is None:
                dark = isDarkTheme()
            setTheme(Theme.DARK if dark else Theme.LIGHT)
        else:
            setTheme(Theme.DARK if mode == "dark" else Theme.LIGHT)
        if save:
            with be.settings_lock():
                settings = be.load_settings()
                settings["theme"] = mode
                be.save_settings(settings)
        self._update_theme_btn_text()
        # MUHIM: temani almashtirgandan keyin oyna foni ANIQ rangga qayta
        # o'rnatiladi -- aks holda macOS tizim Dark Mode'da bo'lsa, "Kunduzgi"
        # temaga o'tgandan keyin ham fon qora bo'lib qolar edi.
        apply_window_background(self)
        self._apply_windows11_effect()
        self._restyle_header_title()
        for page in self.pages.values():
            if hasattr(page, "refresh"):
                page.refresh()
        for _b in self.nav_buttons.values():
            _b.update()
        self.nav_bar.indicator.update()
        self.update()

    def _restyle_header_title(self):
        """Tepadagi "Treydchi" (APP_NAME) yozuvining ACCENT rangini qayta
        o'rnatadi.

        MUHIM TUZATISH: qfluentwidgets.TitleLabel o'zining ICHKI mexanizmi
        orqali `qconfig.themeChanged` signaliga ulanib, HAR TEMA
        o'ZGARGANDA o'z matn rangini standart qora/oq (light/dark)
        rangiga QAYTA O'RNATIB QO'YADI -- bu bizning maxsus (doim ACCENT,
        ya'ni to'q sariq) stilimizni "ustidan bosib" ketardi. Natijada
        birinchi ochilishda yozuv sariq bo'lib ko'rinsa-da, keyinchalik
        temani bir marta almashtirgandan so'ng, u qora yoki oq rangga
        aylanib qolardi (tema qanday bo'lishidan qat'i nazar sariq turishi
        kerak edi). Shu sababli, HAR safar tema o'zgarganda, ushbu funksiya
        chaqirilib, ACCENT rangi yana majburan qayta o'rnatiladi."""
        if hasattr(self, "app_title_lbl"):
            self.app_title_lbl.setStyleSheet(
                f"font-size: 42px; font-weight: 800; color: {ACCENT_COLOR};")

    def _check_system_theme_sync(self):
        """'Tizimga mos (avto)' rejimida ishlayotganda, operatsion tizim
        Dark/Light holatini davriy tekshiradi va dastur temasi u bilan mos
        kelmasa, avtomatik qayta moslaydi (saqlangan sozlamani o'zgartirmay,
        chunki rejim allaqachon 'auto')."""
        if getattr(self, "_theme_mode", "auto") != "auto":
            return
        dark = detect_system_dark_mode()
        if dark is None:
            return
        if dark != isDarkTheme():
            def _apply():
                setTheme(Theme.DARK if dark else Theme.LIGHT)
                apply_window_background(self)
                self._apply_windows11_effect()
                self._restyle_header_title()
                for page in self.pages.values():
                    if hasattr(page, "refresh"):
                        page.refresh()
                for _b in self.nav_buttons.values():
                    _b.update()
                self.nav_bar.indicator.update()
                self.update()

            self._crossfade(_apply)

    # ---- Windows 11 Mica/Acrylic ----
    def _apply_windows11_effect(self):
        """Windows'da sarlavha satri (title bar) rangini dastur temasiga
        majburlaydi.

        MUHIM TUZATISH (2-marta ko'rib chiqilgan): avval bu yerda Mica/
        Acrylic shaffof fon effekti ham yoqilar edi -- lekin bu effekt
        ba'zi Windows kompyuterlarida operatsion tizimning o'z fon
        rangidan "iz" qoldirib, foydalanuvchi ta'kidlaganidek, dastur
        ichida tanlangan tema (qora/oq) bilan Windows'ning tizim
        sozlamasi HAMON bir-biriga mos kelmay qolishiga sabab bo'lardi.
        Shu sababli Mica effekti BUTUNLAY OLIB TASHLANDI -- oyna foni endi
        FAQAT apply_window_background() belgilagan ANIQ (qattiq) rangda
        chiziladi, bu Windows tizim sozlamalaridan MUTLAQO mustaqil va
        100% ishonchli usul. Faqat native sarlavha satrining (title bar)
        rangi DWMWA_USE_IMMERSIVE_DARK_MODE orqali dastur temasiga
        moslashtiriladi, shunda title bar ham dastur tanasi bilan bir xil
        (qora/oq) ko'rinadi."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            dark = isDarkTheme()
            value = ctypes.c_int(1 if dark else 0)
            # MUHIM: Windows versiyasiga qarab bu atribut ikki xil raqam
            # bilan (19 -- eski "insider" build'lar, 20 -- rasmiy
            # 20H1+ build'lar) tanilishi mumkin. Ikkalasini ham urinib
            # ko'ramiz -- noto'g'risi shunchaki e'tiborsiz qoldiriladi.
            for attr_id in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr_id, ctypes.byref(value), ctypes.sizeof(value))
            # MUHIM: atribut o'rnatilgandan keyin Windows odatda sarlavha
            # satrini DARHOL qayta chizmaydi (keyingi resize/move'gacha eski
            # rangda ko'rinib turishi mumkin). SWP_FRAMECHANGED bilan
            # "freym o'zgardi" deb signal berib, darhol qayta chizishga
            # majburlaymiz.
            SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER = 0x0002, 0x0001, 0x0004
            SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
        except Exception:
            pass
        # Oyna foni har doim apply_window_background() bilan belgilangan
        # aniq rangda qoladi -- bu yerda hech qanday qo'shimcha
        # stylesheet/backdrop o'zgartirilmaydi.

    # ---- Telegram sozlamalari ----
    def _open_telegram_settings(self):
        TelegramSettingsDialog(self).exec()

    # ---- yarim tunda avtomatik kunni yopish ----
    def _check_midnight_auto_close(self):
        today = be.today_str()
        if today != self._last_auto_close_check_date:
            self._last_auto_close_check_date = today
            try:
                # be.auto_close_missed_days() bugungi kundan OLDINGI barcha
                # ochiq kunlarni yopadi (odatda faqat kecha), so'ng
                # sahifalarni yangilaymiz.
                be.auto_close_missed_days()
                self.dashboard_page.refresh()
                if hasattr(self, "closures_page"):
                    self.closures_page.refresh()
            except Exception:
                pass


class SplashScreen(QWidget):
    """Dastur ochilganda ko'rinadigan boshlang'ich oyna: o'rtada katta
    "Treydchi" yozuvi yumshoq paydo bo'ladi, tagida chiziq o'sib chiqadi,
    so'ng asosiy oyna silliq ochiladi."""

    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(660, 380)
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center() - self.rect().center())
        self._p = 0.0
        self._line = 0.0
        self._out = 1.0
        self._dark = isDarkTheme()
        self._anims = []

    def _set_p(self, v):
        self._p = float(v)
        self.update()

    def _set_line(self, v):
        self._line = float(v)
        self.update()

    def _set_out(self, v):
        self._out = float(v)
        self.update()

    def play_intro(self):
        a = QVariantAnimation(self)
        a.setDuration(800)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.valueChanged.connect(self._set_p)
        b = QVariantAnimation(self)
        b.setDuration(650)
        b.setStartValue(0.0)
        b.setEndValue(1.0)
        b.setEasingCurve(QEasingCurve.OutCubic)
        b.valueChanged.connect(self._set_line)
        self._anims += [a, b]
        a.start()
        QTimer.singleShot(300, b.start)

    def fade_out(self):
        c = QVariantAnimation(self)
        c.setDuration(350)
        c.setStartValue(1.0)
        c.setEndValue(0.0)
        c.setEasingCurve(QEasingCurve.InOutCubic)
        c.valueChanged.connect(self._set_out)
        c.finished.connect(self.close)
        self._anims.append(c)
        c.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setOpacity(self._out)
        rect = QRectF(self.rect()).adjusted(24, 24, -24, -24)

        # yumshoq soya
        for i in range(10):
            alpha = 5
            grow = i * 2.0
            r = rect.adjusted(-grow, -grow + 6, grow, grow + 6)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(r, 26 + grow, 26 + grow)

        bg = QColor("#15171C") if self._dark else QColor("#FFFFFF")
        border = QColor(255, 255, 255, 28) if self._dark else QColor(0, 0, 0, 22)
        p.setBrush(bg)
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(rect, 26, 26)

        cx, cy = rect.center().x(), rect.center().y()
        e = self._p
        p.save()
        p.translate(cx, cy - 8)
        s = 0.86 + 0.14 * e
        p.scale(s, s)
        p.setOpacity(self._out * e)
        font = QFont(be.FONT_SANS_NAME)
        font.setPixelSize(70)
        font.setBold(True)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(font)
        p.setPen(QColor("#FFFFFF") if self._dark else QColor("#1B1D22"))
        p.drawText(QRectF(-300, -60, 600, 120), Qt.AlignCenter, APP_NAME)
        p.restore()

        w = 130.0 * self._line
        p.setOpacity(self._out)
        line_rect = QRectF(cx - w / 2, cy + 56, w, 5)
        # chiziq ORQASIDAN chiqadigan ikki rangli neon nur
        if w > 2:
            n1, n2 = neon_pair(ACCENT_COLOR)
            glow_m = 16
            p.setBrush(Qt.NoBrush)
            for i in range(glow_m, 0, -1):
                k = 1.0 - i / float(glow_m)
                alpha = int(95 * self._line * (k ** 2.0))
                if alpha <= 0:
                    continue
                gr = QLinearGradient(line_rect.left(), 0, line_rect.right(), 0)
                a = QColor(n1); a.setAlpha(alpha)
                b = QColor(n2); b.setAlpha(alpha)
                gr.setColorAt(0.0, a)
                gr.setColorAt(1.0, b)
                p.setPen(QPen(QBrush(gr), 1.4))
                r = line_rect.adjusted(-i, -i, i, i)
                p.drawRoundedRect(r, 2.5 + i, 2.5 + i)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT_COLOR))
        p.drawRoundedRect(line_rect, 2.5, 2.5)
        p.end()


def main():
    be.init_db()

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    try:
        if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
            QApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setStyleSheet(MAIN_QSS)

    settings = be.load_settings()
    # MUHIM: standart qiymat endi "light" emas, "auto" -- shunda birinchi
    # marta ochilganda ham dastur darhol Windows/macOS tizim Dark/Light
    # rejimiga mos holda ochiladi (avval doim "Kunduzgi" bilan ochilib,
    # tizim tungi rejimda bo'lsa mos kelmasdi).
    saved_theme = settings.get("theme", "auto")
    if saved_theme == "auto":
        dark = detect_system_dark_mode()
        setTheme(Theme.DARK if dark else Theme.LIGHT)
    else:
        setTheme(Theme.DARK if saved_theme == "dark" else Theme.LIGHT)
    setThemeColor(ACCENT_COLOR)

    # --- Boshlang'ich animatsiya (splash) va asosiy oynani silliq ochish ---
    splash = SplashScreen()
    splash.show()
    splash.play_intro()
    app.processEvents()
    state = {}
    clock = QElapsedTimer()
    clock.start()

    def reveal():
        window = state["window"]
        try:
            window.setWindowOpacity(0.0)
            window.show()
            window.raise_()
            window.activateWindow()
            fade = QPropertyAnimation(window, b"windowOpacity", window)
            fade.setDuration(350)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(QEasingCurve.OutCubic)
            fade.finished.connect(lambda: window.setWindowOpacity(1.0))
            fade.start()
            state["fade"] = fade
        except Exception:
            window.setWindowOpacity(1.0)
            window.show()
        splash.fade_out()

    def build_and_reveal():
        # Asosiy oyna splash animatsiyasining statik (to'xtab turgan) qismida
        # quriladi -- shunda animatsiya "qotib" qolmaydi.
        try:
            state["window"] = MainWindow()
        except Exception:
            import traceback
            traceback.print_exc()
            splash.close()
            app.exit(1)
            return
        remaining = max(0, 1500 - clock.elapsed())
        QTimer.singleShot(remaining, reveal)

    QTimer.singleShot(850, build_and_reveal)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
