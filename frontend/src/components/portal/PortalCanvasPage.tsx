// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useMemo, useState } from "react";
import { Canvas } from "@/components/portal/Canvas";
import { WidgetRenderer, pickInstance } from "@/components/portal/WidgetRenderer";
import { Button, Callout, Card, Dialog, EmptyState, ErrorState, LoadingState, PageHeader, SelectField, Tabs, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { MyExtension, MyVoicemail, PortalLayoutOut } from "@/lib/types";
import { addWidget, applyTemplate, idOf, newTabId, removeWidget, type Layout, type Placed } from "@/portal/layout";
import { DEFAULT_LAYOUT, WIDGETS, widgetByKey } from "@/portal/widgets";
import { useApiData } from "@/hooks/useApiData";
import { useOnChange } from "@/hooks/useOnChange";

/** My Phone as a canvas (docs/USER_PORTAL.md §10): tabs of widgets the user arranges; a template from the administrators supplies the default. */
export function PortalCanvasPage() {
  const toast = useToast();
  const exts = useApiData<MyExtension[]>("/me/extensions");
  const boxes = useApiData<MyVoicemail[]>("/me/voicemail");
  const saved = useApiData<PortalLayoutOut>("/me/portal/layout");
  const [layout, setLayout] = useState<Layout | null>(null);
  const [tab, setTab] = useState("");
  const [arranging, setArranging] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [history, setHistory] = useState<Layout[]>([]);
  const locked = useMemo(() => new Set(saved.data?.locked_widgets ?? []), [saved.data]);

  // The effective layout is derived from the server's answer once (and again
  // after a reset clears it); derived state is set during render, like the
  // other pages' useOnChange users.
  useOnChange(saved.data, (d) => {
    if (!d || layout) return;
    const base = (d.layout as Layout | null) ?? (DEFAULT_LAYOUT as Layout);
    const effective = applyTemplate(d.source === "default" ? null : base, d.source === "default" ? (DEFAULT_LAYOUT as Layout) : base, d.locked_widgets);
    setLayout(effective);
    setTab(effective.tabs[0]?.id ?? "home");
  });
  if (saved.data && !layout) {
    const d = saved.data;
    const base = (d.layout as Layout | null) ?? (DEFAULT_LAYOUT as Layout);
    const effective = applyTemplate(d.source === "default" ? null : base, d.source === "default" ? (DEFAULT_LAYOUT as Layout) : base, d.locked_widgets);
    setLayout(effective);
    setTab(effective.tabs[0]?.id ?? "home");
  }

  if (exts.error) return <ErrorState title="Could not load your phone" error={exts.error} onRetry={exts.reload} />;
  if (saved.error) return <ErrorState title="Could not load your layout" error={saved.error} onRetry={saved.reload} />;
  if (!exts.data || !layout) return <LoadingState />;
  const current = layout.tabs.find((t) => t.id === tab) ?? layout.tabs[0]!;

  const update = (widgets: Placed[]) => {
    setHistory((h) => [...h.slice(-19), layout]);
    setLayout({ ...layout, tabs: layout.tabs.map((t) => (t.id === current.id ? { ...t, widgets } : t)) });
    setDirty(true);
  };
  const undo = () => {
    const prev = history[history.length - 1];
    if (!prev) return;
    setHistory((h) => h.slice(0, -1));
    setLayout(prev);
    setDirty(true);
  };
  const save = async () => {
    setBusy(true);
    try {
      const out = await api.put<PortalLayoutOut>("/me/portal/layout", { layout });
      saved.setData(out);
      setDirty(false);
      setArranging(false);
      toast.success("Layout saved", "Your My Phone page keeps this arrangement.");
    } catch (err) {
      toast.error("Could not save the layout", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const reset = async () => {
    setBusy(true);
    try {
      const out = await api.post<PortalLayoutOut>("/me/portal/layout/reset");
      saved.setData(out);
      setLayout(null);
      setDirty(false);
      setArranging(false);
      setHistory([]);
      toast.success("Back to the default layout");
    } catch (err) {
      toast.error("Could not reset", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const addTab = () => {
    const id = newTabId(layout.tabs);
    setLayout({ ...layout, tabs: [...layout.tabs, { id, name: `Tab ${layout.tabs.length + 1}`, widgets: [] }] });
    setTab(id);
    setDirty(true);
  };
  const renameTab = (name: string) => { setLayout({ ...layout, tabs: layout.tabs.map((t) => (t.id === current.id ? { ...t, name } : t)) }); setDirty(true); };
  const removeTab = () => {
    if (layout.tabs.length <= 1) return;
    const lockedHere = current.widgets.filter((w) => locked.has(w.key));
    const rest = layout.tabs.filter((t) => t.id !== current.id);
    if (lockedHere.length && rest[0]) rest[0] = { ...rest[0], widgets: lockedHere.reduce((ws, w) => addWidget(ws, w.key, w.instance, { w: w.w, h: w.h }), rest[0].widgets) };
    setLayout({ ...layout, tabs: rest });
    setTab(rest[0]!.id);
    setDirty(true);
  };

  const extensions = exts.data;
  const boxList = boxes.data ?? [];
  if (extensions.length === 0 && boxList.length === 0) {
    return (
      <div className="stack">
        <PageHeader title="My Phone" description="Your own extensions, voicemail, contacts and colleagues." />
        <Card><EmptyState icon="phone" title="No phone is assigned to you">An administrator assigns an extension to your account under Telephony → Extensions.</EmptyState></Card>
      </div>
    );
  }
  return (
    <div className="stack">
      <PageHeader title="My Phone" description={saved.data?.template_name ? `Layout from your administrators: ${saved.data.template_name}. Arrange it as you like; your changes stay yours.` : "Your own extensions, voicemail, calls, contacts and colleagues. Arrange the page as you like."}
        actions={arranging ? (
          <div className="row">
            <Button onClick={() => setAdding(true)} icon="plus">Add widget</Button>
            <Button onClick={undo} disabled={!history.length}>Undo</Button>
            <Button onClick={reset} disabled={busy}>Reset to default</Button>
            <Button onClick={() => { setArranging(false); if (dirty) { setLayout(null); setDirty(false); setHistory([]); } }} disabled={busy}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!dirty} onClick={save}>Save layout</Button>
          </div>
        ) : <Button icon="settings" onClick={() => setArranging(true)}>Arrange</Button>} />
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <Tabs idBase="portal" active={current.id} onChange={setTab} tabs={layout.tabs.map((t) => ({ id: t.id, label: t.name }))} />
        {arranging ? (
          <span className="row">
            <TextField label={<span className="sr-only">Tab name</span>} value={current.name} maxLength={40} onChange={(e) => renameTab(e.target.value)} style={{ width: 160 }} />
            <Button size="sm" icon="plus" onClick={addTab} disabled={layout.tabs.length >= 8}>Tab</Button>
            <Button size="sm" variant="ghost" icon="trash" aria-label="Remove this tab" onClick={removeTab} disabled={layout.tabs.length <= 1} />
          </span>
        ) : null}
      </div>
      {arranging ? <Callout tone="info">Drag a widget by its title bar, resize from the corner, or use the arrows. On a phone the widgets stack in this order.</Callout> : null}
      <Canvas widgets={current.widgets} arranging={arranging} locked={locked}
        onChange={update}
        onRemove={(id) => update(removeWidget(current.widgets, id))}
        render={(p) => <WidgetRenderer placed={p} extensions={extensions} boxes={boxList} announcement={saved.data?.announcement} />} />
      <Dialog open={adding} onClose={() => setAdding(false)} title="Add a widget" size="lg">
        <AddWidget extensions={extensions} boxes={boxList} onAdd={(key, instance) => {
          const m = widgetByKey(key);
          if (!m) return;
          update(addWidget(current.widgets, key, instance, m.defaultSize));
          setAdding(false);
        }} />
      </Dialog>
    </div>
  );
}

function AddWidget({ extensions, boxes, onAdd }: { extensions: MyExtension[]; boxes: MyVoicemail[]; onAdd: (key: string, instance: string) => void }) {
  const [instances, setInstances] = useState<Record<string, string>>({});
  return (
    <ul className="list-plain">
      {WIDGETS.filter((w) => !w.lockable).map((w) => {
        const options = w.needs === "extension" ? extensions.map((x) => ({ value: x.id, label: `${x.number} ${x.display_name}` })) : w.needs === "box" ? boxes.map((b) => ({ value: b.id, label: `${b.number} ${b.name}` })) : [];
        const instance = instances[w.key] ?? options[0]?.value ?? "default";
        const unavailable = w.needs && options.length === 0;
        return (
          <li key={w.key} className="list-row" style={{ paddingLeft: 0, paddingRight: 0, alignItems: "center" }}>
            <span style={{ minWidth: 0 }}>
              <span className="table__primary">{w.title}</span>
              <span className="table__secondary" style={{ display: "block" }}>{w.description}</span>
            </span>
            <span className="row">
              {options.length > 1 ? <SelectField label={<span className="sr-only">Which</span>} value={instance} options={options} onChange={(e) => setInstances((all) => ({ ...all, [w.key]: e.target.value }))} /> : null}
              <Button size="sm" icon="plus" disabled={!!unavailable} onClick={() => onAdd(w.key, w.needs ? instance : "default")}>Add</Button>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export { idOf, pickInstance };
