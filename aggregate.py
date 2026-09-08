#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retainer-log 集計スクリプト

log.txt は歯科矯正の保定装置（マウスピース）を外していた時刻の記録。
1日ごとに【朝】【昼】【夜】の区分があり、各区分に
    「外した時刻-つけた時刻」のペアが、複数あれば「、」区切りで並ぶ。

例:
    2026/1/27（火）
    【朝】6:18-6:52
    【夜】17:30-17:43、20:01-20:33

使い方:
    python aggregate.py                    log.txt 全体（月ごと＋全期間通算）
    python aggregate.py other.txt          別ファイルを集計
    python aggregate.py --month 2026-02    2026年2月だけ集計
    python aggregate.py other.txt -m 2026-02
"""

import sys
import re
import argparse
from datetime import date, timedelta
from pathlib import Path

# PowerShellの画面にそのまま表示する想定。文字化けする場合は
# 事前に `chcp 65001` を実行してから python を起動してください。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WEEKDAY_CHARS = ["月", "火", "水", "木", "金", "土", "日"]
LABELS = ["朝", "昼", "夜"]

DATE_RE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})（(.)）\s*$")
SECTION_RE = re.compile(r"^【(朝|昼|夜)】(.*)$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
MONTH_ARG_RE = re.compile(r"^(\d{4})-(\d{1,2})$")

DAILY_LIMIT_MIN = 240  # 1日の目標上限(4時間)
BAR_WIDTH = 20


def format_hm(minutes):
    """分 -> "H時間M分" 表記。負値はそのまま(異常値確認用)。"""
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    h, m = divmod(minutes, 60)
    return f"{sign}{h}時間{m}分"


def add_warning(warnings, when, text):
    """
    warnings に構造化した警告を追記する。
    when: 関連する date、または日付が特定できない場合は None。
    """
    warnings.append({"date": when, "text": text})


def parse_time(token):
    """
    "8:24" のような文字列を分(0-1439)に変換する。
    戻り値: (分, エラーメッセージ or None)
    """
    token = token.strip()
    m = TIME_RE.match(token)
    if not m:
        return None, f"時刻の形式が不正です: '{token}'"
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, f"存在しない時刻です: '{token}'"
    return hour * 60 + minute, None


def parse_pair(chunk, label, day_str, when, warnings):
    """
    "8:24-9:22" のようなペア文字列を (start_min, end_min) に変換する。
    不正な場合は None を返し、warnings に追記する。
    """
    chunk = chunk.strip()
    if not chunk:
        return None
    parts = chunk.split("-")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        add_warning(warnings, when, f"[時刻不正] {day_str} 【{label}】: 片方しか時刻がありません ('{chunk}')")
        return None

    start_str, end_str = parts[0], parts[1]
    start_min, err1 = parse_time(start_str)
    end_min, err2 = parse_time(end_str)

    if err1:
        add_warning(warnings, when, f"[時刻不正] {day_str} 【{label}】: {err1}")
    if err2:
        add_warning(warnings, when, f"[時刻不正] {day_str} 【{label}】: {err2}")
    if err1 or err2:
        return None

    if end_min < start_min:
        add_warning(
            warnings, when,
            f"[時刻不正] {day_str} 【{label}】: 終了({end_str})が開始({start_str})より前です ('{chunk}')",
        )
        return None

    return (start_min, end_min)


def parse_log(path):
    """
    log.txt を読み込み、日ごとのレコードのリストを返す。
    各レコード:
        {
            "date": date または None(パース失敗時),
            "weekday_char": 元テキストの曜日文字,
            "raw": 元の日付行,
            "sections": {"朝": [(start,end),...], "昼": [...], "夜": [...]},
            "present_labels": {"朝","夜"} のような、行として存在した区分の集合,
        }
    warnings: {"date": date または None, "text": str} のリスト
    """
    days = []
    warnings = []
    current = None

    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue

        m = DATE_RE.match(line)
        if m:
            year, month, day, wd_char = m.groups()
            try:
                d = date(int(year), int(month), int(day))
            except ValueError:
                d = None
                add_warning(warnings, None, f"[日付不正] {line} (行{lineno}): カレンダー上存在しない日付です")
            current = {
                "date": d,
                "weekday_char": wd_char,
                "raw": line,
                "sections": {label: [] for label in LABELS},
                "present_labels": set(),
            }
            days.append(current)
            continue

        m = SECTION_RE.match(line)
        if m and current is not None:
            label, rest = m.groups()
            current["present_labels"].add(label)
            day_str = current["raw"]
            when = current["date"]
            chunks = rest.split("、")
            pairs = []
            for chunk in chunks:
                pair = parse_pair(chunk, label, day_str, when, warnings)
                if pair is not None:
                    pairs.append(pair)
            # 同一区分内の重なりチェック
            pairs_sorted = sorted(pairs, key=lambda p: p[0])
            for i in range(1, len(pairs_sorted)):
                prev_start, prev_end = pairs_sorted[i - 1]
                cur_start, cur_end = pairs_sorted[i]
                if cur_start < prev_end:
                    add_warning(
                        warnings, when,
                        f"[重なり] {day_str} 【{label}】: "
                        f"{prev_start//60}:{prev_start%60:02d}-{prev_end//60}:{prev_end%60:02d} と "
                        f"{cur_start//60}:{cur_start%60:02d}-{cur_end//60}:{cur_end%60:02d} が重なっています",
                    )
            current["sections"][label] = pairs
            continue

        add_warning(
            warnings, current["date"] if current is not None else None,
            f"[解析不能] 行{lineno}: '{raw_line}' を認識できませんでした",
        )

    return days, warnings


def check_dates(days, warnings):
    """曜日不一致・日付の飛びをチェックする。"""
    for rec in days:
        if rec["date"] is None:
            continue
        actual_wd = WEEKDAY_CHARS[rec["date"].weekday()]
        if actual_wd != rec["weekday_char"]:
            add_warning(warnings, rec["date"], f"[曜日不一致] {rec['raw']}: 実際の曜日は「{actual_wd}」です")

    # ファイルは新しい日付が先頭の降順想定。連続する行の日付差が1日でない箇所を検出。
    dated = [rec for rec in days if rec["date"] is not None]
    for i in range(1, len(dated)):
        prev_d = dated[i - 1]["date"]
        cur_d = dated[i]["date"]
        expected = prev_d - timedelta(days=1)
        if cur_d != expected:
            # 新しい方(prev_d)の月に紐付けて表示する
            add_warning(
                warnings, prev_d,
                f"[日付の飛び] {dated[i-1]['raw']} の次が {dated[i]['raw']} になっています"
                f"（期待される日付: {expected.strftime('%Y/%m/%d')}）",
            )


def check_missing_sections(rec, warnings):
    """朝・夜は常に警告。昼は土日のみ警告(平日の昼欠けは正常)。"""
    day_str = rec["raw"]
    present = rec["present_labels"]

    if "朝" not in present:
        add_warning(warnings, rec["date"], f"[区分欠け] {day_str}: 【朝】の記録がありません")
    if "夜" not in present:
        add_warning(warnings, rec["date"], f"[区分欠け] {day_str}: 【夜】の記録がありません")
    if "昼" not in present:
        if rec["date"] is not None and rec["date"].weekday() in (5, 6):  # 土,日
            add_warning(warnings, rec["date"], f"[区分欠け] {day_str}: 【昼】の記録がありません(休日)")
        # 平日の昼欠けは正常なので警告しない


def summarize(days):
    """
    与えられた日次レコード群について、日ごとの合計時間と、
    区分ごとの時間の一覧を計算する。
    区分の時間 = その区分内の有効なペアの合計(分)。
    """
    daily_totals = []      # [(rec, 分)]
    section_records = []   # [(rec, label, 分)]

    for rec in days:
        if rec["date"] is None:
            continue
        day_total = 0
        for label in LABELS:
            pairs = rec["sections"][label]
            if not pairs:
                continue
            section_minutes = sum(end - start for start, end in pairs)
            section_records.append((rec, label, section_minutes))
            day_total += section_minutes
        daily_totals.append((rec, day_total))

    return daily_totals, section_records


def make_bar(minutes, width=BAR_WIDTH, limit=DAILY_LIMIT_MIN):
    """4時間(limit)を基準にした割合バーを作る。"""
    ratio = minutes / limit if limit else 0
    filled = round(min(ratio, 1.0) * width)
    filled = max(0, min(filled, width))
    bar = "█" * filled + "░" * (width - filled)
    pct = round(ratio * 100)
    marker = " ⚠" if minutes > limit else ""
    return f"[{bar}] {pct:3d}%{marker}"


def print_stats_block(daily_totals, section_records):
    """月合計・月平均などの数値をまとめて表示する。"""
    month_total = sum(total for _, total in daily_totals)
    num_days = len(daily_totals)
    month_avg = month_total / num_days if num_days else 0

    num_sections = len(section_records)
    section_avg = sum(m for _, _, m in section_records) / num_sections if num_sections else 0

    print(f"合計時間          : {format_hm(month_total)}")
    print(f"平均時間(1日あたり): {format_hm(round(month_avg))} (記録日数 {num_days}日)")
    print(f"1回あたりの平均時間: {format_hm(round(section_avg))} (外した回数 {num_sections}回)")

    if section_records:
        longest = max(section_records, key=lambda x: x[2])
        shortest = min(section_records, key=lambda x: x[2])
        print(f"いちばん長く外した時間: {format_hm(longest[2])} ({longest[0]['raw']} 【{longest[1]}】)")
        print(f"いちばん短く外した時間: {format_hm(shortest[2])} ({shortest[0]['raw']} 【{shortest[1]}】)")


def print_daily_table(daily_totals):
    print(f"日ごとの内訳  (目標4時間 = バー全埋め)")
    print("-" * 62)
    for rec, total in daily_totals:
        d = rec["date"]
        wd = WEEKDAY_CHARS[d.weekday()]
        label = f"{d.month:02d}/{d.day:02d}({wd})"
        print(f"{label}  {format_hm(total):>8}  {make_bar(total)}")
    print("-" * 62)


def print_warnings(month_warnings):
    print(f"警告 ({len(month_warnings)}件)")
    print("-" * 62)
    if month_warnings:
        for w in month_warnings:
            print(w["text"])
    else:
        print("警告はありません。")


def month_key_of(d):
    return (d.year, d.month)


def main():
    default_path = Path(__file__).resolve().parent / "log.txt"

    parser = argparse.ArgumentParser(description="保定装置を外していた時間の集計")
    parser.add_argument("file", nargs="?", default=None, help="log.txtへのパス(省略時はスクリプト横のlog.txt)")
    parser.add_argument("--month", "-m", default=None, help="集計対象を絞り込む月。形式: YYYY-MM (例: 2026-02)")
    args = parser.parse_args()

    path = Path(args.file) if args.file else default_path
    if not path.exists():
        print(f"ファイルが見つかりません: {path}")
        sys.exit(1)

    target_month = None
    if args.month:
        m = MONTH_ARG_RE.match(args.month)
        if not m:
            print(f"--month の形式が不正です: '{args.month}' (例: 2026-02)")
            sys.exit(1)
        target_month = (int(m.group(1)), int(m.group(2)))

    days, warnings = parse_log(path)
    check_dates(days, warnings)
    for rec in days:
        if rec["date"] is not None:
            check_missing_sections(rec, warnings)

    all_daily_totals, all_section_records = summarize(days)

    # 1日の合計が4時間(240分)を超える日を警告
    for rec, total in all_daily_totals:
        if total > DAILY_LIMIT_MIN:
            add_warning(warnings, rec["date"], f"[4時間超過] {rec['raw']}: 合計 {format_hm(total)}")

    print("=" * 62)
    print("保定装置(マウスピース)を外していた時間の集計")
    print("=" * 62)

    if not all_daily_totals:
        print("有効な日次データがありません。")
        return

    month_keys = sorted({month_key_of(rec["date"]) for rec, _ in all_daily_totals}, reverse=True)

    if target_month is not None:
        if target_month not in month_keys:
            y, m = target_month
            print(f"{y}年{m}月のデータが見つかりません。")
            sys.exit(1)
        month_keys = [target_month]

    def warnings_for(pred):
        return [w for w in warnings if w["date"] is not None and pred(w["date"])]

    # ---- 全期間 通算(複数月あり、かつ月指定なしのときだけ表示) ----
    if target_month is None and len(month_keys) > 1:
        min_d = min(rec["date"] for rec, _ in all_daily_totals)
        max_d = max(rec["date"] for rec, _ in all_daily_totals)
        print()
        print("=" * 62)
        print(f" 全期間 通算 ({min_d.strftime('%Y/%m')} - {max_d.strftime('%Y/%m')})")
        print("=" * 62)
        print_stats_block(all_daily_totals, all_section_records)

    # ---- 月ごとのセクション ----
    for y, m in month_keys:
        month_days = [rec for rec, _ in all_daily_totals if month_key_of(rec["date"]) == (y, m)]
        month_daily_totals = [(rec, total) for rec, total in all_daily_totals if month_key_of(rec["date"]) == (y, m)]
        month_section_records = [
            (rec, label, mins) for rec, label, mins in all_section_records if month_key_of(rec["date"]) == (y, m)
        ]
        month_total = sum(total for _, total in month_daily_totals)
        month_warns = warnings_for(lambda d, y=y, m=m: month_key_of(d) == (y, m))

        print()
        print("=" * 62)
        print(f" {y}年{m:02d}月  (月合計 {format_hm(month_total)} / 回数 {len(month_section_records)}回)")
        print("=" * 62)
        print_stats_block(month_daily_totals, month_section_records)
        print()
        print_daily_table(month_daily_totals)
        print()
        print_warnings(sorted(month_warns, key=lambda w: w["date"], reverse=True))

    # ---- 日付に紐づかない警告(月指定なしのときだけ) ----
    dateless = [w for w in warnings if w["date"] is None]
    if target_month is None and dateless:
        print()
        print("=" * 62)
        print(" 月に紐づかない警告")
        print("=" * 62)
        print_warnings(dateless)


if __name__ == "__main__":
    main()
