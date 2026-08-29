---
name: init
description: 初始化项目结构
aliases: []
auto_approve: true
trigger: 当用户要求初始化新项目、搭建项目骨架时
---

请在当前工作区初始化项目：

{args}

## 步骤

1. 检查现有文件，推断项目类型（如果未指定）
2. 创建或确认项目结构：
   - 源码目录
   - 配置文件（package.json / pyproject.toml / Cargo.toml 等）
   - `.gitignore`（根据项目类型选择合适的模板）
   - `README.md`（项目名称、简介、使用说明）
3. 初始化包管理工具（如需要）
4. 初始化 git 仓库（如果还没有）
5. 安装基础依赖（如果适用）

根据项目类型和用户指定的参数灵活调整。
