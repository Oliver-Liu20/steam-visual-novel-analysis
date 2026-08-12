import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

process.on("uncaughtException", (error) => {
  console.error("BUILD_ERROR:", error?.message ?? String(error));
  console.error(String(error?.stack ?? "").split("\n").slice(0, 8).join("\n"));
  process.exit(1);
});
process.on("unhandledRejection", (error) => {
  console.error("BUILD_REJECTION:", error?.message ?? String(error));
  console.error(String(error?.stack ?? "").split("\n").slice(0, 8).join("\n"));
  process.exit(1);
});

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/, "$1")), "..");

if (process.argv.includes("--chart-help")) {
  const probe = Workbook.create();
  probe.worksheets.add("Probe");
  console.log(probe.help("chart", {
    search: "log|logarith|combo|series|axis",
    include: "index,examples,notes",
    maxChars: 10000,
  }).ndjson);
  process.exit(0);
}

if (process.argv.includes("--diag-simple") || process.argv.includes("--diag-formula") || process.argv.includes("--diag-bar") || process.argv.includes("--diag-local-formula") || process.argv.includes("--diag-large")) {
  const diag = Workbook.create();
  const source = diag.worksheets.add("Source");
  source.getRange("A1:B4").values = [["Period", "Count"], ["A", 1], ["B", 3], ["C", 2]];
  if (process.argv.includes("--diag-simple")) {
    const chart = source.charts.add("line", source.getRange("A1:B4"));
    chart.title = "Simple";
    chart.setPosition("D2", "K15");
  } else if (process.argv.includes("--diag-local-formula") || process.argv.includes("--diag-large")) {
    const target = diag.worksheets.add("Target");
    const large = process.argv.includes("--diag-large");
    const count = large ? 72 : 3;
    if (large) {
      const sourceRows = Array.from({ length: count }, (_, i) => [`2020-${String((i % 12) + 1).padStart(2, "0")}`, (i % 40) + 10]);
      source.getRange(`A2:B${count + 1}`).values = sourceRows;
    }
    target.getRange("S1:T1").values = [["Period", "Count"]];
    const formulas = Array.from({ length: count }, (_, i) => [`='Source'!A${i + 2}`, `='Source'!B${i + 2}`]);
    target.getRange(`S2:T${count + 1}`).formulas = formulas;
    const chart = target.charts.add("bar", target.getRange(`S1:T${count + 1}`));
    chart.title = "Local formula";
    chart.setPosition("A2", "H15");
  } else {
    const target = diag.worksheets.add("Target");
    const chart = target.charts.add(process.argv.includes("--diag-bar") ? "bar" : "line", { from: { row: 1, col: 1 }, extent: { widthPx: 500, heightPx: 300 } });
    const series = chart.series.add("Count");
    series.categoryFormula = "'Source'!$A$2:$A$4";
    series.formula = "'Source'!$B$2:$B$4";
    chart.title = "Formula";
  }
  console.log((await diag.inspect({ kind: "drawing", maxChars: 3000 })).ndjson);
  process.exit(0);
}

// The workbook implementation is appended below after the single targeted
// chart capability lookup above has been run.

const processedDir = path.join(root, "data", "processed", "expanded");
const outputDir = path.join(root, "outputs", "expanded_vndb_complete_2020_2025");
const chartDir = path.join(outputDir, "charts");
const previewDir = path.join(outputDir, "previews");
await fs.mkdir(chartDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

function parseCSV(text) {
  text = text.replace(/^\uFEFF/, "");
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
  const headers = rows[0];
  return rows.map((cells, rowIndex) => cells.map((value, colIndex) => {
    if (rowIndex === 0) return value;
    const header = headers[colIndex];
    if (value === "") return null;
    if (header === "steam_appid") return value;
    if (header === "steam_release_date" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
      return new Date(`${value}T00:00:00Z`);
    }
    if (/^(true|false)$/i.test(value)) return value.toLowerCase() === "true";
    if (/^-?\d+(?:\.\d+)?$/.test(value)) return Number(value);
    return value;
  }));
}

function columnName(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    const rem = (value - 1) % 26;
    result = String.fromCharCode(65 + rem) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

const masterText = await fs.readFile(path.join(processedDir, "visual_novels_master_2020_2025.csv"), "utf8");
const monthlyText = await fs.readFile(path.join(processedDir, "monthly_expanded_summary.csv"), "utf8");
const annualText = await fs.readFile(path.join(processedDir, "annual_expanded_summary.csv"), "utf8");
const metadata = JSON.parse(await fs.readFile(path.join(processedDir, "expanded_metadata.json"), "utf8"));
const masterValues = parseCSV(masterText);
const monthlyValues = parseCSV(monthlyText);
const annualValues = parseCSV(annualText);
const masterRows = masterValues.length;
const threshold = Number(metadata.threshold);
const highLabel = `高热度（>${threshold}）`;
const lowLabel = `低热度（≤${threshold}）`;
const positiveCopies = masterValues.slice(1).filter((row) => Number(row[8]) > 0).length;

const workbook = Workbook.create();
const dashboard = workbook.worksheets.add("总览");
const master = workbook.worksheets.add("游戏总表");
const monthly = workbook.worksheets.add("月度统计");
const annual = workbook.worksheets.add("年度统计");
const params = workbook.worksheets.add("参数与口径");
const chartData = workbook.worksheets.add("图表数据");

const chartSheetNames = [
  "图1_整体月度", "图2_整体年度", "图3_整体销量散点",
  "图4_热度月度", "图5_热度年度", "图6_热度销量散点",
  "图7_年龄月度", "图8_年龄年度", "图9_年龄销量散点",
  "图10_年龄占比",
];
const chartSheets = Object.fromEntries(chartSheetNames.map((name) => [name, workbook.worksheets.add(name)]));

const colors = {
  navy: "#17324D",
  navy2: "#244B6B",
  teal: "#168A7A",
  tealLight: "#DDF3EF",
  coral: "#E76F51",
  coralLight: "#FBE4DE",
  blue: "#3A86FF",
  blueLight: "#E3EEFF",
  gold: "#E9B949",
  gray: "#7B8794",
  grayLight: "#EEF1F4",
  grid: "#D9E1E8",
  white: "#FFFFFF",
  ink: "#1F2933",
};

function writeDataSheet(sheet, values, tableName) {
  const lastCol = columnName(values[0].length - 1);
  sheet.getRange(`A1:${lastCol}${values.length}`).values = values;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(2);
  const used = sheet.getRange(`A1:${lastCol}${values.length}`);
  used.format.font = { name: "Aptos", size: 9, color: colors.ink };
  const header = sheet.getRange(`A1:${lastCol}1`);
  header.format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 9 },
    rowHeight: 34,
    wrapText: true,
    verticalAlignment: "center",
  };
  const table = sheet.tables.add(`A1:${lastCol}${values.length}`, true, tableName);
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
  return { lastCol, used };
}

writeDataSheet(master, masterValues, "MasterTable");
master.getRange("A:A").format.columnWidth = 13;
master.getRange("B:B").format.columnWidth = 34;
master.getRange("C:C").format.columnWidth = 14;
master.getRange("D:E").format.columnWidth = 12;
master.getRange("F:F").format.columnWidth = 15;
master.getRange("G:H").format.columnWidth = 29;
master.getRange("I:I").format.columnWidth = 16;
master.getRange("J:J").format.columnWidth = 16;
master.getRange("K:M").format.columnWidth = 15;
master.getRange("N:N").format.columnWidth = 14;
master.getRange("O:P").format.columnWidth = 18;
master.getRange("Q:R").format.columnWidth = 20;
master.getRange("S:T").format.columnWidth = 13;
master.getRange("U:U").format.columnWidth = 32;
master.getRange("V:X").format.columnWidth = 16;
master.getRange("Y:AH").format.columnWidth = 20;
master.getRange(`C2:C${masterRows}`).format.numberFormat = "yyyy-mm-dd";
master.getRange(`F2:F${masterRows}`).format.numberFormat = "0.0";
master.getRange(`I2:M${masterRows}`).format.numberFormat = "#,##0";
master.getRange(`N2:N${masterRows}`).format.numberFormat = "0.0%";
master.getRange(`I2:I${masterRows}`).conditionalFormats.add("dataBar", { color: colors.teal, gradient: true });
master.getRange(`K2:K${masterRows}`).conditionalFormats.add("dataBar", { color: colors.blue, gradient: true });
master.getRange(`Q2:Q${masterRows}`).conditionalFormats.add("containsText", {
  text: "高热度", format: { fill: colors.coralLight, font: { color: "#9C2F18", bold: true } },
});
master.getRange(`Q2:Q${masterRows}`).conditionalFormats.add("containsText", {
  text: "低热度", format: { fill: colors.blueLight, font: { color: "#2257A5" } },
});
master.getRange(`R2:R${masterRows}`).conditionalFormats.add("containsText", {
  text: "全年龄", format: { fill: colors.tealLight, font: { color: "#0D655A", bold: true } },
});
master.getRange(`R2:R${masterRows}`).conditionalFormats.add("containsText", {
  text: "非全年龄", format: { fill: colors.coralLight, font: { color: "#9C2F18", bold: true } },
});

writeDataSheet(monthly, monthlyValues, "MonthlyExpandedTable");
monthly.getRange("A:A").format.columnWidth = 13;
monthly.getRange("B:J").format.columnWidth = 17;
monthly.getRange(`B2:J${monthlyValues.length}`).format.numberFormat = "#,##0";

writeDataSheet(annual, annualValues, "AnnualExpandedTable");
annual.getRange("A:A").format.columnWidth = 13;
annual.getRange("B:J").format.columnWidth = 17;
annual.getRange(`B2:J${annualValues.length}`).format.numberFormat = "#,##0";

params.showGridLines = false;
params.getRange("A1:F2").merge();
params.getRange("A1").values = [["参数、分类规则与数据来源"]];
params.getRange("A1:F2").format = {
  fill: colors.navy, font: { bold: true, color: colors.white, size: 17 },
  verticalAlignment: "center",
};
params.getRange("A4:B13").values = [
  ["参数", "数值 / 说明"],
  ["评论热度阈值", threshold],
  ["阈值以下实际占比", Number(metadata.low_share)],
  ["统计截止日", new Date(`${metadata.as_of_date}T00:00:00Z`)],
  ["新增名单选择", "只纳入原名单之外、仅由 VNDB 找到且发行类型为“完整游戏”的记录（技术值：VNDB_ONLY；vndb_rtypes=complete）"],
  ["全年龄游戏", "所有关联发行版本中都没有色情内容标记，并且至少一个版本明确标记为不含色情内容（技术字段：has_ero=false）"],
  ["非全年龄游戏", "任一关联发行版本明确标记为包含色情内容（技术字段：has_ero=true）"],
  ["年龄分级（minage）", "只记录年龄门槛，例如 18+；它不能单独证明游戏包含色情内容"],
  ["估算累计销量（copiesSold）", "Gamalytic 对截至采集日累计售出份数的估算，不是官方销量，也不是发行当月销量"],
  ["上市时长", `从发行日到 ${metadata.as_of_date} 的月数`],
];
for (let row = 4; row <= 13; row += 1) params.getRange(`B${row}:D${row}`).merge();
params.getRange("A4:D4").format = { fill: colors.teal, font: { bold: true, color: colors.white } };
params.getRange("A5:A13").format = { fill: colors.tealLight, font: { bold: true, color: colors.navy } };
params.getRange("A4:D13").format.borders = { preset: "inside", style: "thin", color: colors.grid };
params.getRange("B4:D13").format.wrapText = true;
params.getRange("A5:D13").format.rowHeight = 34;
params.getRange("B6").format.numberFormat = "0.0%";
params.getRange("B7").format.numberFormat = "yyyy-mm-dd";
params.getRange("A15:B18").values = [
  ["数据源", "URL"],
  ["VNDB Release API", "https://api.vndb.org/kana"],
  ["Steam 官方评论接口说明", "https://partner.steamgames.com/doc/store/getreviews"],
  ["Gamalytic API", "https://api.gamalytic.com/reference/"],
];
for (let row = 15; row <= 18; row += 1) params.getRange(`B${row}:D${row}`).merge();
params.getRange("A15:D15").format = { fill: colors.navy2, font: { bold: true, color: colors.white } };
params.getRange("A16:A18").format = { fill: colors.grayLight, font: { bold: true } };

const fieldDictionary = [
  ["英文字段名", "中文名称", "给非技术人员的解释", "数据来源 / 注意事项"],
  ["steam_appid", "Steam 应用编号", "Steam 为每个商店应用分配的唯一数字编号，用于准确识别游戏。", "Steam；同名游戏也可以用该编号区分。"],
  ["name", "游戏名称", "Steam 商店中显示的游戏名称。", "Steam 商店。"],
  ["steam_release_date", "Steam 发行日期", "游戏在 Steam 上正式发行的日期。", "Steam；格式为年-月-日。"],
  ["release_month", "发行月份", "把发行日期整理到月份，便于统计每月发行数量。", "根据 Steam 发行日期计算；格式为年-月。"],
  ["release_year", "发行年份", "把发行日期整理到年份，便于进行年度比较。", "根据 Steam 发行日期计算。"],
  ["months_since_release", "上市时长（月）", "从 Steam 发行日到统计截止日经历的月数。", `计算值；截止日为 ${metadata.as_of_date}。`],
  ["store_url", "Steam 商店链接", "打开该游戏 Steam 商店页面的网址。", "Steam。"],
  ["vndb_url", "VNDB 作品链接", "打开该游戏对应 VNDB 视觉小说条目的网址。", "VNDB；一个 Steam 游戏可能关联多个 VNDB 记录，此处提供主要链接。"],
  ["copies_sold", "估算累计销量", "Gamalytic 估算该游戏截至采集日累计售出的份数。", "Gamalytic 估算值，不是 Steam 官方销量；缺失时留空。"],
  ["gamalytic_status", "销量取数状态", "说明是否成功从 Gamalytic 获得估算销量。", "FOUND=已取得；NOT_FOUND 等值表示未取得。"],
  ["steam_review_count", "Steam 评论总数", "Steam 商店中该游戏收到的用户评论总数。", "Steam 官方评论接口；包含所选语言范围内的评论。"],
  ["steam_review_positive", "Steam 好评数", "Steam 用户评论中评价为推荐的数量。", "Steam 官方评论接口。"],
  ["steam_review_negative", "Steam 差评数", "Steam 用户评论中评价为不推荐的数量。", "Steam 官方评论接口。"],
  ["steam_review_positive_rate", "Steam 好评率", "好评数占全部评论数的比例。", "计算值：好评数÷评论总数。"],
  ["steam_review_score_desc", "Steam 评价等级", "Steam 展示的综合评价文字，例如“特别好评”或“多半好评”。", "Steam；部分返回值可能为英文。"],
  ["steam_review_status", "评论取数状态", "说明是否成功取得 Steam 评论汇总。", "FOUND=已取得；其他值表示接口未返回完整数据。"],
  ["review_heat_group", "评论热度分组", "按评论数量把游戏分成高热度和低热度两组。", `计算值；高热度为评论数>${threshold}，低热度为评论数≤${threshold}。`],
  ["all_ages_status", "成人内容分类", "按 VNDB 发行版本的色情内容标记分为全年龄或非全年龄。", "本项目的分析分组，不等同于法定年龄分级。"],
  ["is_all_ages", "是否归为全年龄", "True 表示归为全年龄，False 表示归为非全年龄。", "由 has_ero_any 推导；便于程序筛选。"],
  ["has_ero_any", "是否含色情内容", "只要任一关联 VNDB 发行版本标记为包含色情内容，就记为 True。", "VNDB Release.has_ero；本项目按用户指定规则执行。"],
  ["sexual_content_basis", "成人内容分类依据", "记录为什么把该游戏归入全年龄或非全年龄。", "通常显示 has_ero=true 或 has_ero=false。"],
  ["vndb_minage_values", "VNDB 年龄分级记录", "汇总关联发行版本的最低年龄要求，例如 18。", "VNDB Release.minage；只作参考，不用于判断色情内容。"],
  ["vndb_has_ero_values", "VNDB 色情内容标记记录", "汇总关联发行版本的 has_ero 原始取值。", "VNDB；true=包含，false=不包含。"],
  ["vndb_uncensored_values", "VNDB 无码状态记录", "汇总关联发行版本是否标记为未经内容遮挡处理。", "VNDB Release.uncensored；不能代替 has_ero。"],
  ["sexual_content_conflict", "成人内容标记是否冲突", "不同关联发行版本同时出现包含与不包含色情内容时记为 True。", "用于提醒读者同一作品可能存在不同版本。"],
  ["expanded_source", "进入名单的来源", "说明游戏来自原始交集名单，还是后来补充的 VNDB 完整游戏名单。", "ORIGINAL_INTERSECTION=原交集；VNDB_ONLY_COMPLETE_INCREMENT=新增名单。"],
  ["in_steam_visual_novel_tag", "是否有 Steam 视觉小说标签", "说明该游戏在 Steam 数据中是否带有 Visual Novel 标签。", "True/False；没有该标签并不必然表示不是视觉小说。"],
  ["vndb_ids", "VNDB 作品编号", "与该 Steam 游戏关联的 VNDB 作品编号，可有多个。", "VNDB；多个编号使用分隔符连接。"],
  ["vndb_release_ids", "VNDB 发行版本编号", "与 Steam 版本关联的 VNDB Release 编号，可用于追溯具体发行版本。", "VNDB。"],
  ["vndb_rtypes", "VNDB 发行类型", "说明关联记录是完整游戏、补丁或其他发行类型。", "complete=完整游戏；其他值按 VNDB 定义。"],
  ["vndb_official", "是否官方发行", "True 表示 VNDB 将该发行版本标记为官方版本。", "VNDB Release.official。"],
  ["price_text", "商店价格", "采集时 Steam 商店显示的价格文字。", "Steam；可能受地区、折扣和采集时间影响。"],
  ["is_free", "是否免费", "True 表示商店数据显示该游戏可免费获取。", "Steam；免费试玩或暂时促销不一定等同于永久免费。"],
  ["copies_sold_fetched_at", "销量估算采集时间", "取得 Gamalytic 估算销量的时间。", "通常为带时区的时间戳；便于日后更新和核对。"],
];
const documentedFields = new Set(fieldDictionary.slice(1).map((row) => row[0]));
const undocumentedFields = masterValues[0].filter((field) => !documentedFields.has(field));
if (undocumentedFields.length > 0) throw new Error(`字段词典缺少说明：${undocumentedFields.join(", ")}`);
const dictionaryEndRow = 19 + fieldDictionary.length;
params.getRange(`A20:D${dictionaryEndRow}`).values = fieldDictionary;
params.getRange("A20:D20").format = {
  fill: colors.teal, font: { bold: true, color: colors.white },
  verticalAlignment: "center", wrapText: true,
};
params.getRange(`A21:D${dictionaryEndRow}`).format = {
  verticalAlignment: "top", wrapText: true,
  borders: { insideHorizontal: { style: "thin", color: colors.grid } },
};
params.getRange(`A21:A${dictionaryEndRow}`).format = { fill: colors.blueLight, font: { bold: true, color: colors.navy }, wrapText: true };
params.getRange(`B21:B${dictionaryEndRow}`).format = { fill: colors.tealLight, font: { bold: true, color: colors.navy }, wrapText: true };
params.getRange("A:A").format.columnWidth = 29;
params.getRange("B:B").format.columnWidth = 30;
params.getRange("C:C").format.columnWidth = 62;
params.getRange("D:D").format.columnWidth = 46;
params.getRange(`A20:D${dictionaryEndRow}`).format.rowHeight = 34;
params.getRange("A20:D20").format.rowHeight = 28;

chartData.showGridLines = false;
chartData.freezePanes.freezeRows(1);
chartData.getRange("A1:AG1").format = { fill: colors.navy, font: { bold: true, color: colors.white, size: 9 } };
chartData.getRange("A1:B1").values = [["月份", "全部游戏"]];
chartData.getRange("A2:B2").formulas = [["='月度统计'!A2", "='月度统计'!B2"]];
chartData.getRange("A2:B73").fillDown();
chartData.getRange("D1:E1").values = [["年份", "全部游戏"]];
chartData.getRange("D2:E2").formulas = [["='年度统计'!A2", "='年度统计'!B2"]];
chartData.getRange("D2:E7").fillDown();
chartData.getRange("G1:I1").values = [["月份", highLabel, lowLabel]];
chartData.getRange("G2:I2").formulas = [["='月度统计'!A2", "='月度统计'!C2", "='月度统计'!D2"]];
chartData.getRange("G2:I73").fillDown();
chartData.getRange("K1:M1").values = [["年份", highLabel, lowLabel]];
chartData.getRange("K2:M2").formulas = [["='年度统计'!A2", "='年度统计'!C2", "='年度统计'!D2"]];
chartData.getRange("K2:M7").fillDown();
chartData.getRange("O1:R1").values = [["月份", "全年龄", "非全年龄", "未知"]];
chartData.getRange("O2:R2").formulas = [["='月度统计'!A2", "='月度统计'!F2", "='月度统计'!G2", "='月度统计'!H2"]];
chartData.getRange("O2:R73").fillDown();
chartData.getRange("T1:W1").values = [["年份", "全年龄", "非全年龄", "未知"]];
chartData.getRange("T2:W2").formulas = [["='年度统计'!A2", "='年度统计'!F2", "='年度统计'!G2", "='年度统计'!H2"]];
chartData.getRange("T2:W7").fillDown();
chartData.getRange("Y1:AD1").values = [["上市月数", "全部 log10销量", `${highLabel} log10销量`, `${lowLabel} log10销量`, "全年龄 log10销量", "非全年龄 log10销量"]];
chartData.getRange("Y2:AD2").formulas = [[
  "='游戏总表'!F2",
  "=IF('游戏总表'!I2>0,LOG('游戏总表'!I2,10),\"\")",
  `=IF(AND('游戏总表'!I2>0,'游戏总表'!Q2=\"${highLabel}\"),LOG('游戏总表'!I2,10),\"\")`,
  `=IF(AND('游戏总表'!I2>0,'游戏总表'!Q2=\"${lowLabel}\"),LOG('游戏总表'!I2,10),\"\")`,
  "=IF(AND('游戏总表'!I2>0,'游戏总表'!R2=\"全年龄\"),LOG('游戏总表'!I2,10),\"\")",
  "=IF(AND('游戏总表'!I2>0,'游戏总表'!R2=\"非全年龄\"),LOG('游戏总表'!I2,10),\"\")",
]];
chartData.getRange(`Y2:AD${masterRows}`).fillDown();
chartData.getRange("AF1:AG4").values = [
  ["分类", "游戏数"],
  ["全年龄", null],
  ["非全年龄", null],
  ["未知", null],
];
chartData.getRange("AG2:AG4").formulas = [
  [`=COUNTIF('游戏总表'!$R$2:$R$${masterRows},AF2)`],
  [`=COUNTIF('游戏总表'!$R$2:$R$${masterRows},AF3)`],
  [`=COUNTIF('游戏总表'!$R$2:$R$${masterRows},AF4)`],
];
chartData.getRange("A:AG").format.columnWidth = 16;
chartData.getRange(`Z2:AD${masterRows}`).format.numberFormat = "0.00";

function titleBand(sheet, title, subtitle = "") {
  sheet.showGridLines = false;
  sheet.getRange("A1:Q2").merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A1:Q2").format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 17 },
    verticalAlignment: "center",
  };
  if (subtitle) {
    sheet.getRange("A25:Q27").merge();
    sheet.getRange("A25").values = [[subtitle]];
    sheet.getRange("A25:Q27").format = {
      fill: "#F7F9FB", font: { color: colors.gray, size: 10 }, wrapText: true,
      verticalAlignment: "center", borders: { preset: "outside", style: "thin", color: colors.grid },
    };
  }
  sheet.getRange("A:Q").format.columnWidth = 12;
}

function styleChart(chart, title, tickInterval = 1) {
  chart.title = title;
  void tickInterval;
}

function colorSeries(chart, palette) {
  // The current artifact-tool build cannot serialize direct fill assignment
  // on formula-backed chart series. Keep the workbook theme palette here.
  void chart;
  void palette;
}

function columnIndex(name) {
  let value = 0;
  for (const ch of name) value = value * 26 + ch.charCodeAt(0) - 64;
  return value - 1;
}

function copyFormulaBlock(targetSheet, sourceRange, targetStartCol = "S") {
  const match = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(sourceRange);
  if (!match) throw new Error(`Unsupported chart source range: ${sourceRange}`);
  const [, startCol, startRowText, endCol, endRowText] = match;
  const startRow = Number(startRowText);
  const endRow = Number(endRowText);
  const startIndex = columnIndex(startCol);
  const endIndex = columnIndex(endCol);
  const targetIndex = columnIndex(targetStartCol);
  const width = endIndex - startIndex + 1;
  const targetEndCol = columnName(targetIndex + width - 1);
  const headers = [];
  for (let sourceIndex = startIndex; sourceIndex <= endIndex; sourceIndex += 1) {
    headers.push(chartData.getRange(`${columnName(sourceIndex)}${startRow}`).values[0][0]);
  }
  targetSheet.getRange(`${targetStartCol}1:${targetEndCol}1`).values = [headers];
  const sourceData = chartData.getRange(`${startCol}${startRow + 1}:${endCol}${endRow}`);
  const targetData = targetSheet.getRange(`${targetStartCol}2:${targetEndCol}${endRow - startRow + 1}`);
  targetData.values = sourceData.values;
  const sourceFormulas = sourceData.formulas;
  for (let offset = 0; offset < width; offset += 1) {
    const columnFormulas = sourceFormulas.map((row) => [row[offset] ?? ""]);
    if (columnFormulas.every((row) => String(row[0]).trim() !== "")) {
      const targetCol = columnName(targetIndex + offset);
      targetSheet.getRange(`${targetCol}2:${targetCol}${endRow - startRow + 1}`).formulas = columnFormulas;
    }
  }
  return targetSheet.getRange(`${targetStartCol}1:${targetEndCol}${endRow - startRow + 1}`);
}

function addBarLinePage(sheet, title, sourceRange, barTitle, lineTitle, subtitle, palette, tickInterval, showLabels = false) {
  titleBand(sheet, title, subtitle);
  copyFormulaBlock(sheet, sourceRange, "S");
  const values = chartData.getRange(sourceRange).values;
  const categories = values.slice(1).map((row) => row[0]);
  const series = values[0].slice(1).map((name, index) => ({
    name: String(name), values: values.slice(1).map((row) => row[index + 1]),
  }));
  sheet.charts.add("bar", {
    title: barTitle,
    titleTextStyle: { fontSize: 13, bold: true },
    categories,
    series,
    hasLegend: series.length > 1,
    legend: { position: "top" },
    barOptions: { direction: "column", grouping: "clustered", gapWidth: 70 },
    dataLabels: showLabels ? { showValue: true, position: "outEnd" } : { showValue: false },
    xAxis: { axisType: "textAxis", tickLabelInterval: tickInterval },
    yAxis: { numberFormatCode: "#,##0", title: { text: "游戏数量" } },
    from: { row: 3, col: 0 }, extent: { widthPx: 560, heightPx: 430 },
  });
  sheet.charts.add("line", {
    title: lineTitle,
    titleTextStyle: { fontSize: 13, bold: true },
    categories,
    series,
    hasLegend: series.length > 1,
    legend: { position: "top" },
    xAxis: { axisType: "textAxis", tickLabelInterval: tickInterval },
    yAxis: { numberFormatCode: "#,##0", title: { text: "游戏数量" } },
    from: { row: 3, col: 9 }, extent: { widthPx: 560, heightPx: 430 },
  });
  void palette;
}

addBarLinePage(
  chartSheets["图1_整体月度"],
  "2020–2025 视觉小说月度发行趋势（扩展口径）",
  "A1:B73", "每月发行数量｜柱状图", "每月发行数量｜折线图",
  `共 ${metadata.expanded_total.toLocaleString()} 款；月份按 Steam 对应发行日归组。柱状与折线展示同一计数，便于同时观察规模和趋势。`,
  [colors.blue], 6,
);
addBarLinePage(
  chartSheets["图2_整体年度"],
  "2020–2025 视觉小说年度发行趋势（扩展口径）",
  "D1:E7", "每年发行数量｜柱状图", "每年发行数量｜折线图",
  "年度汇总来自同一游戏总表；每个 Steam AppID 只计一次。",
  [colors.blue], 1, true,
);
addBarLinePage(
  chartSheets["图4_热度月度"],
  `月度发行数量：评论数 >${threshold} 与 ≤${threshold}`,
  "G1:I73", "月度发行数量｜分组柱状图", "月度发行数量｜分组折线图",
  `阈值 ${threshold} 使评论数不超过阈值的游戏占 ${(metadata.low_share * 100).toFixed(2)}%，约筛出热度最高的 20%。评论数来自 Steam 全语言、全部购买来源。`,
  [colors.coral, colors.blue], 6,
);
addBarLinePage(
  chartSheets["图5_热度年度"],
  `年度发行数量：评论数 >${threshold} 与 ≤${threshold}`,
  "K1:M7", "年度发行数量｜分组柱状图", "年度发行数量｜分组折线图",
  `高热度：Steam 评论数 >${threshold}；低热度：Steam 评论数 ≤${threshold}。`,
  [colors.coral, colors.blue], 1, true,
);
addBarLinePage(
  chartSheets["图7_年龄月度"],
  "月度发行数量：全年龄与非全年龄（按 has_ero）",
  "O1:Q73", "月度发行数量｜分组柱状图", "月度发行数量｜分组折线图",
  "任一关联 VNDB Release 的 has_ero=true 即归为非全年龄；否则已知 has_ero=false 归为全年龄。minage 不参与判断。",
  [colors.teal, colors.coral], 6,
);
addBarLinePage(
  chartSheets["图8_年龄年度"],
  "年度发行数量：全年龄与非全年龄（按 has_ero）",
  "T1:V7", "年度发行数量｜分组柱状图", "年度发行数量｜分组折线图",
  "分类直接依据 VNDB Release.has_ero；本次样本没有 has_ero 未知项。",
  [colors.teal, colors.coral], 1, true,
);

const pythonScatterFiles = [
  "03_overall_duration_sales_scatter.png",
  "06_review_heat_duration_sales_scatter.png",
  "09_all_ages_duration_sales_scatter.png",
];
const pythonScatterImages = await Promise.all(
  pythonScatterFiles.map((filename) => fs.readFile(path.join(chartDir, filename))),
);
let pythonScatterIndex = 0;

function addScatterPage(sheet, title, seriesDefs, subtitle) {
  const imageIndex = pythonScatterIndex++;
  const imageBytes = pythonScatterImages[imageIndex];
  const heightPx = imageIndex === 0 ? 647 : 615;
  sheet.showGridLines = false;
  sheet.images.add({
    dataUrl: `data:image/png;base64,${imageBytes.toString("base64")}`,
    anchor: {
      from: { row: 0, col: 0 },
      extent: { widthPx: 1180, heightPx },
    },
  });
  return;
  titleBand(sheet, title, subtitle);
  const categories = chartData.getRange(`Y2:Y${masterRows}`).values.map((row) => row[0]);
  const series = seriesDefs.map((def) => ({
    name: def.name,
    values: chartData.getRange(`${def.column}2:${def.column}${masterRows}`).values.map((row) => row[0]),
  }));
  sheet.charts.add("scatter", {
    title,
    titleTextStyle: { fontSize: 13, bold: true },
    categories,
    series,
    hasLegend: true,
    legend: { position: "top" },
    xAxis: { title: { text: `上市后的月数（截至 ${metadata.as_of_date}）` }, numberFormatCode: "0" },
    yAxis: { title: { text: "累计 copiesSold（log10 对数尺度）" }, numberFormatCode: "0", min: 0, max: 7, majorUnit: 1 },
    from: { row: 3, col: 0 }, extent: { widthPx: 1180, heightPx: 400 },
  });
}

addScatterPage(
  chartSheets["图3_整体销量散点"],
  "上市时长—累计销量散点图｜全部游戏",
  [{ name: "全部游戏", column: "Z", color: colors.blue }],
  `仅绘制 copiesSold>0 的 ${positiveCopies.toLocaleString()} 款。纵轴使用 log10 变换，等价于对数刻度：2=100、3=1,000、4=10,000、5=100,000。`,
);
addScatterPage(
  chartSheets["图6_热度销量散点"],
  `上市时长—累计销量｜评论数 >${threshold} 与 ≤${threshold}`,
  [
    { name: highLabel, column: "AA", color: colors.coral },
    { name: lowLabel, column: "AB", color: colors.blue },
  ],
  `纵轴为 log10(copiesSold)。阈值 ${threshold} 将约 20% 评论更多的游戏标为高热度。缺失或 copiesSold≤0 的点不绘制。`,
);
addScatterPage(
  chartSheets["图9_年龄销量散点"],
  "上市时长—累计销量｜全年龄与非全年龄",
  [
    { name: "全年龄", column: "AC", color: colors.teal },
    { name: "非全年龄", column: "AD", color: colors.coral },
  ],
  "纵轴为 log10(copiesSold)。分类仅依据 VNDB Release.has_ero；minage=18 不会单独触发非全年龄分类。",
);

const pieSheet = chartSheets["图10_年龄占比"];
titleBand(
  pieSheet,
  "全年龄与非全年龄游戏占比（按 VNDB Release.has_ero）",
  "非全年龄：任一关联 Release 的 has_ero=true；全年龄：无 true 且至少一个 has_ero=false。",
);
copyFormulaBlock(pieSheet, "AF1:AG4", "S");
const pieValues = chartData.getRange("AF1:AG4").values;
pieSheet.charts.add("pie", {
  title: "游戏数量占比",
  titleTextStyle: { fontSize: 13, bold: true },
  categories: pieValues.slice(1).map((row) => row[0]),
  series: [{ name: "游戏数", values: pieValues.slice(1).map((row) => row[1]) }],
  hasLegend: true,
  legend: { position: "right" },
  dataLabels: { showValue: true, position: "bestFit" },
  from: { row: 3, col: 0 }, extent: { widthPx: 720, heightPx: 430 },
});
pieSheet.getRange("L5:P5").merge();
pieSheet.getRange("L5").values = [["分类明细"]];
pieSheet.getRange("L5:P5").format = { fill: colors.teal, font: { bold: true, color: colors.white } };
pieSheet.getRange("L6:N9").values = [
  ["分类", "游戏数", "占比"],
  ["全年龄", null, null],
  ["非全年龄", null, null],
  ["未知", null, null],
];
pieSheet.getRange("M7:M9").formulas = [["='图表数据'!AG2"], ["='图表数据'!AG3"], ["='图表数据'!AG4"]];
pieSheet.getRange("N7:N9").formulas = [["=M7/SUM($M$7:$M$9)"], ["=M8/SUM($M$7:$M$9)"], ["=M9/SUM($M$7:$M$9)"]];
pieSheet.getRange("L6:N6").format = { fill: colors.navy2, font: { bold: true, color: colors.white } };
pieSheet.getRange("L7:L9").format = { fill: colors.grayLight, font: { bold: true } };
pieSheet.getRange("M7:M9").format.numberFormat = "#,##0";
pieSheet.getRange("N7:N9").format.numberFormat = "0.0%";
pieSheet.getRange("L6:N9").format.borders = { preset: "inside", style: "thin", color: colors.grid };

dashboard.showGridLines = false;
dashboard.getRange("A1:P2").merge();
dashboard.getRange("A1").values = [["Steam 视觉小说 2020–2025｜扩展总览"]];
dashboard.getRange("A1:P2").format = {
  fill: colors.navy, font: { bold: true, color: colors.white, size: 20 }, verticalAlignment: "center",
};
dashboard.getRange("A3:P3").merge();
dashboard.getRange("A3").values = [["原始交集名单 + 仅由 VNDB 补充的完整游戏；评论热度与成人内容分类规则详见“参数与口径”"]];
dashboard.getRange("A3:P3").format = { fill: colors.grayLight, font: { color: colors.gray, italic: true } };

function addKpi(range, label, formula, fill) {
  const [labelRange, valueRange] = range;
  dashboard.getRange(labelRange).merge();
  dashboard.getRange(labelRange.split(":")[0]).values = [[label]];
  dashboard.getRange(labelRange).format = { fill, font: { bold: true, color: colors.navy, size: 11 } };
  dashboard.getRange(valueRange).merge();
  dashboard.getRange(valueRange.split(":")[0]).formulas = [[formula]];
  dashboard.getRange(valueRange).format = {
    fill: colors.white, font: { bold: true, color: colors.navy, size: 20 },
    horizontalAlignment: "center", verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: colors.grid }, numberFormat: "#,##0",
  };
}

addKpi(["A5:D5", "A6:D9"], "纳入统计的游戏总数", `=COUNTA('游戏总表'!$A$2:$A$${masterRows})`, colors.blueLight);
addKpi(["F5:I5", "F6:I9"], "新增：仅由 VNDB 补充的完整游戏", `=COUNTIF('游戏总表'!$Z$2:$Z$${masterRows},\"VNDB_ONLY_COMPLETE_INCREMENT\")`, colors.tealLight);
addKpi(["K5:N5", "K6:N9"], "已取得估算销量的游戏", `=COUNT('游戏总表'!$I$2:$I$${masterRows})`, colors.coralLight);
addKpi(["A11:D11", "A12:D15"], `高热度游戏（Steam 评论数>${threshold}）`, `=COUNTIF('游戏总表'!$K$2:$K$${masterRows},\">${threshold}\")`, colors.coralLight);
addKpi(["F11:I11", "F12:I15"], "全年龄游戏（无色情内容标记）", `=COUNTIF('游戏总表'!$R$2:$R$${masterRows},\"全年龄\")`, colors.tealLight);
addKpi(["K11:N11", "K12:N15"], "非全年龄游戏（含色情内容标记）", `=COUNTIF('游戏总表'!$R$2:$R$${masterRows},\"非全年龄\")`, colors.coralLight);
dashboard.getRange("A:P").format.columnWidth = 11;

copyFormulaBlock(dashboard, "AF1:AG4", "R");
dashboard.charts.add("pie", {
  title: "全年龄 / 非全年龄占比",
  categories: pieValues.slice(1).map((row) => row[0]),
  series: [{ name: "游戏数", values: pieValues.slice(1).map((row) => row[1]) }],
  hasLegend: true,
  legend: { position: "right" },
  from: { row: 17, col: 0 }, extent: { widthPx: 520, heightPx: 340 },
});
copyFormulaBlock(dashboard, "D1:E7", "U");
const annualChartValues = chartData.getRange("D1:E7").values;
dashboard.charts.add("bar", {
  title: "每年发行游戏数量",
  categories: annualChartValues.slice(1).map((row) => row[0]),
  series: [{ name: "游戏数", values: annualChartValues.slice(1).map((row) => row[1]) }],
  hasLegend: false,
  barOptions: { direction: "column", grouping: "clustered" },
  dataLabels: { showValue: true, position: "outEnd" },
  yAxis: { numberFormatCode: "#,##0" },
  from: { row: 17, col: 8 }, extent: { widthPx: 560, heightPx: 340 },
});

const summaryInspect = await workbook.inspect({
  kind: "table", range: "总览!A1:P15", include: "values,formulas",
  tableMaxRows: 18, tableMaxCols: 16, maxChars: 9000,
});
console.log(summaryInspect.ndjson);
const statsInspect = await workbook.inspect({
  kind: "table", range: "月度统计!A1:J73", include: "values,formulas",
  tableMaxRows: 8, tableMaxCols: 10, maxChars: 6000,
});
console.log(statsInspect.ndjson);
const formulaErrors = await workbook.inspect({
  kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 }, summary: "expanded workbook formula error scan",
});
console.log(formulaErrors.ndjson);

const renderSpecs = [
  ["总览", "A1:P38", path.join(previewDir, "dashboard.png")],
  ["游戏总表", "A1:R14", path.join(previewDir, "master.png")],
  ["月度统计", "A1:J18", path.join(previewDir, "monthly_table.png")],
  ["年度统计", "A1:J7", path.join(previewDir, "annual_table.png")],
  ["参数与口径", "A1:F18", path.join(previewDir, "parameters.png")],
  ["参数与口径", `A20:D${dictionaryEndRow}`, path.join(previewDir, "field_dictionary.png")],
  ["图表数据", "A1:W10", path.join(previewDir, "chart_data.png")],
  ["图1_整体月度", "A1:Q27", path.join(chartDir, "01_overall_monthly.png")],
  ["图2_整体年度", "A1:Q27", path.join(chartDir, "02_overall_annual.png")],
  ["图3_整体销量散点", "A1:Q27", path.join(previewDir, "python_03_overall_duration_sales_scatter.png")],
  ["图4_热度月度", "A1:Q27", path.join(chartDir, "04_review_heat_monthly.png")],
  ["图5_热度年度", "A1:Q27", path.join(chartDir, "05_review_heat_annual.png")],
  ["图6_热度销量散点", "A1:Q27", path.join(previewDir, "python_06_review_heat_duration_sales_scatter.png")],
  ["图7_年龄月度", "A1:Q27", path.join(chartDir, "07_all_ages_monthly.png")],
  ["图8_年龄年度", "A1:Q27", path.join(chartDir, "08_all_ages_annual.png")],
  ["图9_年龄销量散点", "A1:Q27", path.join(previewDir, "python_09_all_ages_duration_sales_scatter.png")],
  ["图10_年龄占比", "A1:Q27", path.join(chartDir, "10_all_ages_pie.png")],
];
for (const [sheetName, range, filePath] of renderSpecs) {
  const blob = await workbook.render({ sheetName, range, scale: 1.2, format: "png" });
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
const outputPath = path.join(outputDir, "steam_visual_novels_expanded_2020_2025_cn_guide.xlsx");
await xlsx.save(outputPath);
console.log(JSON.stringify({ outputPath, chartDir, masterRows: masterRows - 1, threshold, positiveCopies }));
