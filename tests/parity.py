#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aggregate.py と docs/aggregate.js が同じ結果を返すことを確認する。

    python tests/parity.py

tests/*.txt と（あれば）log.txt, test_log.txt を対象に、
--today を固定した状態で両者の JSON を比較する。--month 指定も1ケース確認する。
node が必要。
"""
import sys
import json
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = "2026-09-13"


def run_py(file, month=None):
    cmd = [sys.executable, str(ROOT / "aggregate.py"), str(file), "--json", "--today", TODAY]
    if month:
        cmd += ["--month", month]
    out = subprocess.run(cmd, capture_output=True, encoding="utf-8")
    return out.returncode, out.stdout


def run_js(file, month=None):
    cmd = ["node", str(ROOT / "tests" / "run_js.js"), str(file), TODAY]
    if month:
        cmd.append(month)
    out = subprocess.run(cmd, capture_output=True, encoding="utf-8", shell=(sys.platform == "win32"))
    return out.returncode, out.stdout


def compare(label, py_out, js_out):
    try:
        a = json.loads(py_out)
        b = json.loads(js_out)
    except json.JSONDecodeError as e:
        print(f"[NG] {label}: JSON を読めません ({e})")
        print("--- python ---", py_out[:500], "--- js ---", js_out[:500], sep="\n")
        return False
    if a == b:
        months = ", ".join(f"{m['year']}/{m['month']:02d}({m['stats']['total']}分, 警告{len(m['warnings'])})" for m in a.get("months", []))
        print(f"[OK] {label}: {months or 'データなし'}")
        return True
    print(f"[NG] {label}: 結果が一致しません")
    sa = json.dumps(a, ensure_ascii=False, indent=1, sort_keys=True).splitlines()
    sb = json.dumps(b, ensure_ascii=False, indent=1, sort_keys=True).splitlines()
    import difflib
    for line in difflib.unified_diff(sa, sb, "python", "js", lineterm="", n=2):
        print(line)
    return False


def main():
    files = sorted((ROOT / "tests").glob("*.txt"))
    for name in ("log.txt", "test_log.txt"):
        if (ROOT / name).exists():
            files.append(ROOT / name)

    ok = True
    for f in files:
        rc_py, py_out = run_py(f)
        rc_js, js_out = run_js(f)
        ok &= compare(f.name, py_out, js_out)

    # --month の絞り込みも1ケース確認（存在する月は python 側の結果から拾う）
    sample = ROOT / "tests" / "sample_taps.txt"
    if sample.exists():
        rep = json.loads(run_py(sample)[1])
        if rep.get("months"):
            m = rep["months"][0]
            month = f"{m['year']}-{m['month']:02d}"
            ok &= compare(f"{sample.name} --month {month}", run_py(sample, month)[1], run_js(sample, month)[1])
        # 存在しない月はどちらも error を返す
        pe, je = run_py(sample, "1999-01")[1], run_js(sample, "1999-01")[1]
        if pe.strip() == json.loads(je)["error"]:
            print("[OK] 存在しない月: 両者とも同じエラー")
        else:
            print(f"[NG] 存在しない月: python='{pe.strip()}' js='{je.strip()}'")
            ok = False

    print("ALL OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
