import { useEffect, useState } from "react";
import { ApiError, listVersions, restoreVersion, type FileVersion, type StoredFile } from "./api";
import { formatDate } from "./format";

type Props = {
  workspaceId: string;
  file: StoredFile;
  onChanged: () => Promise<void> | void;
};

export function History({ workspaceId, file, onChanged }: Props) {
  const [versions, setVersions] = useState<FileVersion[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    void listVersions(workspaceId, file.id)
      .then((next) => {
        if (alive) setVersions(next);
      })
      .catch((caught: unknown) => {
        if (alive) setError(caught instanceof Error ? caught.message : "تاریخچه خوانده نشد.");
      });
    return () => {
      alive = false;
    };
  }, [workspaceId, file.id, file.current_version_id]);

  async function restore(versionId: string) {
    setBusy(true);
    setError(null);
    try {
      await restoreVersion(workspaceId, file.id, versionId);
      await onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "بازگشت انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card stack">
      <div className="section-head">
        <h2>تاریخچه</h2>
      </div>
      <p className="muted">بازگشت، نشانگر نسخه جاری را عوض می‌کند. نسخه‌های میانی حذف نمی‌شوند.</p>
      {error ? (
        <p className="alert" role="alert">
          {error}
        </p>
      ) : null}
      <ul className="history-list">
        {versions.map((version) => (
          <li key={version.id} className="history-row" data-current={version.current ? "true" : "false"}>
            <span>
              <strong>{version.note || "نسخه"}</strong>
              <span className="muted"> {formatDate(version.created_at)}</span>
              <span className="muted">
                {" "}
                <bdi dir="ltr">{version.sha256.slice(0, 12)}</bdi>
              </span>
            </span>
            {version.current ? (
              <span className="pill">جاری</span>
            ) : (
              <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => void restore(version.id)}>
                بازگشت
              </button>
            )}
          </li>
        ))}
      </ul>
    </article>
  );
}
