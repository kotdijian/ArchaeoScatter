"""Reproduce the KDE figure from the bundled sample CSV."""
import csv
import numpy as np
from scipy.stats import gaussian_kde
from scipy.ndimage import maximum_filter
from archaeo_scatter import figure

from pathlib import Path

SAMPLE = Path(__file__).with_name("archaeo_scatter_kde_demo.csv")
OUTPUT = Path("example-output")
OUTPUT.mkdir(exist_ok=True)

with SAMPLE.open(encoding="utf-8-sig", newline="") as source:
    rows = list(csv.reader(source))[1:]
arr = np.array([[float(row[1]), float(row[2])] for row in rows])
lab = np.array([row[3] for row in rows])
x=np.linspace(15,35,260);y=np.linspace(10,26,240);xx,yy=np.meshgrid(x,y)
xy=np.vstack([xx.ravel(),yy.ravel()])
for multiplier in [.75,1,1.25]:
 kde=gaussian_kde(arr.T,bw_method=lambda k: k.scotts_factor()*multiplier)
 z=kde(xy).reshape(xx.shape)
 peaks=np.argwhere((maximum_filter(z,size=5)==z)&(z>.03*z.max()))
 print(multiplier,[(round(x[c],2),round(y[r],2)) for r,c in peaks])
 if multiplier==1:
  chosen=z
for g in 'ABC': print(g, len(arr[lab==g]),arr[lab==g].min(0),arr[lab==g].max(0))
fig,ax=figure("KDEデモ｜近接する2群と離れた小群",8.0,5.65)
ax.contourf(xx,yy,chosen,levels=np.linspace(chosen.max()*.055,chosen.max()*1.05,12),cmap="GnBu",alpha=.31)
ax.contour(xx,yy,chosen,levels=chosen.max()*np.array([.06,.12,.21,.34,.5,.7,.87]),colors="#377c83",linewidths=.8,alpha=.78)
for group,color,marker,label in [("A","#284968","o","A｜35点"),("B","#974d29","^","B｜34点"),("C","#69568c","s","C｜11点")]:
 ax.scatter(*arr[lab==group].T,s=34,color=color,marker=marker,edgecolors="white",linewidths=.55,alpha=.9,label=label,zorder=3)
ax.set(xlabel="口径 (cm)",ylabel="器高 (cm)",xlim=(15,35),ylim=(10,26),aspect="equal")
ax.legend(title="生成群",loc="upper left",framealpha=.95,edgecolor="#dce8eb")
fig.savefig(OUTPUT/"archaeo_scatter_kde_demo.png",dpi=190)
