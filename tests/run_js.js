// node tests/run_js.js <file> <today YYYY-MM-DD> [month YYYY-MM]
// docs/aggregate.js を node で実行して JSON を出力する（parity.py から使う）。
const fs = require("fs");
const path = require("path");
const OfftimeLog = require(path.join(__dirname, "..", "docs", "aggregate.js"));

const [file, today, month] = process.argv.slice(2);
let text = fs.readFileSync(file, "utf8");
if (text.charCodeAt(0) === 0xfeff) text = text.slice(1); // BOM は Python (utf-8-sig) と同様に除去
const report = OfftimeLog.buildReport(text, { today, month });
process.stdout.write(JSON.stringify(report, null, 2) + "\n");
