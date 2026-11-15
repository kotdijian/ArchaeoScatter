"""Local scatterplot GUI. Run with Python 3.10+ and open the printed URL."""
import argparse
import base64
import csv
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO, StringIO
import json
from pathlib import Path
import threading
import webbrowser

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager, rcParams
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
import numpy as np
from scipy.spatial.distance import pdist
from scipy.stats import chi2

LEVELS = {"50": .5, "66.7": 2/3, "90": .9, "95": .95}
COLORS = {"50": "#11796e", "66.7": "#386ba0", "90": "#875691", "95": "#ab572e"}
DEMO_NAME = "pottery_demo.csv"
for family in ("Noto Sans CJK JP", "Hiragino Sans", "Yu Gothic", "Meiryo", "IPA Gothic"):
    if any(font.name == family for font in font_manager.fontManager.ttflist):
        rcParams["font.family"] = [family, "DejaVu Sans"]
        break
rcParams["axes.unicode_minus"] = False


def demo_csv():
    """A selected realization from a fixed bivariate normal model, rounded to mm."""
    x, residual = np.random.default_rng(64).standard_normal((2, 80))
    y = .70 * x + np.sqrt(1 - .70**2) * residual
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["資料ID", "口径 (cm)", "器高 (cm)"])
    for i, (diameter, height) in enumerate(zip(23 + 4.5*x, 16 + 3.8*y), 1):
        writer.writerow([f"P{i:03d}", f"{diameter:.1f}", f"{height:.1f}"])
    return buffer.getvalue()


def read_csv(raw):
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("cp932")
    rows = [row for row in csv.reader(StringIO(content), strict=True)
            if any(cell.strip() for cell in row)]
    if not rows or len(rows[0]) < 2:
        raise ValueError("見出し行と2列以上のデータを含むCSVを選んでください。")
    headers = [name.strip() or f"列{i}" for i, name in enumerate(rows[0], 1)]
    duplicates = {name for name in headers if headers.count(name) > 1}
    return [f"{name}（列{i}）" if name in duplicates else name
            for i, name in enumerate(headers, 1)], rows[1:]


def number(row, column):
    try:
        value = float(row[column].strip())
        return value if np.isfinite(value) else np.nan
    except (IndexError, ValueError):
        return np.nan


def hz_statistic(data):
    """Henze–Zirkler statistic using covariance with divisor n."""
    n, dimension = data.shape
    centered = data - data.mean(axis=0)
    factor = np.linalg.cholesky(centered.T @ centered / n)
    whitened = np.linalg.solve(factor, centered.T).T
    radius_sq = np.einsum("ij,ij->i", whitened, whitened)
    beta_sq = (((2*dimension + 1)*n/4)**(1/(dimension + 4)))**2 / 2
    pairs = pdist(whitened, "sqeuclidean")
    pair_term = (n + 2*np.exp(-beta_sq*pairs/2).sum()) / n**2
    normal_term = ((1+beta_sq)**(-dimension/2)
                   * np.exp(-beta_sq*radius_sq/(2*(1+beta_sq))).mean())
    return n * (pair_term - 2*normal_term + (1+2*beta_sq)**(-dimension/2))


@lru_cache(maxsize=24)
def null_statistics(n):
    """Monte Carlo calibration under N(0,I), valid by affine invariance."""
    rng = np.random.default_rng(11487)
    return np.array([hz_statistic(rng.standard_normal((n, 2))) for _ in range(499)])


@lru_cache(maxsize=8)
def diagnostics(raw, x_col, y_col, id_col):
    headers, rows = read_csv(raw)
    if x_col == y_col or not all(0 <= i < len(headers) for i in (x_col, y_col)):
        raise ValueError("XとYには別々の列を指定してください。")
    if not -1 <= id_col < len(headers):
        raise ValueError("資料ID列の選択を確認してください。")
    values = np.array([(number(row, x_col), number(row, y_col))
                       for row in rows]).reshape(-1, 2)
    good = np.isfinite(values).all(axis=1)
    data = values[good]
    ids = [rows[i][id_col] if 0 <= id_col < len(rows[i]) and rows[i][id_col].strip()
           else f"データ行 {i+1}" for i in np.flatnonzero(good)]
    n = len(data)
    p = statistic = distance_sq = eigenvalues = eigenvectors = center = None
    n_test = 0
    reason = "正規性診断には有効なデータが5点以上必要です。"
    if n >= 3:
        center = data.mean(axis=0)
        sd = data.std(axis=0, ddof=1)
        if np.all(np.isfinite(sd)) and np.all(sd > 0):
            z = (data - center) / sd
            if np.linalg.matrix_rank(z, tol=np.linalg.norm(z)*1e-10) == 2:
                corr = z.T @ z / (n - 1)
                factor = np.linalg.cholesky(corr)
                whitened = np.linalg.solve(factor, z.T).T
                distance_sq = np.einsum("ij,ij->i", whitened, whitened)
                # SVD avoids loss of precision with differently scaled axes.
                _, singular_values, axes = np.linalg.svd(data - center, full_matrices=False)
                eigenvalues = singular_values**2 / (n - 1)
                eigenvectors = axes.T
                if n >= 5:
                    tested = z
                    if n > 350:
                        sample = np.random.default_rng(621).choice(n, 350, replace=False)
                        tested = z[sample]
                    try:
                        statistic = float(hz_statistic(tested))
                    except np.linalg.LinAlgError:
                        reason = "検定に使う点の共分散を計算できません。"
                    else:
                        n_test = len(tested)
                        p = float((1 + np.count_nonzero(null_statistics(n_test) >= statistic))/500)
                        reason = ""
            else:
                reason = "点がほぼ一直線上にあるため、二変量の共分散を計算できません。"
        else:
            reason = "片方の列が一定、または数値の範囲が大きすぎます。"
    return headers, rows, data, ids, center, eigenvalues, eigenvectors, distance_sq, statistic, p, n_test, reason


def validated_limits(low, high):
    try:
        low, high = float(low), float(high)
    except (ValueError, TypeError):
        raise ValueError("手動軸の最小値と最大値に数値を入力してください。") from None
    if not (np.isfinite(low) and np.isfinite(high) and low < high):
        raise ValueError("手動軸は有限の数値で、最小値 < 最大値にしてください。")
    return low, high


def figure(title, width, height):
    fig = Figure(figsize=(width, height), facecolor="white", layout="constrained")
    ax = fig.add_subplot()
    ax.set_title(title, loc="left", fontsize=14, fontweight="bold", pad=12, color="#172b35")
    ax.grid(color="#e1e9ea", linewidth=.65)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#b4c4ca")
    ax.tick_params(colors="#3d525d", labelsize=9)
    return fig, ax


def png(fig, dpi):
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def analyse(request):
    raw = base64.b64decode(request["csv"], validate=True)
    x_col, y_col, id_col = (int(request[key]) for key in ("x", "y", "id"))
    (headers, rows, points, ids, center, values, vectors, d2, hz, p, n_test,
     reason) = diagnostics(raw, x_col, y_col, id_col)
    labels = [(request[key].strip() or headers[col])[:100]
              for key, col in (("xlabel", x_col), ("ylabel", y_col))]
    limits = {}
    for key in ("x", "y"):
        if request[key+"mode"] == "manual":
            limits[key] = validated_limits(request[key+"min"], request[key+"max"])
    display = request["ellipse"]
    draw = values is not None and (display == "always"
                                   or (display == "auto" and p is not None and p >= .05))
    fig, ax = figure("土器の口径と器高" if request["demo_axes"] else "二変量散布図", 7.4, 5.05)
    ax.set(xlabel=labels[0], ylabel=labels[1])
    n = len(points)
    outside_view = 0
    summaries = []
    if n:
        all_x, all_y = points.T
        ax.scatter(all_x, all_y, s=26, c="#294d66", edgecolors="white",
                   linewidths=.42, alpha=.77, zorder=3)
        clipped = np.zeros(n, dtype=bool)
        for key, data_axis in (("x", all_x), ("y", all_y)):
            if key in limits:
                lower, upper = limits[key]
                clipped |= (data_axis < lower) | (data_axis > upper)
        outside_view = int(clipped.sum())
        if d2 is not None:
            tail = (d2 > chi2.ppf(.99, 2)) & ~clipped
            if np.any(tail) and request["tail"]:
                ax.scatter(all_x[tail], all_y[tail], s=82, facecolors="none",
                           edgecolors="#ae562c", linewidths=1.3, zorder=4)
                if tail.sum() <= 5:
                    for i in np.flatnonzero(tail):
                        align = "right" if all_x[i] >= np.median(all_x) else "left"
                        offset = -7 if align == "right" else 7
                        ax.annotate(ids[i][:25], points[i], xytext=(offset, 8),
                                    textcoords="offset points", ha=align,
                                    fontsize=8, color="#904522", clip_on=True)
    else:
        ax.text(.5, .5, "選択した列に有効な数値の組がありません", transform=ax.transAxes,
                ha="center", color="#49616c")
    handles = []
    if draw:
        theta = np.linspace(0, 2*np.pi, 361)
        unit_circle = np.array([np.cos(theta), np.sin(theta)])
        for level in LEVELS:
            if level not in request["levels"]:
                continue
            cutoff = -2*np.log1p(-LEVELS[level])
            outline = center[:, None] + vectors @ (np.sqrt(cutoff*values)[:, None]*unit_circle)
            color = COLORS[level]
            ax.plot(*outline, color=color, linewidth=1.55, zorder=2)
            handles.append(Line2D([], [], color=color, label=f"モデル上 {level}%"))
            summaries.append({"level": level, "inside": int((d2 <= cutoff).sum()),
                              "scale": round(float(np.sqrt(cutoff)), 3)})
    if d2 is not None and request["tail"] and np.any(tail):
        handles.append(Line2D([], [], linestyle="none", marker="o", markerfacecolor="none",
                              markeredgecolor="#ae562c", label="99%領域の外側"))
    if handles:
        ax.legend(handles=handles, loc="upper left", fontsize=8, framealpha=.96,
                  edgecolor="#e1e9ea")
    for key, setter in (("x", ax.set_xlim), ("y", ax.set_ylim)):
        if key in limits:
            setter(*limits[key])
    if request["equal"]:
        ax.set_aspect("equal", adjustable="box")
    ax.margins(.09)
    if request.get("download"):
        return {"plot": png(fig, 240)}
    qq = None
    if d2 is not None:
        qq_fig, qq_ax = figure("カイ二乗 Q–Q プロット", 4.3, 3.25)
        theoretical = chi2.ppf((np.arange(n)+.5)/n, 2)
        upper = max(d2.max(), theoretical.max()) * 1.05
        qq_ax.plot([0, upper], [0, upper], "--", color="#9bafb6", linewidth=1.1)
        qq_ax.scatter(theoretical, np.sort(d2), s=14, color="#11796e", alpha=.8)
        qq_ax.set(xlabel="理論分位点（自由度2）", ylabel="観測マハラノビス距離の二乗")
        qq = png(qq_fig, 120)
    return {"plot": png(fig, 135), "qq": qq, "total": len(rows), "n": n,
            "p": p, "hz": hz, "n_test": n_test, "reason": reason, "summaries": summaries,
            "clipped": outside_view, "tail": int((d2 > chi2.ppf(.99, 2)).sum()) if d2 is not None else None,
            "draw": draw}

PAGE = r"""<!doctype html>
<html lang="ja">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>archaeo_scatter</title>
<style>
:root{font-family:"Noto Sans CJK JP","Hiragino Sans",Meiryo,sans-serif;color:#192e38;background:#edf3f2;font-size:14px}
*{box-sizing:border-box} body{margin:0} button,input,select{font:inherit} button{cursor:pointer}
header{background:#16343c;color:white;padding:23px 30px} header div{max-width:1450px;margin:auto}
h1{font-size:27px;letter-spacing:.025em;margin:0} header p{color:#d1e5e3;margin:6px 0 0;font-size:13px}
main{max-width:1450px;margin:auto;padding:22px 26px;display:grid;grid-template-columns:340px minmax(0,1fr);gap:18px;align-items:start}
.panel{background:white;border:1px solid #dce7e6;border-radius:13px;padding:16px;margin-bottom:14px}
h2{font-size:15px;margin:0 0 12px} .step{color:#08796d;font-size:12px;margin-right:7px}
p{margin:6px 0} .muted,small{color:#4e6570} small{font-size:11px}
.row,.buttons{display:flex;gap:8px;align-items:center}.row>*{flex:1;min-width:0}
button,.fileButton{border:1px solid #b4cbc7;border-radius:6px;background:#f7fbfa;color:#174944;padding:7px 10px;text-align:center}
.primary{background:#116d64;color:white;border-color:#116d64;width:100%;font-weight:bold;padding:10px}
button:disabled{opacity:.5;cursor:default} .fileButton{display:inline-block;cursor:pointer}
input[type=file]{position:absolute;width:1px;height:1px;opacity:0} input[type=file]:focus-visible+.fileButton{outline:2px solid #116d64}
select,input[type=text],input[type=number]{width:100%;padding:5px 7px;border:1px solid #cbdad9;border-radius:5px;background:white;color:#19343e}
label.field{display:block;margin:7px 0} .axis{margin:8px 0} .axis .row{margin-bottom:5px}
details{margin-top:9px} summary{cursor:pointer;color:#27594e;font-size:12px}
table{border-collapse:collapse;width:100%;font-size:11px;margin-top:8px} td,th{border-bottom:1px solid #e0e9e8;text-align:left;padding:4px 5px;white-space:nowrap} .scroll{overflow:auto}
.options{display:flex;flex-wrap:wrap;gap:5px 10px;margin:8px 0;font-variant-numeric:tabular-nums}
input[type=checkbox]{accent-color:#11796e;vertical-align:middle;margin-right:3px}
#status{font-size:12px;color:#315d5a;overflow-wrap:anywhere} #error{color:#a13f29;font-size:12px;white-space:pre-wrap}
.results{display:grid;grid-template-columns:minmax(0,1fr) minmax(250px, .57fr);gap:14px;align-items:start}
.plotPanel{padding:11px} .plotPanel .row{justify-content:space-between;padding:3px 5px 6px} .plotPanel .row>*{flex:0 0 auto} .plotPanel h2{margin:0}
img{width:100%;display:block} img:not([src]),[hidden]{display:none!important}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 10px}
.metric{background:#e9f4f0;border:1px solid #d4e8e2;border-radius:8px;padding:8px 12px;font-size:12px;color:#295851}
.metric b{color:#173d38;font-size:16px;margin-left:6px}
.diagnosis{font-weight:bold;color:#116d64} #cover td:last-child,#cover th:last-child{text-align:right}
@media(max-width:1180px){.results{grid-template-columns:1fr}.diagnostics{display:grid;grid-template-columns:1fr 1fr;gap:10px}.diagnostics .panel{margin-bottom:0}}
@media(max-width:740px){main{display:block;padding:12px}header{padding:16px}h1{font-size:21px}.diagnostics{display:block}.diagnostics .panel{margin-bottom:12px}}
</style></head>
<body>
<header><div><h1>archaeo_scatter</h1><p>CSVから、散布図・正規性診断・確率楕円を作成</p></div></header>
<main><aside>
<section class="panel"><h2><span class="step">1.</span>データを選ぶ</h2>
<div class="buttons"><button id="demo">土器デモを開く</button><input type="file" id="file" accept=".csv,text/csv"><label class="fileButton" for="file">CSVを開く</label></div>
<p id="name" class="muted"></p>
<div class="row"><label class="field">Xの列<select id="x"></select></label><label class="field">Yの列<select id="y"></select></label></div>
<details><summary>CSVプレビュー・資料ID</summary>
<label class="field">資料IDの列<select id="id"></select></label><div class="scroll"><table id="preview"></table></div></details>
</section>
<section class="panel"><h2><span class="step">2.</span>軸を設定する</h2>
<div class="axis"><div class="row"><label>X軸の名前<input id="xlabel" type="text" maxlength="100"></label>
<label>表示範囲<select id="xmode"><option value="auto">自動</option><option value="manual">手動</option></select></label></div>
<div class="row bounds" id="xbounds" hidden><label>X 最小値<input id="xmin" type="number" step="any"></label><label>X 最大値<input id="xmax" type="number" step="any"></label></div></div>
<div class="axis"><div class="row"><label>Y軸の名前<input id="ylabel" type="text" maxlength="100"></label>
<label>表示範囲<select id="ymode"><option value="auto">自動</option><option value="manual">手動</option></select></label></div>
<div class="row bounds" id="ybounds" hidden><label>Y 最小値<input id="ymin" type="number" step="any"></label><label>Y 最大値<input id="ymax" type="number" step="any"></label></div></div>
<label><input type="checkbox" id="equal">X・Yの1単位を同じ長さで表示</label>
</section>
<section class="panel"><h2><span class="step">3.</span>確率楕円を設定する</h2>
<label class="field">表示方法<select id="ellipse"><option value="auto">自動（正規性を棄却しない場合）</option><option value="always">常に表示（参考）</option><option value="off">非表示</option></select></label>
<div class="options" aria-label="モデル上の包含確率">
<label><input type="checkbox" name="level" value="50" checked>50%</label>
<label><input type="checkbox" name="level" value="66.7">66.7%</label>
<label><input type="checkbox" name="level" value="90">90%</label>
<label><input type="checkbox" name="level" value="95" checked>95%</label>
</div>
<label><input type="checkbox" id="tail" checked>99%領域の外側の点を強調</label>
</section>
<button id="update" class="primary">散布図を更新</button><p id="status" role="status"></p><p id="error" role="alert"></p>
</aside>
<div>
<div class="stats" id="stats" hidden><span class="metric">有効<b id="valid"></b></span><span class="metric">除外<b id="excluded"></b></span><span class="metric">表示範囲外<b id="clipped"></b></span></div>
<div class="results">
<section class="panel plotPanel"><div class="row"><h2>散布図</h2><button id="save" disabled>PNGを保存</button></div><img id="plot" alt="選択した変数の散布図と確率楕円"></section>
<div class="diagnostics">
<section class="panel"><h2>二変量正規性</h2><p id="decision" class="diagnosis"></p><p id="hz"></p><small id="test-note"></small><img id="qq" alt="マハラノビス距離の二乗と理論カイ二乗分位点の比較"><small id="qq-note" hidden>点が破線に沿うほど、観測距離の分布が理論分布に近くなります。</small></section>
<section class="panel"><h2>楕円内の観測点</h2><div id="cover"></div><p><small id="tail-count"></small></p></section>
</div></div>
</div>
</main>
<script>
const $ = id => document.getElementById(id);
let current = null, last = null, busy = false;
function state(text) { $('status').textContent = text; }
function setBusy(value) {
  busy = value;
  $('update').disabled = $('demo').disabled = $('file').disabled = value;
  $('save').disabled = value || !last;
}
async function call(url, payload) {
  const response = await fetch(url, payload ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)} : {});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}
function error(err) { $('error').textContent = err.message; state(''); }
function table(target, headers, rows) {
  target.replaceChildren();
  for (const [index, row] of [headers, ...rows].entries()) {
    const tr = target.insertRow();
    for (const value of row) {
      const cell = document.createElement(index ? 'td' : 'th');
      cell.textContent = value;
      tr.append(cell);
    }
  }
}
function install(info, isDemo, name) {
  current = {...info, isDemo};
  last = null;
  $('plot').removeAttribute('src');
  $('qq').removeAttribute('src');
  $('qq-note').hidden = true;
  $('stats').hidden = true;
  for (const id of ['decision','hz','test-note','cover','tail-count']) $(id).replaceChildren();
  $('name').textContent = name + ' / ' + info.total + '行';
  for (const axis of ['x','y','id']) {
    const select = $(axis);
    select.replaceChildren();
    if (axis === 'id') select.add(new Option('指定なし', -1));
    info.headers.forEach((header, index) => select.add(new Option(header,index)));
  }
  $('x').value = info.suggested[0];
  $('y').value = info.suggested[1];
  $('id').value = isDemo ? 0 : -1;
  for (const axis of ['x','y']) {
    $(axis+'label').value = info.headers[$(axis).value];
    $(axis+'mode').value = 'auto';
    $(axis+'bounds').hidden = true;
    $(axis+'min').value = $(axis+'max').value = '';
  }
  $('equal').checked = isDemo;
  table($('preview'), info.headers.slice(0,20), info.preview.map(row => row.slice(0,20)));
}
async function plot() {
  const options = {csv:current.csv};
  for (const key of ['x','y','id','xlabel','ylabel','xmode','xmin','xmax','ymode','ymin','ymax','ellipse']) options[key] = $(key).value;
  for (const key of ['equal','tail']) options[key] = $(key).checked;
  options.demo_axes = current.isDemo && options.x === '1' && options.y === '2';
  options.levels = [...document.querySelectorAll('[name=level]:checked')].map(el=>el.value);
  const data = await call('/analyse', options);
  $('plot').src = 'data:image/png;base64,'+data.plot;
  if (data.qq) $('qq').src = 'data:image/png;base64,'+data.qq;
  else $('qq').removeAttribute('src');
  $('qq-note').hidden = !data.qq;
  $('valid').textContent = data.n+' 件';
  $('excluded').textContent = (data.total-data.n)+' 件';
  $('clipped').textContent = data.clipped+' 件';
  $('stats').hidden = false;
  $('decision').textContent = data.p === null ? '判定保留' : (data.p < .05 ? '正規性を棄却' : '正規性を棄却せず');
  $('hz').textContent = data.p === null ? data.reason : 'Henze–Zirkler　p = '+data.p.toFixed(3);
  $('test-note').textContent = data.p === null ? '' : '有意水準 5% ・ Monte Carlo 499回'+(data.n_test < data.n ? ' ・ 検定は無作為抽出した '+data.n_test+'点' : '');
  $('cover').replaceChildren();
  if (data.summaries.length) {
    const t = document.createElement('table');
    $('cover').append(t);
    table(t,['モデル上','係数','実測包含率'],data.summaries.map(item => [
      item.level+'%',item.scale.toFixed(3),item.inside+'/'+data.n+'（'+(100*item.inside/data.n).toFixed(1)+'%）'
    ]));
  } else {
    $('cover').textContent = '表示中の確率楕円はありません。';
  }
  $('tail-count').textContent = data.tail === null ? '' : '99%領域の外側 '+data.tail+'件（全有効点で計算）';
  last = options;
  state('描画しました。');
}
async function action(fn) {
  if (busy) return;
  setBusy(true);
  $('error').textContent = '';
  try { await fn(); } catch (err) { error(err); }
  finally { setBusy(false); }
}
function showDemo() { return action(async () => {
  state('土器デモを読み込み中…');
  install(await call('/demo'),true,'pottery_demo.csv');
  await plot();
}); }
$('demo').onclick = showDemo;
$('file').onchange = () => action(async () => {
  const file = $('file').files[0];
  if (!file) return;
  if (file.size > 10*1024*1024) { $('file').value=''; throw new Error('10 MB以下のCSVを選んでください。'); }
  state('CSVを読み込み中…');
  try {
    const csv = await new Promise((resolve,reject) => {
      const reader=new FileReader();
      reader.onload=()=>resolve(reader.result.split(',')[1]);
      reader.onerror=()=>reject(new Error('CSVを読み込めませんでした。'));
      reader.readAsDataURL(file);
    });
    install(await call('/inspect',{csv}),false,file.name);
    await plot();
  } finally { $('file').value=''; }
});
for (const axis of ['x','y']) {
  $(axis).onchange = () => { $(axis+'label').value = current.headers[$(axis).value]; };
  $(axis+'mode').onchange = () => { $(axis+'bounds').hidden = $(axis+'mode').value !== 'manual'; };
}
$('update').onclick = () => action(async () => {
  if (!current) throw new Error('CSVを選ぶか土器デモを開いてください。');
  state('計算・描画中…');
  await plot();
});
$('save').onclick = () => action(async () => {
  state('PNGを作成中…');
  const data = await call('/analyse', {...last, download:true});
  const link = document.createElement('a');
  link.href = 'data:image/png;base64,'+data.plot;
  link.download = last.demo_axes ? 'pottery_scatter.png' : 'scatterplot.png';
  link.click();
  state('描画済みの散布図をPNGに書き出しました。');
});
showDemo();
</script></body></html>"""


def inspect(raw):
    headers, rows = read_csv(raw)
    numeric = [i for i in range(len(headers))
               if any(np.isfinite(number(row, i)) for row in rows[:200])]
    return {"headers": headers, "preview": rows[:5], "total": len(rows),
            "suggested": numeric[:2] if len(numeric) >= 2 else [0, 1],
            "csv": base64.b64encode(raw).decode("ascii")}


class Handler(BaseHTTPRequestHandler):
    def reply(self, payload, status=200, html=False):
        data = (payload if html else json.dumps(payload, ensure_ascii=False,
                                                allow_nan=False)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ("text/html" if html else "application/json") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self.reply(PAGE, html=True)
        elif self.path == "/demo":
            self.reply(inspect(demo_csv().encode("utf-8-sig")))
        else:
            self.reply({"error": "ページが見つかりません。"}, 404)

    def do_POST(self):
        try:
            content_type = self.headers.get("Content-Type", "").split(";")[0]
            if content_type != "application/json":
                raise ValueError("リクエスト形式を確認してください。")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 15*1024*1024:
                raise ValueError("10 MB以下のCSVを選んでください。")
            payload = json.loads(self.rfile.read(size))
            if self.path == "/inspect":
                self.reply(inspect(base64.b64decode(payload["csv"], validate=True)))
            elif self.path == "/analyse":
                self.reply(analyse(payload))
            else:
                self.reply({"error": "機能が見つかりません。"}, 404)
        except (UnicodeError, csv.Error):
            self.reply({"error":"CSVを読み込めません。UTF-8またはCP932のカンマ区切りCSVを選んでください。"}, 400)
        except (ValueError, TypeError, KeyError, np.linalg.LinAlgError) as err:
            self.reply({"error": str(err)}, 400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="Local port (default: automatic)")
    parser.add_argument("--no-browser", action="store_true", help="Print URL only")
    parser.add_argument("--write-demo", type=Path, help="Write the example CSV and exit")
    args = parser.parse_args()
    if args.write_demo:
        args.write_demo.write_text(demo_csv(), encoding="utf-8-sig")
        return
    with HTTPServer(("127.0.0.1", args.port), Handler) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Open {url}  |  Stop: Ctrl+C", flush=True)
        if not args.no_browser:
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
