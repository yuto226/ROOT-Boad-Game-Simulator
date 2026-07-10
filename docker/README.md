# フェーズ6b: Windows機(RTX 4080 Super)での学習環境セットアップ

MacからSSHで制御し、PCは起動しておくだけの運用にする(ロードマップ6b)。
学習コード本体はOS非依存(`rl/`)。ここではWindows側の準備手順をまとめる。

## 1. WSL2 + Docker + GPU

Windows側(PowerShell、管理者):

```powershell
wsl --install -d Ubuntu    # WSL2 + Ubuntu
```

- **Docker Desktop** をインストールし、Settings → Resources → WSL Integration で
  Ubuntu を有効化(WSL2バックエンド)。Docker Desktop に NVIDIA GPU サポートは
  同梱される(ホストに最新の NVIDIA ドライバがあればよい。WSL内にドライバは入れない)。
- 確認(WSL2のUbuntu内):

```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
# RTX 4080 Super が表示されればOK
```

## 2. SSH到達性(Tailscale。ポート開放なし)

- Windows に Tailscale をインストールしてログイン(Mac側も同一アカウント)。
- SSHサーバは2案。**A案(推奨・単純)**: Windows の OpenSSH Server を有効化し、
  Mac から `ssh <user>@<tailscale名>` → `wsl` でUbuntuに入る。
  **B案**: WSL2内に openssh-server を入れ、`.bashrc` 等で `service ssh start` を
  自動起動(WSL2はsystemd有効化: `/etc/wsl.conf` に `[boot] systemd=true`)。
- どちらでも Tailscale の MagicDNS 名で Mac から直接届く(LAN外でも可)。

## 3. リポジトリ取得と学習ジョブ

WSL2のUbuntu内:

```bash
git clone git@github.com:yuto226/ROOT-Boad-Game-Simulator.git root-sim
cd root-sim
docker compose -f docker/compose.yaml build

# detached で学習開始(SSHが切れても死なない)
docker compose -f docker/compose.yaml run -d train \
    --total-steps 10000000 --run-name gpu-10m --num-envs 16

# 進捗確認(チェックポイントとCSVログはホスト側 rl_runs/ にマウント済み)
tail -f rl_runs/gpu-10m/log.csv
docker ps                      # コンテナ状態
docker logs -f <container>     # 標準出力

# 中断からの再開
docker compose -f docker/compose.yaml run -d train \
    --resume rl_runs/gpu-10m/ckpt_<N>.pt --run-name gpu-10m
```

チェックポイントは `--save-every`(既定10更新)ごとに保存されるので、
コンテナやPCが落ちても最後のckptから再開できる。

## 4. 学習曲線の監視

- 最小構成: `rl_runs/<run名>/log.csv` を Mac から
  `ssh <host> tail -f ...` するか、`scp`/`rsync` で取得して
  `analysis/` 系のツールで可視化(必要になったら log.csv 用の簡易HTMLを追加)。
- W&B / TensorBoard の導入は学習が本格化してから判断(DESIGN.md 13.3)。

## 5. 注意

- ボトルネック想定はエンジン(純Python)のCPU側。GPU使用率が低い場合は
  `--num-envs` を増やす(収集がenv間バッチ推論のため、env数≒バッチ幅)。
  それでも足りなければ `legal_actions`/`apply` のRust/C++移植を検討
  (インターフェースと決定性制約=DESIGN.md 10.2 が仕様書になる)。
- Mac(CPU)で約1350 steps/s。10⁷ステップ≒2時間強がMacでの目安であり、
  GPU化の主目的は更新側(ネット大型化・minibatch増)とenv並列の余地。
