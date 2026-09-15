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
保護検査が失敗した場合も後段の対照を試し、最初の失敗の終了コードを維持する。
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
`TEST_RUNTIME_USERNS=1` と併せて、この検査用のタグ・ログ・Compose project を他の実行から分ける。

## runner の前提と判定

- GitHub hosted `ubuntu-24.04` の rootless Podman を使用する。Podman 本体・ネットワーク backend
  の版は runner に従い、`environment.log` に記録する。rootful や privileged コンテナへは切り替えない。
- `podman-compose 1.6.0`、`PyYAML 6.0.2`、`python-dotenv 1.1.1` を専用 venv に導入する。
  Python パッケージは版固定のみで、配布物のハッシュ固定は行わない。
  実マウント検査の `--in-pod false` を使うため、PR CI の Docker Compose とは別 provider にする。
- runner の UID/GID を `environment.log` に記録する。CI 専用の
  `tests/compose.runtime-userns.yml` で `keep-id:uid=1000,gid=1000` を指定し、
  ホストの実行者をイメージ内の node に対応付ける。マウント検査にも同じ override を渡す。
  素の keep-id はホストの UID/GID を維持するため、この対応付けがない UID 1000 以外の
  ホストでの製品 launcher の動作は、この CI の保証範囲外になる。
  仕様は [Podman 4.9.3 の userns](https://docs.podman.io/en/v4.9.3/markdown/podman-run.1.html#userns-mode) を参照。
- user namespace、keep-id、コンテナ内の iptables・sysctl 操作と外部 IPv4 通信が必要。
  Podman の起動不能・provider 不在は環境段階の `not run`。環境確認を通った後のビルド・
  マウント・通常起動の異常は `FAIL` とし、ログから原因を調べる。
- `--build-only` の GitHub meta 取得が失敗し fallback もない場合は `not run`（77）。
  未認証 API のレート制限、通信障害、応答形式をログから確認する。個人トークンは使わない。
- IPv6 opt-in の疎通は **not run**。この検査は既定の IPv4 構成を対象とする。
  IPv6 の実疎通には別途対応 runner を用意する。CLI helper の起動検査は IPv6 疎通を証明しない。
- 検査失敗は非 0、環境の前提未達は 77。環境の `not run` も workflow を成功にはしない。
  未到達の段階は `not run` として残す。

ジョブ全体は 55 分、検査ステップは 45 分で打ち切る。スクリプト内もビルド 25 分、
マウント 5 分、保護起動 5 分、前後の対照各 2 分で打ち切り、30 秒後に強制終了する。
終了コード・対象 commit・段階別結果・所要時間を `summary.md` に記録し、Actions のサマリにも載せる。
準備段階での失敗や中断で検査サマリがなければ、workflow が未生成の旨とステップ状態を記録する。
ログは成否にかかわらず artifact に 14 日保存する。ただし runner の強制停止時は保存できない場合がある。

## 検証の限界

外部通信先の障害・DNS 変化・依存パッケージ配布の問題は、製品の回帰と別途切り分ける必要がある。
この検査は実プロセスの権限と固定した接続先の疎通を確認するが、すべての接続先、
長時間の DNS 更新、対話 UI や実アカウントでの認証を網羅するものではない。
製品の境界全体の保証には、既存のテスト・コードレビュー・利用側の実起動確認も必要になる。

## 初回の実測と実行頻度

2026-09-15（JST）、commit `4470876d2c964235f0dc3d01310f7a90409361c2` で
`tests/test-runtime.sh` をビルドから実行した。rootless Podman 5.8.6、netavark 1.17.2、
podman-compose 1.6.0、Linux 7.2.4-local / amd64 のホストで **62 秒、終了コード 0**。
ビルド・ツール起動は 7 件、マウント保護は 25 件すべて PASS。権限・通信・前後の対照と清掃も成功した。
ビルドした Claude Code は 2.1.271、gh は 2.100.0、jq は 1.7。
Podman のビルドキャッシュは無効、ベースイメージはホストに取得済みだった。

レビュー修正後の commit `2514fbdb2c65d4dbd7191b57901986d482e37203` でも、
同じホスト・provider でビルドから清掃まで再実行し、**61 秒、終了コード 0、全段階 PASS**。
CI 専用の UID 対応付けを含め、probe の UID:GID は `1000:1000`、
`CapInh`・`CapPrm`・`CapEff`・`CapAmb` はすべて 0 だった。

### GitHub hosted runner

2026-09-15（JST）、初回マージ後の main commit
`f497a5e6fc68c9f251a41b00779427839b39dffa` を
[手動実行](https://github.com/jj1xgo/claude-container/actions/runs/34912915312)した。
検査スクリプトは **64 秒、準備込み 69 秒、終了コード 0、全 6 段階 PASS**。
ビルド・ツール起動 7 件、マウント保護 25 件が PASS、後始末の終了コードも 0 だった。
ジョブ開始から終了までは 73 秒で、準備込みの値には artifact 保存と checkout 前後の処理を含めない。

環境は Ubuntu 24.04 / amd64、Linux 6.17.0-1022-azure、rootless Podman 4.9.3、
netavark 1.4.0、podman-compose 1.6.0。ホストの UID:GID は `1001:1001`、
CI 専用の対応付け後の検査プロセスは `1000:1000` だった。
`CapInh`・`CapPrm`・`CapEff`・`CapAmb` はすべて 0 で、許可通信・禁止通信と前後の対照も成功した。
IPv6 opt-in の疎通は引き続き **not run**。

この実測を踏まえ、依存パッケージと runner の変化を定点観測する頻度は週 1 回を維持する。
定期実行の cron は main に登録済みだが、この記録時点では schedule イベントによる起動は未観測。
今後の実行結果と所要時間を基に頻度・上限を調整する。
