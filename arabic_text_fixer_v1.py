#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
arabic_text_fixer_v1.py — مُصلِح النص العربي (Arabic Text Fixer) — Dagdog Tools

FREE tool. Fixes Arabic text broken by copying from PDF / Word files:
  • presentation-form glyphs (ﷲ ﻻ …) back to standard letters
  • visually-reversed lines back to logical order (auto-detect + force)
  • letters split by spaces (ح ر و ف) joined back into words
  • hard-wrapped PDF lines merged back into paragraphs
  • optional: tatweel removal, diacritics strip, ى→ي, ة→ه

Run:  python arabic_text_fixer_v1.py   →  page opens at http://127.0.0.1:8242
100% local: stdlib only, binds 127.0.0.1, per-run token, zero outbound.
"""

import hmac
import json
import re
import secrets
import sys
import unicodedata
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT_START = 8242
PORT_TRIES = 20
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")
# Per-run access token: generated at boot, embedded only in the page served
# to this machine's own browser; every API route requires it.
RUN_TOKEN = secrets.token_urlsafe(24)
MAX_BODY = 2_000_000  # 2 MB of pasted text is plenty; refuse more (413)

# ============================================================ text engine ==

_TATWEEL = "ـ"


def _is_ar_letter(ch):
    """True for Arabic letters (not marks, not tatweel)."""
    o = ord(ch)
    if o == 0x0640:  # tatweel is a stretcher, not a letter
        return False
    if unicodedata.category(ch).startswith("M"):  # combining marks
        return False
    return (0x0621 <= o <= 0x064A) or (0x066E <= o <= 0x06D3) \
        or (0x06FA <= o <= 0x06FF)


def unshape(text):
    """Presentation-form glyphs (U+FB50–FDFF, U+FE80–FEFF) → standard letters.

    Each glyph is mapped through its Unicode compatibility decomposition,
    which also expands lam-alef ligatures (ﻻ → لا) and ﷲ → الله. Characters
    outside the presentation ranges are left byte-identical.
    """
    out = []
    for ch in text:
        o = ord(ch)
        if (0xFB50 <= o <= 0xFDFF) or (0xFE80 <= o <= 0xFEFF):
            out.append(unicodedata.normalize("NFKC", ch))
        else:
            out.append(ch)
    return "".join(out)


_DIACRITIC_RANGES = ((0x064B, 0x065F), (0x0670, 0x0670), (0x06D6, 0x06DC),
                     (0x06DF, 0x06E4), (0x06E7, 0x06E8), (0x06EA, 0x06ED))


def strip_diacritics(text):
    return "".join(ch for ch in text
                   if not any(a <= ord(ch) <= b
                              for a, b in _DIACRITIC_RANGES))


def _strip_marks(s):
    """Remove diacritics/tatweel — used only for word scoring."""
    return "".join(ch for ch in s if ch != _TATWEEL
                   and not any(a <= ord(ch) <= b
                               for a, b in _DIACRITIC_RANGES))


# Frequent Arabic words — the compass for visual-order detection. A reversed
# line scores ~0 with these; its mirror image scores high, and vice versa.
COMMON_WORDS = frozenset("""
في من إلى على أن إن ما لا لم لن هو هي كان كانت هذا هذه ذلك تلك التي الذي
مع عن بعد قبل عند غير كل أي بين حتى إذا لكن بل قد ثم أو يا له لها به بها
فيه منه منها عليه إليها الناس الله اليوم العلم الكتاب أحد ذات يتم يكون
لدى لدى نحو ضد مثل منذ خلال أثناء لدى لدى دون عبر أيضا أكثر قال قالت
""".split())

_STRIP_CHARS = ' \t.،؛؟?!:؛«»"\'()[]{}…-–—/\\|<>*'


def _word_score(line):
    s = 0
    for tok in line.split():
        core = _strip_marks(tok.strip(_STRIP_CHARS))
        if not core:
            continue
        if core in COMMON_WORDS:
            s += 1
        elif len(core) > 2 and core[0] == "و" and core[1:] in COMMON_WORDS:
            s += 1
        elif len(core) > 3 and core[:2] == "ال" and core[2:] in COMMON_WORDS:
            s += 1
    return s


def _line_visual(line):
    """Heuristic: does this line look stored in visual (reversed) order?"""
    ar = sum(1 for c in line if _is_ar_letter(c))
    lat = sum(1 for c in line if c.isascii() and c.isalpha())
    if ar < 4 or ar < lat:
        return False
    s0 = _word_score(line)
    s1 = _word_score(line[::-1])
    if s1 > s0 and s1 >= 1:
        return True
    # sentence-final punctuation migrated to the front is a strong tell
    if line.lstrip()[:1] in (".", "؟", "?", "!", "…") and s0 == 0 and s1 >= 1:
        return True
    return False


def _expand_char(ch, expand):
    o = ord(ch)
    if expand and ((0xFB50 <= o <= 0xFDFF) or (0xFE80 <= o <= 0xFEFF)):
        return unicodedata.normalize("NFKC", ch)
    return ch


def _tokenize(line):
    """Split a raw line into ('base', ch) / ('mark', ch) items. A 'base' is
    any non-combining character (letter, digit, space, punctuation, or one
    presentation glyph); marks are combining characters."""
    return [("mark", ch) if unicodedata.category(ch).startswith("M")
            else ("base", ch) for ch in line]


def _skeleton(items, expand):
    """The line's base characters only (marks dropped), presentation
    glyphs expanded — what direction detection judges."""
    return "".join(_expand_char(ch, expand) for kind, ch in items
                   if kind == "base")


def _render_logical(items, expand):
    """Render a line that is already in logical order: bases in order,
    each followed by the marks that follow it in the raw text."""
    out = []
    pending = ""
    for kind, ch in items:
        if kind == "mark":
            if out:
                out.append(ch)
            else:
                pending += ch
        else:
            out.append(_expand_char(ch, expand))
            if pending:
                out.append(pending)
                pending = ""
    if pending:
        out.append(pending)
    return "".join(out)


def _render_visual(items, expand):
    """Render a line stored in visual order back to logical order.

    In visual order a combining mark sits BEFORE its base glyph (the pure
    character reversal that broken extractors produce), and a ligature
    glyph (ﷲ, ﻻ) is a single glyph. So: group (leading marks + base),
    reverse the groups, and emit each group as expansion(base) + marks —
    the marks land on the expansion's last letter, where they belong.
    """
    groups = []
    pending = ""
    for kind, ch in items:
        if kind == "mark":
            pending += ch
        else:
            groups.append((pending, ch))
            pending = ""
    if pending and groups:
        m, b = groups[-1]
        groups[-1] = (m + pending, b)
    elif pending:
        groups.append((pending, ""))
    out = []
    for marks, base in reversed(groups):
        out.append(_expand_char(base, expand) if base else "")
        out.append(marks)
    return "".join(out)


def _fix_directions(lines, mode, expand):
    """Render each raw line of a block in its correct direction."""
    if mode == "force":
        return [_render_visual(_tokenize(l), expand) for l in lines]
    if mode != "auto":
        return [_render_logical(_tokenize(l), expand) for l in lines]
    items = [_tokenize(l) for l in lines]
    skels = [_skeleton(it, expand) for it in items]
    flags = [_line_visual(s) for s in skels]
    ar_idx = [i for i, s in enumerate(skels)
              if any(_is_ar_letter(c) for c in s)]
    votes = sum(1 for i in ar_idx if flags[i])
    # Block vote: if at least half of the Arabic lines look visual, the
    # whole block came from the same broken source — reverse every Arabic
    # line, including fragments too short to judge on their own.
    block_visual = bool(ar_idx) and votes >= max(1, (len(ar_idx) + 1) // 2)
    out = []
    for it, s, f in zip(items, skels, flags):
        visual = f or (block_visual and any(_is_ar_letter(c) for c in s))
        out.append(_render_visual(it, expand) if visual
                   else _render_logical(it, expand))
    return out


_PUNCT_TAIL = '.,،؛؟?!:؛»"”’…)]}'


def _letter_token(tok):
    """If tok is exactly ONE Arabic letter (+ marks) + optional trailing
    punctuation, return (letter_part, punct_tail); else None."""
    core = tok.rstrip(_PUNCT_TAIL)
    if not core:
        return None
    bases = [c for c in core if _is_ar_letter(c)]
    if len(bases) == 1 and all(
            _is_ar_letter(c) or unicodedata.category(c).startswith("M")
            for c in core):
        return core, tok[len(core):]
    return None


def _join_segment(seg):
    toks = seg.split(" ")
    out = []  # (text, was_merged)
    i = 0
    while i < len(toks):
        lt = _letter_token(toks[i]) if toks[i] else None
        if lt:
            run = [lt]
            j = i + 1
            while j < len(toks):
                lt2 = _letter_token(toks[j]) if toks[j] else None
                if not lt2:
                    break
                run.append(lt2)
                j += 1
            if len(run) >= 2:
                merged = "".join(c + t for c, t in run)
                out.append((merged, True))
                i = j
                continue
            out.append((toks[i], False))
            i += 1
            continue
        # a bare punctuation token right after a joined word belongs to it
        if toks[i] and all(c in _PUNCT_TAIL for c in toks[i]) \
                and out and out[-1][1]:
            out[-1] = (out[-1][0] + toks[i], True)
            i += 1
            continue
        out.append((toks[i], False))
        i += 1
    return " ".join(t for t, _ in out)


def join_split_letters(line):
    """Join space-split letters into words. Runs separated by 2+ spaces are
    treated as original word boundaries and re-joined with a single space."""
    chunks = re.split(r"\s{2,}|\t", line)
    return " ".join(_join_segment(c) for c in chunks if c != "")


_ENDERS = set(".؟?!…:؛»\"”’)")
_LIST_RE = re.compile(r"^(\d{1,3}\s*[\.\)\-]|[-•*]\s|\(\d+\))")


def _should_merge(cur, nxt, ref):
    if _LIST_RE.match(nxt):
        return False
    # a line that reached the column edge continues on the next line,
    # even when a sentence happened to end exactly at the margin
    if len(cur) >= 0.5 * ref:
        return True
    # a long-ish line with no sentence ender is a wrapped continuation
    if len(cur.split()) >= 5 and cur[-1] not in _ENDERS:
        return True
    # an Arabic comma never ends a thought
    if cur.endswith("،"):
        return True
    return False


def _merge_block(lines):
    if len(lines) < 2:
        return lines
    ref = max(len(l) for l in lines)
    out = [lines[0]]
    for nxt in lines[1:]:
        cur = out[-1]
        if cur and nxt and _should_merge(cur, nxt, ref):
            out[-1] = cur + " " + nxt
        else:
            out.append(nxt)
    return out


DEFAULT_OPTS = dict(unshape=True, reverse="auto", join_letters=True,
                    merge_lines=True, tatweel=True, diacritics=False,
                    alef_maksura=False, teh_marbuta=False)


def fix_text(text, opts=None):
    """Run the fixing pipeline. Returns (fixed_text, stats dict)."""
    o = dict(DEFAULT_OPTS)
    if opts:
        o.update({k: v for k, v in opts.items() if k in DEFAULT_OPTS})
    if o["reverse"] not in ("auto", "force", "off"):
        o["reverse"] = "auto"
    chars_in = len(text)
    lines_in = text.count("\n") + 1 if text else 0
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # group raw lines into blank-line-separated blocks
    blocks, cur = [], []
    for raw in text.split("\n"):
        if raw.strip():
            cur.append(raw.strip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    out_blocks = []
    for block in blocks:
        lines = _fix_directions(block, o["reverse"], o["unshape"])
        if o["join_letters"]:
            lines = [join_split_letters(l) for l in lines]
        if o["merge_lines"]:
            lines = _merge_block(lines)
        out_blocks.append("\n".join(lines))
    text = "\n\n".join(out_blocks)
    if o["tatweel"]:
        text = text.replace(_TATWEEL, "")
    if o["alef_maksura"]:
        text = text.replace("ى", "ي")
    if o["teh_marbuta"]:
        text = text.replace("ة", "ه")
    if o["diacritics"]:
        text = strip_diacritics(text)
    stats = {"chars_in": chars_in, "chars_out": len(text),
             "lines_in": lines_in,
             "lines_out": text.count("\n") + 1 if text else 0}
    return text, stats


# ============================================================== the page ==

PAGE = '<!DOCTYPE html>\n<html lang="ar" dir="rtl">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>مُصلِح النص العربي — Dagdog Tools</title>\n<style>\n  :root { --bg:#0b1220; --panel:#101a2e; --panel2:#0d1626; --line:#1e2c47;\n          --line2:#2a3c5f; --txt:#e8eef7; --mut:#93a4bd; --cyan:#19c2d8;\n          --amber:#f5a623; --grad:linear-gradient(135deg,#19c2d8,#f5a623); }\n  * { box-sizing:border-box; }\n  body { font-family:"Segoe UI", Tahoma, Arial, sans-serif; background:var(--bg);\n         color:var(--txt); margin:0; padding:22px 14px 40px; }\n  .wrap { max-width:1060px; margin:0 auto; }\n  header { display:flex; align-items:center; gap:13px; flex-wrap:wrap; }\n  .logo { width:48px; height:48px; border-radius:14px; background:var(--grad);\n          display:flex; align-items:center; justify-content:center;\n          font-weight:900; color:#0b1220; font-size:19px; flex:none; }\n  header h1 { font-size:23px; margin:0; }\n  header .sub { margin:3px 0 0; color:var(--mut); font-size:13.5px; }\n  .spacer { flex:1; }\n  .pill { font-size:12px; color:var(--mut); background:var(--panel);\n          border:1px solid var(--line); border-radius:20px; padding:5px 12px; }\n  #langBtn { background:var(--panel); color:var(--txt); border:1px solid var(--line);\n             border-radius:20px; padding:6px 14px; cursor:pointer; font-size:13px; }\n  .card { background:var(--panel); border:1px solid var(--line);\n          border-radius:16px; padding:14px; margin-top:14px; }\n  .lab { font-size:12.5px; color:var(--mut); margin:0 2px 7px; }\n  .chips { display:flex; gap:8px; flex-wrap:wrap; }\n  .chip { flex:1 1 150px; text-align:center; font-size:13.5px; padding:9px 6px;\n          border-radius:12px; background:var(--panel2); border:1px solid var(--line);\n          color:var(--txt); cursor:pointer; user-select:none; }\n  .chip .s { display:block; font-size:11px; color:var(--mut); margin-top:2px; }\n  .chip.sel { background:var(--grad); color:#0b1220; font-weight:800;\n              border-color:transparent; }\n  .chip.sel .s { color:#22304a; }\n  .cols { display:grid; grid-template-columns:1fr 1fr; gap:12px; }\n  @media (max-width:760px){ .cols { grid-template-columns:1fr; } }\n  textarea { width:100%; min-height:260px; resize:vertical; background:var(--panel2);\n             color:var(--txt); border:1px solid var(--line); border-radius:12px;\n             padding:12px; font-size:16px; line-height:1.9;\n             font-family:"Segoe UI", Tahoma, Arial, sans-serif; }\n  textarea:focus { outline:none; border-color:var(--cyan); }\n  .btns { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }\n  button.act { padding:11px 18px; font-size:14.5px; font-weight:700;\n               background:var(--panel); color:var(--txt);\n               border:1px solid var(--line2); border-radius:11px; cursor:pointer; }\n  button.act:hover { border-color:var(--cyan); }\n  #fixAll { flex:1 1 220px; padding:14px; font-size:17px; font-weight:900;\n            color:#0b1220; background:var(--grad); border:0; border-radius:13px;\n            cursor:pointer; }\n  #stats { font-size:12.5px; color:var(--cyan); min-height:18px; margin-top:9px; }\n  #msg { font-size:13px; color:var(--amber); min-height:18px; margin-top:4px; }\n  footer { margin-top:22px; text-align:center; color:var(--mut); font-size:13px;\n           line-height:2; }\n  footer .brand { font-weight:900; font-size:15px;\n                  background:var(--grad); -webkit-background-clip:text;\n                  background-clip:text; color:transparent; }\n  footer a { color:var(--cyan); text-decoration:none; font-weight:700; }\n</style>\n</head>\n<body>\n<div class="wrap">\n  <header>\n    <div class="logo">&lt;/&gt;</div>\n    <div>\n      <h1 data-i18n="title">مُصلِح النص العربي</h1>\n      <p class="sub" data-i18n="sub">يصلّح النص العربي المكسور من النسخ من ملفات PDF وWord — مجاناً، على جهازك، بلا إنترنت</p>\n    </div>\n    <div class="spacer"></div>\n    <span class="pill" data-i18n="free">مجاني 100%</span>\n    <button id="langBtn">English</button>\n  </header>\n\n  <div class="card">\n    <p class="lab" data-i18n="opts">خيارات الإصلاح</p>\n    <div class="chips" id="chips">\n      <div class="chip sel" data-k="unshape"><span data-i18n="c_unshape">فكّ الحروف المرسومة</span><span class="s" data-i18n="c_unshape_s">ﷲ وﻻ ← الله ولا</span></div>\n      <div class="chip sel" data-k="reverse"><span data-i18n="c_reverse">إصلاح الانعكاس</span><span class="s" data-i18n="c_reverse_s">أسطر معكوسة ← ترتيب صحيح</span></div>\n      <div class="chip sel" data-k="join"><span data-i18n="c_join">وصل الحروف المفرّقة</span><span class="s" data-i18n="c_join_s">ح ر و ف ← حروف</span></div>\n      <div class="chip sel" data-k="merge"><span data-i18n="c_merge">دمج أسطر PDF</span><span class="s" data-i18n="c_merge_s">أسطر مقطوعة ← فقرات</span></div>\n      <div class="chip sel" data-k="tatweel"><span data-i18n="c_tatweel">إزالة الكشيدة</span><span class="s" data-i18n="c_tatweel_s">العــالمين ← العالمين</span></div>\n      <div class="chip" data-k="diacritics"><span data-i18n="c_diac">حذف التشكيل</span><span class="s" data-i18n="c_diac_s">اختياري</span></div>\n      <div class="chip" data-k="alef"><span data-i18n="c_alef">توحيد ى ← ي</span><span class="s" data-i18n="c_alef_s">اختياري — يغيّر الرسم</span></div>\n      <div class="chip" data-k="teh"><span data-i18n="c_teh">توحيد ة ← ه</span><span class="s" data-i18n="c_teh_s">اختياري — يغيّر الرسم</span></div>\n    </div>\n    <div class="btns">\n      <button id="fixAll" data-i18n="fixall">إصلاح شامل</button>\n      <button class="act" id="applyBtn" data-i18n="apply">تطبيق المحدد</button>\n      <button class="act" id="forceRev" data-i18n="forcerev">عكس كل الأسطر</button>\n      <button class="act" id="clearBtn" data-i18n="clear">مسح</button>\n    </div>\n    <div id="msg"></div>\n  </div>\n\n  <div class="card">\n    <div class="cols">\n      <div>\n        <p class="lab" data-i18n="inlab">النص المكسور — الصقه هنا</p>\n        <textarea id="in" dir="rtl" placeholder="..."></textarea>\n      </div>\n      <div>\n        <p class="lab" data-i18n="outlab">النص المُصلَح</p>\n        <textarea id="out" dir="rtl" readonly></textarea>\n      </div>\n    </div>\n    <div class="btns">\n      <button class="act" id="copyBtn" data-i18n="copy">نسخ النتيجة</button>\n      <button class="act" id="dlBtn" data-i18n="dl">تنزيل TXT</button>\n    </div>\n    <div id="stats"></div>\n  </div>\n\n  <footer>\n    <div class="brand">Dagdog Tools</div>\n    <div data-i18n="foot1">أدوات صغيرة لمشاكل حقيقية — تعمل بلا إنترنت</div>\n    <div>\n      <span data-i18n="foot2">أدواتنا الكاملة:</span>\n      <a href="https://dagdog2.gumroad.com" target="_blank" rel="noopener">Gumroad</a>\n      ·\n      <a href="https://payhip.com/DagdogTools" target="_blank" rel="noopener">Payhip</a>\n    </div>\n    <div data-i18n="foot3">🔒 النص لا يغادر جهازك أبداً</div>\n  </footer>\n</div>\n\n<script>\nvar TOKEN = \'__TOKEN__\';\nvar I18N = {\n  ar: { title:"مُصلِح النص العربي",\n        sub:"يصلّح النص العربي المكسور من النسخ من ملفات PDF وWord — مجاناً، على جهازك، بلا إنترنت",\n        free:"مجاني 100%", opts:"خيارات الإصلاح",\n        c_unshape:"فكّ الحروف المرسومة", c_unshape_s:"ﷲ وﻻ ← الله ولا",\n        c_reverse:"إصلاح الانعكاس", c_reverse_s:"أسطر معكوسة ← ترتيب صحيح",\n        c_join:"وصل الحروف المفرّقة", c_join_s:"ح ر و ف ← حروف",\n        c_merge:"دمج أسطر PDF", c_merge_s:"أسطر مقطوعة ← فقرات",\n        c_tatweel:"إزالة الكشيدة", c_tatweel_s:"العــالمين ← العالمين",\n        c_diac:"حذف التشكيل", c_diac_s:"اختياري",\n        c_alef:"توحيد ى ← ي", c_alef_s:"اختياري — يغيّر الرسم",\n        c_teh:"توحيد ة ← ه", c_teh_s:"اختياري — يغيّر الرسم",\n        fixall:"إصلاح شامل", apply:"تطبيق المحدد", forcerev:"عكس كل الأسطر",\n        clear:"مسح", inlab:"النص المكسور — الصقه هنا", outlab:"النص المُصلَح",\n        copy:"نسخ النتيجة", dl:"تنزيل TXT",\n        foot1:"أدوات صغيرة لمشاكل حقيقية — تعمل بلا إنترنت",\n        foot2:"أدواتنا الكاملة:",\n        foot3:"🔒 النص لا يغادر جهازك أبداً",\n        copied:"تم النسخ ✔", empty:"الصق النص أولاً",\n        stats:function(a,b,c,d){ return "أحرف: " + a + " ← " + b + " · أسطر: " + c + " ← " + d; },\n        langName:"English" },\n  en: { title:"Arabic Text Fixer",\n        sub:"Repairs Arabic text broken by copying from PDF & Word files — free, on your machine, no internet",\n        free:"100% Free", opts:"Fix options",\n        c_unshape:"Unshape glyphs", c_unshape_s:"ﷲ / ﻻ → الله / لا",\n        c_reverse:"Fix reversal", c_reverse_s:"reversed lines → logical order",\n        c_join:"Join split letters", c_join_s:"ح ر و ف → حروف",\n        c_merge:"Merge PDF lines", c_merge_s:"wrapped lines → paragraphs",\n        c_tatweel:"Remove tatweel", c_tatweel_s:"العــالمين → العالمين",\n        c_diac:"Strip diacritics", c_diac_s:"optional",\n        c_alef:"Normalize ى → ي", c_alef_s:"optional — changes spelling",\n        c_teh:"Normalize ة → ه", c_teh_s:"optional — changes spelling",\n        fixall:"Fix All", apply:"Apply Selected", forcerev:"Reverse All Lines",\n        clear:"Clear", inlab:"Broken text — paste here", outlab:"Fixed text",\n        copy:"Copy Result", dl:"Download TXT",\n        foot1:"Small tools for real problems — fully offline",\n        foot2:"Our full tools:",\n        foot3:"🔒 Your text never leaves this machine",\n        copied:"Copied ✔", empty:"Paste some text first",\n        stats:function(a,b,c,d){ return "Chars: " + a + " → " + b + " · Lines: " + c + " → " + d; },\n        langName:"العربية" }\n};\nvar lang = \'ar\';\nvar state = { unshape:true, reverse:true, join:true, merge:true,\n              tatweel:true, diacritics:false, alef:false, teh:false };\n\nfunction T(k){ return I18N[lang][k]; }\nfunction applyLang(){\n  document.documentElement.lang = lang;\n  document.documentElement.dir = (lang === \'ar\') ? \'rtl\' : \'ltr\';\n  document.querySelectorAll(\'[data-i18n]\').forEach(function(el){\n    var k = el.getAttribute(\'data-i18n\');\n    if (I18N[lang][k]) el.textContent = I18N[lang][k];\n  });\n  document.getElementById(\'langBtn\').textContent = T(\'langName\');\n  document.getElementById(\'in\').dir = \'rtl\';\n  document.getElementById(\'out\').dir = \'rtl\';\n}\ndocument.getElementById(\'langBtn\').onclick = function(){\n  lang = (lang === \'ar\') ? \'en\' : \'ar\'; applyLang();\n};\ndocument.querySelectorAll(\'#chips .chip\').forEach(function(ch){\n  ch.onclick = function(){\n    var k = ch.getAttribute(\'data-k\');\n    state[k] = !state[k];\n    ch.classList.toggle(\'sel\', state[k]);\n  };\n});\nfunction optsFromState(){\n  return { unshape: state.unshape,\n           reverse: state.reverse ? \'auto\' : \'off\',\n           join_letters: state.join, merge_lines: state.merge,\n           tatweel: state.tatweel, diacritics: state.diacritics,\n           alef_maksura: state.alef, teh_marbuta: state.teh };\n}\nfunction runFix(options){\n  var text = document.getElementById(\'in\').value;\n  var msg = document.getElementById(\'msg\');\n  if (!text.trim()) { msg.textContent = T(\'empty\'); return; }\n  msg.textContent = \'\';\n  fetch(\'/fix\', { method:\'POST\',\n                  headers:{ \'Content-Type\':\'application/json\',\n                            \'X-Fixer-Token\': TOKEN },\n                  body: JSON.stringify({ text:text, options:options }) })\n    .then(function(r){ return r.json(); })\n    .then(function(d){\n      document.getElementById(\'out\').value = d.result || \'\';\n      var s = d.stats || {};\n      document.getElementById(\'stats\').textContent =\n        T(\'stats\')(s.chars_in||0, s.chars_out||0, s.lines_in||0, s.lines_out||0);\n    })\n    .catch(function(){ msg.textContent = \'⚠\'; });\n}\ndocument.getElementById(\'fixAll\').onclick = function(){\n  var o = optsFromState();\n  o.unshape = true; o.reverse = \'auto\'; o.join_letters = true;\n  o.merge_lines = true; o.tatweel = true;\n  runFix(o);\n};\ndocument.getElementById(\'applyBtn\').onclick = function(){ runFix(optsFromState()); };\ndocument.getElementById(\'forceRev\').onclick = function(){\n  runFix({ unshape:false, reverse:\'force\', join_letters:false,\n           merge_lines:false, tatweel:false, diacritics:false,\n           alef_maksura:false, teh_marbuta:false });\n};\ndocument.getElementById(\'clearBtn\').onclick = function(){\n  document.getElementById(\'in\').value = \'\';\n  document.getElementById(\'out\').value = \'\';\n  document.getElementById(\'stats\').textContent = \'\';\n  document.getElementById(\'msg\').textContent = \'\';\n};\ndocument.getElementById(\'copyBtn\').onclick = function(){\n  var out = document.getElementById(\'out\');\n  out.select();\n  function done(){ document.getElementById(\'msg\').textContent = T(\'copied\'); }\n  if (navigator.clipboard && navigator.clipboard.writeText) {\n    navigator.clipboard.writeText(out.value).then(done, function(){\n      document.execCommand(\'copy\'); done(); });\n  } else { document.execCommand(\'copy\'); done(); }\n};\ndocument.getElementById(\'dlBtn\').onclick = function(){\n  var blob = new Blob([document.getElementById(\'out\').value],\n                      { type:\'text/plain;charset=utf-8\' });\n  var a = document.createElement(\'a\');\n  a.href = URL.createObjectURL(blob);\n  a.download = \'fixed-text.txt\';\n  a.click();\n  setTimeout(function(){ URL.revokeObjectURL(a.href); }, 2000);\n};\napplyLang();\n</script>\n</body>\n</html>\n'


# ================================================================ server ==

class Handler(BaseHTTPRequestHandler):
    server_version = "ArabicTextFixer/1.0"

    def version_string(self):
        return "ArabicTextFixer"

    def log_message(self, *args):
        pass

    # -- security guard: only this machine's own browser may talk to us --
    def _guard(self):
        host = (self.headers.get("Host") or "").strip()
        if host.startswith("["):
            hostname = host[1:host.find("]")] if "]" in host else host
        else:
            hostname = host.split(":")[0]
        if hostname.lower() not in ALLOWED_HOSTS:
            self._send(403, "Forbidden", "text/plain; charset=utf-8")
            return False
        origin = self.headers.get("Origin")
        if origin:
            oh = urlparse(origin).hostname
            if oh is None or oh.lower() not in ALLOWED_HOSTS:
                self._send(403, "Forbidden", "text/plain; charset=utf-8")
                return False
        # Per-run token: the page itself ("/") is the only open route — it
        # hands the token solely to this machine's own browser. Every API
        # route requires it (header or ?tok=).
        if urlparse(self.path).path != "/":
            given = self.headers.get("X-Fixer-Token") or ""
            if not given:
                qs = parse_qs(urlparse(self.path).query)
                given = (qs.get("tok") or [""])[0]
            if not hmac.compare_digest(given, RUN_TOKEN):
                self._send(403, "Forbidden", "text/plain; charset=utf-8")
                return False
        return True

    def _send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if ctype.startswith("text/html") \
                    or ctype.startswith("application/json"):
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                    "frame-ancestors 'none'")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cache-Control", "no-store")
            if extra:
                for k, v in extra.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if not self._guard():
            return
        route = urlparse(self.path).path
        if route == "/":
            page = PAGE.replace("__TOKEN__", RUN_TOKEN)
            self._send(200, page, "text/html; charset=utf-8")
        else:
            self._send(404, "Not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if not self._guard():
            return
        route = urlparse(self.path).path
        if route != "/fix":
            self._send(404, "Not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._send_json(413, {"error": "text too large"})
            return
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            data = json.loads(raw.decode("utf-8"))
            text = data.get("text", "")
            options = data.get("options") or {}
            if not isinstance(text, str) or not isinstance(options, dict):
                raise ValueError("bad payload")
        except Exception:
            self._send_json(400, {"error": "bad request"})
            return
        result, stats = fix_text(text, options)
        self._send_json(200, {"result": result, "stats": stats})


def main():
    server = None
    port = None
    for candidate in range(PORT_START, PORT_START + PORT_TRIES):
        try:
            server = ThreadingHTTPServer((HOST, candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        print("تعذر تشغيل الخادم المحلي — Could not bind a local port.")
        return 1
    url = "http://%s:%d/" % (HOST, port)
    print("مُصلِح النص العربي — Arabic Text Fixer (Dagdog Tools)")
    print("افتح في المتصفح: " + url)
    print("لإيقاف البرنامج: أغلق هذه النافذة أو اضغط Ctrl+C")
    if "--no-open" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
