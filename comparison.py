"""GMM comparison figures for arbitrary uploaded CSV data."""
import numpy as np
from matplotlib.figure import Figure
from scipy.optimize import linear_sum_assignment
from plot_axes import apply_axes

PALETTE = ("#226994", "#ac4c27", "#715197", "#287963", "#8c6a24", "#974267")


def render_comparison(request, headers, rows, points, ids, candidates):
    label_col = int(request.get("label", -1))
    if not -1 <= label_col < len(headers):
        raise ValueError("ラベル列を確認してください。")
    valid_rows = []
    x, y = int(request["x"]), int(request["y"])
    for row in rows:
        try:
            if np.isfinite([float(row[x]), float(row[y])]).all():
                valid_rows.append(row)
        except (IndexError, ValueError):
            pass
    labels = [row[label_col].strip() if 0 <= label_col < len(row) else ""
              for row in valid_rows]
    names = list(dict.fromkeys(label for label in labels if label))
    if len(names) > 30:
        raise ValueError("比較図のラベルは30種類まで対応します。ラベル列に資料IDを選んでいないか確認してください。")
    ks = sorted(set(int(k) for k in request.get("compare_counts", [2, 3, 4])))
    if not ks or len(ks) > 6 or any(k not in candidates for k in ks):
        raise ValueError("計算可能な成分数を1〜6個選んでください。")
    lower, upper = points.min(axis=0), points.max(axis=0)
    padding = np.maximum((upper-lower)*.18, 1e-6)
    limits = [tuple(t) for t in zip(lower-padding, upper+padding)]
    for axis, key in enumerate(("x", "y")):
        if request[key+"mode"] == "manual":
            limits[axis] = float(request[key+"min"]), float(request[key+"max"])
    xx, yy = np.meshgrid(np.linspace(*limits[0], 140), np.linspace(*limits[1], 120))
    grid = np.column_stack((xx.ravel(), yy.ravel()))
    fig = Figure(figsize=(5.0*len(ks), 8+min(len(names),30)*.18),
                 layout="constrained", facecolor="white")
    plots = fig.subplots(2, len(ks), squeeze=False, gridspec_kw={"height_ratios":[3,2]})
    results = []
    for column, k in enumerate(ks):
        model, bic = candidates[k]
        order = np.lexsort((model.means_[:,1], model.means_[:,0]))
        probability = model.predict_proba(points)[:, order]
        predicted = probability.argmax(axis=1)
        counts = np.zeros((len(names),k), dtype=int)
        lookup = {label:i for i,label in enumerate(names)}
        for label, component in zip(labels,predicted):
            if label:
                counts[lookup[label],component] += 1
        matching = {}
        if names:
            label_indices, component_indices = linear_sum_assignment(-counts)
            matching = dict(zip(component_indices, label_indices))
        different = np.array([bool(label) and matching.get(component,-1)!=lookup.get(label,-2)
                              for label,component in zip(labels,predicted)])
        ax = plots[0,column]
        region = model.predict_proba(grid)[:,order].argmax(axis=1).reshape(xx.shape)
        if k > 1:
            from matplotlib.colors import ListedColormap, to_rgb
            colors = [tuple(.94+.06*c for c in to_rgb(PALETTE[i])) for i in range(k)]
            ax.contourf(xx,yy,region,levels=np.arange(k+1)-.5,cmap=ListedColormap(colors))
        for i in range(k):
            ax.scatter(*points[predicted==i].T,c=PALETTE[i],s=24,edgecolors="white",
                       linewidths=.4,label=f"成分{i+1} ({np.count_nonzero(predicted==i)})",zorder=3)
        ax.scatter(*points[different].T,facecolors="none",edgecolors="#cc1262",
                   marker="D",s=85,linewidths=1.1,zorder=4)
        ax.scatter(*model.means_[order].T,marker="x",c="#172f3a",s=45,zorder=5)
        ax.set(xlim=limits[0],ylim=limits[1],
               xlabel=request["xlabel"] or headers[x],ylabel=request["ylabel"] or headers[y])
        apply_axes([ax], request, limits)
        ax.set_title(f"{k}成分  BIC={bic:.1f}")
        ax.grid(alpha=.2)
        ax.legend(fontsize=8,loc="best")
        table_ax=plots[1,column]
        table_ax.axis("off")
        if names:
            cells=[[label,*map(str,counts[i])] for i,label in enumerate(names)]
            if "" in labels:
                cells.append(["ラベル未設定", *[str(np.count_nonzero((predicted==i)&(np.array(labels)==""))) for i in range(k)]])
            table=table_ax.table(cellText=cells,colLabels=["元ラベル",*[f"成分{i+1}" for i in range(k)]],
                                cellLoc="center",loc="center")
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1,1.45)
            mapping=" / ".join(f"成分{i+1}↔{names[matching[i]]}" if i in matching else f"成分{i+1}↔対応なし" for i in range(k))
            table_ax.set_title(mapping,fontsize=8,wrap=True,pad=15)
        else:
            table_ax.text(.5,.5,"ラベル列を選ぶと元ラベルとの対応件数を表示します。",
                          ha="center",wrap=True,transform=table_ax.transAxes,fontsize=10)
        changed=[{"id":ids[i],"from":labels[i],"component":int(predicted[i])+1,
                  "matched_label":names[matching[predicted[i]]] if predicted[i] in matching else "",
                  "probability":float(probability[i,predicted[i]])}
                 for i in np.flatnonzero(different)]
        results.append({"k":k,"bic":bic,"different":changed,"unlabeled":labels.count("")})
    fig.suptitle("GMM成分数の比較（"+("成分ごとの共分散" if request["covariance"]=="full" else "共通の共分散")+"）",
                 fontsize=15)
    if names:
        fig.supxlabel("赤紫のひし形は、対応件数を最大にする1対1の照合と異なる点。統合・分割時は対応表で判断してください。",
                      fontsize=9)
    return fig, results
