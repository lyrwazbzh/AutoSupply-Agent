---
name: skill-management
description: 用户级技能发现与安全安装流程
scope: main
version: 1.0.0
---

# 技能管理操作手册

## 概述
本技能定义用户级 Skill 的发现与安全安装流程。系统核心 Skill 由发布流程维护，
运行时不得修改或向子Agent复制宿主机 `src/skills/` 内容。

## 技能生命周期

### 1. 下载技能
仅当当前用户拥有 `assistant:skill:install` 时调用 `install_skill`，不得用
`execute`、`web_fetch` 或自写脚本绕过权限。

**流程：**
1. 从指定URL下载 .zip 文件
2. 解压到目标目录
3. 验证 SKILL.md 存在且格式正确
4. 仅写入当前用户 `/skills/custom/<name>/` 与当前用户 Store namespace

### 2. 创建技能
新技能必须包含：
- `SKILL.md` — 技能定义文件（含 YAML frontmatter）
- 可选的 Python 脚本（沙箱内执行）

**SKILL.md 格式：**
```markdown
---
name: skill-name
description: 一句话描述
scope: procurement|main
version: 1.0.0
---

# 技能标题

## 使用场景
...

## 操作步骤
...
```

### 3. 测试技能
在沙箱中执行技能附带的脚本，验证：
- 脚本无语法错误
- 依赖已安装
- 输出格式正确

### 4. 使用技能
先用 `list_user_skills` 发现当前用户的技能，再读取其 `SKILL.md`。子Agent 的
工具能力由服务端 YAML 精确授权，Skill 不能扩大工具或审批权限。

## 注意事项
- 用户技能持久化在当前用户 Store namespace
- 系统核心技能只读，位于 `/skills/<scope>/<skill-name>/`
- 用户技能位于 `/skills/custom/<skill-name>/`
