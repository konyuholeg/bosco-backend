import io

import matplotlib

matplotlib.use('Agg')

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator


def build_status_chart(labels, values, colors, kind='pie'):
    """Будує діаграму статусів у Matplotlib і повертає PNG як bytes."""
    fig, ax = plt.subplots(figsize=(5.4, 3.8), dpi=110)

    if sum(values) == 0:
        ax.text(0.5, 0.5, 'Немає даних', ha='center', va='center', fontsize=13, color='#6b7280')
        ax.axis('off')
    elif kind == 'bar':
        bars = ax.bar(range(len(values)), values, color=colors)
        ax.bar_label(bars, padding=2, fontsize=9)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=25, ha='right', fontsize=8)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_ylabel('Кількість вакансій', fontsize=9)
        for side in ('top', 'right'):
            ax.spines[side].set_visible(False)
    else:
        pairs = [(v, c) for v, c in zip(values, colors) if v > 0]
        ax.pie(
            [p[0] for p in pairs],
            colors=[p[1] for p in pairs],
            startangle=90,
            counterclock=False,
            wedgeprops={'width': 0.45, 'edgecolor': 'white'},
        )
        ax.legend(
            handles=[Patch(color=c, label=f'{l} — {v}') for l, v, c in zip(labels, values, colors)],
            loc='center left',
            bbox_to_anchor=(1.0, 0.5),
            frameon=False,
            fontsize=9,
        )
        ax.set_aspect('equal')

    buffer = io.BytesIO()
    fig.savefig(buffer, format='png', bbox_inches='tight')
    plt.close(fig)
    return buffer.getvalue()
