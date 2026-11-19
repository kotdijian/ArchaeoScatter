"""Shared axis scale and common major-tick spacing for XY data plots."""
import math

from matplotlib.ticker import MultipleLocator


def common_interval(request, spans):
    if request.get("tickmode", "auto") == "manual":
        try:
            step = float(request.get("tickstep", ""))
        except (ValueError, TypeError):
            raise ValueError("目盛間隔に正の数値を入力してください。") from None
        if not math.isfinite(step) or step <= 0:
            raise ValueError("目盛間隔に正の有限な数値を入力してください。")
        if max(spans) / step > 200:
            raise ValueError("目盛が多すぎます。表示範囲内の間隔数が200以下になる値を指定してください。")
        return step
    target = max(spans) / 6
    power = 10 ** math.floor(math.log10(target))
    return next(factor * power for factor in (1, 2, 2.5, 5, 10)
                if factor * power >= target)


def apply_axes(axes, request, limits=None):
    if limits is None:
        limits = [axes[0].get_xlim(), axes[0].get_ylim()]
    limits = [tuple(pair) for pair in limits]
    for i, key in enumerate(("x", "y")):
        if request.get(key+"mode") == "manual":
            limits[i] = float(request[key+"min"]), float(request[key+"max"])
    step = common_interval(request, [high-low for low, high in limits])
    for ax in axes:
        ax.set_xlim(*limits[0])
        ax.set_ylim(*limits[1])
        ax.set_aspect("equal", adjustable="box")
        ax.xaxis.set_major_locator(MultipleLocator(step))
        ax.yaxis.set_major_locator(MultipleLocator(step))
    return step
