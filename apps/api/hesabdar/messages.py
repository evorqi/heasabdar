"""متن‌های فارسی قابل‌نمایش. مسیر دیسک و محتوای سلول در این متن‌ها نیست."""


FILE_CORRUPT_EXCEL = (
    "این فایل اکسل قابل‌خواندن نیست. فایل را دوباره ذخیره کنید و بار دیگر بارگذاری کنید."
)
FILE_CORRUPT_CSV = "این فایل CSV قابل‌خواندن نیست. آن را با رمز UTF-8 ذخیره کنید و دوباره بارگذاری کنید."
FILE_EMPTY = "این فایل خالی است و ذخیره نشد."
FILE_UNSUPPORTED = "این قالب پشتیبانی نمی‌شود. فقط فایل‌های xlsx، xls و csv پذیرفته می‌شوند."
FILE_UNSAFE_ARCHIVE = "این فایل فشرده از حد مجاز بزرگ‌تر است و برای ایمنی باز نشد."
FILE_INVALID_NAME = "نام فایل قابل قبول نیست. نام را بدون مسیر پوشه بنویسید."
NONE_ACCEPTED = "هیچ فایلی ذخیره نشد."
NO_FILES = "فایلی برای بارگذاری انتخاب نشده است."
TOO_MANY_FILES = "در هر نوبت حداکثر {limit} فایل می‌توانید بارگذاری کنید."
WORKSPACE_NOT_FOUND = "این فضای کار پیدا نشد."
FILE_NOT_FOUND = "این فایل در این فضای کار پیدا نشد."
VERSION_NOT_FOUND = "این نسخه در این فضای کار پیدا نشد."
FORBIDDEN = "شما به این پرونده دسترسی ندارید."
TITLE_REQUIRED = "نام فضای کار را وارد کنید."
TITLE_LONG = "نام فضای کار بیش از حد طولانی است."
REQUEST_INVALID = "درخواست نامعتبر است."
INTERNAL = "خطای داخلی رخ داد. دوباره تلاش کنید."
ROUTE_NOT_FOUND = "این نشانی پیدا نشد."
OUTPUT_INVALID = "خروجی پاک‌سازی با داده مبدأ هم‌خوان نیست و نسخه جدید ساخته نشد."
CLEAN_SUCCEEDED = "نسخه پاک‌شده ساخته شد. فایل اصلی دست نخورده است."
CLEAN_UNCHANGED = "هیچ خانه‌ای نیاز به پاک‌سازی نداشت."
CLEAN_WAITING = "پاک‌سازی منتظر تأیید است. فایلی نوشته نشد."
UNSAFE_BIND = "برای شنیدن روی شبکه، متغیر HESABDAR_ACCESS_TOKEN لازم است."


def file_too_large(limit_bytes: int) -> str:
    return f"حجم فایل از سقف {format_size(limit_bytes)} بیشتر است."


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} بایت"
    if size < 1024 * 1024:
        amount = size / 1024
        return f"{amount:.1f} کیلوبایت"
    amount = size / (1024 * 1024)
    return f"{amount:.1f} مگابایت"
