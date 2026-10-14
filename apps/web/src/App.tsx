import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  createWorkspace,
  downloadVersion,
  getWorkspace,
  inspectFile,
  listFiles,
  uploadFiles,
  type RejectedFile,
  type StoredFile,
  type StructureReport,
  type Workspace,
} from "./api";
import { formatDate, formatLabel, formatSize, savedMessage, statusLabel } from "./format";
import { Chat } from "./Chat";
import { History } from "./History";
import { Cleaning } from "./Cleaning";
import { Inspection } from "./Inspection";
import { Reconcile } from "./Reconcile";

const WORKSPACE_KEY = "hesabdar.workspaceId";

export function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [pending, setPending] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [rejections, setRejections] = useState<RejectedFile[]>([]);
  const [reports, setReports] = useState<Record<string, StructureReport>>({});
  const [inspectErrors, setInspectErrors] = useState<Record<string, string>>({});
  const [inspectingId, setInspectingId] = useState<string | null>(null);
  const inspectToken = useRef(0);

  useEffect(() => {
    const saved = localStorage.getItem(WORKSPACE_KEY);
    if (!saved) {
      setLoading(false);
      return;
    }
    void openWorkspace(saved);
  }, []);

  const selectedVersion = files.find((file) => file.id === selectedId)?.current_version_id ?? null;

  useEffect(() => {
    if (!workspace || !selectedId || !selectedVersion) return;
    if (inspectingId === selectedId) return;
    if (reports[selectedId]?.version_id === selectedVersion) return;
    if (!reports[selectedId] && inspectErrors[selectedId]) return;
    void runInspect(workspace.id, selectedId);
  }, [workspace, selectedId, selectedVersion, reports, inspectErrors, inspectingId]);

  async function openWorkspace(id: string) {
    setLoading(true);
    setError(null);
    try {
      const found = await getWorkspace(id);
      const listed = await listFiles(id);
      setWorkspace(found);
      setFiles(listed);
      setSelectedId(listed[0]?.id ?? null);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "workspace.not_found") {
        localStorage.removeItem(WORKSPACE_KEY);
        setWorkspace(null);
      } else {
        setError(caught instanceof Error ? caught.message : "فضای کار باز نشد.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    const nextTitle = title.trim();
    if (!nextTitle) {
      setError("نام فضای کار را وارد کنید.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const created = await createWorkspace(nextTitle);
      localStorage.setItem(WORKSPACE_KEY, created.id);
      setWorkspace(created);
      setFiles([]);
      setSelectedId(null);
      setTitle("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "فضای کار ساخته نشد.");
    } finally {
      setCreating(false);
    }
  }

  function startFresh() {
    inspectToken.current += 1;
    localStorage.removeItem(WORKSPACE_KEY);
    setWorkspace(null);
    setFiles([]);
    setSelectedId(null);
    setSuccess(null);
    setRejections([]);
    setError(null);
    setPending([]);
    setReports({});
    setInspectErrors({});
    setInspectingId(null);
  }

  async function runInspect(workspaceId: string, fileId: string) {
    const token = inspectToken.current + 1;
    inspectToken.current = token;
    setInspectingId(fileId);
    setInspectErrors((current) => {
      if (!current[fileId]) return current;
      const next = { ...current };
      delete next[fileId];
      return next;
    });
    try {
      const report = await inspectFile(workspaceId, fileId);
      if (token !== inspectToken.current) return;
      setReports((current) => ({ ...current, [fileId]: report }));
    } catch (caught) {
      if (token !== inspectToken.current) return;
      const message = caught instanceof Error ? caught.message : "بررسی ساختار انجام نشد.";
      setInspectErrors((current) => ({ ...current, [fileId]: message }));
    } finally {
      if (token === inspectToken.current) setInspectingId(null);
    }
  }

  async function send(list: File[]) {
    if (!workspace || list.length === 0) return;
    setUploading(true);
    setSuccess(null);
    setError(null);
    setRejections([]);
    setPending(list);
    try {
      const result = await uploadFiles(workspace.id, list);
      const listed = await listFiles(workspace.id);
      setFiles(listed);
      if (result.accepted[0]) {
        setSelectedId(result.accepted[0].id);
      }
      setRejections(result.rejected);
      if (result.accepted.length > 0) {
        setSuccess(savedMessage(result.accepted.length));
        setPending([]);
      }
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
        setRejections(caught.rejected);
      } else {
        setError("ارتباط با سرور برقرار نشد. اتصال را بررسی کنید و دوباره تلاش کنید.");
      }
    } finally {
      setUploading(false);
      setFilesOpen(false);
    }
  }

  async function receive(file: StoredFile) {
    if (!workspace) return;
    setDownloading(true);
    setError(null);
    setSuccess(null);
    try {
      await downloadVersion(workspace.id, file.current_version_id, file.original_name);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "دریافت فایل انجام نشد.");
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return (
      <main className="gate">
        <p>در حال باز کردن فضای کار…</p>
      </main>
    );
  }

  if (!workspace) {
    return (
      <main className="gate">
        <form className="gate-card" onSubmit={onCreate}>
          <div className="brand-row">
            <span className="brand-mark" aria-hidden="true">
              ح
            </span>
            <h1>حسابدار</h1>
          </div>
          <p className="lede">فضای کار فایل‌های جدولی. فایل را وارد کنید؛ نسخه اصلی می‌ماند و ساختار همان فایل خوانده می‌شود.</p>
          {error ? (
            <p className="alert" role="alert">
              {error}
            </p>
          ) : null}
          <label className="field">
            <span>نام فضای کار</span>
            <input
              type="text"
              value={title}
              maxLength={120}
              autoComplete="off"
              placeholder="مثلاً فروش مهر"
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <button className="btn btn-primary" type="submit" disabled={creating}>
            {creating ? "در حال ساخت…" : "ساخت فضای کار"}
          </button>
        </form>
      </main>
    );
  }

  const selected = files.find((file) => file.id === selectedId) ?? null;

  return (
    <>
      <header className="topbar">
        <div className="brand-row">
          <span className="brand-mark" aria-hidden="true">
            ح
          </span>
          <div>
            <h1>حسابدار</h1>
            <p>فضای کار فایل</p>
          </div>
        </div>
        <div className="topbar-actions">
          <span className="workspace-title">{workspace.title}</span>
          <button className="btn btn-secondary files-toggle" type="button" onClick={() => setFilesOpen((open) => !open)}>
            فایل‌ها
          </button>
          <button className="btn btn-secondary" type="button" onClick={startFresh}>
            فضای کار جدید
          </button>
        </div>
      </header>
      <div className="workspace">
        <aside className={filesOpen ? "files is-open" : "files"}>
          <h2>فایل‌ها</h2>
          <label
            className={dragging || uploading ? "dropzone is-dragging" : "dropzone"}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              void send(Array.from(event.dataTransfer.files));
            }}
          >
            <input
              type="file"
              multiple
              accept=".xlsx,.xls,.csv,application/vnd.ms-excel,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              disabled={uploading}
              onChange={(event) => {
                const chosen = Array.from(event.target.files ?? []);
                event.target.value = "";
                void send(chosen);
              }}
            />
            <strong>{uploading ? "در حال ذخیره…" : "فایل‌ها را اینجا رها کنید یا برای انتخاب کلیک کنید."}</strong>
            <span className="muted">xlsx، xls و csv. چند فایل با هم ممکن است.</span>
          </label>
          {pending.length > 0 && error ? (
            <button className="btn btn-secondary" type="button" onClick={() => void send(pending)}>
              تلاش دوباره
            </button>
          ) : null}
          {files.length === 0 ? (
            <p className="empty">هنوز فایلی بارگذاری نشده است.</p>
          ) : (
            <ul className="file-list">
              {files.map((file) => (
                <li key={file.id}>
                  <button
                    type="button"
                    className={file.id === selectedId ? "file-row is-selected" : "file-row"}
                    onClick={() => {
                      setSelectedId(file.id);
                      setFilesOpen(false);
                    }}
                  >
                    <span className="file-name" title={file.original_name}>
                      <bdi>{file.original_name}</bdi>
                    </span>
                    <span className="file-meta">
                      <span>{formatLabel(file.format)}</span>
                      <span>{formatSize(file.byte_size)}</span>
                      <span>{statusLabel(file.status)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>
        <main className="detail">
          <div className="detail-inner stack">
            {success ? (
              <p className="alert alert-success" role="status">
                {success}
              </p>
            ) : null}
            {error ? (
              <p className="alert" role="alert">
                {error}
              </p>
            ) : null}
            {rejections.length > 0 ? (
              <div className="alert" role="alert">
                <p>این فایل‌ها ذخیره نشدند.</p>
                <ul>
                  {rejections.map((item) => (
                    <li key={`${item.filename}-${item.code}`}>
                      {item.filename}: {item.message}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {selected ? (
              <article className="card">
                <h2>جزئیات فایل</h2>
                <dl className="meta">
                  <dt>نام</dt>
                  <dd>
                    <bdi>{selected.original_name}</bdi>
                  </dd>
                  <dt>قالب</dt>
                  <dd>{formatLabel(selected.format)}</dd>
                  <dt>حجم</dt>
                  <dd>{formatSize(selected.byte_size)}</dd>
                  <dt>وضعیت</dt>
                  <dd>
                    <span className="pill">{statusLabel(selected.status)}</span>
                  </dd>
                  <dt>زمان ذخیره</dt>
                  <dd>{formatDate(selected.created_at)}</dd>
                </dl>
                <p className="muted">این نسخه، همان فایل بارگذاری‌شده است و جایگزین نمی‌شود.</p>
                <div className="detail-actions">
                  <button
                    className="btn btn-primary"
                    type="button"
                    disabled={downloading}
                    onClick={() => void receive(selected)}
                  >
                    {downloading ? "در حال دریافت…" : "دریافت فایل"}
                  </button>
                </div>
              </article>
            ) : (
              <article className="card">
                <h2>جزئیات فایل</h2>
                <p className="empty">
                  {files.length === 0
                    ? "فایل اکسل یا CSV را وارد کنید. فایل اصلی همان‌طور که هست ذخیره می‌شود."
                    : "برای دیدن جزئیات، یک فایل را از فهرست انتخاب کنید."}
                </p>
                {files.length === 0 ? (
                  <button className="btn btn-primary files-toggle" type="button" onClick={() => setFilesOpen(true)}>
                    بارگذاری فایل
                  </button>
                ) : null}
              </article>
            )}
            {workspace ? (
              <Chat
                workspaceId={workspace.id}
                files={files}
                selectedId={selectedId}
                onChanged={async () => {
                  const listed = await listFiles(workspace.id);
                  setFiles(listed);
                }}
              />
            ) : null}
            {selected && workspace ? (
              <History
                key={`${selected.id}:${selected.current_version_id}`}
                workspaceId={workspace.id}
                file={selected}
                onChanged={async () => {
                  const listed = await listFiles(workspace.id);
                  setFiles(listed);
                  setReports((current) => {
                    const next = { ...current };
                    delete next[selected.id];
                    return next;
                  });
                  setInspectErrors((current) => {
                    const next = { ...current };
                    delete next[selected.id];
                    return next;
                  });
                }}
              />
            ) : null}
            {selected && workspace ? (
              <Inspection
                report={reports[selected.id] ?? null}
                loading={inspectingId === selected.id}
                error={inspectErrors[selected.id] ?? null}
                onInspect={() => void runInspect(workspace.id, selected.id)}
              />
            ) : null}
            {selected && workspace ? (
              <Cleaning
                key={selected.id}
                workspaceId={workspace.id}
                file={selected}
                onChanged={async () => {
                  const listed = await listFiles(workspace.id);
                  setFiles(listed);
                }}
              />
            ) : null}
            {workspace && files.length >= 2 ? (
              <Reconcile
                workspaceId={workspace.id}
                files={files}
                onChanged={async () => {
                  const listed = await listFiles(workspace.id);
                  setFiles(listed);
                }}
              />
            ) : null}
          </div>
        </main>
      </div>
    </>
  );
}
