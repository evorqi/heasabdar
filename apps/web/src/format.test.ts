import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { formatDate, formatLabel, formatSize, savedMessage, statusLabel } from "./format";

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
