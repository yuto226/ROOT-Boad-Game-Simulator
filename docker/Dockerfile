# フェーズ6b: Windows機(WSL2+Docker+RTX 4080 Super)用の学習イメージ。
# ベースは公式 PyTorch CUDA ランタイム(Mac開発環境の torch 2.8.0 と揃える)。
# ビルドはリポジトリルートをコンテキストに: docker compose -f docker/compose.yaml build
FROM pytorch/pytorch:2.8.0-cuda12.6-cudnn9-runtime

WORKDIR /workspace/root-sim

# 依存メタデータを先にコピーしてレイヤーキャッシュを効かせる
COPY pyproject.toml README.md ./
COPY engine ./engine
COPY bots ./bots
COPY sim ./sim
COPY simulation ./simulation
COPY analysis ./analysis
COPY rl ./rl

# エンジンは依存ゼロ、rl は numpy のみ(torch はベースイメージ由来)
RUN pip install --no-cache-dir -e ".[rl]"

# チェックポイント・ログの出力先(compose 側でホストにマウントする)
VOLUME /workspace/root-sim/rl_runs

# 既定コマンド: PPO 学習(--device auto = cuda を自動選択)。
# 引数は docker compose run / docker run の末尾で上書きできる。
ENTRYPOINT ["python", "-m", "rl.train"]
CMD ["--device", "auto", "--run-name", "gpu-run"]
