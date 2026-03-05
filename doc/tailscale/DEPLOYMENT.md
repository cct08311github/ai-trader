# Tailscale 私有網路隔離部署（Mac mini）

目標：讓外部裝置（老闆手機/筆電）**僅透過 Tailscale** 安全存取 Dashboard 與 API，**不暴露公網 IP**。

> 本專案已將 Web/API 服務改為 **只綁定 localhost**：
> - Web: `127.0.0.1:3000`
> - API: `127.0.0.1:8080`
>
> 對外（Tailnet 內）存取請使用 Tailscale 的 `serve` 或反向代理（Caddy）。

---

## 1) 先決條件

- 需要在 Mac mini 安裝並登入 Tailscale（GUI 或 CLI）
- Tailnet 建議開啟：
  - Device approval（裝置需核准）
  - MagicDNS（方便用名稱存取）
  - Key expiry（不要用永久 key）

---

## 2) Mac mini：Tailscale 基本設定

### 2.1 安裝與登入

GUI：下載安裝後登入即可。

CLI（若已安裝）：

```bash
tailscale up --accept-dns=true --accept-routes=false
```

### 2.2（選配）啟用 Exit Node

若需求是讓外部裝置把「所有流量」都走 Mac mini（例如在外地使用家中網路出口），才需要啟用。

在 Mac mini 上：

```bash
tailscale up --advertise-exit-node=true
```

在客戶端裝置上：選擇使用此 Exit Node。

> 安全提醒：Exit Node 會讓裝置的所有流量經過 Mac mini，請務必搭配 ACL/裝置核准與定期檢查。

---

## 3) 服務曝光方式（擇一）

### 方案 A（建議、最省事）：`tailscale serve`

優點：不需要額外安裝反向代理；服務僅在 tailnet 內可達。

1) 先確保 Web/API 服務已由 PM2 啟動（本機仍是 localhost）：

```bash
pm2 start ecosystem.config.js
pm2 status
```

2) 讓 tailnet 內用 HTTPS 存取 Dashboard（對應 localhost:3000）：

```bash
# 讓 443 -> http://127.0.0.1:3000
tailscale serve --bg --https=443 http://127.0.0.1:3000
```

3) 讓 tailnet 內用 HTTP 存取 API（對應 localhost:8080）：

```bash
# 讓 8080 -> http://127.0.0.1:8080
tailscale serve --bg --tcp=8080 tcp://127.0.0.1:8080
```

檢查：

```bash
tailscale serve status
```

存取方式：
- Dashboard（HTTPS）：`https://<mac-mini-hostname>.<tailnet-name>.ts.net/`
- API（HTTP）：`http://<mac-mini-hostname>.<tailnet-name>.ts.net:8080/`

> 若你已開 MagicDNS，可直接用 `<mac-mini-hostname>`。

---

### 方案 B（需要既有憑證）：Caddy 只綁 Tailscale IP

此方案使用既有 `agent-monitor-web` 憑證：
- `/Users/openclaw/.openclaw/shared/projects/agent-monitor-web/cert/cert.pem`
- `/Users/openclaw/.openclaw/shared/projects/agent-monitor-web/cert/key.pem`

1) 取得 Tailscale IP：

```bash
tailscale ip -4
```

2) 建立 `docs/tailscale/Caddyfile.example`（已提供範本）並啟動 Caddy：

```bash
caddy run --config /path/to/Caddyfile
```

> Caddy 需要自行安裝（例如 brew）。

---

## 4) ACL（只允許老闆裝置）建議

在 Tailscale Admin Console → **Access controls** 設定 ACL，建議做法：

- 先把「老闆手機」「老闆筆電」「Mac mini」命名清楚
- 建議建立 device tags（例如 `tag:dashboard-host`）
- ACL 只允許：老闆裝置 → dashboard-host 的 `443,8080`

範例（概念示意，需依 tailnet 實際 identity 調整）：

```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["user:boss@example.com"],
      "dst": [
        "tag:dashboard-host:443",
        "tag:dashboard-host:8080"
      ]
    }
  ]
}
```

---

## 5) 防火牆/暴露面檢查

因本專案已改為綁 `127.0.0.1`，即使在 LAN 內也無法直接連到 `3000/8080`，只會在本機可達。

建議定期檢查：

```bash
# 本機確認只在 loopback 聆聽
lsof -nP -iTCP:3000 -sTCP:LISTEN
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

---

## 6) 監控與稽核

- 連線狀態：

```bash
tailscale status
```

- `serve` 狀態：

```bash
tailscale serve status
```

- Admin Console：查看 Device 連線/登入事件/ACL 命中

---

## 7) 回復/停用

停用 `serve`：

```bash
tailscale serve reset
```

停用 exit node：

```bash
tailscale up --advertise-exit-node=false
```
