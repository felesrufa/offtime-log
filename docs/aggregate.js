/*
 * retainer-log 集計ロジック（JavaScript 版）
 *
 * aggregate.py の build_report() と同じ結果（同じ JSON）を返すように移植したもの。
 * ブラウザ（PWA）と node の両方で動く。仕様の正本は aggregate.py で、
 * 両者の一致は tests/parity.py で確認する。
 *
 *   const report = RetainerLog.buildReport(text, { today: "2026-09-13" });
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.RetainerLog = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const WEEKDAY_CHARS = ["月", "火", "水", "木", "金", "土", "日"];
  const LABELS = ["朝", "昼", "夜"];

  const DATE_RE = /^(\d{4})\/(\d{1,2})\/(\d{1,2})（(.)）\s*$/;
  const SECTION_RE = /^【(朝|昼|夜)】(.*)$/;
  const TIME_RE = /^(\d{1,2}):(\d{2})$/;
  const TAP_RE = /^(\d{4})\/(\d{1,2})\/(\d{1,2})[ 　]+(\d{1,2}):(\d{2})[ 　]*(外|着)[ 　]*$/;

  const DAILY_LIMIT_MIN = 240;   // 1日の目標上限(4時間)
  const NOON_START_MIN = 11 * 60;    // これより前に外した → 【朝】
  const EVENING_START_MIN = 16 * 60; // これより前に外した → 【昼】、以降 → 【夜】

  // ---------------------------------------------------------- 日付ユーティリティ
  // 日付は「1970-01-01 からの日数」(整数) で扱う。比較・翌日計算が簡単になる。
  const MS_PER_DAY = 86400000;

  function makeDay(y, m, d) {
    const t = Date.UTC(y, m - 1, d);
    const dt = new Date(t);
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) {
      return null;
    }
    return Math.round(t / MS_PER_DAY);
  }

  function ymd(day) {
    const dt = new Date(day * MS_PER_DAY);
    return { y: dt.getUTCFullYear(), m: dt.getUTCMonth() + 1, d: dt.getUTCDate() };
  }

  function weekday(day) {
    // Python の date.weekday() と同じく 月=0 ... 日=6
    return (new Date(day * MS_PER_DAY).getUTCDay() + 6) % 7;
  }

  function pad2(n) {
    return (n < 10 ? "0" : "") + n;
  }

  function isoDate(day) {
    const { y, m, d } = ymd(day);
    return `${y}-${pad2(m)}-${pad2(d)}`;
  }

  function slashDate(day) {
    const { y, m, d } = ymd(day);
    return `${y}/${pad2(m)}/${pad2(d)}`;
  }

  function dayLabel(day) {
    const { y, m, d } = ymd(day);
    return `${y}/${m}/${d}（${WEEKDAY_CHARS[weekday(day)]}）`;
  }

  function monthKey(day) {
    const { y, m } = ymd(day);
    return y * 100 + m;
  }

  function parseIsoDay(s) {
    const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
    if (!m) return null;
    return makeDay(+m[1], +m[2], +m[3]);
  }

  function todayLocal() {
    const now = new Date();
    return makeDay(now.getFullYear(), now.getMonth() + 1, now.getDate());
  }

  // ---------------------------------------------------------- 表示ユーティリティ
  function formatHm(minutes) {
    const sign = minutes < 0 ? "-" : "";
    minutes = Math.abs(minutes);
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return `${sign}${h}時間${m}分`;
  }

  function formatTime(minutes) {
    return `${Math.floor(minutes / 60)}:${pad2(minutes % 60)}`;
  }

  // Python の round() (偶数丸め) と同じ結果にする
  function pyRound(x) {
    const f = Math.floor(x);
    const diff = x - f;
    if (diff < 0.5) return f;
    if (diff > 0.5) return f + 1;
    return f % 2 === 0 ? f : f + 1;
  }

  // ---------------------------------------------------------- 解析
  function addWarning(warnings, when, text) {
    warnings.push({ date: when, text: text });
  }

  function newRecord(day, weekdayChar, raw) {
    const sections = {};
    for (const label of LABELS) sections[label] = [];
    return { date: day, weekday_char: weekdayChar, raw: raw, sections: sections, present: new Set() };
  }

  function sectionOf(startMin) {
    if (startMin < NOON_START_MIN) return "朝";
    if (startMin < EVENING_START_MIN) return "昼";
    return "夜";
  }

  function parseTime(token) {
    token = token.trim();
    const m = TIME_RE.exec(token);
    if (!m) return [null, `時刻の形式が不正です: '${token}'`];
    const hour = +m[1], minute = +m[2];
    if (!(hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59)) {
      return [null, `存在しない時刻です: '${token}'`];
    }
    return [hour * 60 + minute, null];
  }

  function parsePair(chunk, label, dayStr, when, warnings) {
    chunk = chunk.trim();
    if (!chunk) return null;
    const parts = chunk.split("-");
    if (parts.length !== 2 || !parts[0].trim() || !parts[1].trim()) {
      addWarning(warnings, when, `[時刻不正] ${dayStr} 【${label}】: 片方しか時刻がありません ('${chunk}')`);
      return null;
    }
    const [startStr, endStr] = parts;
    const [startMin, err1] = parseTime(startStr);
    const [endMin, err2] = parseTime(endStr);
    if (err1) addWarning(warnings, when, `[時刻不正] ${dayStr} 【${label}】: ${err1}`);
    if (err2) addWarning(warnings, when, `[時刻不正] ${dayStr} 【${label}】: ${err2}`);
    if (err1 || err2) return null;
    if (endMin < startMin) {
      addWarning(
        warnings, when,
        `[時刻不正] ${dayStr} 【${label}】: 終了(${endStr})が開始(${startStr})より前です ('${chunk}')`
      );
      return null;
    }
    return [startMin, endMin];
  }

  function parseLogText(text) {
    const days = [];
    const taps = [];
    const warnings = [];
    let current = null;

    const lines = text.split(/\r\n|\r|\n/);
    for (let i = 0; i < lines.length; i++) {
      const lineno = i + 1;
      const rawLine = lines[i];
      const line = rawLine.trim();
      if (!line) continue;

      let m = TAP_RE.exec(line);
      if (m) {
        const day = makeDay(+m[1], +m[2], +m[3]);
        const hour = +m[4], minute = +m[5];
        if (day === null || hour > 23 || minute > 59) {
          addWarning(warnings, null, `[日付不正] ${line} (行${lineno}): 存在しない日時です`);
          continue;
        }
        taps.push({ day: day, min: hour * 60 + minute, kind: m[6], raw: line, lineno: lineno });
        continue;
      }

      m = DATE_RE.exec(line);
      if (m) {
        const day = makeDay(+m[1], +m[2], +m[3]);
        if (day === null) {
          addWarning(warnings, null, `[日付不正] ${line} (行${lineno}): カレンダー上存在しない日付です`);
        }
        current = newRecord(day, m[4], line);
        days.push(current);
        continue;
      }

      m = SECTION_RE.exec(line);
      if (m && current !== null) {
        const label = m[1];
        current.present.add(label);
        for (const chunk of m[2].split("、")) {
          const pair = parsePair(chunk, label, current.raw, current.date, warnings);
          if (pair !== null) current.sections[label].push(pair);
        }
        continue;
      }

      addWarning(
        warnings, current !== null ? current.date : null,
        `[解析不能] 行${lineno}: '${rawLine}' を認識できませんでした`
      );
    }
    return { days, taps, warnings };
  }

  function buildTapDays(taps, warnings, today) {
    const events = taps.slice().sort((a, b) =>
      (a.day - b.day) || (a.min - b.min) || (a.lineno - b.lineno)
    );
    const byDate = new Map();

    function addPair(day, startMin, endMin) {
      if (endMin <= startMin) return; // 0分は打ち直し扱いで無視
      if (!byDate.has(day)) {
        byDate.set(day, newRecord(day, WEEKDAY_CHARS[weekday(day)], dayLabel(day)));
      }
      const rec = byDate.get(day);
      const label = sectionOf(startMin);
      rec.sections[label].push([startMin, endMin]);
      rec.present.add(label);
    }

    let pending = null;
    let ongoing = null;
    for (const ev of events) {
      if (ev.kind === "外") {
        if (pending !== null) {
          addWarning(warnings, pending.day,
            `[打刻不整合] ${pending.raw}: 「着」の打刻がないまま次の「外」があります（この「外」は無視）`);
        }
        pending = ev;
        continue;
      }
      if (pending === null) {
        addWarning(warnings, ev.day, `[打刻不整合] ${ev.raw}: 直前に「外」の打刻がありません（無視）`);
        continue;
      }
      if (ev.day === pending.day) {
        addPair(pending.day, pending.min, ev.min);
      } else if (ev.day === pending.day + 1) {
        addWarning(warnings, pending.day,
          `[日跨ぎ] ${pending.raw} → ${ev.raw}: 日付をまたいでいるので 24:00 で分割しました`);
        addPair(pending.day, pending.min, 24 * 60);
        addPair(ev.day, 0, ev.min);
      } else {
        addWarning(warnings, pending.day,
          `[打刻不整合] ${pending.raw} → ${ev.raw}: 2日以上離れています（無視）`);
      }
      pending = null;
    }

    if (pending !== null) {
      if (pending.day === today) {
        ongoing = pending;
      } else {
        addWarning(warnings, pending.day, `[打刻不整合] ${pending.raw}: 「着」の打刻がありません`);
      }
    }
    return { byDate, ongoing };
  }

  function mergeDays(structured, tapByDate, warnings) {
    const days = structured.slice();
    const dated = new Map();
    for (const rec of structured) {
      if (rec.date !== null) dated.set(rec.date, rec);
    }
    const keys = Array.from(tapByDate.keys()).sort((a, b) => a - b);
    for (const day of keys) {
      const trec = tapByDate.get(day);
      if (dated.has(day)) {
        const rec = dated.get(day);
        for (const label of LABELS) {
          if (trec.sections[label].length) {
            rec.sections[label].push(...trec.sections[label]);
            rec.present.add(label);
          }
        }
        addWarning(warnings, day, `[重複日付] ${rec.raw}: 手書き形式と打刻形式の両方に記録があります（合算しました）`);
      } else {
        days.push(trec);
      }
    }
    return days;
  }

  function sortDays(days) {
    const dated = days.filter((r) => r.date !== null).sort((a, b) => b.date - a.date);
    const undated = days.filter((r) => r.date === null);
    return dated.concat(undated);
  }

  function checkDates(days, warnings) {
    for (const rec of days) {
      if (rec.date === null) continue;
      const actual = WEEKDAY_CHARS[weekday(rec.date)];
      if (actual !== rec.weekday_char) {
        addWarning(warnings, rec.date, `[曜日不一致] ${rec.raw}: 実際の曜日は「${actual}」です`);
      }
    }
    const dated = days.filter((r) => r.date !== null);
    for (let i = 1; i < dated.length; i++) {
      const prevD = dated[i - 1].date;
      const curD = dated[i].date;
      if (curD === prevD) {
        addWarning(warnings, prevD, `[重複日付] ${dated[i].raw} が2回あります`);
        continue;
      }
      const expected = prevD - 1;
      if (curD !== expected) {
        addWarning(warnings, prevD,
          `[日付の飛び] ${dated[i - 1].raw} の次が ${dated[i].raw} になっています（期待される日付: ${slashDate(expected)}）`);
      }
    }
  }

  function checkOverlaps(days, warnings) {
    for (const rec of days) {
      for (const label of LABELS) {
        const pairs = rec.sections[label].slice().sort((a, b) => a[0] - b[0]);
        for (let i = 1; i < pairs.length; i++) {
          const [ps, pe] = pairs[i - 1];
          const [cs, ce] = pairs[i];
          if (cs < pe) {
            addWarning(warnings, rec.date,
              `[重なり] ${rec.raw} 【${label}】: ${formatTime(ps)}-${formatTime(pe)} と ${formatTime(cs)}-${formatTime(ce)} が重なっています`);
          }
        }
      }
    }
  }

  function checkMissingSections(rec, warnings, today) {
    if (rec.date === today) return;
    const p = rec.present;
    if (!p.has("朝")) addWarning(warnings, rec.date, `[区分欠け] ${rec.raw}: 【朝】の記録がありません`);
    if (!p.has("夜")) addWarning(warnings, rec.date, `[区分欠け] ${rec.raw}: 【夜】の記録がありません`);
    if (!p.has("昼")) {
      if (rec.date !== null && weekday(rec.date) >= 5) {
        addWarning(warnings, rec.date, `[区分欠け] ${rec.raw}: 【昼】の記録がありません(休日)`);
      }
    }
  }

  function summarize(days) {
    const dailyTotals = [];
    const sectionRecords = [];
    for (const rec of days) {
      if (rec.date === null) continue;
      let dayTotal = 0;
      for (const label of LABELS) {
        const pairs = rec.sections[label];
        if (!pairs.length) continue;
        let mins = 0;
        for (const [s, e] of pairs) mins += e - s;
        sectionRecords.push({ rec, label, minutes: mins });
        dayTotal += mins;
      }
      dailyTotals.push({ rec, total: dayTotal });
    }
    return { dailyTotals, sectionRecords };
  }

  function makeStats(dailyTotals, sectionRecords) {
    let total = 0;
    for (const d of dailyTotals) total += d.total;
    let sectionTotal = 0;
    for (const s of sectionRecords) sectionTotal += s.minutes;
    const stats = {
      total: total,
      days: dailyTotals.length,
      sections: sectionRecords.length,
      section_total: sectionTotal,
      longest: null,
      shortest: null,
    };
    if (sectionRecords.length) {
      // Python の max/min と同じく「最初に現れた」最大・最小を採用する
      let lg = sectionRecords[0], sh = sectionRecords[0];
      for (const s of sectionRecords) {
        if (s.minutes > lg.minutes) lg = s;
        if (s.minutes < sh.minutes) sh = s;
      }
      stats.longest = { minutes: lg.minutes, raw: lg.rec.raw, label: lg.label };
      stats.shortest = { minutes: sh.minutes, raw: sh.rec.raw, label: sh.label };
    }
    return stats;
  }

  function analyze(text, today) {
    const { days: structured, taps, warnings } = parseLogText(text);
    const { byDate, ongoing } = buildTapDays(taps, warnings, today);
    const days = sortDays(mergeDays(structured, byDate, warnings));
    checkDates(days, warnings);
    checkOverlaps(days, warnings);
    for (const rec of days) {
      if (rec.date !== null) checkMissingSections(rec, warnings, today);
    }
    const { dailyTotals, sectionRecords } = summarize(days);
    for (const d of dailyTotals) {
      if (d.total > DAILY_LIMIT_MIN) {
        addWarning(warnings, d.rec.date, `[4時間超過] ${d.rec.raw}: 合計 ${formatHm(d.total)}`);
      }
    }
    return { days, warnings, ongoing, dailyTotals, sectionRecords };
  }

  /**
   * text: log.txt の中身
   * opts.today: "YYYY-MM-DD"（省略時は端末の今日）
   * opts.month: "YYYY-MM"（省略時は全月）
   * 戻り値: aggregate.py の build_report() と同じ構造
   */
  function buildReport(text, opts) {
    opts = opts || {};
    const today = opts.today ? parseIsoDay(opts.today) : todayLocal();
    let targetMonth = null;
    if (opts.month) {
      const m = /^(\d{4})-(\d{1,2})$/.exec(opts.month);
      if (!m) return { error: `--month の形式が不正です: '${opts.month}' (例: 2026-02)` };
      targetMonth = (+m[1]) * 100 + (+m[2]);
    }

    const { warnings, ongoing, dailyTotals, sectionRecords } = analyze(text, today);
    const report = {
      today: isoDate(today),
      ongoing: null,
      overall: null,
      months: [],
      dateless_warnings: [],
    };
    if (ongoing !== null) {
      report.ongoing = { date: isoDate(ongoing.day), start_min: ongoing.min, raw: ongoing.raw };
    }
    const datelessTexts = () => warnings.filter((w) => w.date === null).map((w) => w.text);

    if (!dailyTotals.length) {
      report.dateless_warnings = datelessTexts();
      return report;
    }

    let monthKeys = Array.from(new Set(dailyTotals.map((d) => monthKey(d.rec.date)))).sort((a, b) => b - a);
    if (targetMonth !== null) {
      if (!monthKeys.includes(targetMonth)) {
        return { error: `${Math.floor(targetMonth / 100)}年${targetMonth % 100}月のデータが見つかりません。` };
      }
      monthKeys = [targetMonth];
    }

    if (targetMonth === null && monthKeys.length > 1) {
      let minD = dailyTotals[0].rec.date, maxD = minD;
      for (const d of dailyTotals) {
        if (d.rec.date < minD) minD = d.rec.date;
        if (d.rec.date > maxD) maxD = d.rec.date;
      }
      const a = ymd(minD), b = ymd(maxD);
      report.overall = {
        from: `${a.y}/${pad2(a.m)}`,
        to: `${b.y}/${pad2(b.m)}`,
        stats: makeStats(dailyTotals, sectionRecords),
      };
    }

    for (const mk of monthKeys) {
      const mDaily = dailyTotals.filter((d) => monthKey(d.rec.date) === mk);
      const mSections = sectionRecords.filter((s) => monthKey(s.rec.date) === mk);
      const mWarns = warnings
        .filter((w) => w.date !== null && monthKey(w.date) === mk)
        .sort((a, b) => b.date - a.date);
      report.months.push({
        year: Math.floor(mk / 100),
        month: mk % 100,
        stats: makeStats(mDaily, mSections),
        days: mDaily.map((d) => {
          const sections = {};
          for (const label of LABELS) sections[label] = d.rec.sections[label].map((p) => p.slice());
          return {
            date: isoDate(d.rec.date),
            weekday: WEEKDAY_CHARS[weekday(d.rec.date)],
            raw: d.rec.raw,
            total: d.total,
            sections: sections,
          };
        }),
        warnings: mWarns.map((w) => w.text),
      });
    }

    if (targetMonth === null) report.dateless_warnings = datelessTexts();
    return report;
  }

  return {
    buildReport,
    formatHm,
    formatTime,
    pyRound,
    parseIsoDay,
    isoDate,
    ymd,
    weekday,
    WEEKDAY_CHARS,
    LABELS,
    DAILY_LIMIT_MIN,
  };
});
