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
