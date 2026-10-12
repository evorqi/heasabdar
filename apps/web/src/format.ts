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

function trimNumber(value: number): string {
  const rounded = value.toFixed(1);
  return rounded.endsWith(".0") ? rounded.slice(0, -2) : rounded;
}
