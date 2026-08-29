## Summary / 摘要

What this PR does and why. One or two sentences. / 本 PR 做了什么、为什么,一两句说清。

## Type / 类型

<!-- conventional-commit type that will appear in the changelog / 将出现在 changelog 中的类型 -->
feat / fix / docs / perf / refactor / test / chore

## Checklist / 检查清单

- [ ] Commit subjects follow conventional commits (they feed the auto-generated release notes) / 提交信息符合 conventional commits(Release 说明由此自动生成)
- [ ] Tests added or updated — backend `pytest`, frontend `vitest` / 新行为已带测试
- [ ] UI text (if any) added to **both** `zh.json` and `en.json`, rendered via `t('...')` / 界面文案已同时进中英字典并走 t()
- [ ] UI changes: before/after screenshots attached / UI 改动已附前后截图
- [ ] CI green: backend (ruff, mypy, import-linter, pytest) + frontend (eslint, tsc, build, vitest) / CI 全绿
