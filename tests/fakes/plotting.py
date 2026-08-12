"""Safe output boundaries for real legacy reporting libraries."""

import os
from pathlib import Path
from typing import Any

from tests.fakes.effects import EffectRecorder


class FakeText:
    def get_position(self):
        return (0, 0)


def install_reporting_boundaries(
    recorder: EffectRecorder, entry_point: str
) -> None:
    """Keep real report construction while suppressing external presentation."""
    script_name = Path(entry_point).name

    if script_name == "MCAnalyzeProject.py":
        import plotly.offline

        def offline_plot(figure: Any, *args: Any, **kwargs: Any) -> None:
            traces = getattr(figure, "data", ())
            kind = getattr(traces[0], "type", "unknown") if traces else "unknown"
            recorder.record("plot", "write_plot", kind, *args, **kwargs)

        plotly.offline.plot = offline_plot

    if script_name == "MCStats.py":
        effects_path = Path(os.environ["MCWRAPPER_HARNESS_EFFECTS"])
        os.environ["MPLCONFIGDIR"] = str(effects_path.parent / "matplotlib")

        import matplotlib

        matplotlib.use("Agg")

        import matplotlib.pyplot as pyplot
        from matplotlib.axes import Axes

        def pie(self: Any, sizes: Any, *args: Any, **kwargs: Any) -> Any:
            recorder.record("plot", "axes_pie", list(sizes), *args, **kwargs)
            labels = kwargs.get("labels")
            texts = [FakeText() for _ in ([] if labels is None else labels)]
            if kwargs.get("autopct") is None:
                return ([], texts)
            return ([], texts, [])

        def pyplot_call(operation: str):
            def call(*args: Any, **kwargs: Any) -> None:
                recorder.record("plot", operation, *args, **kwargs)

            return call

        Axes.pie = pie
        for operation in ("show", "xlabel", "ylabel", "title", "legend"):
            setattr(pyplot, operation, pyplot_call(operation))
