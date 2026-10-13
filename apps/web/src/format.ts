export function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} بایت`;
  }
  if (bytes < 1024 * 1024) {
    return `${trimNumber(bytes / 1024)} کیلوبایت`;
  }
  return `${trimNumber(bytes / (1024 * 1024))} مگابایت`;
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return new Intl.DateTimeFormat("fa-IR-u-nu-latn", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatLabel(format: string): string {
  if (format === "xlsx") return "Excel";
  if (format === "xls") return "Excel قدیمی";
  if (format === "csv") return "CSV";
  return format;
}

export function statusLabel(status: string): string {
  if (status === "stored") return "ذخیره شد";
  return status;
}

export function savedMessage(count: number): string {
  if (count === 1) return "1 فایل ذخیره شد.";
  return `${count} فایل ذخیره شد.`;
}

const KINDS: Record<string, string> = {
  text: "متن",
  identifier: "شناسه",
  number: "عدد",
  currency: "مبلغ",
  date: "تاریخ",
  boolean: "بله یا خیر",
  blank: "خالی",
  mixed: "مخلوط",
  unknown: "نامشخص",
};

const ROLES: Record<string, string> = {
  national_id: "کد ملی",
  phone: "تلفن",
  invoice_no: "شماره فاکتور",
  amount: "مبلغ",
  date: "تاریخ",
  person_name: "نام",
  city: "شهر",
  employee_id: "کد پرسنلی",
  customer_id: "شناسه مشتری",
  account_no: "شماره حساب",
  product_code: "کد کالا",
};

const SEVERITIES: Record<string, string> = {
  error: "خطا",
  warning: "هشدار",
  info: "توضیح",
  hypothesis: "احتمال",
};

const UNSUPPORTED: Record<string, string> = {
  macro: "ماکرو",
  pivot_table: "جدول محوری",
  external_link: "اتصال خارجی",
  chart: "نمودار",
  table: "جدول اکسل",
  data_validation: "اعتبارسنجی داده",
};

export function kindLabel(kind: string): string {
  return KINDS[kind] ?? kind;
}

export function roleLabel(role: string): string {
  return ROLES[role] ?? role;
}

export function severityLabel(severity: string): string {
  return SEVERITIES[severity] ?? severity;
}

export function headerStatusLabel(status: string): string {
  if (status === "detected") return "عنوان تشخیص داده شد";
  if (status === "hypothesized") return "عنوان قطعی نیست";
  return status;
}

export function unsupportedLabel(flag: string): string {
  return UNSUPPORTED[flag] ?? flag;
}

const RULES: Record<string, string> = {
  "text.trim": "فاصله دو سر",
  "text.collapse_spaces": "فاصله‌های پیاپی",
  "text.arabic_yeh": "ی عربی",
  "text.arabic_kaf": "ک عربی",
  "number.parse": "عدد",
  "date.parse_jalali": "تاریخ شمسی",
  "date.parse_gregorian": "تاریخ میلادی",
  "identifier.leading_zeros": "شناسه",
  "output.neutralize": "خنثی‌سازی",
};

export function ruleLabel(ruleId: string): string {
  return RULES[ruleId] ?? ruleId;
}

const MATCHES: Record<string, string> = {
  full_match: "منطبق",
  value_mismatch: "مغایر",
  only_left: "فقط فایل اول",
  only_right: "فقط فایل دوم",
  ambiguous: "مشکوک",
};

export function matchLabel(status: string): string {
  return MATCHES[status] ?? status;
}

export function operationLooksSuccessful(status: string): boolean {
  return status === "succeeded";
}

export function isTabularValue(raw: string | null): boolean {
  if (!raw) return false;
  if (raw.startsWith("=") || raw.startsWith("#")) return true;
  return /^[0-9۰-۹٠-٩+\-.,٬،%/]+$/.test(raw);
}

export function isDateText(raw: string | null): boolean {
  if (!raw) return false;
  const text = raw.trim();
  if (/^[0-9۰-۹٠-٩]{4}[-/][0-9۰-۹٠-٩]{1,2}[-/][0-9۰-۹٠-٩]{1,2}$/.test(text)) return true;
  return /^[0-9۰-۹٠-٩]{1,2}\s+\S+\s+[0-9۰-۹٠-٩]{4}$/.test(text);
}

function trimNumber(value: number): string {
  const rounded = value.toFixed(1);
  return rounded.endsWith(".0") ? rounded.slice(0, -2) : rounded;
}
