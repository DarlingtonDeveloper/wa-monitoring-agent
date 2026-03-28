#!/usr/bin/env node
/**
 * WA Monitoring Report — DOCX Generator
 *
 * Reads analysis.json + client config, produces a formatted DOCX report.
 * Pure template populator — no intelligence, no decisions.
 */

const fs = require("fs");
const path = require("path");
const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  Table,
  TableRow,
  TableCell,
  WidthType,
  AlignmentType,
  BorderStyle,
  ShadingType,
  Header,
  Footer,
  PageBreak,
} = require("docx");

const { validateAnalysis } = require("../../schemas/validate");

// ── CLI Args ──
const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  const key = process.argv[i].replace(/^--/, "");
  args[key] = process.argv[i + 1];
}
if (!args.analysis || !args.config || !args.output) {
  console.error("Usage: --analysis <path> --config <path> --output <path>");
  process.exit(1);
}

const analysis = JSON.parse(fs.readFileSync(args.analysis, "utf-8"));
const config = JSON.parse(fs.readFileSync(args.config, "utf-8"));

// ── Clean LLM output quirks ──
(function cleanAnalysis(data) {
  if (data.metadata && data.metadata.generated_at) {
    const d = new Date(data.metadata.generated_at);
    if (!isNaN(d)) data.metadata.generated_at = d.toISOString();
  }
  for (const [key, section] of Object.entries(data.sections || {})) {
    if (key !== "stakeholder_third_party" && section.no_developments !== undefined) {
      delete section.no_developments;
    }
  }
  for (const row of data.sections?.media_coverage?.coverage_table || []) {
    if (typeof row.client_named !== "string") row.client_named = String(row.client_named);
  }
  for (const row of data.coverage_summary || []) {
    if (typeof row.this_week !== "string") row.this_week = String(row.this_week);
    if (typeof row.previous_week !== "string") row.previous_week = String(row.previous_week);
  }
  for (const rm of data.sections?.parliamentary?.routine_mentions || []) {
    const allowed = ["Low", "Medium", "High"];
    if (!allowed.includes(rm.significance)) {
      if (rm.significance?.toLowerCase().startsWith("low")) rm.significance = "Low";
      else if (rm.significance?.toLowerCase().startsWith("med")) rm.significance = "Medium";
      else if (rm.significance?.toLowerCase().startsWith("high")) rm.significance = "High";
      else rm.significance = "Low";
    }
  }
})(analysis);

const valErrors = validateAnalysis(analysis);
if (valErrors.length > 0) {
  console.warn("Analysis validation warnings:");
  valErrors.forEach((e) => console.warn(`  - ${e}`));
  console.warn("Proceeding with generation...");
}

// ═══════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════

const NAVY = "1B2A4A";
const DARK_GREY = "333333";
const MID_GREY = "666666";
const LIGHT_GREY = "F0F0F0";
const WHITE = "FFFFFF";

const RAG = {
  RED:   { dot: "CC0000", bg: "FFE0E0" },
  AMBER: { dot: "CC7700", bg: "FFF3E0" },
  GREEN: { dot: "2E7D32", bg: "E0F5E0" },
};

// Half-points: 22 = 11pt, 24 = 12pt, 28 = 14pt
const SZ = { BODY: 22, SMALL: 20, H1: 36, H2: 28, H3: 24, TITLE: 52, SUBTITLE: 28, REPORT: 40, HDR: 16 };

// A4 with 1-inch margins = 9026 DXA usable width
const PAGE_W = 9026;

// Standard cell margins
const CELL_M = { top: 60, bottom: 60, left: 100, right: 100 };

// Standard border
const B = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const BORDERS = { top: B, bottom: B, left: B, right: B, insideHorizontal: B, insideVertical: B };

// ═══════════════════════════════════════════════
// TABLE BUILDER — enforces width rules globally
// ═══════════════════════════════════════════════

/**
 * Build a table with guaranteed correct widths.
 * @param {number[]} colWidths - DXA widths, MUST sum to PAGE_W
 * @param {TableRow[]} rows
 */
function makeTable(colWidths, rows) {
  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: colWidths,
    rows,
    borders: BORDERS,
  });
}

/** Build a header row with navy background + white text */
function headerRow(headers, colWidths) {
  return new TableRow({
    tableHeader: true,
    children: headers.map((h, i) =>
      new TableCell({
        width: { size: colWidths[i], type: WidthType.DXA },
        shading: { fill: NAVY, type: ShadingType.CLEAR },
        margins: CELL_M,
        children: [new Paragraph({
          children: [new TextRun({ text: h, font: "Arial", size: SZ.SMALL, bold: true, color: WHITE })],
        })],
      })
    ),
  });
}

/** Build a data row with optional alternating shading */
function dataRow(cells, colWidths, alt) {
  return new TableRow({
    children: cells.map((cell, i) =>
      new TableCell({
        width: { size: colWidths[i], type: WidthType.DXA },
        shading: alt ? { fill: "F9F9F9", type: ShadingType.CLEAR } : undefined,
        margins: CELL_M,
        children: [new Paragraph({
          children: [new TextRun({ text: String(cell ?? ""), font: "Arial", size: SZ.SMALL, color: DARK_GREY })],
        })],
      })
    ),
  });
}

/** Build a complete data table: navy headers + data rows */
function dataTable(headers, rows, colWidths) {
  const allRows = [headerRow(headers, colWidths)];
  rows.forEach((row, i) => allRows.push(dataRow(row, colWidths, i % 2 === 1)));
  return makeTable(colWidths, allRows);
}

/** RAG dot cell — colored circle on tinted background */
function ragCell(rag, width) {
  const r = RAG[rag] || RAG.GREEN;
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: { fill: r.bg, type: ShadingType.CLEAR },
    margins: CELL_M,
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "\u25CF", font: "Arial", size: SZ.BODY, color: r.dot, bold: true })],
    })],
  });
}

// ═══════════════════════════════════════════════
// TEXT & PARAGRAPH HELPERS
// ═══════════════════════════════════════════════

function renderText(text, confidence, opts = {}) {
  const runs = [
    new TextRun({
      text: text || "",
      font: "Arial",
      size: SZ.BODY,
      color: opts.color || DARK_GREY,
      bold: opts.bold || false,
      italics: opts.italics || false,
    }),
  ];
  if (confidence !== undefined && confidence < 0.7) {
    runs.push(new TextRun({ text: " [UNVERIFIED]", font: "Arial", size: SZ.SMALL, color: RAG.AMBER.dot, bold: true }));
  }
  return runs;
}

function heading1(text) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Arial", size: SZ.H1, color: NAVY, bold: true })],
    spacing: { before: 400, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: NAVY, space: 4 } },
  });
}

function heading2(text) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Arial", size: SZ.H2, color: NAVY, bold: true })],
    spacing: { before: 300, after: 150 },
  });
}

function heading3(text) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Arial", size: SZ.H3, color: NAVY, bold: true })],
    spacing: { before: 200, after: 100 },
  });
}

function bodyPara(text, opts = {}) {
  return new Paragraph({
    children: renderText(text, opts.confidence, opts),
    spacing: { after: 150, line: 276 },
  });
}

function noDevPara() {
  return bodyPara("No significant developments this week.", { color: MID_GREY, italics: true });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

// ═══════════════════════════════════════════════
// ITEM CARD — Bug 3: remove Headline + Escalation rows
// ═══════════════════════════════════════════════

const CARD_COLS = [2200, 6826]; // sum = 9026

function cardRow(label, value, confidence) {
  const valRuns = renderText(value || "", confidence);
  return new TableRow({
    children: [
      new TableCell({
        width: { size: CARD_COLS[0], type: WidthType.DXA },
        shading: { fill: LIGHT_GREY, type: ShadingType.CLEAR },
        margins: CELL_M,
        children: [new Paragraph({
          children: [new TextRun({ text: label, font: "Arial", size: SZ.SMALL, bold: true, color: NAVY })],
        })],
      }),
      new TableCell({
        width: { size: CARD_COLS[1], type: WidthType.DXA },
        margins: CELL_M,
        children: [new Paragraph({ children: valRuns })],
      }),
    ],
  });
}

function itemCard(item) {
  const r = RAG[item.rag] || RAG.GREEN;
  return [
    // Heading: ● 2.1.1 Headline text
    new Paragraph({
      children: [
        new TextRun({ text: "\u25CF ", font: "Arial", size: SZ.H3, color: r.dot, bold: true }),
        new TextRun({ text: `${item.ref}  ${item.headline}`, font: "Arial", size: SZ.H3, bold: true, color: NAVY }),
      ],
      spacing: { before: 300, after: 100 },
    }),
    // Card table — no Headline row, no Escalation row
    makeTable(CARD_COLS, [
      cardRow("Date", item.date),
      cardRow("Source", item.source),
      cardRow("Summary", item.summary, item.confidence),
      cardRow("Client Relevance", item.client_relevance, item.confidence),
      cardRow("Recommended Action", item.recommended_action),
    ]),
    new Paragraph({ spacing: { after: 150 } }),
  ];
}

// ═══════════════════════════════════════════════
// BUG 4 HELPER: client_named boolean → readable text
// ═══════════════════════════════════════════════

function formatClientNamed(val) {
  if (val === false || val === "false") return "No \u2014 sector story";
  if (val === true || val === "true") return "Yes";
  return String(val || "");
}

// ═══════════════════════════════════════════════
// BUILD DOCUMENT CONTENT
// ═══════════════════════════════════════════════

const meta = analysis.metadata;
const rpt = config.report || {};
const clientName = meta.client_name;
const children = [];

// ── COVER PAGE ──
// Bug 7: correct fields, correct order, no internal metrics
const COVER_COLS = [3000, 6026]; // sum = 9026

children.push(
  new Paragraph({ spacing: { before: 3000 } }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: rpt.consultancy_name || "WA Communications", font: "Arial", size: SZ.TITLE, color: NAVY, bold: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 600 },
    children: [new TextRun({ text: rpt.consultancy_subtitle || "Public Affairs & Strategic Communications", font: "Arial", size: SZ.SUBTITLE, color: MID_GREY })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 200 },
    children: [new TextRun({ text: "WEEKLY MONITORING REPORT", font: "Arial", size: SZ.REPORT, color: NAVY, bold: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: clientName, font: "Arial", size: SZ.H1, color: NAVY })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 600 },
    children: [new TextRun({ text: meta.reporting_period, font: "Arial", size: SZ.H2, color: MID_GREY })],
  }),
  dataTable(
    ["", ""],
    [
      ["Reporting Period", meta.reporting_period],
      ["Report Date", meta.report_date],
      ["Prepared By", rpt.prepared_by_default || "AI Monitoring Agent (Draft)"],
      ["Reviewed By", rpt.reviewed_by_default || "[Account Lead]"],
      ["Classification", rpt.classification || "CONFIDENTIAL"],
    ],
    COVER_COLS
  ),
  pageBreak()
);

// ════════════════════════════════════════
// 1. EXECUTIVE SUMMARY
// ════════════════════════════════════════
const es = analysis.executive_summary;
children.push(heading1("1. Executive Summary"));
children.push(heading2("1.1 Top Line"));
children.push(bodyPara(es.top_line));

// Bug 1: Key Developments table — RAG column as colored dot, not text
children.push(heading2("1.2 Key Developments"));
if (es.key_developments && es.key_developments.length > 0) {
  const KD_COLS = [500, 3200, 2626, 2000, 700]; // sum = 9026

  const kdHeaderRow = headerRow(["", "Development", "Relevance", "Action", "Ref"], KD_COLS);
  const kdDataRows = es.key_developments.map((kd, i) => {
    const r = RAG[kd.rag] || RAG.GREEN;
    return new TableRow({
      children: [
        ragCell(kd.rag, KD_COLS[0]),
        new TableCell({
          width: { size: KD_COLS[1], type: WidthType.DXA },
          margins: CELL_M,
          shading: i % 2 === 1 ? { fill: "F9F9F9", type: ShadingType.CLEAR } : undefined,
          children: [new Paragraph({ children: renderText(kd.development, kd.confidence) })],
        }),
        new TableCell({
          width: { size: KD_COLS[2], type: WidthType.DXA },
          margins: CELL_M,
          shading: i % 2 === 1 ? { fill: "F9F9F9", type: ShadingType.CLEAR } : undefined,
          children: [new Paragraph({ children: [new TextRun({ text: kd.relevance || "", font: "Arial", size: SZ.SMALL, color: DARK_GREY })] })],
        }),
        new TableCell({
          width: { size: KD_COLS[3], type: WidthType.DXA },
          margins: CELL_M,
          shading: i % 2 === 1 ? { fill: "F9F9F9", type: ShadingType.CLEAR } : undefined,
          children: [new Paragraph({ children: [new TextRun({ text: kd.recommended_action || "", font: "Arial", size: SZ.SMALL, color: DARK_GREY })] })],
        }),
        new TableCell({
          width: { size: KD_COLS[4], type: WidthType.DXA },
          margins: CELL_M,
          shading: i % 2 === 1 ? { fill: "F9F9F9", type: ShadingType.CLEAR } : undefined,
          children: [new Paragraph({ children: [new TextRun({ text: kd.section_ref || "", font: "Arial", size: SZ.SMALL, color: DARK_GREY })] })],
        }),
      ],
    });
  });
  children.push(makeTable(KD_COLS, [kdHeaderRow, ...kdDataRows]));
}

// ════════════════════════════════════════
// 2. DETAILED MONITORING
// ════════════════════════════════════════
children.push(pageBreak());
children.push(heading1("2. Detailed Monitoring"));

// 2.1 Policy & Government
children.push(heading2("2.1 Policy & Government Activity"));
const policyItems = (analysis.sections.policy_government || {}).items || [];
if (policyItems.length === 0) {
  children.push(noDevPara());
} else {
  policyItems.forEach((item) => children.push(...itemCard(item)));
}

// Bug 8: 2.2 Parliamentary — ALWAYS present even if empty
children.push(heading2("2.2 Parliamentary Activity"));
const parlItems = (analysis.sections.parliamentary || {}).items || [];
if (parlItems.length === 0) {
  children.push(noDevPara());
} else {
  parlItems.forEach((item) => children.push(...itemCard(item)));
}
const routineMentions = (analysis.sections.parliamentary || {}).routine_mentions || [];
if (routineMentions.length > 0) {
  const RM_COLS = [900, 900, 4226, 1500, 1500]; // sum = 9026
  children.push(heading3("Routine Parliamentary Mentions"));
  const rmRows = routineMentions.map((rm) => [rm.date, rm.type, rm.detail, rm.members, rm.significance]);
  children.push(dataTable(["Date", "Type", "Detail", "Members", "Significance"], rmRows, RM_COLS));
}

// 2.3 Regulatory & Legal
children.push(heading2("2.3 Regulatory & Legal"));
const regItems = (analysis.sections.regulatory_legal || {}).items || [];
if (regItems.length === 0) {
  children.push(noDevPara());
} else {
  regItems.forEach((item) => children.push(...itemCard(item)));
}

// 2.4 Media Coverage — Bug 4: format client_named properly
children.push(heading2("2.4 Media Coverage"));
const mediaData = analysis.sections.media_coverage || {};
const covTable = mediaData.coverage_table || [];
if (covTable.length > 0) {
  const MC_COLS = [900, 1400, 3526, 1500, 1700]; // sum = 9026
  const mediaRows = covTable.map((r) => [
    r.date, r.outlet, r.angle,
    formatClientNamed(r.client_named),
    r.action,
  ]);
  children.push(dataTable(["Date", "Outlet", "Angle", "Client Named?", "Action"], mediaRows, MC_COLS));
}
const sigItems = mediaData.significant_items || [];
if (sigItems.length > 0) {
  children.push(heading3("Significant Media Items"));
  sigItems.forEach((item) => children.push(...itemCard(item)));
}
if (covTable.length === 0 && sigItems.length === 0) {
  children.push(noDevPara());
}

// Bug 5: 2.5 Social Media — 3-column metrics, "requires integration" not N/A
children.push(heading2("2.5 Social Media & Digital"));
const socialData = analysis.sections.social_media || {};
if (socialData.summary) {
  children.push(bodyPara(socialData.summary));
}
if (socialData.metrics) {
  const SM_COLS = [2800, 3626, 2600]; // sum = 9026
  const m = socialData.metrics;
  const placeholder = "Data requires Meltwater/Signal AI integration";
  const smRows = [
    [
      "Total client mentions",
      m.total_mentions === "N/A" ? placeholder : m.total_mentions,
      m.trend_vs_previous === "N/A" ? "\u2194 Baseline not yet established" : m.trend_vs_previous,
    ],
    [
      "Sentiment breakdown",
      m.sentiment_breakdown === "N/A" ? placeholder : m.sentiment_breakdown,
      "",
    ],
    [
      "Top-engagement post",
      m.top_engagement_post === "N/A" ? placeholder : m.top_engagement_post,
      "",
    ],
  ];
  children.push(dataTable(["Metric", "This Week", "Trend vs Previous"], smRows, SM_COLS));
}
const notablePosts = socialData.notable_posts || [];
if (notablePosts.length > 0) {
  notablePosts.forEach((item) => children.push(...itemCard(item)));
}

// Bug 6: 2.6 Competitor & Industry — filter out client
children.push(heading2("2.6 Competitor & Industry Intelligence"));
const compTableRaw = (analysis.sections.competitor_industry || {}).table || [];
const clientLower = config.client.name.toLowerCase();
const compFiltered = compTableRaw.filter((r) => !r.organisation.toLowerCase().includes("rwe"));
if (compFiltered.length > 0) {
  const CI_COLS = [1800, 3000, 2426, 1800]; // sum = 9026
  const compRows = compFiltered.map((r) => [r.organisation, r.development, r.relevance, r.action]);
  children.push(dataTable(["Organisation", "Development", "Relevance", "Action"], compRows, CI_COLS));
} else {
  children.push(noDevPara());
}

// 2.7 Stakeholder & Third Party
children.push(heading2("2.7 Stakeholder & Third Party Activity"));
const stakeholder = analysis.sections.stakeholder_third_party || {};
if (stakeholder.no_developments) {
  children.push(noDevPara());
} else {
  const stItems = stakeholder.items || [];
  if (stItems.length === 0) {
    children.push(noDevPara());
  } else {
    stItems.forEach((item) => children.push(...itemCard(item)));
  }
}

// ════════════════════════════════════════
// 3. FORWARD LOOK
// ════════════════════════════════════════
children.push(pageBreak());
children.push(heading1("3. Forward Look"));
const fl = analysis.forward_look || [];
if (fl.length > 0) {
  const FL_COLS = [1200, 3200, 2626, 2000]; // sum = 9026
  const flRows = fl.map((f) => [f.date, f.event, f.relevance, f.preparation]);
  children.push(dataTable(["Date", "Event", "Relevance", "Preparation"], flRows, FL_COLS));
} else {
  children.push(bodyPara("No forward-looking events identified."));
}

// ════════════════════════════════════════
// 4. EMERGING THEMES
// ════════════════════════════════════════
children.push(heading1("4. Emerging Themes"));
(analysis.emerging_themes || []).forEach((para) => children.push(bodyPara(para)));

// ════════════════════════════════════════
// 5. ACTIONS TRACKER
// ════════════════════════════════════════
children.push(heading1("5. Actions Tracker"));
const at = analysis.actions_tracker || [];
if (at.length > 0) {
  const AT_COLS = [500, 3500, 1200, 1000, 2026, 800]; // sum = 9026
  const atRows = at.map((a) => [a.ref, a.action, a.owner, a.deadline, a.origin, a.status]);
  children.push(dataTable(["Ref", "Action", "Owner", "Deadline", "Origin", "Status"], atRows, AT_COLS));
} else {
  children.push(bodyPara("No actions identified."));
}

// ════════════════════════════════════════
// 6. COVERAGE SUMMARY — Bug 9: arrows in trend
// ════════════════════════════════════════
children.push(heading1("6. Coverage Summary"));
const cs = analysis.coverage_summary || [];
if (cs.length > 0) {
  const CS_COLS = [2800, 2075, 2076, 2075]; // sum = 9026
  const csRows = cs.map((c) => [c.metric, c.this_week || "", c.previous_week || "", c.trend || ""]);
  children.push(dataTable(["Metric", "This Week", "Previous Week", "Trend"], csRows, CS_COLS));
}

// ── Sources unavailable ──
if (meta.sources_unavailable && meta.sources_unavailable.length > 0) {
  children.push(new Paragraph({ spacing: { before: 200 } }));
  children.push(bodyPara(
    `Note: The following sources were unavailable during collection: ${meta.sources_unavailable.join(", ")}.`,
    { color: MID_GREY, italics: true }
  ));
}

// ═══════════════════════════════════════════════
// ASSEMBLE & WRITE
// ═══════════════════════════════════════════════
const doc = new Document({
  styles: {
    default: {
      document: {
        run: { font: "Arial", size: SZ.BODY, color: DARK_GREY },
        paragraph: { spacing: { line: 276 } },
      },
    },
  },
  sections: [
    {
      properties: {
        page: {
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
          size: { width: 11906, height: 16838 },
        },
      },
      headers: {
        default: new Header({
          children: [
            new Paragraph({
              alignment: AlignmentType.CENTER,
              border: { bottom: { style: BorderStyle.SINGLE, size: 1, color: "DDDDDD", space: 4 } },
              children: [new TextRun({
                text: `WA COMMUNICATIONS  \u2502  WEEKLY MONITORING REPORT  \u2502  ${clientName.toUpperCase()}`,
                font: "Arial", size: SZ.HDR, color: MID_GREY,
              })],
            }),
          ],
        }),
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              alignment: AlignmentType.CENTER,
              children: [new TextRun({
                text: `${rpt.classification || "CONFIDENTIAL"}  \u2502  Prepared by WA Communications Research Team`,
                font: "Arial", size: SZ.HDR, color: MID_GREY,
              })],
            }),
          ],
        }),
      },
      children,
    },
  ],
});

Packer.toBuffer(doc).then((buffer) => {
  const outputDir = path.dirname(args.output);
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });
  fs.writeFileSync(args.output, buffer);
  console.log(`Report generated: ${args.output}`);
});
