// SPDX-License-Identifier: AGPL-3.0-or-later
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  ...nextCoreWebVitals,
  ...nextTypescript,
  { ignores: [".next/**", "out/**", "node_modules/**", "next-env.d.ts"] },
];

export default config;
