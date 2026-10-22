# TeleAgent 部署指南

本指南说明如何将 MCP 服务器注册到 TeleAgent Desktop，包括传输类型选择、JSON 配置格式、UI 操作步骤、凭证管理和常见问题排查。

---

## 传输类型

TeleAgent 工具设置界面支持以下传输类型：

| 传输方式 | 配置标识 | 适用场景 | 状态 |
| --- | --- | --- | --- |
| StreamableHTTP | `url`（路径含 `/mcp`） | 远端服务（默认） | 推荐优先使用 |
| SSE | `url`（路径含 `/sse`） | 远端服务 | deprecated，仍可使用 |
| stdio | `command` + `args` | 本地子进程 | 仅当用户明确要求时使用 |

---

## 配置 JSON 格式

所有配置使用 `mcpServers` 格式，用户将 JSON 粘贴到 TeleAgent 工具设置界面即可完成注册。

**默认优先使用 StreamableHTTP，除非用户明确要求 stdio。**

### StreamableHTTP（远端，默认推荐）

**无需认证：**

```json
{
  "mcpServers": {
    "codebase-analyzer-mcp": {
      "url": "http://127.0.0.1:3001/mcp"
    }
  }
}
```

**需要认证（headers）：**

```json
{
  "mcpServers": {
    "github-mcp-server": {
      "url": "http://127.0.0.1:8080/mcp",
      "headers": {
        "Authorization": "Bearer 用户的Token值"
      }
    }
  }
}
```

**Key 在 URL 参数上：**

```json
{
  "mcpServers": {
    "amap-maps": {
      "url": "https://mcp.amap.com/mcp?key=用户的Key值"
    }
  }
}
```

### stdio（本地子进程，仅当用户明确要求时）

**Python 服务器：**

```json
{
  "mcpServers": {
    "weather_mcp": {
      "command": "python",
      "args": ["/绝对路径/weather_mcp/server.py"]
    }
  }
}
```

**Node 服务器：**

```json
{
  "mcpServers": {
    "github-mcp-server": {
      "command": "node",
      "args": ["/绝对路径/github-mcp-server/dist/index.js"]
    }
  }
}
```

**npx 直接运行：**

```json
{
  "mcpServers": {
    "slack-mcp-server": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-slack"]
    }
  }
}
```

### SSE（远端，deprecated）

**无需认证：**

```json
{
  "mcpServers": {
    "notion_mcp": {
      "url": "http://127.0.0.1:9000/sse"
    }
  }
}
```

**需要认证：**

```json
{
  "mcpServers": {
    "stripe_mcp": {
      "url": "http://127.0.0.1:7000/sse",
      "headers": {
        "Authorization": "Bearer 用户的Token值"
      }
    }
  }
}
```

---

## 凭证管理

### 三种传写方式

| 方式 | 适用场景 | 示例 |
| --- | --- | --- |
| URL 参数 | Key 作为 URL 查询参数（StreamableHTTP） | `"url": "https://xxx/mcp?key=xxx"` |
| Headers | Key 在 HTTP 请求头中（StreamableHTTP） | `"headers": {"Authorization": "Bearer xxx"}` |
| 环境变量注入 | Key 通过子进程环境变量传入（仅 stdio） | `"env": {"API_KEY": "用户的Key值"}` |

**注意：stdio 模式下，用户的 API Key 必须直接填写在 JSON 的 `env` 字段中，不要使用 `{env:变量名}` 占位符引用系统环境变量。** TeleAgent 启动子进程时会自动将 `env` 中的键值对注入为环境变量。

### 直接填写 vs 占位标识

API Key 必须直接写在 JSON 对应字段中，不能使用 `{env:变量名}` 引用系统环境变量。提供两种填写方式：

```json
{
  "mcpServers": {
    "amap-maps": {
      "url": "https://mcp.amap.com/mcp?key=abcd1234"
    }
  }
}
```

**留空自填（Agent 输出占位标识，用户手动替换）：**

```json
{
  "mcpServers": {
    "amap-maps": {
      "url": "https://mcp.amap.com/mcp?key=用户的Key值"
    }
  }
}
```

TeleAgent 启动子进程或发起 HTTP 请求时，会直接使用 JSON 中的值。因此 API Key 必须直接填写，不能使用 `{env:变量名}` 占位符。

### API Key 填写方式（用户选项）

当 MCP 服务器需要 API Key 时，Agent 必须向用户提供以下两种填写方式供选择：

| 选项 | 说明 | Agent 行为 |
| --- | --- | --- |
| 用户直接提供 Key | 用户在对话中将 API Key 告知 Agent | Agent 将 Key 直接填入配置 JSON 对应位置（明文），并提醒用户密钥以明文存在于配置中 |
| 留空自填 | 用户不在对话中提供 Key | Agent 在配置 JSON 的 Key 位置填入占位标识 `<YOUR_API_KEY>`，用户粘贴到工具设置后自行替换为真实 Key |

**留空自填示例输出：**

```json
{
  "mcpServers": {
    "amap-maps": {
      "url": "https://mcp.amap.com/mcp?key=<YOUR_API_KEY>"
    }
  }
}
```

> **Agent 须注意**：选择"留空自填"时，在输出 JSON 后附上说明，指出配置中哪些位置需要用户手动替换为真实 Key。

---

## UI 配置操作步骤

1. 点击 TeleAgent Desktop 左下角头像
2. 点击"工具设置"
3. 在 MCP 配置区域，点击添加
4. 将 `mcpServers` 格式的 JSON 粘贴到输入框
5. 保存

---

## 验证部署

配置完成后，按以下步骤验证：

1. **检查连接状态**：在工具设置界面确认 MCP 服务器状态为"已连接"
2. **测试工具调用**：通过智能体调用 MCP 工具，验证功能正常

---

## 常见问题排查

| 问题 | 可能原因 | 解决方案 |
| --- | --- | --- |
| 状态显示"连接失败" | 服务器未启动 / URL 不可达 | 检查 MCP 服务器是否运行，确认 URL 和端口正确 |
| 状态显示"需要认证" | 配置了 headers 但凭证无效 | 检查 API Key 是否正确，环境变量是否已设置 |
| stdio 服务器无法启动 | command 或 args 路径错误 | 确认可执行文件路径为绝对路径，依赖已安装 |
| Key 无效或过期 | Key 填写错误或已过期 | 检查 JSON 中填写的 Key 是否正确且有效 |
| 端口冲突 | MCP 服务器端口被占用 | 更换 MCP 服务器监听端口，更新 JSON 中的 URL |
| 配置保存后不生效 | 配置写入异常 | 重新打开工具设置界面检查配置是否正确保存 |