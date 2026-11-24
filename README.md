# Arabic Text Fixer — مُصلِح النص العربي

A tiny free tool that repairs Arabic text broken by copying from PDF and Word files.
Runs 100% on your own computer — no internet, no account, and your text never leaves your device.

## What it fixes

- **Reversed lines** — text that comes out backwards after copying from a PDF
- **Presentation-form glyphs** — ﷲ / ﻻ and friends, back to normal letters
- **Split letters** — ح ر و ف reconnected into حروف
- **PDF line breaks** — wrapped lines merged back into clean paragraphs
- Optional: remove tatweel (ـ), strip diacritics, unify ى→ي and ة→ه (off by default — they change spelling)

## Quick start (no Python needed)

Download the ready-to-run package (bundled runtime, double-click `ArabicTextFixer.bat`):

- Gumroad (free): https://dagdog2.gumroad.com
- Payhip (free): https://payhip.com/DagdogTools

## Run from source

```bash
python arabic_text_fixer_v1.py
```

Then your browser opens at `http://127.0.0.1:8242`. Single file, Python standard library only.

Paste the broken text, press **Fix All**, copy the repaired text. Done.

## Privacy

Everything happens locally. The tool serves its page from your own machine,
requires a per-run access token, and sends nothing anywhere. Free forever — no key, no activation.

## License

MIT — see [LICENSE](LICENSE).

Made by **Dagdog Tools** — small tools for real problems.
Full tools: [Gumroad](https://dagdog2.gumroad.com) · [Payhip](https://payhip.com/DagdogTools)

---

# مُصلِح النص العربي

أداة مجانية صغيرة تصلح النص العربي المكسور من النسخ من ملفات PDF وWord.
تعمل 100% على جهازك — بلا إنترنت، بلا حساب، ونصك لا يغادر جهازك أبداً.

## ماذا تصلح؟

- **الأسطر المقلوبة** التي تخرج معكوسة عند النسخ من PDF
- **الحروف المرسومة** (أشكال العرض) — ترجع حروفاً عادية
- **الحروف المفصولة** — تتوصل من جديد في كلمات
- **أسطر PDF المقطوعة** — تندمج في فقرات نظيفة
- اختياري: إزالة الكشيدة والتشكيل وتوحيد ى←ي و ة←ه (مقفولة افتراضياً لأنها تغيّر الرسم)

## بداية سريعة (بلا Python)

نزّل الحزمة الجاهزة (فيها كل شيء، انقر مرتين على `ArabicTextFixer.bat`):

- Gumroad (مجاني): https://dagdog2.gumroad.com
- Payhip (مجاني): https://payhip.com/DagdogTools

## التشغيل من المصدر

```bash
python arabic_text_fixer_v1.py
```

يفتح المتصفح على `http://127.0.0.1:8242`. ملف واحد، مكتبة Python القياسية فقط.

الصق النص المكسور، اضغط **إصلاح شامل**، انسخ النص المُصلَح. خلاص.

## الخصوصية

كل شيء محلي: الصفحة تُقدَّم من جهازك، برمز دخول يتجدد مع كل تشغيل، ولا يُرسل أي شيء إلى أي مكان.
مجاني دائماً — لا مفتاح ولا تفعيل.

## الرخصة

MIT — انظر [LICENSE](LICENSE).

من **Dagdog Tools** — أدوات صغيرة لمشاكل حقيقية.
أدواتنا الكاملة: [Gumroad](https://dagdog2.gumroad.com) · [Payhip](https://payhip.com/DagdogTools)
