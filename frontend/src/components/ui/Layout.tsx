// SPDX-License-Identifier: AGPL-3.0-or-later
import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "./Icon";

export function Card({
  title,
  subtitle,
  actions,
  children,
  footer,
  flush = false,
  className,
  id,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  flush?: boolean;
  className?: string;
  id?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section className={["card", className].filter(Boolean).join(" ")} aria-labelledby={title ? headingId : undefined} id={id}>
      {title || actions ? (
        <div className="card__header">
          <div>
            {title ? <h2 className="card__title" id={headingId}>{title}</h2> : null}
            {subtitle ? <p className="card__subtitle">{subtitle}</p> : null}
          </div>
          {actions ? <div className="row">{actions}</div> : null}
        </div>
      ) : null}
      <div className={flush ? "card__body card__body--flush" : "card__body"}>{children}</div>
      {footer ? <div className="card__footer">{footer}</div> : null}
    </section>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  back,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <header className="page-header">
      <div>
        {back ? (
          <Link href={back.href} className="page-header__back">
            <Icon name="arrowLeft" size={14} /> {back.label}
          </Link>
        ) : null}
        <h1 className="page-header__title">{title}</h1>
        {description ? <p className="page-header__description">{description}</p> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}

export function FormSection({
  title,
  description,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="form-section">
      <div>
        <h3 className="form-section__title">{title}</h3>
        {description ? <p className="form-section__description">{description}</p> : null}
      </div>
      <div className="form-section__fields">{children}</div>
    </div>
  );
}
