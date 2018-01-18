import numpy as np


def plot_heatmap(values, xlabel="", ylabel="", xticklabels=None,
                 yticklabels=None, title=None, cmap=None, vmin=None,
                 vmax=None, ax=None, fmt="{:.2f}", xtickrotation=45,
                 norm=None):
    """Plot a matrix as heatmap with explicit numbers.

    Parameters
    ----------
    values : ndarray
        Two-dimensional array to visualize.

    xlabel : string, default=""
        Label for the x-axis.

    ylabel : string, default=""
        Label for the y-axis.

    xticklabels : list of string or None, default=None
        Tick labels for the x-axis.

    yticklabels : list of string or None, default=None
        Tick labels for the y-axis

    title : string or None, default=None
        Title of the chart

    cmap : string or colormap
        Matpotlib colormap to use.

    vmin : int, float or None
        Minimum clipping value.

    vmax : int, float or None
        Maximum clipping value.

    ax : axes object or None
        Matplotlib axes object to plot into. If None, the current axes are
        used.

    fmt : string, default="{:.2f}"
        Format string to convert value to text.

    xtickrotation : float, default=45
        Rotation of the xticklabels.

    norm : matplotlib normalizer
        Normalizer passed to pcolor
    """

    import matplotlib.pyplot as plt
    if ax is None:
        fig = plt.figure()
        ax = fig.add_subplot(111)
    img = ax.pcolormesh(values, cmap=cmap, vmin=vmin, vmax=vmax, norm=norm)

    # this will allow us to access the pixel values:
    img.update_scalarmappable()
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)

    ax.set_xlim(0, values.shape[1])
    ax.set_ylim(0, values.shape[0])

    if xticklabels is None:
        xticklabels = [""] * values.shape[1]
    if yticklabels is None:
        yticklabels = [""] * values.shape[0]

    # +.5 makes the ticks centered on the pixels
    ax.set_xticks(np.arange(values.shape[1]) + .5)
    ax.set_xticklabels(xticklabels, ha="center", rotation=xtickrotation)
    ax.set_yticks(np.arange(values.shape[0]) + .5)
    ax.set_yticklabels(yticklabels, va="center")
    ax.set_aspect(1)

    for p, color, value in zip(img.get_paths(), img.get_facecolors(),
                               img.get_array()):
        x, y = p.vertices[:-2, :].mean(0)

        # adjusting x and y for alignment:
        x = x - 1./6
        y = y + 1./6

        if np.mean(color[:3]) > 0.5:
            # pixel bright: use black for number
            c = 'k'
        else:
            c = 'w'
        ax.text(x, y, fmt.format(value), color=c, ha="center", va="center")

    # Invert the y-axis so that the matrix looks like a diagonal matrix and
    # not anti-diagonal matrix
    ax.invert_yaxis()

    # set title if not none:
    if title is not None:
        ax.set_title(title)

    return img
