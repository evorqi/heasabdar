export const FILTER_TEXT = "فروش بیشتر از ۵۰ میلیون را پیدا کن";
export const SORT_TEXT = "داده‌ها را بر اساس مبلغ مرتب کن";
export const COMPUTE_TEXT = "ستون درصد اختلاف را اضافه کن";
export const RECONCILE_TEXT = "این دو فایل را تطبیق بده، اختلاف مبالغ را پیدا کن و فایل مغایرت بده";
export const INSPECT_TEXT = "ساختار فایل را بررسی کن";
export const PREVIEW_TEXT = "پیش\u200cنمایش این فایل";
export const CLEAN_TEXT = "این فایل را پاکسازی کن";
export const RANK_TEXT = "بیشترین فروش متعلق به کدام شهر است";
export const REPORT_TEXT = "یک گزارش مدیریتی بساز";
export const TREND_TEXT = "روند فروش ماهانه را نشان بده";
export const OUTLIER_TEXT = "مقدارهای پرت مبلغ را نشان بده";
export const KPI_TEXT = "شاخص‌های مبلغ را حساب کن";
export const AGGREGATE_TEXT = "مجموع و میانگین مبلغ را حساب کن";
export const CHART_TEXT = "یک نمودار ستونی از فروش بساز";
export const DASHBOARD_TEXT = "یک داشبورد فروش بساز";
export const FORMULA_TEXT = "فرمول درصد اختلاف را بنویس";
export const CREATE_TEXT = "یک فایل مدیریت فروش با برگه‌های فروش، مشتریان، محصولات، گزارش و داشبورد بساز";
export const MERGE_TEXT = "دو برگه را با هم ادغام کن";
export const RESTORE_TEXT = "به نسخه اصلی برگرد";

export type QuickAction = {
  label: string;
  text: string;
  files: "one" | "pair" | "none";
};

export const QUICK_ACTIONS: QuickAction[] = [
  { label: "ساخت فایل", text: CREATE_TEXT, files: "none" },
  { label: "ادغام برگه", text: MERGE_TEXT, files: "one" },
  { label: "بازگشت", text: RESTORE_TEXT, files: "one" },
  { label: "بررسی ساختار", text: INSPECT_TEXT, files: "one" },
  { label: "پیش‌نمایش", text: PREVIEW_TEXT, files: "one" },
  { label: "پاک‌سازی", text: CLEAN_TEXT, files: "one" },
  { label: "مرتب بر اساس مبلغ", text: SORT_TEXT, files: "one" },
  { label: "فیلتر فروش", text: FILTER_TEXT, files: "one" },
  { label: "درصد اختلاف", text: COMPUTE_TEXT, files: "one" },
  { label: "مغایرت", text: RECONCILE_TEXT, files: "pair" },
  { label: "رتبه شهر", text: RANK_TEXT, files: "one" },
  { label: "گزارش مدیریتی", text: REPORT_TEXT, files: "one" },
  { label: "روند", text: TREND_TEXT, files: "one" },
  { label: "پرت", text: OUTLIER_TEXT, files: "one" },
  { label: "شاخص‌ها", text: KPI_TEXT, files: "one" },
  { label: "مجموع و میانگین", text: AGGREGATE_TEXT, files: "one" },
  { label: "نمودار", text: CHART_TEXT, files: "one" },
  { label: "داشبورد", text: DASHBOARD_TEXT, files: "one" },
  { label: "فرمول زنده", text: FORMULA_TEXT, files: "one" },
];
