export const FILTER_TEXT = "فروش بیشتر از ۵۰ میلیون را پیدا کن";
export const SORT_TEXT = "داده‌ها را بر اساس مبلغ مرتب کن";
export const COMPUTE_TEXT = "ستون درصد اختلاف را اضافه کن";
export const RECONCILE_TEXT = "این دو فایل را تطبیق بده، اختلاف مبالغ را پیدا کن و فایل مغایرت بده";
export const INSPECT_TEXT = "ساختار فایل را بررسی کن";
export const PREVIEW_TEXT = "پیش\u200cنمایش این فایل";
export const CLEAN_TEXT = "این فایل را پاکسازی کن";

export type QuickAction = {
  label: string;
  text: string;
  files: "one" | "pair";
};

export const QUICK_ACTIONS: QuickAction[] = [
  { label: "بررسی ساختار", text: INSPECT_TEXT, files: "one" },
  { label: "پیش‌نمایش", text: PREVIEW_TEXT, files: "one" },
  { label: "پاک‌سازی", text: CLEAN_TEXT, files: "one" },
  { label: "مرتب بر اساس مبلغ", text: SORT_TEXT, files: "one" },
  { label: "فیلتر فروش", text: FILTER_TEXT, files: "one" },
  { label: "درصد اختلاف", text: COMPUTE_TEXT, files: "one" },
  { label: "مغایرت", text: RECONCILE_TEXT, files: "pair" },
];
