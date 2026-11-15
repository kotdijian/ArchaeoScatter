"""Plot probability ellipses and approximate Bagplots for the sample."""
import argparse
import csv
import numpy as np
from scipy.optimize import linprog
from sklearn.mixture import GaussianMixture
from scipy.spatial import ConvexHull
import archaeo_scatter as base
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon
from pathlib import Path

SAMPLE = Path(__file__).with_name("archaeo_scatter_kde_demo.csv")
OUTPUT = Path("example-output")
OUTPUT.mkdir(exist_ok=True)

parser = argparse.ArgumentParser(description="Plot the bundled sample by group.")
parser.add_argument("--refit", action="store_true", help="Use three-component GMM assignments")
args = parser.parse_args()

with SAMPLE.open(encoding="utf-8-sig", newline="") as f:
    rows=list(csv.reader(f))[1:]
labels=np.array([r[3] for r in rows])
data=np.array([[float(r[1]),float(r[2])] for r in rows])
original=labels.copy()
if args.refit:
    gmm = GaussianMixture(3, covariance_type="full", n_init=24, random_state=12, reg_covar=1e-5).fit(data)
    order = np.argsort(gmm.means_[:, 0])
    labels = np.array(list("ABC"))[gmm.predict_proba(data)[:, order].argmax(axis=1)]
changed = original != labels
colors={"A":"#255e8b","B":"#aa522c","C":"#795b9e"}
markers={"A":"o","B":"^","C":"s"}

def bagplot(points):
    """Approximate halfspace-depth regions with a dense grid of directions."""
    origin=points.mean(axis=0)
    points=points-origin
    angles=np.linspace(0,2*np.pi,2048,endpoint=False)
    directions=np.column_stack((np.cos(angles),np.sin(angles)))
    thresholds=np.sort(directions @ points.T,axis=1)
    bounds=np.column_stack((directions,np.ones(len(directions))))
    deepest=None
    counts=[]
    for k in range(1,len(points)//2+1):
        upper=thresholds[:,-k]
        fit=linprog([0,0,-1],A_ub=bounds,b_ub=upper,
                    bounds=[(None,None),(None,None),(0,None)],method="highs")
        if not fit.success:
            break
        deepest=fit.x[:2]
        counts.append(np.count_nonzero(np.all(directions@points.T <= upper[:,None]+1e-9,axis=0)))
    center=deepest
    target=len(points)//2
    outer_k=max(i+1 for i,count in enumerate(counts) if count>=target)
    inner_k=outer_k+1
    obs=points-center
    obs_radius=np.linalg.norm(obs,axis=1)
    obs_dirs=obs/np.maximum(obs_radius[:,None],1e-15)
    ray_angles=np.unique(np.r_[np.mod(np.arctan2(obs_dirs[:,1],obs_dirs[:,0]),2*np.pi),
                               np.linspace(0,2*np.pi,720,endpoint=False)])
    ray_dirs=np.column_stack((np.cos(ray_angles),np.sin(ray_angles)))
    rays=np.vstack((obs_dirs,ray_dirs))
    projection=directions@rays.T
    def radii(k):
        slack=np.maximum(0,thresholds[:,-k]-directions@center)
        return np.divide(slack[:,None],projection,out=np.full_like(projection,np.inf),
                         where=projection>1e-12).min(axis=0)
    outer=radii(outer_k)
    inner=radii(inner_k) if inner_k<=len(counts) else np.zeros_like(outer)
    n=len(points)
    growth=outer[:n]-inner[:n]
    entering=np.divide(obs_radius-inner[:n],growth,out=np.full(n,np.inf),where=growth>1e-12)
    entering[obs_radius<=inner[:n]+1e-9]=0
    entering=np.sort(entering)
    fraction=float(np.clip((entering[target-1]+entering[target])/2,0,1))
    candidate_fractions=np.unique(np.r_[0.,fraction,1.])
    def score(f):
        candidate=inner[:n]+f*growth
        count=np.count_nonzero(obs_radius<=candidate+1e-9)
        return abs(count-target), count<target
    fraction=min(candidate_fractions,key=score)
    radii_mid=inner+fraction*(outer-inner)
    bag=center+origin+ray_dirs*radii_mid[n:,None]
    outliers=obs_radius>3*radii_mid[:n]+1e-9
    kept=(points+origin)[~outliers]
    loop=kept[ConvexHull(kept).vertices]
    count=int((obs_radius<=radii_mid[:n]+1e-9).sum())
    return bag,loop,center+origin,outliers,count

fig,axs=plt.subplots(1,2,figsize=(14.1,7.05),facecolor="#edf3f2",sharex=True,sharey=True)
fig.subplots_adjust(left=.068,right=.97,bottom=.249,top=.755,wspace=.155)
fig.text(.068,.94,"archaeo_scatter",fontsize=27,fontweight="bold",color="#16343c")
fig.text(.068,.889,"3成分に再編成した確率楕円と Bagplot" if args.refit else "群別の確率楕円と Bagplot",fontsize=17,fontweight="bold",color="#192e38")
fig.text(.068,.846,f"GMMの推定群 A・B・C  ｜  80点・うち{changed.sum()}点が群を移動" if args.refit else "KDEデモの生成群を使用  ｜  口径 × 器高（cm）  ｜  80点",fontsize=11,color="#49616c")
fig.text(.965,.948,"デモ画面",fontsize=10,ha="right",color="#49616c")
for ax,title in zip(axs,["確率楕円","Bagplot（二次元ボックスプロット）"]):
    ax.set_title(title,loc="left",pad=12,fontsize=15,fontweight="bold",color="#192e38")
    ax.set(xlim=(14.4,34.4),ylim=(9.3,25.8),xlabel="口径 (cm)",ylabel="器高 (cm)",aspect="equal")
    ax.set_xticks(np.arange(15,35,2.5))
    ax.set_yticks(np.arange(10,26,2.5))
    ax.set_axisbelow(True)
    ax.grid(color="#e4ecec",linewidth=.7)
    for side,spine in ax.spines.items():
        spine.set_visible(side in ("left","bottom"))
        spine.set_color("#a8bdc2")
    ax.tick_params(labelsize=9,colors="#3d525d",labelleft=True)
    ax.xaxis.label.set_color("#253f4b")
    ax.yaxis.label.set_color("#253f4b")

angles=np.linspace(0,2*np.pi,361)
circle=np.stack((np.cos(angles),np.sin(angles)))
handles=[]
summaries=[]
for group in "ABC":
    points=data[labels==group]
    color=colors[group]
    center=points.mean(axis=0)
    covariance=np.cov(points.T)
    vals,vecs=np.linalg.eigh(covariance)
    radii=np.einsum("ij,ij->i",points-center,np.linalg.solve(covariance,(points-center).T).T)
    inside=[]
    for level,linestyle in [(.95,"--"),(.5,"-")]:
        cutoff=-2*np.log1p(-level)
        xy=center[:,None]+vecs@(np.sqrt(vals*cutoff)[:,None]*circle)
        axs[0].plot(*xy,color=color,ls=linestyle,lw=1.5)
        inside.append(int((radii<=cutoff).sum()))
    bag,loop,median,outliers,count=bagplot(points)
    axs[1].add_patch(Polygon(loop,facecolor=color,edgecolor="none",alpha=.1,zorder=1))
    axs[1].add_patch(Polygon(loop,facecolor="none",edgecolor=color,linestyle="--",linewidth=1,zorder=2))
    axs[1].add_patch(Polygon(bag,facecolor=color,edgecolor="none",alpha=.32,zorder=3))
    axs[1].add_patch(Polygon(bag,facecolor="none",edgecolor=color,linewidth=1,zorder=3))
    axs[1].scatter(*median,marker="+",s=50,color=color,linewidths=1.6,zorder=6)
    for ax,good in [(axs[0],np.ones(len(points),dtype=bool)),(axs[1],~outliers)]:
        ax.scatter(*points[good].T,color=color,marker=markers[group],s=27,
                   alpha=.9,edgecolors="white",linewidths=.4,zorder=5)
    axs[1].scatter(*points[outliers].T,facecolors="none",edgecolors=color,
                   marker=markers[group],s=49,linewidths=1.35,zorder=6)
    handles.append(Line2D([],[],color=color,marker=markers[group],linestyle="none",
                          label=f"{group}  {len(points)}点",markersize=7))
    summaries.append((group,len(points),inside[1],inside[0],count,int(outliers.sum())))
if args.refit:
    for ax in axs:
        ax.scatter(*data[changed].T,s=111,facecolors="none",edgecolors="#ce1462",
                   linewidths=1.55,marker="D",zorder=8)
        notes={"K036":(14.95,10.75),"K048":(16.1,20.5),"K029":(25.0,20.0),
               "K075":(26.15,18.77),"K038":(26.95,11.10)}
        for i in np.flatnonzero(changed):
            identifier=rows[i][0]
            name=f"{identifier}  {original[i]}→{labels[i]}"
            ax.annotate(name,data[i],xytext=notes.get(identifier, data[i] + [0.8, 1.2]),fontsize=9.2,
                        fontweight="bold",color="#9c1251",zorder=10,
                        bbox={"boxstyle":"round,pad=.24","fc":"#fff7fb","ec":"#e5aac4","lw":.65},
                        arrowprops={"arrowstyle":"-","color":"#b2195f","lw":.8,
                                    "shrinkA":3,"shrinkB":5})
    handles.append(Line2D([],[],color="#ce1462",marker="D",markerfacecolor="none",
                          linestyle="none",label="元の群から移動",markersize=7))
fig.legend(handles=handles,loc="upper right",bbox_to_anchor=(.972,.892),ncols=4,frameon=False,fontsize=9)
axs[0].legend(handles=[Line2D([],[],color="#334c56",label="50%（実線）"),
                       Line2D([],[],color="#334c56",linestyle="--",label="95%（破線）")],
              loc="upper left",fontsize=9,framealpha=.96,edgecolor="#dce8e8")
axs[1].legend(handles=[Patch(facecolor="#a6b9bf",label="bag（中心約50%）"),
                       Patch(facecolor="#edf3f2",edgecolor="#667982",linestyle="--",label="loop（外側の範囲）"),
                       Line2D([],[],color="#334c56",marker="+",linestyle="none",label="深さ中央値"),
                       Line2D([],[],color="#334c56",marker="o",markerfacecolor="none",linestyle="none",label="外れ値候補")],
              loc="upper left",fontsize=8.7,framealpha=.96,edgecolor="#dce8e8")
for x,head,subtitle in [
    (.068,"楕円内の観測点（50% / 95%）","各群の標本平均・共分散から計算"),
    (.554,"bag 内の観測点 / 外れ値候補","深さが同じ点はまとめて扱う。外れ値候補は3倍の境界の外側")]:
    fig.text(x,.146,head,fontsize=11,fontweight="bold",color="#192e38")
    fig.text(x,.067,subtitle,fontsize=9,color="#49616c")
fig.text(.068,.107,"　".join(f"{g}  {a}/{n}・{b}/{n}" for g,n,a,b,c,o in summaries),fontsize=10,color="#253f4b")
fig.text(.554,.107,"　".join(f"{g}  {c}/{n}・{o}点" for g,n,a,b,c,o in summaries),fontsize=10,color="#253f4b")
print(summaries)
for g in "ABC":
    d=base.hz_statistic(data[labels==g])
    n=np.count_nonzero(labels==g)
    p=(1+np.count_nonzero(base.null_statistics(n)>=d))/500
    print(g,n,p)
filename = "archaeo_scatter_gmm3_reclustered.png" if args.refit else "archaeo_scatter_group_demo.png"
fig.savefig(OUTPUT / filename,dpi=160,facecolor=fig.get_facecolor())
