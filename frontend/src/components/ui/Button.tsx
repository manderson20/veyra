// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon } from "./Icon";

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "md" | "sm";
  icon?: string;
  loading?: boolean;
  block?: boolean;
  children?: ReactNode;
}

export function buttonClass(variant: Variant = "secondary", size: "md" | "sm" = "md", block = false) {
  return ["btn", `btn--${variant}`, size === "sm" && "btn--sm", block && "btn--block"]
    .filter(Boolean)
    .join(" ");
}

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  loading = false,
  block = false,
  disabled,
  children,
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={[buttonClass(variant, size, block), className].filter(Boolean).join(" ")}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className="spinner" aria-hidden="true" /> : icon ? <Icon name={icon} size={16} /> : null}
      {children}
    </button>
  );
}

export function LinkButton({
  href,
  variant = "secondary",
  size = "md",
  icon,
  children,
}: {
  href: string;
  variant?: Variant;
  size?: "md" | "sm";
  icon?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={buttonClass(variant, size)}>
      {icon ? <Icon name={icon} size={16} /> : null}
      {children}
    </Link>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: string;
  label: string;
  size?: "md" | "sm";
}

export function IconButton({ icon, label, size = "md", className, type = "button", ...rest }: IconButtonProps) {
  return (
    <button
      type={type}
      className={["icon-btn", size === "sm" && "icon-btn--sm", className].filter(Boolean).join(" ")}
      aria-label={label}
      title={label}
      {...rest}
    >
      <Icon name={icon} size={size === "sm" ? 16 : 18} />
    </button>
  );
}
