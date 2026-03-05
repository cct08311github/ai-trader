# 老闆端（手機/筆電）連線指南：透過 Tailscale 存取 Dashboard

目標：人在外面也能安全打開 Dashboard，不需要公開 IP、不需要開路由器 port forwarding。

---

## A. 安裝並加入同一個 Tailnet

1) 安裝 Tailscale
- iOS/Android：App Store / Google Play 搜尋「Tailscale」
- macOS/Windows：到 Tailscale 官網下載安裝

2) 登入
- 使用公司指定的登入方式（Google/Microsoft/SSO）

3) 等待 Mac mini 裝置核准
- 第一次加入可能需要 Admin 核准（建議開啟 Device approval）

---

## B. 連線確認

開啟 Tailscale App，確認：
- 狀態顯示 Connected
- 能看到 Mac mini（例如名稱：`mac-mini` 或 `life-macmini`）

---

## C. 開啟 Dashboard / API

### Dashboard（HTTPS）
- 建議使用 MagicDNS：
  - `https://<mac-mini-hostname>.<tailnet-name>.ts.net/`
  - 或 `https://<mac-mini-hostname>/`（若 MagicDNS 已開啟）

### API（HTTP / TCP）
- `http://<mac-mini-hostname>.<tailnet-name>.ts.net:8080/`

> 若使用 Caddy 方案，可能會是 `https://<TAILSCALE_IP>/`。

---

## D.（選配）使用 Exit Node

若你在外面想把「所有流量」走家裡的 Mac mini（例如公司網路限制、或需要固定出口），可以：

- 手機：Tailscale App → Exit Node → 選 Mac mini
- 筆電：同上

不用時請關閉 Exit Node。

---

## E. 故障排除

1) 打不開網頁
- 確認 Tailscale 已 Connected
- 確認你加入的是同一個 Tailnet
- 確認 Admin Console 裝置已核准
- 確認 ACL 允許你連到 `443/8080`

2) DNS 找不到主機
- 確認 MagicDNS 已開啟
- 改用 IP 測試：在 Mac mini 上查 `tailscale ip -4`，用 `https://<ip>/` 測試

3) 速度慢
- 先關閉 Exit Node 測試
- 在手機/筆電查看是否顯示 Direct 連線（不是 DERP 中繼）

4) 回報時請提供
- 你的裝置名稱
- 當下使用的網址
- Tailscale App 畫面（Connected / Exit Node / 連線方式）
