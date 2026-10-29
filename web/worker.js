// Runs VnEMT in a Web Worker with Pyodide so the page stays responsive during a run.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.js");

let pyodide = null;

const RUN = `
import json, time
import numpy as np
import vnemt

case = vnemt.loads(yaml_text)
case.data["case"].pop("snapshot", None)  # no snapshot files in the browser
if t_end is not None:
    case.data["case"]["solver"]["t_end_s"] = float(t_end)
t0 = time.perf_counter()
res = case.run()
elapsed = time.perf_counter() - t0
step = max(1, len(res.time) // int(max_points))
meta = {k: v for k, v in res.meta.items() if k not in ("platform", "case_file")}
json.dumps({
    "t": res.time[::step].tolist(),
    "signals": {k: np.nan_to_num(v[::step]).tolist() for k, v in res.signals.items()},
    "units": dict(res.units),
    "n_samples": int(len(res.time)),
    "step": step,
    "elapsed_s": elapsed,
    "meta": meta,
}, default=str)
`;

async function init(wheelUrl) {
  pyodide = await loadPyodide();
  postMessage({ type: "status", text: "Đang tải NumPy, SciPy, h5py…" });
  await pyodide.loadPackage(["numpy", "scipy", "pyyaml", "jsonschema", "h5py", "micropip"]);
  postMessage({ type: "status", text: "Đang cài VnEMT…" });
  pyodide.globals.set("wheel_url", wheelUrl);
  // numba is a desktop speed-up only and not available in Pyodide: install without deps
  await pyodide.runPythonAsync(
    "import micropip\nawait micropip.install(wheel_url, deps=False)\n" +
    "import vnemt\nvnemt_version = getattr(vnemt, '__version__', '?')");
  postMessage({ type: "ready", version: pyodide.globals.get("vnemt_version") });
}

self.onmessage = async (ev) => {
  const m = ev.data;
  try {
    if (m.type === "init") {
      await init(m.wheelUrl);
    } else if (m.type === "run") {
      pyodide.globals.set("yaml_text", m.yaml);
      pyodide.globals.set("t_end", m.tEnd);
      pyodide.globals.set("max_points", m.maxPoints || 5000);
      const out = await pyodide.runPythonAsync(RUN);
      postMessage({ type: "result", data: JSON.parse(out) });
    }
  } catch (err) {
    const text = String(err.message || err);
    const lines = text.trim().split("\n");
    postMessage({ type: "error", text: lines[lines.length - 1], detail: text });
  }
};
