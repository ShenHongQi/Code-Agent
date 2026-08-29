---
name: commit
description: 生成 commit message 并提交
aliases: [ci]
auto_approve: true
trigger: 当用户要求提交代码、生成 commit message 时
---

请完成代码提交：

1. 运行 `git diff --cached` 查看暂存内容；如果没有暂存内容则运行 `git diff` 查看工作区变更
2. 分析变更内容，生成规范的 commit message
3. 如果有未暂存的相关变更，先 `git add` 相关文件
4. 执行 `git commit`

{args}

## Commit Message 格式

遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```
type(scope): description

body (optional)
```

- **type**: feat / fix / refactor / docs / style / test / chore / perf
- **scope**: 受影响的模块（可选）
- **description**: 简洁描述变更内容（中英文均可，与项目风格一致）
- **body**: 较大变更时说明动机和细节
