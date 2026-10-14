// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Callout,
  Card,
  Checkbox,
  ConfirmDialog,
  DataTable,
  Dialog,
  EmptyState,
  ErrorState,
  IconButton,
  LoadingState,
  PageHeader,
  Pagination,
  SelectField,
  TextArea,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { ApiError, createApi, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { Page, UiExtension, UiFormField, UiView } from "@/lib/types";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";
import { useApiData } from "@/hooks/useApiData";

const LIMIT = 25;
type Row = Record<string, unknown> & { id?: string };

/** Module API calls are relative to the module's api_base (e.g. /api/v1/ext/example-notes). */
function moduleApi(apiBase: string) {
  const base = createApi();
  const rel = apiBase.replace(/^\/api\/v1/, "");
  return {
    path: (p: string) => `${rel}/${p}`,
    post: <T,>(p: string, body: unknown) => base.post<T>(`${rel}/${p}`, body),
    del: <T,>(p: string) => base.del<T>(`${rel}/${p}`),
  };
}

function renderCell(value: unknown, format: string) {
  if (value === null || value === undefined || value === "") return <span className="subtle">—</span>;
  if (format === "datetime") return <span className="nowrap">{formatDateTime(String(value))}</span>;
  if (format === "boolean") return <Badge tone={value ? "ok" : "neutral"}>{value ? "Yes" : "No"}</Badge>;
  if (format === "status") return <Badge>{String(value)}</Badge>;
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return <span style={{ display: "block", maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis" }}>{text}</span>;
}

function ResourceTable({ ext, view }: { ext: UiExtension; view: UiView }) {
  const { can } = useSession();
  const toast = useToast();
  const api = useMemo(() => moduleApi(ext.api_base ?? ""), [ext.api_base]);
  const [offset, setOffset] = useState(0);
  const list = useApiData<Page<Row>>(api.path(view.endpoint), { limit: LIMIT, offset });
  const [createOpen, setCreateOpen] = useState(false);
  const [deleting, setDeleting] = useState<Row | null>(null);
  const [delBusy, setDelBusy] = useState(false);
  const [delError, setDelError] = useState<string | null>(null);
  const canWrite = view.write_permission ? can(view.write_permission) : false;

  const columns: Column<Row>[] = view.columns.map((c) => ({ key: c.key, header: c.label, render: (r) => renderCell(r[c.key], c.format) }));
  if (view.delete && canWrite) {
    columns.push({
      key: "_actions",
      header: <span className="sr-only">Actions</span>,
      width: "64px",
      render: (r) => (r.id ? <IconButton icon="trash" size="sm" label="Delete" onClick={() => setDeleting(r)} /> : null),
    });
  }

  const doDelete = async () => {
    if (!deleting?.id) return;
    setDelBusy(true);
    setDelError(null);
    try {
      await api.del(`${view.endpoint}/${encodeURIComponent(String(deleting.id))}`);
      toast.success("Deleted");
      setDeleting(null);
      list.reload();
    } catch (err) {
      setDelError(errorMessage(err));
    } finally {
      setDelBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        title={view.title}
        description={view.description ?? undefined}
        actions={view.create_form.length > 0 && canWrite ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>Add</Button> : null}
      />
      <Card flush>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(r) => String(r.id ?? JSON.stringify(r))}
          loading={list.loading}
          error={list.error}
          onRetry={() => list.reload()}
          caption={view.title}
          empty={<EmptyState icon="note" title={view.empty_title}>{view.empty_body}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <p className="subtle">Provided by the {ext.module_name} module.</p>
      <CreateDialog open={createOpen} onClose={() => setCreateOpen(false)} fields={view.create_form} title={`Add to ${view.title}`}
        submit={(body) => api.post(view.endpoint, body)} onCreated={() => { toast.success("Saved"); setOffset(0); list.reload(); }} />
      <ConfirmDialog open={deleting !== null} title="Delete this item?" confirmLabel="Delete" tone="danger" busy={delBusy} error={delError}
        onConfirm={doDelete} onCancel={() => { setDeleting(null); setDelError(null); }}>
        <p>This cannot be undone.</p>
      </ConfirmDialog>
    </div>
  );
}

function CreateDialog({ open, onClose, fields, title, submit, onCreated }: {
  open: boolean; onClose: () => void; fields: UiFormField[]; title: string;
  submit: (body: Record<string, unknown>) => Promise<unknown>; onCreated: () => void;
}) {
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useOnChange(open, () => {
    if (open) {
      setValues(Object.fromEntries(fields.map((f) => [f.key, f.type === "boolean" ? false : ""])));
      setMessage(null);
      setFieldErrors({});
    }
  });

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    const body: Record<string, unknown> = {};
    for (const f of fields) {
      const v = values[f.key];
      if (f.type === "integer") body[f.key] = v === "" ? null : Number(v);
      else body[f.key] = v;
    }
    try {
      await submit(body);
      onClose();
      onCreated();
    } catch (err) {
      setFieldErrors(err instanceof ApiError ? err.fieldErrors() : {});
      setMessage(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const set = (k: string, v: string | boolean) => setValues((s) => ({ ...s, [k]: v }));
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={title}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="module-create" loading={busy}>Save</Button></>}>
      <form id="module-create" className="stack stack--sm" onSubmit={onSubmit}>
        {fields.map((f, i) => {
          const common = { label: f.label, required: f.required, help: f.help ?? undefined, error: fieldErrors[f.key], autoFocus: i === 0 };
          if (f.type === "textarea") return <TextArea key={f.key} {...common} maxLength={f.max_length ?? undefined} value={String(values[f.key] ?? "")} onChange={(e) => set(f.key, e.target.value)} />;
          if (f.type === "boolean") return <Checkbox key={f.key} label={f.label} description={f.help ?? undefined} checked={Boolean(values[f.key])} onChange={(e) => set(f.key, e.target.checked)} />;
          if (f.type === "choice") return <SelectField key={f.key} {...common} value={String(values[f.key] ?? "")} placeholder="Choose…" options={(f.choices ?? []).map((c) => ({ value: c, label: c }))} onChange={(e) => set(f.key, e.target.value)} />;
          return <TextField key={f.key} {...common} type={f.type === "integer" ? "number" : f.type === "password" ? "password" : "text"} autoComplete={f.type === "password" ? "new-password" : undefined} maxLength={f.max_length ?? undefined} value={String(values[f.key] ?? "")} onChange={(e) => set(f.key, e.target.value)} />;
        })}
        {message ? <Callout tone="danger">{message}</Callout> : null}
      </form>
    </Dialog>
  );
}

function ModuleView() {
  const params = useSearchParams();
  const { extensions, loading } = useSession();
  const moduleId = params.get("module");
  const viewId = params.get("view");
  if (loading) return <LoadingState />;
  const ext = extensions.find((e) => e.module_id === moduleId);
  const view = ext?.views.find((v) => v.id === viewId);
  if (!ext || !view || !ext.api_base) {
    return (
      <Card>
        <EmptyState icon="puzzle" title="This module page is not available">
          The module may be disabled, or you may not have permission to use it.
        </EmptyState>
      </Card>
    );
  }
  if (view.type !== "resource_table") return <ErrorState title="Unsupported view" error={{ message: `View type ${view.type} is not supported.` }} />;
  return <ResourceTable key={`${ext.module_id}/${view.id}`} ext={ext} view={view} />;
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><ModuleView /></Suspense>;
}
