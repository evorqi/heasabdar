export type Workspace = {
  id: string;
  title: string;
  created_at: string;
  file_count: number;
};

export type StoredFile = {
  id: string;
  workspace_id: string;
  original_name: string;
  format: string;
  media_type: string;
  byte_size: number;
  sha256: string;
  current_version_id: string;
  created_at: string;
  status: string;
};

export type RejectedFile = {
  filename: string;
  code: string;
  message: string;
};

export type UploadResult = {
  accepted: StoredFile[];
  rejected: RejectedFile[];
};

export class ApiError extends Error {
  code: string;
  rejected: RejectedFile[];

  constructor(message: string, code = "unknown", rejected: RejectedFile[] = []) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.rejected = rejected;
  }
}

async function readBody(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    const rejected = Array.isArray(body.detail?.rejected) ? body.detail.rejected : [];
    return new ApiError(body.message || "خطای ناشناخته رخ داد.", body.code || "unknown", rejected);
  } catch {
    return new ApiError("پاسخ سرور قابل‌خواندن نیست.");
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(
      "ارتباط با سرور برقرار نشد. اتصال را بررسی کنید و دوباره تلاش کنید.",
      "network",
    );
  }
  if (!response.ok) {
    throw await readBody(response);
  }
  return (await response.json()) as T;
}

export function createWorkspace(title: string): Promise<Workspace> {
  return request<Workspace>("/api/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export function getWorkspace(id: string): Promise<Workspace> {
  return request<Workspace>(`/api/workspaces/${id}`);
}

export async function listFiles(workspaceId: string): Promise<StoredFile[]> {
  const body = await request<{ files: StoredFile[] }>(`/api/workspaces/${workspaceId}/files`);
  return body.files;
}

export function uploadFiles(workspaceId: string, files: File[]): Promise<UploadResult> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file, file.name);
  }
  return request<UploadResult>(`/api/workspaces/${workspaceId}/files`, {
    method: "POST",
    body: form,
  });
}

export type InspectionCell = {
  raw: string | null;
  parsed: string | null;
  warnings: string[];
};

export type InspectionColumn = {
  name: string;
  index: number;
  kind: string;
  kind_confidence: number;
  role_hints: string[];
  empty_count: number;
  samples: string[];
};

export type InspectionSheet = {
  name: string;
  row_count: number;
  column_count: number;
  data_row_count: number;
  columns: InspectionColumn[];
  formula_count: number;
  error_display_count: number;
  merged_cell_count: number;
  unsupported: string[];
  header_row_index: number;
  header_status: string;
  preview: {
    row_limit: number;
    truncated: boolean;
    rows: InspectionCell[][];
  };
};

export type Finding = {
  code: string;
  severity: string;
  sheet: string | null;
  address: string | null;
  count: number;
  message: string;
  evidence: Record<string, unknown>;
};

export type UncheckedItem = {
  code: string;
  count: number;
  message: string;
  sheet?: string;
};

export type StructureReport = {
  file_id: string;
  version_id: string;
  format: string;
  sheet_count: number;
  sheets: InspectionSheet[];
  findings: Finding[];
  unchecked: UncheckedItem[];
};

export type CellChange = {
  sheet: string;
  row_index: number;
  column_index: number;
  before: string;
  after: string;
  rule_id: string;
};

export type SkippedCell = {
  sheet: string | null;
  row_index: number | null;
  column_index: number | null;
  rule_id: string;
  message: string;
};

export type CleaningReport = {
  status: string;
  file_id: string;
  source_version_id: string;
  result_version_id: string | null;
  message: string;
  changes: CellChange[];
  skipped: SkippedCell[];
  stats: {
    change_count: number;
    requires_confirmation: boolean;
    confirmation_reason: string | null;
    sheets: Array<{
      name: string;
      rows_before: number;
      rows_after: number;
      data_rows: number;
      changed_rows: number;
    }>;
  };
};

export function previewCleaning(workspaceId: string, fileId: string): Promise<CleaningReport> {
  return request<CleaningReport>(`/api/workspaces/${workspaceId}/cleanings/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_id: fileId }),
  });
}

export function applyCleaning(
  workspaceId: string,
  fileId: string,
  confirm: boolean,
): Promise<CleaningReport> {
  return request<CleaningReport>(`/api/workspaces/${workspaceId}/cleanings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_id: fileId, confirm }),
  });
}

export function listVersions(workspaceId: string, fileId: string): Promise<FileVersion[]> {
  return request<{ versions: FileVersion[] }>(`/api/workspaces/${workspaceId}/files/${fileId}/versions`).then(
    (body) => body.versions,
  );
}

export function restoreVersion(
  workspaceId: string,
  fileId: string,
  versionId: string,
): Promise<StoredFile> {
  return request<StoredFile>(`/api/workspaces/${workspaceId}/files/${fileId}/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version_id: versionId }),
  });
}

export type ReconcileRow = {
  status: string;
  key: string;
  key_left: string;
  key_right: string;
  confidence: string;
  name_left: string | null;
  name_right: string | null;
  amount_left: string | null;
  amount_right: string | null;
  amount_delta: string | null;
  amount_delta_ratio: string | null;
  reason: string;
};

export type ReconcileReport = {
  status: string;
  message: string;
  left_file_id: string;
  right_file_id: string;
  result_file_id: string | null;
  result_version_id: string | null;
  result_name: string | null;
  key_columns: string[];
  key_decision: string | null;
  key_ambiguous: boolean;
  key_choices: string[];
  question: string | null;
  rows: ReconcileRow[];
  summary: {
    full_match: number;
    value_mismatch: number;
    only_left: number;
    only_right: number;
    ambiguous: number;
  };
  validation: {
    ok: boolean;
    left_rows: number;
    right_rows: number;
    left_amount: string | null;
    right_amount: string | null;
  };
};

export function previewReconciliation(
  workspaceId: string,
  leftFileId: string,
  rightFileId: string,
): Promise<ReconcileReport> {
  return request<ReconcileReport>(`/api/workspaces/${workspaceId}/reconciliations/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ left_file_id: leftFileId, right_file_id: rightFileId }),
  });
}

export type ChartPoint = { category: string; value: string };

export type ChartSeries = { name: string; value_field: string; points: ChartPoint[] };

export type ChartSpec = {
  chart_type: "column" | "bar" | "line" | "pie" | "scatter" | "area" | "combo";
  title: string;
  category_field: string;
  series: ChartSeries[];
  source: string;
};

export type FileVersion = {
  id: string;
  parent_version_id: string | null;
  kind: string;
  sha256: string;
  byte_size: number;
  row_count: number | null;
  sheet_count: number | null;
  created_at: string;
  note: string | null;
  current: boolean;
};

export type OperationChange = {
  rows_before: number | null;
  columns_before: number | null;
  sheets_before: number | null;
  rows_after: number | null;
  columns_after: number | null;
  sheets_after: number | null;
  sha256_before: string | null;
  sha256_after: string | null;
};

export type OperationOutput = {
  file_id: string;
  version_id: string;
  name: string;
};

export type Operation = {
  id: string;
  status: string;
  progress_current: number;
  progress_total: number;
  progress_label: string | null;
  summary: string | null;
  warnings: string[];
  error: { code: string; message: string } | null;
  outputs: OperationOutput[];
  cards?: { name: string; label: string; value: string; unit: string; hypothesis: boolean }[];
  charts?: ChartSpec[];
  evaluation?: string | null;
  change?: OperationChange | null;
  plan: {
    id: string;
    goal: string;
    user_text: string;
    source: string;
    steps: unknown[];
    ambiguities: { code: string; question: string; choices: string[] }[];
  };
  llm_status: string;
};

async function readOperation(response: Response): Promise<Operation> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("پاسخ سرور قابل‌خواندن نیست.");
  }
  if (body && typeof body === "object" && "status" in body && "id" in body) {
    return body as Operation;
  }
  const record = body as { message?: string; code?: string };
  throw new ApiError(record.message || "خطای ناشناخته رخ داد.", record.code || "unknown");
}

async function sendOperation(path: string, init?: RequestInit): Promise<Operation> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(
      "ارتباط با سرور برقرار نشد. اتصال را بررسی کنید و دوباره تلاش کنید.",
      "network",
    );
  }
  return readOperation(response);
}

export function createOperation(
  workspaceId: string,
  text: string,
  fileIds: string[],
): Promise<Operation> {
  return sendOperation(`/api/workspaces/${workspaceId}/operations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, file_ids: fileIds }),
  });
}

export function getOperation(workspaceId: string, operationId: string): Promise<Operation> {
  return sendOperation(`/api/workspaces/${workspaceId}/operations/${operationId}`);
}

export function confirmOperation(
  workspaceId: string,
  operationId: string,
  body: { key_columns?: string[]; column?: string | null },
): Promise<Operation> {
  return sendOperation(`/api/workspaces/${workspaceId}/operations/${operationId}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      key_columns: body.key_columns ?? [],
      column: body.column ?? null,
    }),
  });
}

export function cancelOperation(workspaceId: string, operationId: string): Promise<Operation> {
  return sendOperation(`/api/workspaces/${workspaceId}/operations/${operationId}/cancel`, {
    method: "POST",
  });
}

export async function waitForOperation(
  workspaceId: string,
  operation: Operation,
  onUpdate?: (operation: Operation) => void,
): Promise<Operation> {
  let current = operation;
  for (let attempt = 0; attempt < 120 && current.status === "running"; attempt += 1) {
    onUpdate?.(current);
    await new Promise((resolve) => setTimeout(resolve, 300));
    current = await getOperation(workspaceId, current.id);
  }
  return current;
}

export function applyReconciliation(
  workspaceId: string,
  leftFileId: string,
  rightFileId: string,
  keyColumns: string[],
): Promise<ReconcileReport> {
  return request<ReconcileReport>(`/api/workspaces/${workspaceId}/reconciliations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      left_file_id: leftFileId,
      right_file_id: rightFileId,
      key_columns: keyColumns,
    }),
  });
}

export function inspectFile(workspaceId: string, fileId: string): Promise<StructureReport> {
  return request<StructureReport>(`/api/workspaces/${workspaceId}/inspections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_id: fileId }),
  });
}

export async function downloadVersion(
  workspaceId: string,
  versionId: string,
  filename: string,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/workspaces/${workspaceId}/versions/${versionId}/download`);
  } catch {
    throw new ApiError(
      "ارتباط با سرور برقرار نشد. اتصال را بررسی کنید و دوباره تلاش کنید.",
      "network",
    );
  }
  if (!response.ok) {
    throw await readBody(response);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
