"use client";

import { useState } from "react";

/**
 * Run `onChange` during render when `value` changes (React's recommended way to
 * adjust state in response to a prop change, instead of an effect).
 * See https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
 */
export function useOnChange<T>(value: T, onChange: (value: T) => void): void {
  const [prev, setPrev] = useState(value);
  if (!Object.is(prev, value)) {
    setPrev(value);
    onChange(value);
  }
}
