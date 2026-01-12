# Copilot Instructions for Discord_Bot

## 專案概覽
本專案是一個簡易的 Discord Bot，主要功能為健康檢查（ping/pong）。所有邏輯目前集中於 `bot_ping.py`。

## 架構與主要元件
- 主要檔案：`bot_ping.py`
- 使用 `discord.py` 套件，並透過 `discord.Client` 與 `app_commands.CommandTree` 實作指令。
- 以 `.env` 檔案（需自行建立）管理 Discord Token，建議勿將 Token 寫死於程式碼。
- 指令註冊於特定 Guild（伺服器），Guild ID 於程式碼中指定。

## 關鍵開發流程
- 啟動：直接執行 `bot_ping.py` 即可啟動 Bot。
- 指令同步：於 `on_ready` 事件中自動同步指令到指定 Guild。
- 指令範例：`/ping` 會回覆 `pong`，訊息為 ephemeral（僅自己可見）。

## 專案慣例
- 所有 Discord 指令皆透過 `app_commands.CommandTree` 註冊。
- 事件處理（如 `on_ready`）以 `@client.event` 裝飾器實作。
- 建議將敏感資訊（如 Token）存放於 `.env`，並使用 `dotenv` 載入。
- Intents 預設為 `none`，如需更多事件監聽請調整。

## 外部依賴
- `discord.py`：Discord Bot 主要套件
- `python-dotenv`：載入環境變數

## 重要檔案範例
- `bot_ping.py`：
  - 指令註冊與事件處理皆於此檔案完成。
  - 主要結構如下：
    - 初始化 Client 與 CommandTree
    - 註冊 `/ping` 指令
    - `on_ready` 事件同步指令
    - 啟動 Bot

## 建議改進
- 將 Token 移至 `.env`，避免硬編碼。
- 若功能擴充，建議拆分指令與事件處理至多個檔案。

## 其他
- 若需新增指令，請於 `tree.command` 裝飾器下擴充。
- 若需支援多 Guild，請調整 Guild ID 管理方式。

---
如有不清楚或需補充之處，請回饋以便進一步完善指引。
