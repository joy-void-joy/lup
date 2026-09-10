import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { embedded } from "./api";

export function Layout({ children }: { children: ReactNode }) {
  const held = embedded();
  return (
    <div className="shell">
      <header className="masthead">
        <Link to="/" className="brand">
          Ledger explorer
        </Link>
        {held !== null && (
          <span className="stamp" title="This page shows the log as it was at this moment">
            exported {held.exported_at}
          </span>
        )}
      </header>
      {children}
    </div>
  );
}
