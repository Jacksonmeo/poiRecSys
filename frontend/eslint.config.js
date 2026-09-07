/**
 * ESLint 9 扁平配置文件（Flat Config）。
 * 覆盖 Vue 3 + TypeScript 项目，检查 src/ 下全部 .ts/.vue 文件。
 * 运行：npm run lint
 */
import js from "@eslint/js"
import globals from "globals"
import pluginVue from "eslint-plugin-vue"
import tseslint from "typescript-eslint"

export default tseslint.config(
  {
    ignores: ["dist/**", "node_modules/**"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs["flat/recommended"],
  {
    files: ["**/*.{ts,vue}"],
    languageOptions: {
      // 浏览器环境全局变量（window/document/ResizeObserver 等）
      globals: globals.browser,
      parserOptions: {
        parser: tseslint.parser,
      },
    },
  },
  {
    rules: {
      // Vue 组件名允许单单词（如 App / Dashboard / PoiMap）
      "vue/multi-word-component-names": "off",
      // 允许空 catch：错误提示已由 request 拦截器统一处理
      "no-empty": ["error", { allowEmptyCatch: true }],
      // 项目中有意使用 any 的场景（如后端动态字段）保留告警不阻断
      "@typescript-eslint/no-explicit-any": "off",
      // 模板格式化规则关闭：项目未引入 prettier，避免无意义的换行噪音
      "vue/max-attributes-per-line": "off",
      "vue/singleline-html-element-content-newline": "off",
      "vue/multiline-html-element-content-newline": "off",
      "vue/html-self-closing": "off",
      "vue/html-indent": "off",
      "vue/html-closing-bracket-newline": "off",
      "vue/first-attribute-linebreak": "off",
    },
  },
)
