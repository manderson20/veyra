"use client";

import { useState } from "react";
import { ApiError, errorMessage } from "@/lib/api";

/** Maps an API error into a general message plus per-field messages. */
export function useFormErrors() {
  const [message, setMessage] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  return {
    message,
    fields,
    clear: () => {
      setMessage(null);
      setFields({});
    },
    set: (err: unknown) => {
      if (err instanceof ApiError) {
        setFields(err.fieldErrors());
        setMessage(err.detail || err.title);
      } else {
        setFields({});
        setMessage(errorMessage(err));
      }
    },
  };
}
