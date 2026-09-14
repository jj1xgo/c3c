# 実コンテナの手動・定期検証

`.github/workflows/runtime.yml` は、実イメージのビルドと起動後の境界を検査する。
PR 用の `CI` とは独立し、必須チェックは追加しない。定期実行は水曜 03:23 UTC
（12:23 JST）、対象は既定ブランチの `main`。手動では同じリポジトリ内のブランチを選べる。

## 実行する検査

1. **環境**: rootless Podman、Compose provider、必要なコマンドと対象 commit を記録する。
2. **ビルド**: `test-build.sh --build-only` を再利用する。キャッシュを使わず
   `Dockerfile.claude` をビルドし、`claude --version`、`gh --version`、`jq --version` と
   IPv6 helper の起動を確かめる。追加パッケージの上書き・不正入力ビルドの検査は、
   従来の `./test-build.sh` 全体実行で行う。
3. **マウント**: `test-build.sh --config-ro-only` を再利用する。
   11 項目の設定保護、plugin・共有パス・スキルの別名の読み取り専用性、
   `/shared`・`projects/` の書き込み、ホスト側ファイルの不変を実 Compose 構成で検査する。
4. **権限と通信**: イメージの `ENTRYPOINT` と `entrypoint.sh` を通常どおり実行し、
   最後に起動する `claude` だけを読み取り専用の検査プログラムへ置き換える。
   非 root の子プロセスの capability がなく、iptables を直接操作できないこと、
   GitHub の許可 IP の 443 番に接続でき、同 IP の 80 番と非許可 IP の 443 番へは
   接続できないことを検査する。検査プログラムの完了印がなければ、終了コード 0 でも失敗する。

通信先は最初の対照コンテナで IPv4 に解決して固定する。ファイアウォールを初期化しない
対照コンテナから全接続先へ到達できることを、保護検査の前後に確認する。
対照から接続できなければ、外部障害を遮断成功と区別できないので `not run` とする。
プロキシ設定と個人の認証情報は渡さない。Claude への質問・有料 API 呼び出しは行わない。
起動処理自身のネットワーク自己検証は実行する。

## 手動実行

Actions の「実コンテナ検証」→「Run workflow」でブランチを選ぶ。CLI では次のとおり。

```bash
gh workflow run runtime.yml -R jj1xgo/claude-container --ref <対象ブランチ>
gh run list -R jj1xgo/claude-container --workflow runtime.yml --limit 5
gh run view -R jj1xgo/claude-container <run-id> --log
gh run download -R jj1xgo/claude-container <run-id> --dir ./runtime-results
```

初回導入時の手動実行は workflow を既定ブランチへマージしてから可能になる。
これは [GitHub の workflow_dispatch の条件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)
による。Dockerfile・起動処理・通信制限の変更時は、その後この手順でマージ前のブランチを検証する。
ブランチにこの workflow と検査スクリプトが含まれている必要がある。

ローカルでは次を実行する。ビルド用イメージ・一時設定は実行ごとに分け、終了時に清掃する。
既存イメージや他プロジェクトのコンテナを一括削除する `prune` は使わない。

```bash
PODMAN_COMPOSE_PROVIDER=/usr/bin/podman-compose bash tests/test-runtime.sh
# 起動検査だけを反復するとき。ビルドは not run として記録する。
bash tests/test-runtime.sh --image localhost/claude-test
```

`RUNTIME_RESULTS_DIR` で結果の保存先を指定できる。既定は
`.claude/test-results/claude-runtime-<時刻>-<PID>/`。
再利用する `test-build.sh` には `TEST_IMAGE`・`TEST_LOG_DIR`・`TEST_COMPOSE_PROJECT` を渡し、
この検査用のタグ・ログ・Compose project を他の実行から分ける。

## runner の前提と判定

- GitHub hosted `ubuntu-24.04` の rootless Podman を使用する。Podman 本体・ネットワーク backend
  の版は runner に従い、`environment.log` に記録する。rootful や privileged コンテナへは切り替えない。
- `podman-compose 1.6.0`、`PyYAML 6.0.2`、`python-dotenv 1.1.1` を専用 venv に導入する。
  実マウント検査の `--in-pod false` を使うため、PR CI の Docker Compose とは別 provider にする。
- user namespace、keep-id、コンテナ内の iptables・sysctl 操作と外部 IPv4 通信が必要。
  Podman の起動不能・provider 不在は環境段階の `not run`。環境確認を通った後のビルド・
  マウント・通常起動の異常は `FAIL` とし、ログから原因を調べる。
- IPv6 opt-in の疎通は **not run**。この検査は既定の IPv4 構成を対象とする。
  IPv6 の実疎通には別途対応 runner を用意する。CLI helper の起動検査は IPv6 疎通を証明しない。
- 検査失敗は非 0、環境の前提未達は 77。環境の `not run` も workflow を成功にはしない。
  未到達の段階は `not run` として残す。

ジョブ全体は 50 分、検査ステップは 42 分で打ち切る。スクリプト内もビルド 30 分、
マウント 5 分、保護起動 5 分、前後の対照各 2 分で打ち切り、30 秒後に強制終了する。
終了コード・対象 commit・段階別結果・所要時間を `summary.md` に記録し、Actions のサマリにも載せる。
準備段階での失敗や中断で検査サマリがなければ、workflow が未生成の旨とステップ状態を記録する。
ログは成否にかかわらず artifact に 14 日保存する。ただし runner の強制停止時は保存できない場合がある。

## 検証の限界

外部通信先の障害・DNS 変化・依存パッケージ配布の問題は、製品の回帰と別途切り分ける必要がある。
この検査は実プロセスの権限と固定した接続先の疎通を確認するが、すべての接続先、
長時間の DNS 更新、対話 UI や実アカウントでの認証を網羅するものではない。
製品の境界全体の保証には、既存のテスト・コードレビュー・利用側の実起動確認も必要になる。
