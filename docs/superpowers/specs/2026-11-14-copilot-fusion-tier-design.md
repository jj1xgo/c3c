# Copilot の起動口に Fusion の段階を渡す口を足す 設計（#265）

日付: 2026-11-14

## 目的と理由

Copilot Fusion（`--model fusion`）の段階（`fusionTier`: `standard` / `high` / `max`）は、Copilot CLI 1.0.109 では設定ファイル（`$COPILOT_HOME/settings.json`）でしか受け取らない（`copilot help config`。起動の引数と環境変数の口は無い）。c3c の起動口（`copilot-launcher.sh`）は `COPILOT_HOME` を固定し、`settings.json` を root が持つ雛形から毎回作り直すので、コンテナの中から段階を指定して Fusion を起動できない。

段階は品質の基準の高さで、Fusion は選んだ段階の基準を満たす中で最も効率のよい組み方を選ぶ（GitHub Docs「About GitHub Copilot Fusion」）。Max に固定すると費用と所要が増えやすく、Pro 以下の契約では High と Max を使えないので、起動ごとに段階を選べる口が要る。

## ゴール

- 起動口が、決まった値だけを受け付ける段階の口を持ち、検査した値を作り直した `settings.json`（コンテナの中の `/home/node/.copilot/settings.json`。マウントせず、起動のたびに雛形から作り直す。リポジトリの外）の `fusionTier` に書く。次の起動では雛形どおりに戻る。
- 段階を指定しない起動の振る舞いは変わらない（`fusionTier` を書かない）。
- 決まった値以外は、Copilot を起動せずに ERROR で止まる（fail-closed）。

## やらないこと

- sandbox の設定の検査（弱めた設定、未知のキー、真偽値でない値は不合格）を変えない。
- 雛形（`copilot-settings.json`）に `fusionTier` を足さない。
- `--auto-tier`・`--reasoning-effort` など、引数で渡せるものに手を付けない（今も Copilot へそのまま届く）。
- 保守者の並走の道具の止めを外す作業。#265 が入った後に別に行う。

## 失敗とみなすもの

- プロンプトなど Copilot へ渡すべき引数を、起動口が取り除く・書き換える。
- 段階の口から、sandbox の設定や `fusionTier` 以外のキーを書けてしまう。
- 段階を指定しない起動で、`settings.json` の中身が今と変わる。

## Approaches（検討した作り方）

1. **起動口が解釈して取り除く引数（採用）**: 先頭の `--c3c-fusion-tier <値>` だけを起動口が受け取り、取り除いてから Copilot へ渡す。呼び出しの形に段階が見え、ほかの起動へ漏れない。
2. 環境変数（例 `C3C_COPILOT_FUSION_TIER`）: 呼び出し側の変更は小さいが、親のシェルに残った値が知らないうちに効く。
3. 雛形のキーとして許す: 雛形はビルド時に固定されるので、起動ごとに段階を変えられない。目的に合わない。

持ち主が 2026-11-14 に 1 を選んだ。

## 決まったこと

- 口は `--c3c-fusion-tier <値>`。値は `standard`・`high`・`max` のどれか（完全一致）。standard も受け付ける（Pro の契約で使える唯一の段階で、指定しないときの Copilot の既定が standard かは公式に書かれていない）。

## 設計者の判断（持ち主が直せる）

- 起動口が解釈するのは第 1 引数の位置だけ。2 番目以降に同じ文字列があっても取り除かずに Copilot へ渡す（プロンプトの値などを誤って取らないため。Copilot が未知のオプションとして扱う）。
- `--c3c-fusion-tier` の後に値が無い、値が 3 つ以外、取り除いた直後にもう一度 `--c3c-fusion-tier` がある、`--c3c-fusion-tier=<値>` の形は、ERROR で止める（`=` の形を受け付けないのは、口の形を 1 つに絞るため）。
- 引数の検査は、起動口の最初の段（中継と実体の検査の前）で行う。不正な値なら何も作らずに止まる。`docs/development-invariants.md` の起動口の順序の節を、この段を足した形に直す。
- 段階は `settings.json` を作り直す `python3 -I` に引数で渡し、書いた後の検査で、指定したときは `fusionTier` がその値であること、指定しないときは今と同じ中身であることを確かめる。
- 受け入れの実機確認（指定した段階が `session-state/<id>/events.jsonl` の `session.fusion_resolved` の `data.policy` に出る）は、README「変更後の確認」に手順を書き、保守者が 1 回行う。canary のスクリプトには足さない（canary は sandbox の確認が目的で、段階は関係しない）。
- README の Copilot の節に口を書く。利用者から見える起動の引数が増えるので、SemVer のマイナーの番号案をタグの提案に添える。

## 実装者に任せること

- テスト（`tests/test_copilot_launcher.py` など）の形。振る舞い（取り除く、書く、止まる、指定なしで変わらない）を確かめるものにする。
