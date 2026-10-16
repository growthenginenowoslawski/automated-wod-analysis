"""Turn raw pose landmarks (+ audio) into body signals and low-level events."""
import numpy as np
import pandas as pd
import scipy.io.wavfile as wavfile
import scipy.signal as sg

# MediaPipe landmark ids
NOSE, LSH, RSH, LWR, RWR, LHIP, RHIP, LANK, RANK = 0, 11, 12, 15, 16, 23, 24, 27, 28


class Signals:
    """All signals in 'torso lengths' (shoulder-to-hip distance), positive = higher."""

    def __init__(self, pose):
        F = pose["frames"]
        self.fps = float(pose["fps"])
        self.t = np.array([f["t"] for f in F])
        g = lambda i, k: np.array([f["p"][i][k] if f["p"] else np.nan for f in F])
        sh = (g(LSH, 1) + g(RSH, 1)) / 2
        hp = (g(LHIP, 1) + g(RHIP, 1)) / 2
        wr = (g(LWR, 1) + g(RWR, 1)) / 2
        an = (g(LANK, 1) + g(RANK, 1)) / 2
        nose = g(NOSE, 1)
        self.present = np.array([f["p"] is not None for f in F])
        torso_f = hp - sh
        torso = np.nanmedian(torso_f)
        self.torso = torso
        # frames where the body is the usual size in frame (filters camera setup / walking up to the phone)
        with np.errstate(invalid="ignore"):
            # 2-D torso length (doesn't shrink when you bend over, unlike the vertical one)
            shx = (g(LSH, 0) + g(RSH, 0)) / 2
            hpx = (g(LHIP, 0) + g(RHIP, 0)) / 2
            t2d = np.sqrt((hpx - shx) ** 2 + (hp - sh) ** 2)
            ref = np.nanmedian(t2d)
            self.valid = self.present & (t2d > 0.6 * ref) & (t2d < 1.6 * ref)
        interp = lambda x, lim=10: pd.Series(x).interpolate(limit=lim, limit_area="inside").values
        smooth = lambda x, w=3: pd.Series(interp(x)).rolling(w, center=True, min_periods=1).mean().values
        self.hip_up_raw = interp(-hp / torso, 5)                       # for jump detection
        self.wrist_over_head = smooth((nose - wr) / torso)
        self.wrist_over_shoulder = smooth((sh - wr) / torso)
        self.feet_over_hip = smooth((hp - an) / torso)
        # floor reference = rolling high percentile of ankle y over 60 s (robust to slight camera drift)
        an_s = pd.Series(interp(an))
        floor = an_s.rolling(int(60 * self.fps), center=True, min_periods=int(5 * self.fps)).quantile(0.8).values
        self.ankle_lift = smooth((floor - an) / torso)
        sh_s = pd.Series(interp(sh))
        stand = sh_s.rolling(int(60 * self.fps), center=True, min_periods=int(5 * self.fps)).quantile(0.2).values
        self.shoulder_drop = smooth((sh - stand) / torso)
        # horizontal position in torso lengths (x is a fraction of frame width, y of frame height)
        aspect = float(pose.get("aspect", 1.0))
        self.hip_x = interp(((g(LHIP, 0) + g(RHIP, 0)) / 2) * aspect / torso)
        kl, kr = g(25, 1), g(26, 1)
        self.knee_lr = interp((kl - kr) / torso)                         # alternates when pedaling or walking
        self.knee_over_hip = smooth((hp - (kl + kr) / 2) / torso)       # small when seated (knees near hip height)
        self.wrist_x_spread = interp(np.abs(g(LWR, 0) - g(RWR, 0)) * aspect / torso)
        X = np.stack([g(i, 0) for i in range(33)], 1)
        Y = np.stack([g(i, 1) for i in range(33)], 1)
        with np.errstate(all="ignore"):
            sp = np.sqrt(np.diff(X, axis=0) ** 2 + np.diff(Y, axis=0) ** 2)
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                spd = np.r_[0, np.nanmean(sp, 1)] / torso * self.fps
        self.motion = pd.Series(interp(spd)).rolling(int(self.fps), center=True, min_periods=1).mean().values

    def idx(self, a, b):
        return (self.t >= a) & (self.t <= b)

    def peaks(self, x, a=None, b=None, height=None, prominence=None, min_gap=0.5, mask=None):
        a = self.t[0] if a is None else a
        b = self.t[-1] if b is None else b
        m = self.idx(a, b)
        if mask is not None:
            m &= mask
        tt = self.t[m]
        xx = np.nan_to_num(x[m], nan=-99)
        p, _ = sg.find_peaks(xx, height=height, prominence=prominence, distance=max(1, int(min_gap * self.fps)))
        return tt[p]


def runs(mask, t, min_len=0.0, merge_gap=0.0):
    """Contiguous True intervals of a boolean mask -> [(start, end)]."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = t[i]
        if (not v or i == len(mask) - 1) and start is not None:
            end = t[i] if v else t[i - 1]
            out.append([start, end])
            start = None
    merged = []
    for a, b in out:
        if merged and a - merged[-1][1] <= merge_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged if b - a >= min_len]


def cadence_runs(times, lo, hi, min_count):
    """Group event times into runs where consecutive gaps are within [lo, hi]."""
    groups, cur = [], []
    for x in times:
        if cur and not (lo <= x - cur[-1] <= hi):
            if len(cur) >= min_count:
                groups.append(cur)
            cur = []
        cur.append(x)
    if len(cur) >= min_count:
        groups.append(cur)
    return groups


# ---------------- audio ----------------
class Audio:
    def __init__(self, wav_path):
        sr, x = wavfile.read(wav_path)
        x = x.astype(float)
        if x.ndim > 1:
            x = x.mean(1)
        x /= (np.abs(x).max() + 1e-9)
        self.sr, self.x = sr, x
        hop = sr // 100  # 10 ms
        b, a = sg.butter(4, 2000 / (sr / 2), "high")
        y = sg.filtfilt(b, a, x)
        self.env = np.sqrt(np.convolve(y ** 2, np.ones(hop) / hop, "same"))[::hop]
        self.t = np.arange(len(self.env)) * hop / sr

    def clicks(self, a, b, prominence=1.0):
        """Sharp broadband transients (rope hitting the floor, bar drops)."""
        m = (self.t >= a) & (self.t <= b)
        p, _ = sg.find_peaks(np.log(self.env[m] + 1e-5), prominence=prominence, distance=25)
        return self.t[m][p]

    def beeps(self, fmin=700, fmax=4000, min_dur=0.25, max_dur=1.6):
        """Gym-timer beeps: a narrow, steady tone well above the background."""
        f, tt, Z = sg.stft(self.x, fs=self.sr, nperseg=1024, noverlap=768)
        P = np.abs(Z) ** 2
        band = (f >= fmin) & (f <= fmax)
        peak = P[band].max(0)
        total = P.sum(0) + 1e-12
        tonal = peak / total  # fraction of energy in one bin
        loud = P[band].sum(0) > np.percentile(P[band].sum(0), 90)
        mask = (tonal > 0.25) & loud
        return [(round(a, 2), round(b - a, 2)) for a, b in runs(mask, tt, min_len=min_dur) if b - a <= max_dur]
