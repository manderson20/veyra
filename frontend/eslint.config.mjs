// SPDX-License-Identifier: AGPL-3.0-or-later
// The rule set eslint-config-next (core-web-vitals + typescript) composes,
// written out so the Next.js lint plugin itself is not a dependency: it
// pins fast-glob 3.3.1, which pulls braces, for which the stack-exhaustion
// advisory GHSA-vfj7-8cjw-p6xm has no fixed release (SECURITY.md). The
// @next/next rules it added guard pages-router and next/image patterns this
// static export does not use.
import jsxA11y from "eslint-plugin-jsx-a11y";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

const config = [
  {
    name: "veyra/react",
    files: ["**/*.{js,jsx,mjs,ts,tsx,mts,cts}"],
    plugins: { react, "react-hooks": reactHooks, "jsx-a11y": jsxA11y },
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: { sourceType: "module" },
      globals: { ...globals.browser, ...globals.node },
    },
    // Pinned: "detect" calls context.getFilename(), which ESLint 10 removed.
    settings: { react: { version: "19.3" } },
    rules: {
      ...react.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      "react/no-unknown-property": "off",
      "react/react-in-jsx-scope": "off",
      "react/prop-types": "off",
      "jsx-a11y/alt-text": ["warn", { elements: ["img"], img: ["Image"] }],
      "jsx-a11y/aria-props": "warn",
      "jsx-a11y/aria-proptypes": "warn",
      "jsx-a11y/aria-unsupported-elements": "warn",
      "jsx-a11y/role-has-required-aria-props": "warn",
      "jsx-a11y/role-supports-aria-props": "warn",
      "react/jsx-no-target-blank": "off",
    },
  },
  ...tseslint.configs.recommended,
  {
    name: "veyra/typescript",
    rules: {
      "@typescript-eslint/no-unused-vars": "warn",
      "@typescript-eslint/no-unused-expressions": "warn",
    },
  },
  { ignores: [".next/**", "out/**", "build/**", "node_modules/**", "next-env.d.ts"] },
];

export default config;
