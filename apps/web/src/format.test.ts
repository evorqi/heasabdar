import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import {
  formatDate,
  formatLabel,
  formatSize,
  headerStatusLabel,
  isTabularValue,
  kindLabel,
  matchLabel,
  operationLooksSuccessful,
  ruleLabel,
  roleLabel,
  savedMessage,
  severityLabel,
  statusLabel,
  unsupportedLabel,
} from "./format";
import { QUICK_ACTIONS, RECONCILE_TEXT } from "./quick";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

describe("format", () => {
  test("uses latin digits and persian units", () => {
    expect(formatSize(0)).toBe("0 بایت");
    expect(formatSize(1536)).toBe("1.5 کیلوبایت");
    expect(formatSize(2048)).toBe("2 کیلوبایت");
  });

  test("labels stay in logical persian order", () => {
    expect(formatLabel("xls")).toBe("Excel قدیمی");
    expect(statusLabel("stored")).toBe("ذخیره شد");
    expect(savedMessage(2)).toBe("2 فایل ذخیره شد.");
    const name = "گزارش فروش مهر.csv";
    expect(name[0]).toBe("گ");
  });

  test("only a succeeded operation looks successful", () => {
    expect(operationLooksSuccessful("succeeded")).toBe(true);
    expect(operationLooksSuccessful("failed")).toBe(false);
    expect(operationLooksSuccessful("cancelled")).toBe(false);
    expect(operationLooksSuccessful("running")).toBe(false);
    expect(operationLooksSuccessful("waiting_confirmation")).toBe(false);
  });

  test("quick actions stay on registered tools and share the reconcile sentence", () => {
    expect(QUICK_ACTIONS.map((action) => action.label)).not.toContain("رتبه");
    expect(QUICK_ACTIONS.map((action) => action.label)).not.toContain("نمودار");
    expect(QUICK_ACTIONS.find((action) => action.label === "مغایرت")?.text).toBe(RECONCILE_TEXT);
    expect(QUICK_ACTIONS.find((action) => action.label === "پیش‌نمایش")?.text.includes("\u200c")).toBe(true);
  });

  test("labels structure without calling an identifier a certain number", () => {
    expect(ruleLabel("text.arabic_yeh")).toBe("ی عربی");
    expect(ruleLabel("identifier.leading_zeros")).toBe("شناسه");
    expect(matchLabel("ambiguous")).toBe("مشکوک");
    expect(matchLabel("full_match")).toBe("منطبق");
    expect(kindLabel("identifier")).toBe("شناسه");
    expect(kindLabel("identifier")).not.toBe("عدد");
    expect(roleLabel("national_id")).toBe("کد ملی");
    expect(roleLabel("amount")).toBe("مبلغ");
    expect(severityLabel("hypothesis")).toBe("احتمال");
    expect(severityLabel("error")).toBe("خطا");
    expect(headerStatusLabel("hypothesized")).toBe("عنوان قطعی نیست");
    expect(unsupportedLabel("pivot_table")).toBe("جدول محوری");
    expect(isTabularValue("0012345678")).toBe(true);
    expect(isTabularValue("1403/07/20")).toBe(true);
    expect(isTabularValue("=C2*2")).toBe(true);
    expect(isTabularValue("سارا احمدی")).toBe(false);
    expect(isTabularValue("20 مهر 1405")).toBe(false);
  });

  test("formats timestamps without throwing", () => {
    const formatted = formatDate("2026-10-12T09:30:00Z");
    expect(formatted).toMatch(/[0-9]/);
  });
});

test("page is persian and right to left", () => {
  const html = readFileSync(resolve(root, "index.html"), "utf8");
  expect(html).toContain('lang="fa"');
  expect(html).toContain('dir="rtl"');
  expect(html).toContain("حسابدار");
});

test("vazirmatn is self hosted", () => {
  const css = readFileSync(resolve(root, "src/styles.css"), "utf8");
  expect(css).toContain("./fonts/Vazirmatn-Regular.woff2");
  expect(css).toContain("./fonts/Vazirmatn-Bold.woff2");
  expect(css).toContain("font-family: Vazirmatn");
  expect(css).not.toContain("fonts.googleapis.com");
  expect(css).not.toContain("fonts.gstatic.com");
});
