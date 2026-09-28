"""
The numeric side of Datalyse: the "Tools" and analysis windows.

The menu structure of the original (recovered from the TDataForm resources)
gives the list; the model templates come from a string table at VA 0x479B10
which holds exactly the expressions the "Model function" dialog offers::

    'a1*t+a2'      'a1*ln(t)+a2'    '*exp('   '*10^('
    'a2*t^a1'      '*t^'            '0.5*a1*t^2+a2*t'   't^2'
    'f(t)='        'a='

and at VA 0x477974 the acid/base tables' pKa separators (``*`` marks the
titrated proton) are parsed out of Basedata.ini / Aciddata.ini.

Everything here works on plain float lists so it is usable from the CLI, the
GUI and tests without touching a serial port.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np


# --------------------------------------------------------------------- windows
def moving_average(y: Sequence[float], width: int = 3) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    if width <= 1:
        return y.copy()
    kernel = np.ones(width) / width
    return np.convolve(y, kernel, mode="same")


def differentiate(x: Sequence[float], y: Sequence[float],
                  log_x: bool = False, log_y: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """
    "Differentiation / logarithmic axis": central differences on the raw or on
    the log-transformed axis, matching the original's Diff/ln dialog.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if log_x:
        x = np.where(x > 0, np.log10(x), np.nan)
    if log_y:
        y = np.where(y > 0, np.log10(y), np.nan)
    dydx = np.gradient(y, x)
    return x, dydx


def integrate(x: Sequence[float], y: Sequence[float],
              a: float | None = None, b: float | None = None) -> float:
    """
    Numerical integration (trapezoidal) over [a, b]; defaults to the whole data
    set, which is what the "Integral" dialog does when no limits are given.
    Ignores NaNs so a log-axis transform with zeros still integrates.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if x.size < 2:
        return float("nan")
    lo = x[0] if a is None else a
    hi = x[-1] if b is None else b
    m = (x >= lo) & (x <= hi)
    if m.sum() < 2:
        return float("nan")
    return float(np.trapezoid(y[m], x[m]))


def tangent(x: Sequence[float], y: Sequence[float], at: float) -> tuple[float, float]:
    """
    Tangent to the curve at x = `at`; returned as (slope, intercept) so the GUI
    can draw the line and the CLI can print it.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if x.size < 2:
        return float("nan"), float("nan")
    i = int(np.argmin(np.abs(x - at)))
    lo, hi = max(0, i - 1), min(x.size - 1, i + 1)
    slope = (y[hi] - y[lo]) / (x[hi] - x[lo]) if hi != lo else float("nan")
    intercept = y[i] - slope * x[i]
    return float(slope), float(intercept)


# ---------------------------------------------------------------- peak finding
def _interp_zero(x, y, i, j) -> float:
    if y[j] == y[i]:
        return float((x[i] + x[j]) / 2)
    return float(x[i] - y[i] * (x[j] - x[i]) / (y[j] - y[i]))


def extrema(x: Sequence[float], y: Sequence[float]) -> dict:
    """
    The "Maximum" / "Minimum" / "Zero" menu points.

    Zero crossings are linearly interpolated, which is what you need to read a
    titration equivalence point or a half-life off the curve.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if x.size == 0:
        return {"maximum": None, "minimum": None, "zeros": []}
    imax = int(np.argmax(y))
    imin = int(np.argmin(y))
    zeros = []
    for i in range(x.size - 1):
        if y[i] == 0:
            zeros.append(float(x[i]))
        elif y[i] * y[i + 1] < 0:
            zeros.append(_interp_zero(x, y, i, i + 1))
    return {"maximum": (float(x[imax]), float(y[imax])),
            "minimum": (float(x[imin]), float(y[imin])),
            "zeros": zeros}


# ------------------------------------------------------------------ regression
def linear_regression(x: Sequence[float], y: Sequence[float],
                      log_x: bool = False, log_y: bool = False) -> dict:
    """
    "Linear regression" with the "Regres on/off" data selection: optionally fit
    log(x) or log(y), which is how the original fits exponentials and powers.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = ~(np.isnan(x) | np.isnan(y))
    if log_x:
        ok &= x > 0
    if log_y:
        ok &= y > 0
    x, y = x[ok], y[ok]
    if x.size < 2:
        raise ValueError("need at least two points")
    fx = np.log10(x) if log_x else x
    fy = np.log10(y) if log_y else y
    slope, intercept = np.polyfit(fx, fy, 1)
    pred = slope * fx + intercept
    ss_res = float(np.sum((fy - pred) ** 2))
    ss_tot = float(np.sum((fy - np.mean(fy)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else float("nan")
    return {"slope": float(slope), "intercept": float(intercept), "r2": r2,
            "log_x": log_x, "log_y": log_y, "n": int(x.size)}


# ------------------------------------------------------------------ model fits
@dataclass
class Model:
    key: str
    template: str                      # exactly as the dialog shows it
    func: Callable[[np.ndarray, float, float], np.ndarray]
    init: Callable[[np.ndarray, np.ndarray], tuple[float, float]]


def _init_linear(x, y):
    s, i = np.polyfit(x, y, 1)
    return float(s), float(i)


def _init_exp(x, y):
    ok = y > 0
    if ok.sum() >= 2:
        s, i = np.polyfit(x[ok], np.log(y[ok]), 1)
        return float(math.exp(i)), float(s)
    return 1.0, 0.1


def _init_pow(x, y):
    ok = (x > 0) & (y > 0)
    if ok.sum() >= 2:
        s, i = np.polyfit(np.log(x[ok]), np.log(y[ok]), 1)
        return float(s), float(math.exp(i))
    return 1.0, 1.0


MODELS = {
    "linear": Model("linear", "a1*t+a2", lambda t, a1, a2: a1 * t + a2, _init_linear),
    "log": Model("log", "a1*ln(t)+a2",
                 lambda t, a1, a2: a1 * np.log(t) + a2,
                 lambda x, y: (float(np.polyfit(np.log(x[x > 0]), y[x > 0], 1)[0]),
                               float(np.polyfit(np.log(x[x > 0]), y[x > 0], 1)[1]))),
    "exp10": Model("exp10", "a1*10^(a2*t)",
                   lambda t, a1, a2: a1 * np.power(10.0, a2 * t), _init_exp),
    "exp": Model("exp", "a1*exp(a2*t)",
                 lambda t, a1, a2: a1 * np.exp(a2 * t), _init_exp),
    "power": Model("power", "a2*t^a1",
                   lambda t, a1, a2: a2 * np.power(t, a1), _init_pow),
    "quadratic": Model("quadratic", "0.5*a1*t^2+a2*t",
                       lambda t, a1, a2: 0.5 * a1 * t * t + a2 * t,
                       _init_linear),
}


def fit_model(x: Sequence[float], y: Sequence[float], model: str = "linear") -> dict:
    """
    Least-squares fit of one of the dialog's model functions.

    Uses numpy's Levenberg-Marquardt (`scipy` is deliberately not a dependency,
    so this is a compact Gauss-Newton with numeric Jacobian).
    """
    if model not in MODELS:
        raise KeyError(f"unknown model {model!r}; have {sorted(MODELS)}")
    m = MODELS[model]
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if x.size < 2:
        raise ValueError("need at least two points")
    p = np.array(m.init(x, y), dtype=float)

    def residual(params):
        try:
            return m.func(x, params[0], params[1]) - y
        except (ValueError, FloatingPointError):
            return np.full_like(y, 1e12)

    lam = 1e-3
    r = residual(p)
    cost = float(np.dot(r, r))
    for _ in range(200):
        # numeric Jacobian
        J = np.zeros((x.size, 2))
        for k in range(2):
            dp = np.zeros(2)
            dp[k] = max(1e-8, abs(p[k]) * 1e-6)
            J[:, k] = (residual(p + dp) - r) / dp[k]
        A = J.T @ J
        g = J.T @ r
        try:
            step = np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-12), -g)
        except np.linalg.LinAlgError:
            break
        trial = p + step
        rt = residual(trial)
        ct = float(np.dot(rt, rt))
        if ct < cost:
            p, r, cost = trial, rt, ct
            lam = max(lam * 0.3, 1e-12)
            if np.linalg.norm(step) < 1e-12 * (1 + np.linalg.norm(p)):
                break
        else:
            lam *= 10
            if lam > 1e12:
                break
    pred = m.func(x, p[0], p[1])
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return {"model": model, "template": m.template, "params": [float(p[0]), float(p[1])],
            "r2": 1.0 - ss_res / ss_tot if ss_tot else float("nan")}


# ---------------------------------------------------------------- half-life etc
def half_life(x: Sequence[float], y: Sequence[float]) -> float | None:
    """
    "Half life" window: fit ln(y) = ln(a1) + a2*t and return ln(2)/-a2.
    Counts must decay, so a positive a2 means the data is not a decay curve.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    # the original subtracts a constant background first if one is entered
    ok = y > 0
    x, y = x[ok], y[ok]
    if x.size < 2:
        return None
    slope, _ = np.polyfit(x, np.log(y), 1)
    if slope >= 0:
        return None
    return float(math.log(2) / -slope)


def poisson_expected(counts: Sequence[float], nbins: int | None = None) -> dict:
    """
    "Poisson" window: the observed histogram of a counting series next to the
    Poisson distribution with the same mean.
    """
    counts = np.asarray(counts, dtype=float)
    counts = counts[~np.isnan(counts)]
    if counts.size == 0:
        return {}
    mean = float(np.mean(counts))
    var = float(np.var(counts, ddof=1)) if counts.size > 1 else float("nan")
    lo, hi = int(counts.min()), int(counts.max())
    edges = np.arange(lo, hi + 2) - 0.5
    obs, _ = np.histogram(counts, bins=edges)
    expected = [
        float(counts.size * math.exp(-mean) * mean ** k / math.factorial(k))
        for k in range(lo, hi + 1)
    ]
    return {"mean": mean, "variance": var, "bins": list(range(lo, hi + 1)),
            "observed": obs.tolist(), "expected": expected,
            "n": int(counts.size)}


# ------------------------------------------------------------------- titration
@dataclass
class Acid:
    name: str
    pka: list[float] = field(default_factory=list)
    #: index of the proton that is being titrated ('*' in the data files)
    marked: int | None = None

    @property
    def z(self) -> int:
        """Number of acidic protons -- one equivalence point per proton."""
        return len(self.pka)


def parse_acid_line(line: str) -> Acid | None:
    """
    One line of Aciddata.ini / Basedata.ini::

        Sulfuric acid/*-3.0/1.99
        L-Arginine/2.02/8.99/*12.47

    '/'-separated: the name, then one field per pKa.  A field containing '*'
    marks the proton the titration actually titrates (the program draws that
    curve); a bare number is a proton that is already dissociated.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = [p.strip() for p in line.split("/")]
    if len(parts) < 2:
        return None
    name, rest = parts[0], parts[1:]
    pka, marked = [], None
    for i, tok in enumerate(rest):
        star = "*" in tok
        num = tok.replace("*", "").strip()
        if num == "":
            continue
        try:
            val = float(num)
        except ValueError:
            continue
        if star:
            marked = len(pka)
        pka.append(val)
    if not pka:
        return None
    return Acid(name=name, pka=pka, marked=marked)


def load_acids(path: str) -> list[Acid]:
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("cp1252")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", "replace")
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        a = parse_acid_line(line)
        if a:
            out.append(a)
    return out


def titration_curve(acid: Acid, conc_acid: float = 0.1, conc_base: float = 0.1,
                    v_acid: float = 25.0, step: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """
    "Simulation of titration curves": theoretical pH versus added titrant for a
    polyprotic acid, computed by solving the charge balance numerically.

    Returns (volume_ml, pH).  This is the simulation the original offers without
    any hardware attached.
    """
    if acid.z == 0:
        raise ValueError("acid has no pKa values")
    ka = [10.0 ** (-p) for p in acid.pka]
    v_max = 2.5 * acid.z * (conc_acid * v_acid) / conc_base
    vols = np.arange(0.0, max(v_max, step * 10), step)
    phs = []
    for v in vols:
        n_acid = conc_acid * v_acid / 1000.0
        n_base = conc_base * v / 1000.0
        vol = (v_acid + v) / 1000.0
        ph = _solve_ph(n_acid, n_base, vol, ka)
        phs.append(ph)
    return vols, np.array(phs)


def _solve_ph(n_acid: float, n_base: float, vol: float, ka: list[float],
              lo: float = -1.0, hi: float = 15.0) -> float:
    """Bisect on pH for the charge-balance function (charge minus net charge 0)."""

    def charge_error(ph: float) -> float:
        h = 10.0 ** (-ph)
        oh = 1e-14 / h
        # fraction of each dissociation state via the cumulative formation
        f = [1.0]
        for k in ka:
            f.append(f[-1] * k / h)          # f[i] proportional to [H_i A]
        denom = sum(f)
        z_avg = sum(i * f[i] for i in range(len(f))) / denom
        # charge balance: cations - anions
        return (n_base / vol + h) - (z_avg * n_acid / vol + oh)

    a, b = lo, hi
    fa = charge_error(a)
    fb = charge_error(b)
    if fa == 0:
        return a
    if fb == 0:
        return b
    if fa * fb > 0:                          # bracket failed; clamp
        return 7.0
    for _ in range(200):
        m = 0.5 * (a + b)
        fm = charge_error(m)
        if fa * fm <= 0:
            b, fb = m, fm
        else:
            a, fa = m, fm
    return 0.5 * (a + b)


# ---------------------------------------------------------------------- fourier
def fourier_spectrum(y: Sequence[float], sample_interval: float = 1.0) -> dict:
    """FFT magnitude/phase for the sound-card "Fourier" window."""
    y = np.asarray(y, dtype=float)
    y = y[~np.isnan(y)]
    n = y.size
    if n < 2:
        return {}
    y = y - y.mean()
    spec = np.fft.rfft(y * np.hanning(n))
    freqs = np.fft.rfftfreq(n, d=sample_interval)
    mag = np.abs(spec) * 2.0 / np.sum(np.hanning(n))
    peak = int(np.argmax(mag[1:]) + 1) if mag.size > 1 else 0
    return {"frequencies": freqs, "magnitude": mag,
            "peak_frequency": float(freqs[peak]) if freqs.size else float("nan")}


# ------------------------------------------------------------------------ scale
def autoscale(y: Sequence[float], padding: float = 0.05) -> tuple[float, float]:
    """
    "Autoscale": the original adds a small margin and snaps the range to
    "nice" numbers, which is why its axes read 0, 20, 40 ... rather than the
    exact data limits.
    """
    y = np.asarray(y, dtype=float)
    y = y[~np.isnan(y)]
    if y.size == 0:
        return 0.0, 1.0
    lo, hi = float(y.min()), float(y.max())
    if lo == hi:
        return lo - 0.5, hi + 0.5
    pad = (hi - lo) * padding
    return _nice(lo - pad, down=True), _nice(hi + pad, down=False)


def _nice(v: float, down: bool) -> float:
    if v == 0:
        return 0.0
    exp = math.floor(math.log10(abs(v)))
    step = 10.0 ** exp
    frac = abs(v) / step
    for cand in (1, 2, 2.5, 5, 10):
        if frac <= cand:
            scaled = cand * step
            break
    else:
        scaled = 10 * step
    return -scaled if v < 0 else scaled
