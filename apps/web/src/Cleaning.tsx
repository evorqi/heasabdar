import { useState } from "react";
import {
  ApiError,
  applyCleaning,
  downloadVersion,
  previewCleaning,
  restoreVersion,
  type CleaningReport,
  type StoredFile,
} from "./api";
import { isTabularValue, ruleLabel } from "./format";

const PREVIEW_LIMIT = 200;

type Props = {
  workspaceId: string;
  file: StoredFile;
  onChanged: () => Promise<void> | void;
};

export function Cleaning({ workspaceId, file, onChanged }: Props) {
  const [report, setReport] = useState<CleaningReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function preview() {
    setBusy(true);
    setError(null);
    try {
      setReport(await previewCleaning(workspaceId, file.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "پیش‌نمایش پاک‌سازی انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function apply(confirm: boolean) {
    setBusy(true);
    setError(null);
    try {
      const next = await applyCleaning(workspaceId, file.id, confirm);
      setReport(next);
      if (next.status === "succeeded") {
        await onChanged();
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "پاک‌سازی انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function restore() {
    if (!report) return;
    setBusy(true);
    setError(null);
    try {
      await restoreVersion(workspaceId, file.id, report.source_version_id);
      await onChanged();
      setReport(await previewCleaning(workspaceId, file.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "بازگشت به نسخه اصلی انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  const shown = report?.changes.slice(0, PREVIEW_LIMIT) ?? [];
  const countMatches = report ? report.stats.change_count === report.changes.length : false;

  return (
    <article className="card stack">
      <div className="section-head">
        <h2>پاک‌سازی</h2>
        <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => void preview()}>
          {busy ? "در حال بررسی…" : "پیش‌نمایش پاک‌سازی"}
        </button>
      </div>
      <p className="muted">نسخه اصلی عوض نمی‌شود. نتیجه، اگر تغییری باشد، در نسخه جدید ذخیره می‌شود.</p>
      {error ? (
        <p className="alert" role="alert">
          {error}
        </p>
      ) : null}
      {report ? (
        <>
          {report.status === "succeeded" ? (
            <p className="alert alert-success" role="status">
              {report.message}
            </p>
          ) : (
            <p className={report.stats.requires_confirmation ? "alert" : "muted"} role="status">
              {report.message}
            </p>
          )}
          <p className="counts">
            {report.stats.change_count} تغییر
            {countMatches ? "" : " — شمارش با فهرست یکی نیست"}
          </p>
          {report.stats.sheets.map((sheet) => (
            <p key={sheet.name} className="muted">
              <bdi>{sheet.name}</bdi>
              {` : ${sheet.rows_before} ردیف قبل، ${sheet.rows_after} ردیف بعد، ${sheet.changed_rows} ردیف تغییرکرده`}
            </p>
          ))}
          {shown.length > 0 ? (
            <div className="table-scroll">
              <table className="grid">
                <caption>تغییرها</caption>
                <thead>
                  <tr>
                    <th>قاعده</th>
                    <th>قبل</th>
                    <th>بعد</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((change, index) => (
                    <tr key={`${change.rule_id}-${index}`}>
                      <td>{ruleLabel(change.rule_id)}</td>
                      <td className={isTabularValue(change.before) ? "num" : undefined}>
                        <bdi>{change.before}</bdi>
                      </td>
                      <td className={isTabularValue(change.after) ? "num" : undefined}>
                        <bdi>{change.after}</bdi>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {report.changes.length > shown.length ? (
            <p className="muted">فقط {PREVIEW_LIMIT} تغییر نخست نشان داده می‌شود. شمارش کل همان عدد بالاست.</p>
          ) : null}
          {report.skipped.length > 0 ? (
            <>
              <h3>دست نخورده</h3>
              <ul className="findings">
                {report.skipped.slice(0, PREVIEW_LIMIT).map((item, index) => (
                  <li key={`${item.rule_id}-${index}`} className="finding finding-warning">
                    <span className="pill pill-warning">بدون تغییر</span>
                    <span>{item.message}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          <div className="detail-actions">
            {report.stats.change_count > 0 && report.status !== "succeeded" ? (
              <button
                className="btn btn-primary"
                type="button"
                disabled={busy}
                onClick={() => void apply(report.stats.requires_confirmation)}
              >
                {report.stats.requires_confirmation ? "تأیید و ساخت نسخه" : "ساخت نسخه پاک‌شده"}
              </button>
            ) : null}
            {report.result_version_id ? (
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => void downloadVersion(workspaceId, report.result_version_id as string, file.original_name)}
              >
                دریافت نسخه پاک‌شده
              </button>
            ) : null}
            <button
              className="btn btn-secondary"
              type="button"
              onClick={() => void downloadVersion(workspaceId, report.source_version_id, file.original_name)}
            >
              دریافت نسخه اصلی
            </button>
            {report.status === "succeeded" ? (
              <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => void restore()}>
                بازگشت به نسخه اصلی
              </button>
            ) : null}
          </div>
        </>
      ) : null}
    </article>
  );
}
