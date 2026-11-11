// ESLint flat config: TypeScript, React hooks and accessibility (jsx-a11y) rules for the app; Node globals for
// tooling and the Playwright specs.
import js from '@eslint/js'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'playwright-report', 'test-results', 'src/types/api.generated.ts'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{js,jsx,ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks, 'jsx-a11y': jsxA11y },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.flatConfigs.recommended.rules,
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // A visible <label> wraps every control in this codebase; the rule cannot always see nested text.
      'jsx-a11y/label-has-associated-control': ['error', { assert: 'either', depth: 3 }],
    },
  },
  {
    files: ['*.{js,ts}', 'e2e/**/*.ts'],
    languageOptions: { globals: globals.node },
  },
)
