"use client";

import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { Icon } from "./Icon";

interface FieldShellProps {
  id: string;
  label: ReactNode;
  help?: ReactNode;
  error?: string | null;
  required?: boolean;
  children: ReactNode;
}

function FieldShell({ id, label, help, error, required, children }: FieldShellProps) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
        {required ? <span className="field__required" aria-hidden="true">*</span> : null}
      </label>
      {children}
      {help ? <p className="field__help" id={`${id}-help`}>{help}</p> : null}
      {error ? (
        <p className="field__error" id={`${id}-error`} role="alert">
          <Icon name="error" size={14} /> {error}
        </p>
      ) : null}
    </div>
  );
}

function describedBy(id: string, help?: ReactNode, error?: string | null) {
  return [help && `${id}-help`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
}

type Common = { label: ReactNode; help?: ReactNode; error?: string | null };

export function TextField({ label, help, error, id, required, ...rest }: Common & InputHTMLAttributes<HTMLInputElement>) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell id={fid} label={label} help={help} error={error} required={required}>
      <input
        id={fid}
        className="input"
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, help, error)}
        {...rest}
      />
    </FieldShell>
  );
}

export function TextArea({ label, help, error, id, required, ...rest }: Common & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell id={fid} label={label} help={help} error={error} required={required}>
      <textarea
        id={fid}
        className="textarea"
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, help, error)}
        {...rest}
      />
    </FieldShell>
  );
}

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export function SelectField({
  label,
  help,
  error,
  id,
  required,
  options,
  placeholder,
  ...rest
}: Common & SelectHTMLAttributes<HTMLSelectElement> & { options: SelectOption[]; placeholder?: string }) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell id={fid} label={label} help={help} error={error} required={required}>
      <select
        id={fid}
        className="select"
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, help, error)}
        {...rest}
      >
        {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

export function Checkbox({
  label,
  description,
  ...rest
}: { label: ReactNode; description?: ReactNode } & Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  return (
    <label className="check">
      <input type="checkbox" {...rest} />
      <span className="check__text">
        <span>{label}</span>
        {description ? <span className="subtle">{description}</span> : null}
      </span>
    </label>
  );
}

export function Switch({
  label,
  description,
  ...rest
}: { label: ReactNode; description?: ReactNode } & Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" {...rest} />
      <span className="check__text">
        <span>{label}</span>
        {description ? <span className="subtle">{description}</span> : null}
      </span>
    </label>
  );
}
