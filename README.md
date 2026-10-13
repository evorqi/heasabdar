# حسابدار

فضای کار فایل و داده. کاربر فایل جدولی را وارد می‌کند و سیستم همان فایل را نگه می‌دارد تا در بخش‌های بعد روی آن کار شود.

نام نمایشی محصول **حسابدار** است. نام مخزن `heasabdar` است.

## وضعیت

بخش صفر تا هشت انجام شده‌اند. جزئیات در [docs/status.md](docs/status.md).

الان می‌توانید فضای کار بسازید، فایل را وارد کنید، ساختارش را ببینید، یک نسخه پاک‌شده بسازید و دو فایل را مغایرت بگیرید. گفتگو رتبه، روند، نمودار، داشبورد و گزارش مدیریتی را هم اجرا می‌کند. فرمول زنده با برچسب ارزیابی‌نشده نوشته می‌شود. نسخه اصلی سر جایش می‌ماند. ساخت فایل از صفر هنوز نیست.

## سندها

| سند | موضوع |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | لایه‌ها، ماژول‌ها، جریان اجرا |
| [docs/contracts.md](docs/contracts.md) | قرارداد داده، عملیات و خروجی |
| [docs/decisions.md](docs/decisions.md) | تصمیم‌های فنی و دلیل آن‌ها |
| [docs/roadmap.md](docs/roadmap.md) | مراحل ساخت، وابستگی و معیار پذیرش |
| [docs/testing.md](docs/testing.md) | راهبرد تست، از جمله فارسی و فایل |
| [docs/design-system.md](docs/design-system.md) | سیستم طراحی و لحن فارسی |
| [docs/risks.md](docs/risks.md) | ریسک، حدود و وابستگی |
| [docs/status.md](docs/status.md) | وضعیت واقعی هر بخش |

## اجرای محلی

دو فرآیند لازم است. هر دو فقط روی همین رایانه گوش می‌دهند.

ترمینال اول، هسته:

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m hesabdar
```

سرویس روی `http://127.0.0.1:8000` بالا می‌آید. داده در `apps/api/data` ذخیره می‌شود و وارد مخزن نمی‌شود.

ترمینال دوم، رابط:

```bash
cd apps/web
npm install
npm run dev
```

رابط روی `http://127.0.0.1:5173` است و درخواست‌های `/api` را به هسته می‌فرستد.

اگر سرویس قرار است روی شبکه‌ای غیر از loopback باشد، `HESABDAR_ACCESS_TOKEN` اجباری است. نمونه تنظیم‌ها در `apps/api/.env.example` است. کلید را در مخزن نگذارید.

## تست

```bash
cd apps/api && .venv/bin/python -m pytest
cd apps/web && npm test && npm run build
```
