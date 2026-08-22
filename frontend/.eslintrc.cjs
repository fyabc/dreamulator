module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs'],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  rules: {
    // `while (true) { ...; if (done) break }` 是读取流的标准写法，
    // 不应被当作恒真条件报错（仍检查 if/三元中的恒定条件）。
    'no-constant-condition': ['error', { checkLoops: false }],
    'react-refresh/only-export-components': [
      'warn',
      { allowConstantExport: true },
    ],
    // 世界数据是动态 YAML/JSON，代码库按设计大量使用 any（90+ 处）。
    // 强制此规则需要大规模类型重构，超出当前范围——维持项目现状。
    '@typescript-eslint/no-explicit-any': 'off',
    // 遵循下划线前缀 = 有意忽略的约定（如解构时跳过某属性）。
    '@typescript-eslint/no-unused-vars': [
      'error',
      {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
      },
    ],
    // 关键安全规则 react-hooks/rules-of-hooks（禁止条件调用 hook 等）
    // 由 react-hooks/recommended 保持为 error。
    // exhaustive-deps 仅为建议性：代码库存在 ~20 处有意省略依赖的
    // useCallback/useMemo/useEffect（例如避免悬停时重复上传 GPU 纹理），
    // 盲目补全可能改变运行时行为。故关闭；如需可按文件单独清理后再启用。
    'react-hooks/exhaustive-deps': 'off',
  },
}
