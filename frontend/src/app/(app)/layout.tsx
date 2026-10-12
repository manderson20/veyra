import { Suspense, type ReactNode } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { LoadingState } from "@/components/ui";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<div className="fullscreen-center"><LoadingState label="Loading Veyra…" /></div>}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
