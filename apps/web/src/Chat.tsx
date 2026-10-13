import { useState, type FormEvent } from "react";
import {
  ApiError,
  cancelOperation,
  confirmOperation,
  createOperation,
  downloadVersion,
  waitForOperation,
  type Operation,
  type StoredFile,
} from "./api";
import { operationLooksSuccessful } from "./format";
import { QUICK_ACTIONS, type QuickAction } from "./quick";

type Turn = {
  key: string;
  role: "user" | "result";
  text: string;
  operation: Operation | null;
  error: string | null;
};

type Props = {
  workspaceId: string;
  files: StoredFile[];
  selectedId: string | null;
  onChanged: () => Promise<void> | void;
};

export function Chat({ workspaceId, files, selectedId, onChanged }: Props) {
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [picks, setPicks] = useState<Record<string, string[]>>({});

  function idsFor(action: QuickAction): string[] {
    if (action.files === "pair") {
      return files.length === 2 ? files.map((file) => file.id) : [];
    }
    return selectedId ? [selectedId] : [];
  }

  function idsForText(text: string): string[] {
    const normal = text.replace(/\u200c/g, "");
    if (normal.includes("تطبیق") || normal.includes("مغایرت")) {
      return files.length === 2 ? files.map((file) => file.id) : [];
    }
    return selectedId ? [selectedId] : [];
  }

  function replace(key: string, operation: Operation | null, error: string | null) {
    setTurns((current) =>
      current.map((turn) => (turn.key === key ? { ...turn, operation, error, text: turn.text } : turn)),
    );
  }

  async function run(text: string, fileIds: string[]) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    const resultKey = crypto.randomUUID();
    setTurns((current) => [
      ...current,
      { key: crypto.randomUUID(), role: "user", text: trimmed, operation: null, error: null },
      { key: resultKey, role: "result", text: "در حال اجرا", operation: null, error: null },
    ]);
    setDraft("");
    setBusy(true);
    try {
      const created = await createOperation(workspaceId, trimmed, fileIds);
      const operation = await waitForOperation(workspaceId, created, (next) => replace(resultKey, next, null));
      replace(resultKey, operation, null);
      if (operationLooksSuccessful(operation.status) && operation.error == null) {
        await onChanged();
      }
    } catch (caught) {
      const message =
        caught instanceof ApiError
          ? caught.message
          : "ارتباط با سرور برقرار نشد. اتصال را بررسی کنید و دوباره تلاش کنید.";
      replace(resultKey, null, message);
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    await run(draft, idsForText(draft));
  }

  async function confirm(turn: Turn, column: string | null, keyColumns: string[]) {
    if (!turn.operation) return;
    setBusy(true);
    try {
      const created = await confirmOperation(workspaceId, turn.operation.id, {
        key_columns: keyColumns,
        column,
      });
      const operation = await waitForOperation(workspaceId, created, (next) => replace(turn.key, next, null));
      replace(turn.key, operation, null);
      if (operationLooksSuccessful(operation.status) && operation.error == null) {
        await onChanged();
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "تأیید انجام نشد.";
      replace(turn.key, null, message);
    } finally {
      setBusy(false);
    }
  }

  async function cancel(turn: Turn) {
    if (!turn.operation) return;
    setBusy(true);
    try {
      const operation = await cancelOperation(workspaceId, turn.operation.id);
      replace(turn.key, operation, null);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "لغو انجام نشد.";
      replace(turn.key, null, message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card stack">
      <div className="section-head">
        <h2>گفتگو</h2>
      </div>
      <div className="quick-actions">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.label}
            className="btn btn-secondary"
            type="button"
            disabled={busy}
            onClick={() => void run(action.text, idsFor(action))}
          >
            {action.label}
          </button>
        ))}
      </div>
      {turns.length > 0 ? (
        <div className="chat-log">
          {turns.map((turn) =>
            turn.role === "user" ? (
              <p key={turn.key} className="chat-bubble is-user">
                {turn.text}
              </p>
            ) : (
              <Result
                key={turn.key}
                turn={turn}
                workspaceId={workspaceId}
                busy={busy}
                picked={picks[turn.key] ?? []}
                onPick={(next) => setPicks((current) => ({ ...current, [turn.key]: next }))}
                onConfirm={(column, keys) => void confirm(turn, column, keys)}
                onCancel={() => void cancel(turn)}
              />
            ),
          )}
        </div>
      ) : (
        <p className="empty">یک جمله بنویسید یا یکی از کارهای آماده را بزنید.</p>
      )}
      <form className="chat-form" onSubmit={(event) => void onSubmit(event)}>
        <input
          type="text"
          value={draft}
          maxLength={2000}
          autoComplete="off"
          placeholder="مثلاً فروش بیشتر از ۵۰ میلیون را پیدا کن"
          onChange={(event) => setDraft(event.target.value)}
        />
        <button className="btn btn-primary" type="submit" disabled={busy || draft.trim() === ""}>
          {busy ? "در حال اجرا" : "بفرست"}
        </button>
      </form>
    </article>
  );
}

function Result({
  turn,
  workspaceId,
  busy,
  picked,
  onPick,
  onConfirm,
  onCancel,
}: {
  turn: Turn;
  workspaceId: string;
  busy: boolean;
  picked: string[];
  onPick: (next: string[]) => void;
  onConfirm: (column: string | null, keyColumns: string[]) => void;
  onCancel: () => void;
}) {
  const operation = turn.operation;
  const ok = Boolean(operation && operationLooksSuccessful(operation.status) && operation.error == null);
  const choices = operation?.plan.ambiguities?.[0]?.choices ?? [];
  const goal = operation?.plan.goal ?? "";
  const waiting = operation?.status === "waiting_confirmation";
  const total = operation?.progress_total || 0;
  const current = operation?.progress_current || 0;

  return (
    <div className="chat-bubble" data-status={turn.error ? "error" : operation?.status || "pending"}>
      {turn.error ? (
        <p className="alert" role="alert">
          {turn.error}
        </p>
      ) : null}
      {operation && ok ? (
        <p className="alert alert-success" role="status">
          {operation.summary}
        </p>
      ) : null}
      {operation && !ok && !turn.error ? (
        <p className={operation.status === "failed" ? "alert" : "muted"} role={operation.status === "failed" ? "alert" : "status"}>
          {operation.status === "failed" ? operation.error?.message : operation.summary || operation.progress_label}
        </p>
      ) : null}
      {!operation && !turn.error ? <p role="status">{turn.text}</p> : null}
      {operation?.status === "running" ? (
        <div className="progress-row">
          <progress className="chat-progress" value={current} max={total || 1} />
          <button className="btn btn-secondary" type="button" disabled={busy} onClick={onCancel}>
            لغو
          </button>
        </div>
      ) : null}
      {ok && operation?.cards?.length ? (
        <ul className="metric-cards">
          {operation.cards.map((card) => (
            <li key={card.name} className="metric-card">
              <span>
                {card.label}
                {card.hypothesis ? <span className="pill pill-hypothesis">احتمال</span> : null}
              </span>
              <strong>{/^[0-9.+-]+$/.test(card.value) ? <bdi>{card.value}</bdi> : card.value}</strong>
              {card.unit ? <span className="muted">{card.unit}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {operation?.warnings?.map((warning) => (
        <p key={warning} className="muted">
          {warning}
        </p>
      ))}
      {waiting && choices.length > 0 ? (
        <fieldset className="choices">
          <legend>{goal === "reconcile" ? "ستون کلید" : operation?.summary || "انتخاب"}</legend>
          {choices.map((choice) => (
            <label key={choice}>
              <input
                type="checkbox"
                checked={picked.includes(choice)}
                onChange={() =>
                  onPick(picked.includes(choice) ? picked.filter((item) => item !== choice) : [...picked, choice])
                }
              />
              <bdi>{choice}</bdi>
            </label>
          ))}
          <button
            className="btn btn-primary"
            type="button"
            disabled={busy || picked.length === 0 || (goal !== "reconcile" && picked.length !== 1)}
            onClick={() => onConfirm(goal === "reconcile" ? null : picked[0], goal === "reconcile" ? picked : [])}
          >
            تأیید
          </button>
        </fieldset>
      ) : null}
      {waiting && goal === "clean" && choices.length === 0 ? (
        <button className="btn btn-primary" type="button" disabled={busy} onClick={() => onConfirm(null, [])}>
          تأیید پاک‌سازی
        </button>
      ) : null}
      {ok
        ? operation?.outputs.map((output) => (
            <button
              key={output.version_id}
              className="btn btn-secondary"
              type="button"
              onClick={() => void downloadVersion(workspaceId, output.version_id, output.name)}
            >
              دریافت <bdi>{output.name}</bdi>
            </button>
          ))
        : null}
    </div>
  );
}
