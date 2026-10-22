---
name: mcp-builder
name_cn: MCP构建器
description: 创建适用于 TeleAgent 的 MCP（模型上下文协议）服务器。支持 stdio 和 StreamableHTTP 传输方式，通过 TeleAgent Desktop 工具设置界面完成注册。适用于 Python（FastMCP）或 Node/TypeScript（MCP SDK）开发。
description_cn: 创建适用于 TeleAgent 的 MCP 服务器，支持 stdio 和 StreamableHTTP 传输方式，通过工具设置界面完成注册。适用于 Python 或 Node/TypeScript 开发。
license: 完整条款见 LICENSE.txt
---

# MCP 服务器开发指南

## 概述

创建 MCP（模型上下文协议）服务器，使大语言模型能够通过精心设计的工具与外部服务交互。本指南基于官方 mcp-builder，增加 TeleAgent 部署配置阶段，引导用户通过 TeleAgent Desktop UI 完成 MCP 服务器注册。

MCP 服务器的质量取决于它能否让 LLM 有效完成真实任务。

---

# 流程

## 总体工作流

创建高质量 MCP 服务器分为五个阶段：

### 阶段一：调研与规划

#### 1.1 理解 MCP 设计原则

**API 覆盖 vs 工作流工具：**
在全面的 API 端点覆盖和专用工作流工具之间取得平衡。不确定时，优先选择全面的 API 覆盖。

**工具命名与可发现性：**
使用一致的前缀（如 `github_create_issue`、`github_list_repos`）和面向动作的命名。

**上下文管理：**
设计返回聚焦、相关数据的工具。支持过滤和分页。

**可操作的错误信息：**
错误信息应引导 LLM 找到解决方案，提供具体建议和后续步骤。

#### 1.2 学习 MCP 协议文档

从 sitemap 开始查找相关页面：`https://modelcontextprotocol.io/sitemap.xml`

然后抓取具体页面（加 `.md` 后缀获取 Markdown 格式）。

关键页面：
- 规范概述和架构
- 传输机制：Streamable HTTP、stdio
- Tool、Resource、Prompt 定义

#### 1.3 学习框架文档

**推荐技术栈：**
- **语言**：TypeScript（SDK 支持好、静态类型、AI 生成质量高）或 Python
- **传输**：StreamableHTTP（远端推荐）、stdio（本地）

**加载框架文档：**

- **MCP 最佳实践**：[查看最佳实践](./reference/mcp_best_practices.md) - 核心指南

**TypeScript（推荐）：**
- **TypeScript SDK**：使用 WebFetch 加载 `https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/main/README.md`
- [TypeScript 指南](./reference/node_mcp_server.md) - TypeScript 模式和示例

**Python：**
- **Python SDK**：使用 WebFetch 加载 `https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md`
- [Python 指南](./reference/python_mcp_server.md) - Python 模式和示例

#### 1.4 规划实现

**理解 API：**
审查服务的 API 文档，识别关键端点、认证要求和数据模型。

**工具选择：**
优先全面的 API 覆盖。列出要实现的端点，从最常用的操作开始。

---

### 阶段二：实现

#### 2.1 搭建项目结构

参见语言特定指南：
- [TypeScript 指南](./reference/node_mcp_server.md) - 项目结构、package.json、tsconfig.json
- [Python 指南](./reference/python_mcp_server.md) - 模块组织、依赖管理

#### 2.2 实现核心基础设施

创建共享工具：
- 带认证的 API 客户端
- 错误处理辅助函数
- 响应格式化（JSON/Markdown）
- 分页支持

#### 2.3 实现工具

每个工具需包含：

**输入 Schema：**
- 使用 Zod（TypeScript）或 Pydantic（Python）
- 包含约束和清晰描述
- 在字段描述中添加示例

**输出 Schema：**
- 尽可能定义 `outputSchema` 用于结构化数据
- 使用 `structuredContent` 返回结构化数据
- 同时返回文本内容（JSON 字符串或 Markdown）

**工具描述：**
- 功能的简洁摘要
- 参数描述
- 返回类型 schema

**实现要点：**
- I/O 操作使用 async/await
- 适当的错误处理，提供可操作的信息
- 适用时支持分页

**注解（Annotations）：**
- `readOnlyHint`：true/false — 是否只读
- `destructiveHint`：true/false — 是否有破坏性
- `idempotentHint`：true/false — 是否幂等
- `openWorldHint`：true/false — 是否与外部实体交互

---

### 阶段三：审查与测试

#### 3.1 代码质量

审查要点：
- 无重复代码（DRY 原则）
- 一致的错误处理
- 完整的类型覆盖
- 清晰的工具描述

#### 3.2 构建与测试

**TypeScript：**
- 运行 `npm run build` 验证编译
- 使用 MCP Inspector 测试：`npx @modelcontextprotocol/inspector`

**Python：**
- 验证语法：`python -m py_compile your_server.py`
- 使用 MCP Inspector 测试

参见语言特定指南了解详细的测试方法和质量检查清单。

---

### 阶段四：创建评估

实现 MCP 服务器后，创建全面的评估来测试其有效性。

**加载 [评估指南](./reference/evaluation.md) 了解完整的评估说明。**

#### 4.1 理解评估目的

使用评估来测试 LLM 是否能有效使用你的 MCP 服务器回答现实的复杂问题。

#### 4.2 创建 10 个评估问题

按照评估指南中的流程：

1. **工具审查**：列出可用工具并理解其能力
2. **内容探索**：使用只读操作探索可用数据
3. **问题生成**：创建 10 个复杂、现实的问题
4. **答案验证**：自己解决每个问题以验证答案

#### 4.3 评估要求

确保每个问题：
- **独立**：不依赖其他问题
- **只读**：只需要非破坏性操作
- **复杂**：需要多个工具调用和深入探索
- **现实**：基于真实用例
- **可验证**：单一、明确的答案
- **稳定**：答案不会随时间变化

#### 4.4 输出格式

创建 XML 文件：

```xml
<evaluation>
  <qa_pair>
    <question>问题描述</question>
    <answer>答案</answer>
  </qa_pair>
</evaluation>
```

---

### 阶段五：TeleAgent 部署配置

MCP 服务器通过构建、测试和评估后，需要注册到 TeleAgent 才能使用。

**加载 [TeleAgent 部署指南](./reference/teleagent_deployment.md) 了解完整的部署说明。**

#### 5.1 传输方式选择

**默认优先使用 StreamableHTTP**，除非用户明确要求 stdio。根据场景选择：

| 场景 | 传输方式 | 说明 |
| --- | --- | --- |
| 远端服务（默认） | StreamableHTTP | 推荐，MCP 服务器作为独立 Web 服务运行，支持 API Key 通过 URL 参数或 Headers 传入 |
| 远端服务 | SSE | 已弃用（deprecated），仍可使用但不推荐 |
| 本地子进程 | stdio | 仅当用户明确要求时使用，MCP 服务器作为 TeleAgent 的子进程运行 |

#### 5.2 确定服务器入口

- **StreamableHTTP（默认）**：提供 MCP 服务器的 URL，如 `http://127.0.0.1:3000/mcp`
- **stdio（用户明确要求时）**：
  - TypeScript：`node /绝对路径/{service}-mcp-server/dist/index.js`
  - Python：`python /绝对路径/{service}_mcp/server.py`

#### 5.3 识别所需凭证

列出服务器启动或连接时需要的所有密钥（API Key、Token 等），确定凭证传写方式：

| 传写方式 | 适用场景 | JSON 示例 |
| --- | --- | --- |
| URL 参数 | Key 作为 URL 查询参数（StreamableHTTP） | `"url": "https://xxx/mcp?key=xxx"` |
| Headers | Key 在 HTTP 请求头中（StreamableHTTP） | `"headers": {"Authorization": "Bearer xxx"}` |
| 环境变量注入 | Key 通过子进程环境变量传入（仅 stdio） | `"env": {"API_KEY": "用户的Key值"}` |

**注意：stdio 模式下，用户的 API Key 必须直接填写在 JSON 的 `env` 字段中，不要使用 `{env:变量名}` 占位符引用系统环境变量。** 用户在工具设置界面粘贴 JSON 后，TeleAgent 启动子进程时会自动将 `env` 中的键值对注入为环境变量。

**当 MCP 服务器需要 API Key 时，必须向用户询问 Key 填写方式：**

| 选项 | 说明 | Agent 行为 |
| --- | --- | --- |
| 用户直接提供 Key | 用户将 API Key 告知 Agent | Agent 将 Key 直接填入配置 JSON 对应位置 |
| 留空自填 | 用户不在对话中提供 Key | Agent 在配置 JSON 的 Key 位置填入占位标识（如 `<YOUR_API_KEY>`），用户在粘贴到工具设置后自行替换 |

> **注意**：选择"用户直接提供 Key"时，Agent 应提醒用户密钥将以明文形式存在于配置中；选择"留空自填"时，Agent 须在输出的 JSON 后附上说明，指出哪些位置需要用户手动替换。

**重要：无论哪种方式，API Key 都必须直接填写在 JSON 的对应字段中（`env`、`headers`、`url` 参数），不能放在代码里。**

#### 5.4 生成配置 JSON

根据传输方式生成 `mcpServers` 格式的 JSON，用户可直接粘贴到 TeleAgent 工具设置界面。

**streamableHTTP（远端，无需认证）：**

```json
{
  "mcpServers": {
    "server-name": {
      "url": "http://127.0.0.1:3000/mcp"
    }
  }
}
```

**streamableHTTP（远端，需要认证 — Key 在 Headers）：**

```json
{
  "mcpServers": {
    "server-name": {
      "url": "http://127.0.0.1:3000/mcp",
      "headers": {
        "Authorization": "Bearer 用户的Token值"
      }
    }
  }
}
```

**streamableHTTP（远端，需要认证 — Key 在 URL 参数）：**

```json
{
  "mcpServers": {
    "server-name": {
      "url": "https://xxx.com/mcp?key=用户的Key值"
    }
  }
}
```

**stdio（本地子进程，仅当用户明确要求时）：**

```json
{
  "mcpServers": {
    "server-name": {
      "command": "node",
      "args": ["/绝对路径/dist/index.js"],
      "env": {
        "API_KEY": "用户的Key值"
      }
    }
  }
}
```

**sse（远端，deprecated）：**

```json
{
  "mcpServers": {
    "server-name": {
      "url": "http://127.0.0.1:3000/sse"
    }
  }
}
```

#### 5.5 UI 配置操作步骤

引导用户通过 TeleAgent Desktop 界面完成 MCP 注册：

1. 点击左下角头像
2. 点击"工具设置"
3. 在 MCP 配置区域，点击添加
4. 将生成的 `mcpServers` 格式 JSON 粘贴到输入框
5. 保存

#### 5.6 验证部署

配置完成后，按以下步骤验证：

1. 在工具设置界面确认 MCP 状态为"已连接"
2. 通过智能体调用 MCP 工具测试功能

---

# 参考文件

## 文档库

根据需要在开发过程中加载以下资源：

### 核心 MCP 文档（优先加载）
- **MCP 协议**：从 `https://modelcontextprotocol.io/sitemap.xml` 开始，然后抓取具体页面
- [MCP 最佳实践](./reference/mcp_best_practices.md) - 通用 MCP 指南，包括：
  - 服务器和工具命名规范
  - 响应格式指南（JSON vs Markdown）
  - 分页最佳实践
  - 传输选择（StreamableHTTP vs stdio）
  - 安全和错误处理标准

### SDK 文档（阶段一/二加载）
- **Python SDK**：从 `https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md` 加载
- **TypeScript SDK**：从 `https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/main/README.md` 加载

### 语言实现指南（阶段二加载）
- [Python 实现指南](./reference/python_mcp_server.md) - 完整的 Python/FastMCP 指南
- [TypeScript 实现指南](./reference/node_mcp_server.md) - 完整的 TypeScript 指南

### 评估指南（阶段四加载）
- [评估指南](./reference/evaluation.md) - 完整的评估创建指南

### TeleAgent 部署指南（阶段五加载）
- [TeleAgent 部署指南](./reference/teleagent_deployment.md) - TeleAgent 部署指南，包括：
  - 传输类型配置格式与 JSON 示例
  - UI 配置操作步骤
  - 凭证三种传写方式（URL 参数、headers、环境变量注入）
  - 常见问题排查
