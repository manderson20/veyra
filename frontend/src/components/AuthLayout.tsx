import type { ReactNode } from "react";
import { BrandLogo } from "./Brand";

export function AuthLayout({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="auth">
      <aside className="auth__aside" aria-hidden="true">
        <BrandLogo onDark height={34} />
        <div>
          <h2>Open Communications Platform</h2>
          <p>Self-hosted, modular telephony management for schools, governments and businesses.</p>
        </div>
        <p style={{ fontSize: 12, color: "#8a9bb3" }}>Veyra</p>
      </aside>
      <main className="auth__main" id="main">
        <div className={wide ? "auth__panel auth__panel--wide" : "auth__panel"}>{children}</div>
      </main>
    </div>
  );
}
