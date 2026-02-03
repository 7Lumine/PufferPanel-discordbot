# PufferPanel Discord Bot

PufferPanel管理下のMinecraftサーバーをDiscordから操作し、ログをリアルタイム同期するBotです。

## 機能

- **サーバー操作**: Start / Stop / Restart ボタン
- **ステータス表示**: サーバー状態、最終操作履歴をダッシュボードに表示
- **ログ同期**: WebSocketでリアルタイムログ受信、プライベートスレッドへ投稿
- **永続ボタン**: Bot再起動後もボタンが機能
- **権限管理**: 指定ロール所持者のみ操作可能

## セットアップ

### 1. 必要要件

- Python 3.10+
- PufferPanel 2.x
- Discord Bot Token

### 2. インストール

```bash
# リポジトリをクローン
git clone https://github.com/your-repo/PufferPanel-discordbot.git
cd PufferPanel-discordbot

# 仮想環境を作成（推奨）
python -m venv venv
venv\Scripts\activate  # Windows
# または
source venv/bin/activate  # Linux/Mac

# 依存パッケージをインストール
pip install -r requirements.txt
```

### 3. 設定

```bash
# 設定ファイルをコピー
cp config.example.yml config.yml

# config.yml を編集
```

#### PufferPanel設定

1. PufferPanelの Settings → OAuth2 Clients でクライアントを作成
2. `client_id` と `client_secret` を config.yml に設定
3. `server_id` はブラウザのネットワークタブで確認（UUIDを推奨）

#### Discord設定

1. [Discord Developer Portal](https://discord.com/developers/applications) でBotを作成
2. Bot Token を取得して config.yml に設定
3. 必要な権限:
   - `Send Messages`
   - `Embed Links`
   - `Create Public Threads`
   - `Create Private Threads`
   - `Send Messages in Threads`
   - `Manage Threads`
4. Guild ID, Channel IDs, Role ID を設定

### 4. 起動

```bash
python bot.py
```

### 5. ダッシュボード設置

Discordで設定したダッシュボードチャンネルに移動し、以下のコマンドを実行:

```
/setup
```

これでダッシュボードメッセージ（ボタン付き）が作成されます。

## 使い方

### ボタン操作

| ボタン | 機能 |
|--------|------|
| ▶️ Start | サーバーを起動 |
| ⏹️ Stop | サーバーを停止 |
| 🔄 Restart | サーバーを再起動（Stop→Start） |
| 🔃 Refresh | ダッシュボード情報を更新 |
| 📋 Logs ON | ログ同期を開始（スレッド作成） |
| 📋 Logs OFF | ログ同期を停止 |

### ログ同期

- 「Logs ON」を押すと、その日のプライベートスレッドが作成されます
- 許可ロールのメンバーが自動招待されます
- サーバーログがリアルタイムでスレッドに投稿されます
- 日付が変わると新しいスレッドに切り替わります

## ファイル構成

```
PufferPanel-discordbot/
├── bot.py                    # エントリーポイント
├── config.yml                # 設定ファイル（自分で作成）
├── config.example.yml        # 設定テンプレート
├── requirements.txt          # 依存パッケージ
│
├── cogs/
│   └── dashboard.py          # ダッシュボード・ボタン
│
├── services/
│   ├── pufferpanel.py        # PufferPanel API クライアント
│   ├── websocket_client.py   # WebSocket ログ受信
│   └── log_sync.py           # ログ同期・スレッド管理
│
├── utils/
│   ├── config.py             # 設定読み込み
│   ├── state.py              # 永続状態管理
│   └── rate_limiter.py       # クールダウン管理
│
└── data/
    └── state.json            # 永続データ（自動生成）
```

## トラブルシューティング

### 「OAuth2 authentication failed」

- `client_id` と `client_secret` が正しいか確認
- PufferPanelのOAuth2クライアントが有効か確認

### 「サーバーIDが見つからない」

- `server_id` はURLの短いIDではなく、UUIDを使用
- ブラウザの開発者ツール → Network タブで実際のAPIリクエストを確認

### 「スレッドが作成されない」

- Botに `Create Private Threads` 権限があるか確認
- `log_parent_channel_id` が正しいか確認

### 「ボタンが反応しない（再起動後）」

- Botが正常に起動しているか確認
- `dashboard_message_id` が state.json に保存されているか確認

## ライセンス

MIT License
