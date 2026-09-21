# c3c 第0B-2段階: 通常初期化後の Codex sandbox 検証結果

日付: 2026-09-20。対象 source commit: `93211ed80ad3e4b4231f40ba5096df6924e76f34`。
計画: [0B-2 検証計画](2026-09-20-c3c-phase0b2-entrypoint-validation.md)。実行・レビューはユーザーの一時的な指示に従って Codex のみ。

## 結果と適用範囲

**main の `entrypoint.sh` を読み取り専用で重ねた既存イメージでは、ファイアウォール初期化後も Codex sandbox の書込み拒否・許可が成立した。** 製品 ENTRYPOINT/CMD の配列を維持し、最後の Claude 呼出しだけを readonly の検査プログラムへ渡した。正式な CLI 切替やモデルとの会話の検証ではない。

| 検査 | 実測 | 判定 |
|---|---|---|
| 通常初期化と検査への到達 | `ENTRYPOINT_SHIM_BEGIN`、`RUNTIME_PROBE_OK`、`C3C_NORMAL_ENTRYPOINT_OK` | 成立 |
| 非特権の検査プロセス | UID:GID=1000:1000、CapInh/Prm/Eff/Amb=0、iptables 直接操作は非0終了 | 成立 |
| IPv4 通信 | GitHub:443 は接続成功、同じ IP の80と非許可 IP の443は拒否 | 成立 |
| 接続の前後対照 | firewall を初期化しない対照から、同じ3宛先すべてに前後とも接続成功 | 成立 |
| firewall 定期更新 | result=success、stale=false、consecutive_failures=0 | 成立 |
| readonly fixture | settings.json、hooks 内ファイル、MCP 承認記録への書込みが EROFS（errno30） | 成立 |
| Python の書込み対照 | inner 到達、rc0、control.txt 生成 | 成立 |
| `:read-only` | inner 到達、EROFS、rc42、ro.txt 不在 | 成立 |
| `:workspace` | inner 到達、rc0、workspace.txt 生成 | 成立 |

Codex は `codex-cli 0.155.1`。各 profile は `codex sandbox --permission-profile <値> -C /workspace python3 ...` で実行した。rc42 は probe が OS の拒否を観測したときの値。引数エラーや inner 未起動を拒否成功とは扱っていない。

## イメージの版と初回停止

image ID は 0A/0B-1 と同じ `28b724cd6363a9bdbc4f0a44386bdd6b7dc18d0c8fd7142ca219a83c277cc05c`。ベースは Debian testing。初回 `c3c-0b2-46e30b998c0b` は、baked entrypoint の SHA256 不一致で検査前に停止した。

読み出した entrypoint は別 worktree `trial/auto-permission-mode` と一致し、main との差は最終行の `--permission-mode auto` / `--dangerously-skip-permissions` だけだった。init-firewall.sh、firewall-refresh.py、ipv6-firewall.py の3本は main と一致。既存の main 向けテストイメージも調べたが Codex がなく、採用していない。

再実測 `c3c-0b2-acc6053b2636` では main entrypoint を専用 fixture にコピーして0755とし、`/usr/local/bin/entrypoint.sh:ro` へ重ねた。baked script の固定 SHA と最終行だけの差、マウント後の4本の SHA、実行前後の fixture 内容不変を確認した。**baked script をそのまま使った current-main のイメージ検証は not run**。build/pull や既存イメージの書換えは行っていない。

## 観測条件と証跡

- rootless Podman、製品既定 NET_ADMIN / NET_RAW と IPv4 設定。特権追加や seccomp 緩和、firewall 無効化なし。
- ホスト実設定・認証・vault はマウントせず、専用の空 Claude/Codex 設定を使用。Codex config.toml は空、auth.json 不在、既知の API/PAT 環境変数不在。MCP 定義は置いていない。
- 製品と同じ setpriv → tini → entrypoint の後から検査。`podman exec` では代用していない。
- 起動ログには、特殊用途 IPv4 を許可対象から除外する警告と `/proc/sys` 書込み不可による IPv6 無効化フォールバックの警告がある。IPv4 の対照・保護検査は上記のとおり成功。IPv6 の実通信は not run。

非公開証跡は `$CC/.claude/test-results/<RUN_ID>/`。初回と再実測を別々に保持する。

| 根拠 | ファイル |
|---|---|
| image / rootless / mount / 起動配列 | `logs/image.log`、`rootless.log`、`resolved.log`、`mounts.json`、`protected-inspect.log` |
| main script の明示指定 | `logs/source-substitution.json`、`provenance.log`、`protected-digests.json`、`probe/main-entrypoint.sh` |
| 実測 rc と出力 | `logs/control-before.*`、`protected.*`、`control-after.*`、`result.json` |
| 清掃 | `logs/cleanup-*`、`network-rm.*`、`remaining.*`、`image-retained.*` |
| 添付と検査プログラム | `run.py`、`probe.py`、`process_runner.py`、`test_process_runner.py`、`probe/` |
| 退避復旧 | `recover-archive.py`、`archive-recovery.json` |

## 終了・検証・レビュー

- 初回は source 不一致で INCOMPLETE。所有コンテナ1件と専用networkを清掃。原因調査の読出しコンテナ2件も `--rm` で終了。
- 再実測は control-before / protected / control-after がすべてrc0。provenanceを含め所有コンテナ4件と専用networkを清掃。imageは保持。
- **再実測 runner 全体の終了コードは1**。検査とコンテナ清掃後の copytree が、Codex のコンテナ内絶対パス symlink をホストで辿って失敗したため。ROOT と元ログを保持し、別の復旧手順で symlink のまま退避した。ファイル68件と symlink 4件の一致、および添付のバイト一致を確認済み。全体rc1を検査失敗や全体rc0へ書き換えていない。
- 独立レビューの証跡照合後、`finalize.py` はrc0。初回・再実測とも所有コンテナ一覧が空（rc0）、専用network不在（exists rc1）、image保持（rc0）を再確認。退避内容を再照合してROOT2件を削除し、不存在を確認した。最終記録は両退避先の `final-checks.json`。原因調査の読出しコンテナにも初回と同じowner labelを付けており、最終の空一覧に含まれる。
- 計画のセルフレビューと独立レビューを実施。timeout時の子孫停止、停止中割込み、fixtureの実行権限を修正。同型指摘2巡で別 Codex の収束診断を挟み、最終の計画確認巡5は Critical 0 / Important 0 / Minor 0。
- 待機中・停止中割込みの回帰確認と Python 構文確認は成功。製品コード差分、commit、push、PR なし。
- lint は sandbox内のPodman制約で一度失敗し、ホストで再実行して成功（Compose検証を含む、警告なし）。
- 新規コンテキストの Codex による結果レビューは Critical 0 / Important 0 / Minor 0、未対応指摘なし。実inspect、SHA、rc、ファイル状態、初回37通常ファイル・再実測68通常ファイル/4 symlink・再実測添付6本の一致まで独立照合済み。レビュー時点で未判定だった最終清掃は上記の実行結果で確認した。

## 未検証と次段階

実認証・トークン更新、モデル経由の sandbox 強制力、設定源別 MCP/hook trust、正式な両 CLI 起動・切替、同一会話内の worktree 移動・再開、正式な current-main image build は not run。0A/0B-1 の既存イメージも試験版だったが、両検証では製品CMDを差し替えて entrypoint.sh を通っていないため、それらの限定観測を通常起動の成立へ拡張しない。

今回の結果で、通常初期化後の sandbox の基本動作に関する不確実性は減った。次は認証保存先と設定の境界を具体化し、モデルを使う動作と同一会話の worktree 移動を検証する。G3 全体の完了や日常利用の安全性承認はまだ行わない。
