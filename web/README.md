# Root 観戦フロントエンド(web/)

Vite + React + TypeScript の SPA。バックエンド(`server/app.py`)が返す対局
レコードを生成・再生する。`ui/viewer.html` の描画ロジックを移植したもの。

## セットアップ

```
npm install
```

## 開発

バックエンドを先に起動しておくこと(別ターミナル、リポジトリルートで):

```
.venv/bin/uvicorn server.app:app --port 8000
```

その後:

```
npm run dev
```

`http://localhost:5173` を開く。`/api/*` は `vite.config.ts` の proxy で
`http://localhost:8000` へ転送される。

## ビルド

```
npm run build
```

`dist/` に出力される(型チェック込み)。
