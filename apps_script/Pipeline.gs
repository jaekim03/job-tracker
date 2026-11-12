/**
 * Pipeline flow chart for job-tracker.
 *
 * Install once: in the sheet, Extensions → Apps Script, replace everything in Code.gs with this
 * file, click Save, then reload the sheet. Use it from the "Pipeline" menu → Show pipeline.
 *
 * It reads the season picked on the Stats tab (or the active season) and draws a Sankey chart:
 * Applied → OA → Interview → Offer, with Rejected / Ghosted / Withdrawn / No response branching off.
 */

var PROGRESS = ['Applied', 'OA', 'Interview', 'Offer'];
var CLOSED = ['Rejected', 'Withdrawn', 'Ghosted'];
var NODE_COLORS = {
  'Applied': '#1a73e8', 'OA': '#8430ce', 'Interview': '#f29900', 'Offer': '#188038',
  'Rejected': '#d93025', 'Withdrawn': '#5f6368', 'Ghosted': '#9aa0a6', 'No response': '#bdc1c6'
};
var NODE_ORDER = ['Applied', 'OA', 'Interview', 'Offer', 'No response', 'Ghosted', 'Withdrawn', 'Rejected'];

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Pipeline').addItem('Show pipeline', 'showPipeline').addToUi();
}

function showPipeline() {
  var ss = SpreadsheetApp.getActive();
  var season = pickSeason_(ss);
  if (!season) {
    SpreadsheetApp.getUi().alert('No season tab found. Run track.py new-season first.');
    return;
  }
  var chart = pipelineFlows(readRows_(ss.getSheetByName(season)));
  var html = HtmlService.createHtmlOutput(renderHtml_(chart)).setWidth(980).setHeight(560);
  SpreadsheetApp.getUi().showModalDialog(html, season + ' pipeline');
}

/** Season picked in Stats!B2, else the active season from the Seasons tab. */
function pickSeason_(ss) {
  var stats = ss.getSheetByName('Stats');
  var picked = stats ? String(stats.getRange('B2').getValue()).trim() : '';
  if (picked && ss.getSheetByName(picked)) return picked;
  var seasons = ss.getSheetByName('Seasons');
  if (!seasons) return '';
  var rows = seasons.getDataRange().getValues().slice(1);
  for (var i = 0; i < rows.length; i++) {
    if (rows[i][3] === true || String(rows[i][3]).toUpperCase() === 'TRUE') return String(rows[i][0]);
  }
  return rows.length ? String(rows[rows.length - 1][0]) : '';
}

function readRows_(sheet) {
  var values = sheet.getDataRange().getValues();
  var head = values[0].map(String);
  var c = head.indexOf('Company'), s = head.indexOf('Stage'), r = head.indexOf('Reached');
  return values.slice(1)
    .filter(function (v) { return String(v[c]).trim() || String(v[s]).trim(); })
    .map(function (v) {
      return { stage: String(v[s]).trim(), reached: r < 0 ? '' : String(v[r]) };
    });
}

/**
 * Turns rows of {stage, reached} into Sankey edges.
 * Each application walks Applied → (OA) → (Interview) → (Offer) for every stage it reached,
 * then ends at its outcome: Rejected / Withdrawn / Ghosted, "No response" if it never moved
 * past Applied, or nowhere if it is still in progress.
 */
function pipelineFlows(rows) {
  var counts = {}, totals = {};
  function bump(map, key) { map[key] = (map[key] || 0) + 1; }
  rows.forEach(function (row) {
    var reached = String(row.reached || '').split(',').map(function (x) { return x.trim(); });
    var stage = row.stage || 'Applied';
    if (PROGRESS.indexOf(stage) >= 0) reached.push(stage);
    var path = PROGRESS.filter(function (p) { return p === 'Applied' || reached.indexOf(p) >= 0; });
    var end = null;
    if (CLOSED.indexOf(stage) >= 0) end = stage;
    else if (path.length === 1 && stage === 'Applied') end = 'No response';
    if (end) path = path.concat([end]);
    path.forEach(function (node) { bump(totals, node); });
    for (var i = 0; i + 1 < path.length; i++) bump(counts, path[i] + '\u0000' + path[i + 1]);
  });
  var edges = Object.keys(counts).map(function (k) {
    var parts = k.split('\u0000');
    return [parts[0], parts[1], counts[k]];
  });
  var rank = function (n) { return NODE_ORDER.indexOf(n); };
  edges.sort(function (a, b) { return rank(a[0]) - rank(b[0]) || rank(a[1]) - rank(b[1]); });
  return { edges: edges, totals: totals, total: rows.length };
}

function renderHtml_(chart) {
  var label = function (n) { return n + '  ' + chart.totals[n]; };
  var seen = [], rows = [];
  chart.edges.forEach(function (e) {
    [e[0], e[1]].forEach(function (n) { if (seen.indexOf(n) < 0) seen.push(n); });
    rows.push([label(e[0]), label(e[1]), e[2]]);
  });
  var colors = seen.map(function (n) { return NODE_COLORS[n] || '#9aa0a6'; });
  var data = JSON.stringify({ rows: rows, colors: colors, total: chart.total }).replace(/</g, '\\u003c');
  return [
    '<!doctype html><html><head><meta charset="utf-8">',
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">',
    '<style>body{margin:0;padding:16px 20px;font-family:Inter,Arial,sans-serif;color:#202124}',
    '.sub{color:#5f6368;font-size:12px;margin:0 0 8px}#chart{width:940px;height:470px}',
    '.empty{color:#5f6368;padding:40px 0}</style></head><body>',
    '<p class="sub" id="sub"></p><div id="chart"></div>',
    '<script src="https://www.gstatic.com/charts/loader.js"></script>',
    '<script>var D=' + data + ';',
    'document.getElementById("sub").textContent=D.total+" applications";',
    'if(!D.rows.length){document.getElementById("chart").innerHTML="<p class=empty>No applications yet.</p>";}',
    'else{google.charts.load("current",{packages:["sankey"]});google.charts.setOnLoadCallback(function(){',
    'var t=new google.visualization.DataTable();t.addColumn("string","From");t.addColumn("string","To");',
    't.addColumn("number","Applications");t.addRows(D.rows);',
    'new google.visualization.Sankey(document.getElementById("chart")).draw(t,{sankey:{',
    'node:{colors:D.colors,width:10,nodePadding:22,label:{fontName:"Inter",fontSize:13,color:"#202124"}},',
    'link:{colorMode:"gradient",colors:D.colors,fillOpacity:0.35}}});});}',
    '</script></body></html>'
  ].join('');
}

// Lets the local test suite load this file with Node; ignored by Apps Script.
if (typeof module !== 'undefined') module.exports = { pipelineFlows: pipelineFlows, renderHtml_: renderHtml_ };
