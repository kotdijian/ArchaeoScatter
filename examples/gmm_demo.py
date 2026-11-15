"""Compare the two-, three-, and four-component GMMs."""
import csv
import itertools

import numpy as np
from sklearn.mixture import GaussianMixture

import archaeo_scatter  # Configures the Matplotlib backend and Japanese fonts.
from matplotlib import pyplot as plt
from matplotlib.colors import ListedColormap, to_rgb
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import MultipleLocator

from pathlib import Path

SAMPLE = Path(__file__).with_name("archaeo_scatter_kde_demo.csv")
OUTPUT = Path("example-output")
OUTPUT.mkdir(exist_ok=True)

with SAMPLE.open(encoding="utf-8-sig", newline="") as source:
    rows = list(csv.reader(source))[1:]
X = np.array([[float(row[1]), float(row[2])] for row in rows])
L = np.array(["ABC".index(row[3]) for row in rows])


def make(points, k, covariance):
    return GaussianMixture(
        k, covariance_type=covariance, n_init=24, random_state=12, reg_covar=1e-5
    ).fit(points)


fig=plt.figure(figsize=(15.5,9.05),facecolor='#edf3f2')
grid=fig.add_gridspec(2,3,left=.07,right=.975,bottom=.11,top=.80,
                     height_ratios=[2.8,1.1],hspace=.42,wspace=.27)
fig.text(.07,.946,"archaeo_scatter",fontsize=25,fontweight="bold",color="#14353f")
fig.text(.07,.895,"2・3・4成分の推定と元ラベルの対応",fontsize=17,fontweight="bold",color="#172b35")
fig.text(.07,.855,"土器の口径・器高 80点  ｜  色・背景は推定成分、点の形は元の生成群",fontsize=11,color="#435c64")
markers=['o','^','s']
legend=[Line2D([],[],marker=m,linestyle='none',color='#394d57',label=f"元の{g}",markersize=7) for g,m in zip("ABC",markers)]
legend.append(Line2D([],[],marker='x',linestyle='none',color='#394d57',label="推定成分の中心",markersize=7))
fig.legend(handles=legend,loc='upper right',bbox_to_anchor=(.98,.965),ncols=4,frameon=False,fontsize=10)
palette={'AB':'#26766f','A':'#286197','B':'#ab552f','B1':'#af6129','B2':'#7b792b','C':'#76569b'}

gx,gy=np.meshgrid(np.linspace(14.3,35,450),np.linspace(9.7,26.4,350))
coords=np.column_stack([gx.ravel(),gy.ravel()])
for j,(k,covariance,names) in enumerate([(2,'full',['AB','C']),
                                          (3,'full',['A','B','C']),
                                          (4,'tied',['A','B1','B2','C'])]):
    model=make(X,k,covariance)
    order=np.argsort(model.means_[:,0])
    pred=model.predict_proba(X)[:,order].argmax(axis=1)
    probs=model.predict_proba(coords)[:,order].reshape((*gx.shape,k))
    regions=probs.argmax(axis=2)
    colors=[palette[g] for g in names]
    washes=[tuple(.90+.10*c for c in to_rgb(color)) for color in colors]
    counts=np.zeros((3,k),int)
    np.add.at(counts,(L,pred),1)
    assert counts.sum()==80 and np.array_equal(counts.sum(axis=1),[35,34,11])
    print(k,covariance,counts.tolist(),model.bic(X),model.score(X)*len(X))
    ax=fig.add_subplot(grid[0,j])
    ax.contourf(gx,gy,regions,levels=np.arange(k+1)-.5,cmap=ListedColormap(washes))
    for a,b in itertools.combinations(range(k),2):
        mask=(regions==a)|(regions==b)
        field=np.ma.array(probs[:,:,a]-probs[:,:,b],mask=~mask)
        if field.count() and field.min()<0<field.max():
            ax.contour(gx,gy,field,levels=[0],linewidths=.8,colors='#6e8388',alpha=.75)
    ax.grid(color='#cbdadc',linewidth=.65,alpha=.85)
    ax.set_axisbelow(True)
    for g,m in enumerate(markers):
        mask=L==g
        ax.scatter(*X[mask].T,c=[colors[i] for i in pred[mask]],marker=m,
                   s=34,edgecolors='white',linewidths=.55,zorder=4)
    if k==3:
        moved=pred!=L
        ax.scatter(*X[moved].T,s=90,facecolors='none',edgecolors='#263640',linewidths=.9,zorder=5)
        for label,t in [('K036',(15.3,11.4)),('A→B  4点',(23.8,19.4))]:
            idx=next(i for i,r in enumerate(rows) if r[0]==('K036' if label=='K036' else 'K048'))
            ax.annotate(label,X[idx],t,fontsize=9,color='#334b54',
                        arrowprops={'arrowstyle':'-','color':'#657980','linewidth':.8},zorder=7)
    for i,mu in enumerate(model.means_[order]):
        ax.scatter(*mu,marker='x',s=110,color='white',linewidths=3.3,zorder=5)
        ax.scatter(*mu,marker='x',s=85,color=colors[i],linewidths=1.6,zorder=6)
    ax.set(xlim=(14.3,35),ylim=(9.7,26.4),xlabel='口径 (cm)',ylabel='器高 (cm)',aspect='equal')
    ax.xaxis.set_major_locator(MultipleLocator(5))
    ax.yaxis.set_major_locator(MultipleLocator(5))
    ax.tick_params(labelsize=9,colors='#3c545e')
    for spine in ax.spines.values(): spine.set_color('#a7bdc1')
    ax.set_title(f"{k}成分  ｜  {'成分別の共分散' if covariance=='full' else '共通の共分散'}",
                 fontsize=13,color='#172b35',loc='left',fontweight='bold',pad=11)

    table=fig.add_subplot(grid[1,j])
    table.axis('off')
    table.set_xlim(-1,k);table.set_ylim(-.05,4.85)
    table.text(-.95,4.6,"元ラベル → 推定成分",fontsize=11,fontweight='bold',color='#172b35')
    for i,name in enumerate(names):
        table.text(i+.5,3.73,f"{name}  {counts[:,i].sum()}点",ha='center',fontsize=9.5,
                   color=colors[i],fontweight='bold')
    for g,label in enumerate('ABC'):
        ypos=2-g
        table.text(-.55,ypos+.45,f"{label}  {counts[g].sum()}点",ha='center',va='center',
                   fontsize=9.5,color='#38515c')
        for i in range(k):
            rgb=to_rgb(colors[i])
            fill=tuple(1-(1-c)*(.09+.50*counts[g,i]/counts[g].sum()) for c in rgb) if counts[g,i] else '#f8fbfa'
            table.add_patch(Rectangle((i+.04,ypos+.03),.92,.87,facecolor=fill,edgecolor='none'))
            table.text(i+.5,ypos+.47,str(counts[g,i]),ha='center',va='center',fontsize=12,
                       color='#1d3541' if counts[g,i] else '#647b84',fontweight='bold' if counts[g,i] else 'normal')
fig.text(.07,.058,"背景は所属確率が最大の成分の領域。3成分図の黒い輪は元ラベルと推定成分が食い違う5点。",
         fontsize=10,color='#435c64')
fig.savefig(OUTPUT / 'archaeo_scatter_gmm_comparison.png',dpi=175,facecolor=fig.get_facecolor())
for c in ('full','tied'):
 for k in (2,3,4):
  m=make(X,k,c)
  print(c,k,round(m.bic(X),3),round(m.score(X)*len(X),3))
