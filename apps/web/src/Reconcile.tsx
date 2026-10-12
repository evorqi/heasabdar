import { useState } from "react";
import {
  ApiError,
  applyReconciliation,
  downloadVersion,
  previewReconciliation,
  type ReconcileReport,
  type StoredFile,
} from "./api";
import { matchLabel } from "./format";

const PREVIEW_LIMIT = 200;

type Props = {
  workspaceId: string;
  files: StoredFile[];
  onChanged: () => Promise<void> | void;
};

export function Reconcile({ workspaceId, files, onChanged }: Props) {
  const [leftId, setLeftId] = useState(files[0]?.id ?? "");
  const [rightId, setRightId] = useState(files[1]?.id ?? files[0]?.id ?? "");
  const [picked, setPicked] = useState<string[]>([]);
  const [report, setReport] = useState<ReconcileReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(column: string) {
    setPicked((current) =>
      current.includes(column) ? current.filter((item) => item !== column) : [...current, column],
    );
  }

  async function preview() {
    if (leftId === rightId) {
      setError("دو فایل متفاوت انتخاب کنید.");
      return;
    }
    setBusy(true);
    setError(null);
    setPicked([]);
    try {
      setReport(await previewReconciliation(workspaceId, leftId, rightId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "پیش‌نمایش مغایرت انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (leftId === rightId) {
      setError("دو فایل متفاوت انتخاب کنید.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await applyReconciliation(workspaceId, leftId, rightId, picked);
      setReport(next);
      if (next.status === "succeeded" && next.result_file_id) {
        await onChanged();
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "ساخت فایل مغایرت انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    if (!report?.result_version_id || !report.result_name) return;
    setBusy(true);
    setError(null);
    try {
      await downloadVersion(workspaceId, report.result_version_id, report.result_name);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "دریافت فایل مغایرت انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  const needsChoice = Boolean(report?.key_ambiguous && picked.length === 0);
  const shown = report?.rows.slice(0, PREVIEW_LIMIT) ?? [];
  const succeeded = report?.status === "succeeded" && Boolean(report.result_file_id);

  return (
    <article className="card stack">
      <div className="section-head">
        <h2>مغایرت</h2>
      </div>
      <p className="muted">دو فایل مقایسه می‌شوند. فایل‌های اصلی عوض نمی‌شوند و نتیجه، اگر کلید معلوم باشد، فایل تازه‌ای است.</p>
      <div className="select-grid">
        <label className="field">
          <span>فایل اول</span>
          <select
            value={leftId}
            onChange={(event) => {
              setLeftId(event.target.value);
              setReport(null);
              setPicked([]);
            }}
          >
            {files.map((file) => (
              <option key={file.id} value={file.id}>
                {file.original_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>فایل دوم</span>
          <select
            value={rightId}
            onChange={(event) => {
              setRightId(event.target.value);
              setReport(null);
              setPicked([]);
            }}
          >
            {files.map((file) => (
              <option key={file.id} value={file.id}>
                {file.original_name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="detail-actions">
        <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => void preview()}>
          {busy ? "در حال بررسی…" : "پیش‌نمایش مغایرت"}
        </button>
        <button className="btn btn-primary" type="button" disabled={busy || needsChoice} onClick={() => void apply()}>
          ساخت فایل مغایرت
        </button>
      </div>
      {error ? (
        <p className="alert" role="alert">
          {error}
        </p>
      ) : null}
      {report ? (
        <>
          {succeeded ? (
            <p className="alert alert-success" role="status">
              {report.message}
            </p>
          ) : (
            <p className={report.key_ambiguous ? "alert" : "muted"} role="status">
              {report.question || report.message}
            </p>
          )}
          {report.key_ambiguous ? (
            <fieldset className="choices">
              <legend>ستون کلید</legend>
              {report.key_choices.map((column) => (
                <label key={column}>
                  <input
                    type="checkbox"
                    checked={picked.includes(column)}
                    onChange={() => toggle(column)}
                  />
                  <bdi>{column}</bdi>
                </label>
              ))}
            </fieldset>
          ) : report.key_columns.length > 0 ? (
            <p className="muted">
              کلید: {report.key_columns.map((column) => column).join("، ")}
            </p>
          ) : null}
          {report.rows.length > 0 ? (
            <>
              <p className="counts">
                {`منطبق ${report.summary.full_match}، مغایر ${report.summary.value_mismatch}، فقط فایل اول ${report.summary.only_left}، فقط فایل دوم ${report.summary.only_right}، مشکوک ${report.summary.ambiguous}`}
              </p>
              <div className="table-scroll">
                <table className="grid">
                  <caption>ردیف‌های مغایرت</caption>
                  <thead>
                    <tr>
                      <th>وضعیت</th>
                      <th>کلید چپ</th>
                      <th>کلید راست</th>
                      <th>نام</th>
                      <th>مبلغ چپ</th>
                      <th>مبلغ راست</th>
                      <th>علت</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((row, index) => (
                      <tr key={`${row.status}-${index}`}>
                        <td>{matchLabel(row.status)}</td>
                        <td>{row.key_left}</td>
                        <td>
                          <bdi>{row.key_right}</bdi>
                        </td>
                        <td>
                          {[row.name_left, row.name_right].filter(Boolean).join(" / ")}
                        </td>
                        <td>
                          <bdi>{row.amount_left ?? ""}</bdi>
                        </td>
                        <td>
                          <bdi>{row.amount_right ?? ""}</bdi>
                        </td>
                        <td>{row.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
          {succeeded ? (
            <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => void download()}>
              دریافت فایل مغایرت
            </button>
          ) : null}
        </>
      ) : null}
    </article>
  );
}
