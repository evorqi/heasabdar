import { useEffect, useState } from "react";
import type { StructureReport } from "./api";
import {
  headerStatusLabel,
  isDateText,
  isEmailText,
  isTabularValue,
  kindLabel,
  roleLabel,
  severityLabel,
  unsupportedLabel,
} from "./format";

const MARK = /(#(?:REF!|VALUE!|N\/A|DIV\/0!|NAME\?|NULL!|NUM!)|=\S+)/g;

function MarkedText({ text }: { text: string }) {
  const parts = text.split(MARK);
  return (
    <>
      {parts.map((part, index) =>
        part.startsWith("#") || part.startsWith("=") ? (
          <bdi key={index} dir="ltr">
            {part}
          </bdi>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

function CellText({ raw }: { raw: string }) {
  if (isEmailText(raw)) {
    return <bdi dir="ltr">{raw}</bdi>;
  }
  if (isTabularValue(raw)) {
    return <bdi dir={isDateText(raw) ? undefined : "ltr"}>{raw}</bdi>;
  }
  if (!raw.includes("@")) {
    return raw;
  }
  const parts = raw.split(/([^\s@]+@[^\s@]+\.[^\s@]+)/);
  return (
    <>
      {parts.map((part, index) =>
        part.includes("@") ? (
          <bdi key={index} dir="ltr">
            {part}
          </bdi>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

type Props = {
  report: StructureReport | null;
  loading: boolean;
  error: string | null;
  onInspect: () => void;
};

export function Inspection({ report, loading, error, onInspect }: Props) {
  const [sheetIndex, setSheetIndex] = useState(0);

  useEffect(() => {
    setSheetIndex(0);
  }, [report?.file_id, report?.version_id]);

  const sheet = report?.sheets[sheetIndex] ?? report?.sheets[0] ?? null;

  return (
    <article className="card stack">
      <div className="section-head">
        <h2>ساختار فایل</h2>
        <button className="btn btn-secondary" type="button" disabled={loading} onClick={onInspect}>
          {loading ? "در حال بررسی…" : "بررسی ساختار"}
        </button>
      </div>
      {error ? (
        <p className="alert" role="alert">
          {error}
        </p>
      ) : null}
      {loading && !report ? <p className="empty">در حال خواندن برگه‌ها و ستون‌ها…</p> : null}
      {report && sheet ? (
        <>
          <p className="muted">بررسی روی نسخه اصلی انجام شد و فایل تغییر نکرد.</p>
          <p className="counts">
            {report.sheet_count} برگه
            {report.unchecked.length > 0 ? ` • ${report.unchecked.length} مورد بررسی‌نشده` : ""}
          </p>
          {report.sheets.length > 1 ? (
            <div className="sheet-tabs" role="tablist" aria-label="برگه‌ها">
              {report.sheets.map((item, index) => (
                <button
                  key={item.name}
                  type="button"
                  role="tab"
                  aria-selected={item.name === sheet.name}
                  className={item.name === sheet.name ? "sheet-tab is-selected" : "sheet-tab"}
                  onClick={() => setSheetIndex(index)}
                >
                  <bdi>{item.name}</bdi>
                </button>
              ))}
            </div>
          ) : null}
          <dl className="meta">
            <dt>برگه</dt>
            <dd>
              <bdi>{sheet.name}</bdi>
            </dd>
            <dt>ردیف‌ها</dt>
            <dd className="num">{sheet.row_count}</dd>
            <dt>ردیف داده</dt>
            <dd className="num">{sheet.data_row_count}</dd>
            <dt>ستون‌ها</dt>
            <dd className="num">{sheet.column_count}</dd>
            <dt>عنوان</dt>
            <dd>{headerStatusLabel(sheet.header_status)}</dd>
            <dt>فرمول</dt>
            <dd className="num">{sheet.formula_count}</dd>
            <dt>خطای نمایشی</dt>
            <dd className="num">{sheet.error_display_count}</dd>
          </dl>
          {sheet.unsupported.length > 0 ? (
            <p>
              ساختارهای پشتیبانی‌نشده: {sheet.unsupported.map(unsupportedLabel).join("، ")}. این بررسی آن‌ها را حذف
              نمی‌کند.
            </p>
          ) : null}
          {sheet.columns.length > 0 ? (
            <div className="table-scroll">
              <table className="grid">
                <caption>ستون‌ها</caption>
                <thead>
                  <tr>
                    <th>ستون</th>
                    <th>نوع</th>
                    <th>نقش</th>
                    <th>اطمینان</th>
                    <th>خانه خالی</th>
                  </tr>
                </thead>
                <tbody>
                  {sheet.columns.map((column) => (
                    <tr key={column.index}>
                      <th scope="row">{column.name}</th>
                      <td>{kindLabel(column.kind)}</td>
                      <td>{column.role_hints.length > 0 ? column.role_hints.map(roleLabel).join("، ") : "—"}</td>
                      <td className="num">{column.kind_confidence}</td>
                      <td className="num">{column.empty_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty">این برگه داده‌ای ندارد.</p>
          )}
          <h3>یافته‌ها</h3>
          {report.findings.length === 0 ? (
            <p className="empty">یافته‌ای برای این فایل ثبت نشد.</p>
          ) : (
            <ul className="findings">
              {report.findings.map((finding, index) => (
                <li key={`${finding.code}-${index}`} className={`finding finding-${finding.severity}`}>
                  <span className={`pill pill-${finding.severity}`}>{severityLabel(finding.severity)}</span>
                  <span>
                    <MarkedText text={finding.message} />
                  </span>
                </li>
              ))}
            </ul>
          )}
          {report.unchecked.length > 0 ? (
            <>
              <h3>بررسی نشده</h3>
              <ul className="findings">
                {report.unchecked.map((item, index) => (
                  <li key={`${item.code}-${index}`} className="finding finding-warning">
                    <span className="pill pill-warning">بررسی نشده</span>
                    <span>
                      {item.message}
                      {item.count > 1 ? ` (${item.count})` : ""}
                      {item.sheet ? ` — ${item.sheet}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          <h3>پیش‌نمایش</h3>
          {sheet.preview.rows.length === 0 ? (
            <p className="empty">ردیفی برای پیش‌نمایش نیست.</p>
          ) : (
            <>
              {sheet.preview.truncated ? (
                <p className="muted">پیش‌نمایش فقط {sheet.preview.row_limit} ردیف نخست را نشان می‌دهد.</p>
              ) : null}
              <div className="table-scroll">
                <table className="grid preview">
                  <caption>مقادیر خام</caption>
                  <thead>
                    <tr>
                      <th>ردیف</th>
                      {sheet.columns.map((column) => (
                        <th key={column.index}>{column.name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sheet.preview.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        <td className="num">{rowIndex + 1}</td>
                        {sheet.columns.map((column, columnIndex) => {
                          const cell = row[columnIndex];
                          const raw = cell?.raw ?? "";
                          return (
                            <td key={column.index} className={isTabularValue(raw) ? "num" : undefined}>
                              <CellText raw={raw} />
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      ) : null}
    </article>
  );
}
