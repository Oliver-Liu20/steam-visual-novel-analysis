import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/, "$1")), "..");
const processedDir = path.join(root, "data", "processed");
const outputDir = path.join(root, "outputs");
const previewDir = path.join(outputDir, "previews");
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const files = {
  Games: "final_visual_novels_2020_2025.csv",
  "VNDB Only": "difference_vndb_only.csv",
  "Steam Only": "difference_steam_only.csv",
  "Source Summary": "source_comparison_summary.csv",
  Excluded: "excluded_candidates.csv",
};

const csvData = {};
const rowCounts = {};
function parseCSV(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (ch === '"') {
        quoted = false;
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += ch;
    }
  }
  if (field.length || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  return rows.map((cells, rowIndex) => cells.map((value) => {
    if (rowIndex === 0) return value;
    if (value === "") return null;
    if (/^(true|false)$/i.test(value)) return value.toLowerCase() === "true";
    if (/^-?\d+(?:\.\d+)?$/.test(value)) return Number(value);
    return value;
  }));
}
for (const [sheetName, fileName] of Object.entries(files)) {
  const text = await fs.readFile(path.join(processedDir, fileName), "utf8");
  csvData[sheetName] = parseCSV(text);
  rowCounts[sheetName] = csvData[sheetName].length;
}

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const monthly = workbook.worksheets.add("Monthly");
const notes = workbook.worksheets.add("Notes");

for (const [sheetName, values] of Object.entries(csvData)) {
  const sheet = workbook.worksheets.add(sheetName);
  const colCount = values[0].length;
  const lastCol = String.fromCharCode(64 + colCount);
  sheet.getRange(`A1:${lastCol}${values.length}`).values = values;
}

const colors = {
  navy: "#17324D",
  teal: "#0F766E",
  tealLight: "#DDF3EF",
  blueLight: "#E8F0F8",
  amberLight: "#FFF3D6",
  redLight: "#FDE8E7",
  greenLight: "#E5F5EA",
  gray: "#5F6B76",
  grid: "#D9E1E8",
  white: "#FFFFFF",
};

function styleImportedSheet(sheetName, lastCol, tableName) {
  const sheet = workbook.worksheets.getItem(sheetName);
  const rows = rowCounts[sheetName];
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  const used = sheet.getRange(`A1:${lastCol}${rows}`);
  used.format.font = { name: "Aptos", size: 10, color: "#1F2933" };
  used.format.wrapText = false;
  const header = sheet.getRange(`A1:${lastCol}1`);
  header.format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 10 },
    rowHeight: 34,
    verticalAlignment: "center",
  };
  header.format.wrapText = true;
  used.format.autofitColumns();
  const table = sheet.tables.add(`A1:${lastCol}${rows}`, true, tableName);
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
  return sheet;
}

const games = styleImportedSheet("Games", "Z", "GamesTable");
const vndbOnly = styleImportedSheet("VNDB Only", "T", "VNDBOnlyTable");
const steamOnly = styleImportedSheet("Steam Only", "T", "SteamOnlyTable");
const sourceSummary = styleImportedSheet("Source Summary", "C", "SourceSummaryTable");
const excluded = styleImportedSheet("Excluded", "T", "ExcludedTable");

for (const sheet of [games, vndbOnly, steamOnly, excluded]) {
  sheet.getRange("A:A").format.columnWidth = 13;
  sheet.getRange("B:B").format.columnWidth = 32;
  sheet.getRange("C:C").format.columnWidth = 14;
  sheet.getRange("D:D").format.columnWidth = 12;
  sheet.getRange("E:E").format.columnWidth = 18;
  sheet.getRange("F:G").format.columnWidth = 12;
  sheet.getRange("H:H").format.columnWidth = 16;
  sheet.getRange("I:I").format.columnWidth = 13;
  sheet.getRange("J:J").format.columnWidth = 22;
  sheet.getRange("K:L").format.columnWidth = 18;
  sheet.getRange("M:M").format.columnWidth = 32;
  sheet.getRange("N:N").format.columnWidth = 18;
  sheet.getRange("O:O").format.columnWidth = 12;
  sheet.getRange("P:P").format.columnWidth = 32;
  sheet.getRange("Q:Q").format.columnWidth = 12;
  sheet.getRange("R:R").format.columnWidth = 10;
  sheet.getRange("S:T").format.columnWidth = 28;
}
games.getRange("U:U").format.columnWidth = 16;
games.getRange("V:V").format.columnWidth = 16;
games.getRange("W:W").format.columnWidth = 30;
games.getRange("X:Z").format.columnWidth = 20;
games.getRange(`U2:U${rowCounts.Games}`).format.numberFormat = "#,##0";
games.getRange(`U2:U${rowCounts.Games}`).conditionalFormats.add("dataBar", {
  color: colors.teal,
  gradient: true,
});
games.getRange(`V2:V${rowCounts.Games}`).conditionalFormats.add("containsText", {
  text: "FOUND",
  format: { fill: colors.greenLight, font: { color: "#166534" } },
});
games.getRange(`V2:V${rowCounts.Games}`).conditionalFormats.add("containsText", {
  text: "NOT_FOUND",
  format: { fill: colors.redLight, font: { color: "#991B1B" } },
});
sourceSummary.getRange("A:A").format.columnWidth = 30;
sourceSummary.getRange("B:B").format.columnWidth = 14;
sourceSummary.getRange("C:C").format.columnWidth = 60;
sourceSummary.getRange(`B2:B${rowCounts["Source Summary"]}`).format.numberFormat = "#,##0";

const gameRows = rowCounts.Games;
const vndbRows = rowCounts["VNDB Only"];
const steamRows = rowCounts["Steam Only"];

summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["Steam 视觉小说（2020–2025）交集统计"]];
summary.getRange("A1:H1").format = {
  fill: colors.navy,
  font: { bold: true, color: colors.white, size: 18 },
  rowHeight: 38,
  horizontalAlignment: "left",
  verticalAlignment: "center",
};
summary.getRange("A3:B3").values = [["核心指标", "数值"]];
summary.getRange("A4:A10").values = [
  ["交集游戏数"],
  ["Gamalytic 已返回"],
  ["Gamalytic 未返回"],
  ["VNDB 独有"],
  ["Steam 标签独有"],
  ["免费游戏（交集）"],
  ["累计 copiesSold（含免费游戏指标）"],
];
summary.getRange("B4:B10").formulas = [
  [`=COUNTA('Games'!$A$2:$A$${gameRows})`],
  [`=COUNT('Games'!$U$2:$U$${gameRows})`],
  [`=B4-B5`],
  [`=COUNTA('VNDB Only'!$A$2:$A$${vndbRows})`],
  [`=COUNTA('Steam Only'!$A$2:$A$${steamRows})`],
  [`=COUNTIF('Games'!$Q$2:$Q$${gameRows},"Free")`],
  [`=SUM('Games'!$U$2:$U$${gameRows})`],
];
summary.getRange("A3:B3").format = {
  fill: colors.teal,
  font: { bold: true, color: colors.white },
};
summary.getRange("A4:B10").format.borders = {
  preset: "inside",
  style: "thin",
  color: colors.grid,
};
summary.getRange("A4:A10").format.fill = colors.tealLight;
summary.getRange("A4:A10").format.font = { bold: true, color: colors.navy };
summary.getRange("B4:B10").format.numberFormat = "#,##0";
summary.getRange("A:A").format.columnWidth = 42;
summary.getRange("B:B").format.columnWidth = 18;
summary.getRange("D3:H3").merge();
summary.getRange("D3").values = [["口径说明"]];
summary.getRange("D3:H3").format = {
  fill: colors.amberLight,
  font: { bold: true, color: "#7A4B00" },
};
summary.getRange("D4:H9").merge();
summary.getRange("D4").values = [[
  "主数据集仅包含同时存在于 VNDB（带 Steam AppID）和 Steam Visual Novel 标签中的基础游戏。月份按 Steam 发行日期划分。copiesSold 是 Gamalytic 在采集日给出的累计估算，并不是发行当月销量；免费游戏的数值不可解释为付费销售份数。",
]];
summary.getRange("D4:H9").format = {
  fill: "#FFFDF5",
  font: { color: colors.gray, size: 11 },
  wrapText: true,
  verticalAlignment: "top",
  borders: { preset: "outside", style: "thin", color: "#E7C76B" },
};
summary.getRange("D:H").format.columnWidth = 15;

monthly.showGridLines = false;
monthly.freezePanes.freezeRows(1);
monthly.getRange("A1:E1").values = [[
  "月份",
  "发布游戏数",
  "有 copiesSold",
  "缺少 copiesSold",
  "累计 copiesSold",
]];
const monthRows = [];
for (let year = 2020; year <= 2025; year += 1) {
  for (let month = 1; month <= 12; month += 1) {
    monthRows.push([`${year}-${String(month).padStart(2, "0")}`]);
  }
}
monthly.getRange(`A2:A${monthRows.length + 1}`).values = monthRows;
monthly.getRange("B2:E2").formulas = [[
  `=COUNTIF('Games'!$D$2:$D$${gameRows},A2)`,
  `=COUNTIFS('Games'!$D$2:$D$${gameRows},A2,'Games'!$V$2:$V$${gameRows},"FOUND")`,
  `=B2-C2`,
  `=SUMIF('Games'!$D$2:$D$${gameRows},A2,'Games'!$U$2:$U$${gameRows})`,
]];
monthly.getRange("B2:E73").fillDown();
monthly.getRange("A1:E1").format = {
  fill: colors.navy,
  font: { bold: true, color: colors.white },
  rowHeight: 28,
};
monthly.getRange("A1:E73").format.borders = {
  insideHorizontal: { style: "thin", color: colors.grid },
};
monthly.getRange("B2:E73").format.numberFormat = "#,##0";
monthly.getRange("A:A").format.columnWidth = 13;
monthly.getRange("B:E").format.columnWidth = 18;
const monthlyTable = monthly.tables.add("A1:E73", true, "MonthlyTable");
monthlyTable.style = "TableStyleMedium2";

const chart = monthly.charts.add("line", monthly.getRange("A1:B73"));
chart.title = "每月发布游戏数量（交集口径）";
chart.titleTextStyle.fontSize = 13;
chart.hasLegend = false;
chart.xAxis = { axisType: "textAxis", textStyle: { fontSize: 8 } };
chart.yAxis = { numberFormatCode: "#,##0" };
chart.setPosition("G2", "P22");

notes.showGridLines = false;
notes.getRange("A1:D1").merge();
notes.getRange("A1").values = [["数据来源与使用说明"]];
notes.getRange("A1:D1").format = {
  fill: colors.navy,
  font: { bold: true, color: colors.white, size: 16 },
  rowHeight: 34,
};
notes.getRange("A3:B8").values = [
  ["项目", "说明"],
  ["VNDB", "https://api.vndb.org/kana — 获取带 Steam 外部链接的视觉小说发行记录"],
  ["Steam 标签", "https://store.steampowered.com/tags/en/Visual%20Novel/ — 标签 ID 3799"],
  ["Gamalytic", "https://api.gamalytic.com/reference/ — 官方匿名列表接口的 copiesSold"],
  ["统计窗口", "Steam 发行日期 2020-01-01 至 2025-12-31（含首尾）"],
  ["主键", "Steam AppID；一个 AppID 即一款 Steam 游戏"],
];
notes.getRange("A3:B3").format = {
  fill: colors.teal,
  font: { bold: true, color: colors.white },
};
notes.getRange("A4:A8").format = { fill: colors.tealLight, font: { bold: true } };
notes.getRange("A3:B8").format.borders = { preset: "inside", style: "thin", color: colors.grid };
notes.getRange("A:A").format.columnWidth = 18;
notes.getRange("B:B").format.columnWidth = 85;
notes.getRange("B:B").format.wrapText = true;

const summaryInspect = await workbook.inspect({
  kind: "table",
  range: "Summary!A1:H10",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 10,
  maxChars: 6000,
});
console.log(summaryInspect.ndjson);
const monthlyInspect = await workbook.inspect({
  kind: "table",
  range: "Monthly!A1:E73",
  include: "values,formulas",
  tableMaxRows: 75,
  tableMaxCols: 6,
  maxChars: 16000,
});
console.log(monthlyInspect.ndjson);
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(formulaErrors.ndjson);

const previews = [
  ["Summary", "A1:P22"],
  ["Monthly", "A1:P22"],
  ["Notes", "A1:D8"],
  ["Games", "A1:V14"],
  ["VNDB Only", "A1:T14"],
  ["Steam Only", "A1:T14"],
  ["Source Summary", "A1:C8"],
  ["Excluded", "A1:T14"],
];
for (const [sheetName, range] of previews) {
  const blob = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(
    path.join(previewDir, `${sheetName.replaceAll(" ", "_")}.png`),
    new Uint8Array(await blob.arrayBuffer()),
  );
}

const output = await SpreadsheetFile.exportXlsx(workbook);
const outputPath = path.join(outputDir, "steam_visual_novels_2020_2025.xlsx");
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, rowCounts }));
