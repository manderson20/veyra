// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import type { ReactNode } from "react";
import { Button } from "./Button";
import { EmptyState, ErrorState, Skeleton } from "./Feedback";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  width?: string;
  className?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  onRowClick?: (row: T) => void;
  rowLabel?: (row: T) => string;
  empty?: ReactNode;
  caption?: string;
  pagination?: ReactNode;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  error,
  onRetry,
  onRowClick,
  rowLabel,
  empty,
  caption,
  pagination,
}: DataTableProps<T>) {
  if (error) return <ErrorState error={error} onRetry={onRetry} compact title="Could not load data" />;
  const showSkeleton = loading && !rows;
  if (!showSkeleton && rows && rows.length === 0) {
    return <>{empty ?? <EmptyState title="Nothing here yet" compact />}</>;
  }
  return (
    <>
      <div className="table-wrap">
        <table className="table">
          {caption ? <caption className="sr-only">{caption}</caption> : null}
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} scope="col" style={c.width ? { width: c.width } : undefined}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody aria-busy={loading || undefined}>
            {showSkeleton
              ? Array.from({ length: 5 }, (_, i) => (
                  <tr key={`s${i}`}>
                    {columns.map((c) => (
                      <td key={c.key}><Skeleton width={`${50 + ((i * 17 + c.key.length * 7) % 40)}%`} /></td>
                    ))}
                  </tr>
                ))
              : rows?.map((row) => (
                  <tr
                    key={rowKey(row)}
                    className={onRowClick ? "is-clickable" : undefined}
                    tabIndex={onRowClick ? 0 : undefined}
                    aria-label={onRowClick && rowLabel ? rowLabel(row) : undefined}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    onKeyDown={
                      onRowClick
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              onRowClick(row);
                            }
                          }
                        : undefined
                    }
                  >
                    {columns.map((c) => (
                      <td key={c.key} className={c.className}>{c.render(row)}</td>
                    ))}
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
      {pagination}
    </>
  );
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit && offset === 0) {
    return (
      <div className="pagination">
        <span>{total} {total === 1 ? "item" : "items"}</span>
      </div>
    );
  }
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav className="pagination" aria-label="Pagination">
      <span>
        Showing {from}–{to} of {total}
      </span>
      <div className="pagination__controls">
        <Button size="sm" icon="chevronLeft" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          Previous
        </Button>
        <Button size="sm" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
          Next
        </Button>
      </div>
    </nav>
  );
}
