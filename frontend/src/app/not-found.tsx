// SPDX-License-Identifier: AGPL-3.0-or-later
import Link from "next/link";
import { EmptyState } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="fullscreen-center">
      <EmptyState icon="search" title="Page not found" action={<Link className="btn btn--primary" href="/">Go to the dashboard</Link>}>
        The page you are looking for does not exist or has moved.
      </EmptyState>
    </div>
  );
}
