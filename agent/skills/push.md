---
name: push
description: 提交并推送到远程
aliases: [p]
auto_approve: true
trigger: 当用户要求推送代码到远程仓库时
---

请完成代码提交和推送：

1. `git status` 查看当前状态
2. `git add` 暂存所有相关变更（排除不应提交的文件）
3. 根据变更内容生成规范的 commit message（Conventional Commits 格式）
4. `git commit`
5. `git push`

{args}

## 注意

- **不要** force push
- 如果远程有新提交，先 `git pull --rebase` 解决
- 如果有合并冲突，解决冲突后再提交
- 检查 `.gitignore`，确保不提交敏感文件或构建产物
