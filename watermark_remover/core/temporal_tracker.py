"""Temporal watermark tracker for corner-hopping watermarks like Doubao."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class TemporalRegion:
    start_sec: float
    end_sec: float
    x: int
    y: int
    w: int
    h: int
    corner: str

    def to_dict(self) -> dict:
        return {
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "corner": self.corner,
        }


def _clamp(value, low, high):
    return max(low, min(high, value))


class TemporalWatermarkTracker:
    """Track a small corner-hopping text watermark (e.g. Doubao).

    Strategy:
      1. Collect candidate text-like patches from the four corners.
      2. Test each candidate by sliding it over the whole video. A true
         watermark gives high matches in several separate time segments
         (it follows the video between corners/scenes), while content
         (titles, subtitles) usually matches only one segment.
      3. Use the best candidate as the template and build time-segmented
         regions from its high-confidence, position-stable matches.
    """

    CORNER_LABELS = {
        "tl": "左上",
        "tr": "右上",
        "bl": "左下",
        "br": "右下",
    }

    def __init__(
        self,
        corner_w_ratio: float = 0.24,
        corner_h_ratio: float = 0.12,
        sample_interval: float = 0.5,
        match_threshold: float = 0.45,
        min_run_seconds: float = 0.25,
        position_tolerance: int = 45,
        extend_ratio: float = 0.75,
        min_confident_score: float = 0.80,
        merge_gap_seconds: float = 0.6,
        pad: int = 8,
        min_area: int = 800,
        max_area: int = 6000,
        min_w: int = 40,
        max_w: int = 190,
        min_h: int = 20,
        max_h: int = 90,
        max_candidates: int = 36,
    ):
        self.corner_w_ratio = corner_w_ratio
        self.corner_h_ratio = corner_h_ratio
        self.sample_interval = sample_interval
        self.match_threshold = match_threshold
        self.min_run_seconds = min_run_seconds
        self.position_tolerance = position_tolerance
        self.extend_ratio = extend_ratio
        self.min_confident_score = min_confident_score
        self.merge_gap_seconds = merge_gap_seconds
        self.pad = pad
        self.min_area = min_area
        self.max_area = max_area
        self.min_w = min_w
        self.max_w = max_w
        self.min_h = min_h
        self.max_h = max_h
        self.max_candidates = max_candidates

    def analyze(self, video_path: str) -> list[TemporalRegion]:
        path = Path(video_path)
        if not path.is_file():
            return []

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            return []
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0.0
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if w == 0 or h == 0:
                return []

            samples = self._collect_samples(cap, duration, fps, total_frames)
            if len(samples) < 2:
                return []

            template, tw, th = self._select_template(samples)
            if template is None:
                return []

            matches = []
            for sample in samples:
                gray = cv2.cvtColor(sample["frame"], cv2.COLOR_BGR2GRAY)
                result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                matches.append({"t": sample["t"], "score": max_val, "x": max_loc[0], "y": max_loc[1]})

            regions = self._build_regions(matches, tw, th, w, h)
            return self._consolidate(regions)
        finally:
            cap.release()

    def _collect_samples(self, cap, duration, fps, total_frames) -> list[dict]:
        samples = []
        t = 0.0
        while t <= duration:
            frame_no = int(round(t * fps))
            frame_no = min(frame_no, total_frames - 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
            ok, frame = cap.read()
            if ok and frame is not None:
                samples.append({"t": t, "frame": frame})
            t += self.sample_interval
        return samples

    def _select_template(self, samples: list[dict]) -> tuple[np.ndarray | None, int, int]:
        candidates: list[tuple[float, np.ndarray, int, int]] = []
        for sample in samples:
            frame = sample["frame"]
            h, w = frame.shape[:2]
            cw = max(self.min_w * 2, int(w * self.corner_w_ratio))
            ch = max(self.min_h * 2, int(h * self.corner_h_ratio))
            corners = [
                (0, 0, cw, ch),
                (w - cw, 0, w, ch),
                (0, h - ch, cw, h),
                (w - cw, h - ch, w, h),
            ]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            for (x1, y1, x2, y2) in corners:
                roi = gray[y1:y2, x1:x2]
                if roi.size == 0:
                    continue
                _, th = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                if th.sum() == 0:
                    continue
                horiz = cv2.dilate(
                    th,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3)),
                    iterations=1,
                )
                n, _, stats, _ = cv2.connectedComponentsWithStats(horiz, connectivity=8)
                rh, rw = roi.shape[:2]
                best_in_roi = None
                best_score = 0.0
                for i in range(1, n):
                    area = stats[i, cv2.CC_STAT_AREA]
                    x = stats[i, cv2.CC_STAT_LEFT]
                    y = stats[i, cv2.CC_STAT_TOP]
                    bw = stats[i, cv2.CC_STAT_WIDTH]
                    bh = stats[i, cv2.CC_STAT_HEIGHT]
                    if not (self.min_area <= area <= self.max_area):
                        continue
                    if not (self.min_w <= bw <= self.max_w and self.min_h <= bh <= self.max_h):
                        continue
                    if bh <= 0:
                        continue
                    aspect = bw / bh
                    if aspect < 0.8 or aspect > 4.0:
                        continue
                    if x <= 1 or y <= 1 or x + bw >= rw - 1 or y + bh >= rh - 1:
                        continue
                    fill = area / (bw * bh)
                    if fill < 0.18 or fill > 0.9:
                        continue
                    aspect_score = 1.0 if 1.1 <= aspect <= 3.0 else 0.75
                    score = fill * aspect_score * min(area / 2500.0, 1.0)
                    if score > best_score:
                        best_score = score
                        best_in_roi = (x, y, bw, bh, score)
                if best_in_roi is not None:
                    x, y, bw, bh, score = best_in_roi
                    patch = gray[y1 + y:y1 + y + bh, x1 + x:x1 + x + bw]
                    if patch.size == 0 or np.std(patch) < 6:
                        continue
                    candidates.append((score, patch.copy(), bw, bh))
        if not candidates:
            return None, 0, 0

        # Prefer candidates that match in multiple separate segments
        candidates.sort(key=lambda c: c[0], reverse=True)
        candidates = candidates[: self.max_candidates]
        best_template = None
        best_run_count = 0
        best_info = (0, 0)
        for score, patch, bw, bh in candidates:
            run_count, _ = self._count_matching_runs(patch, samples)
            if run_count > best_run_count:
                best_run_count = run_count
                best_template = patch
                best_info = (bw, bh)
            if best_run_count >= 2:
                break
        return best_template, best_info[0], best_info[1]

    def _count_matching_runs(self, template: np.ndarray, samples: list[dict]) -> tuple[int, list[tuple[float, float]]]:
        runs: list[tuple[float, float]] = []
        current_start: float | None = None
        last_score = 0.0
        for sample in samples:
            gray = cv2.cvtColor(sample["frame"], cv2.COLOR_BGR2GRAY)
            result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val >= self._template_threshold():
                if current_start is None:
                    current_start = sample["t"]
                last_score = max_val
            else:
                if current_start is not None and sample["t"] - current_start >= self.min_run_seconds:
                    runs.append((current_start, sample["t"]))
                current_start = None
        if current_start is not None:
            runs.append((current_start, samples[-1]["t"]))
        return len(runs), runs

    def _template_threshold(self) -> float:
        """Threshold used when scoring candidate templates (stricter than the
        run threshold so plain scene content is not picked as the watermark)."""
        return max(0.55, self.match_threshold)

    def _build_regions(
        self,
        matches: list[dict],
        tw: int,
        th: int,
        frame_w: int,
        frame_h: int,
    ) -> list[TemporalRegion]:
        # Group high-confidence matches into position-stable runs.
        raw_runs: list[list[int]] = []
        current: list[int] = []
        last_pos: tuple[int, int] | None = None
        for idx, match in enumerate(matches):
            if match["score"] >= self.match_threshold:
                pos = (match["x"], match["y"])
                if current:
                    moved = last_pos is not None and (
                        abs(pos[0] - last_pos[0]) > self.position_tolerance
                        or abs(pos[1] - last_pos[1]) > self.position_tolerance
                    )
                    if moved:
                        raw_runs.append(current)
                        current = []
                current.append(idx)
                last_pos = pos
            else:
                if current:
                    raw_runs.append(current)
                    current = []
                last_pos = None
        if current:
            raw_runs.append(current)

        # Grow each run into nearby transitional frames (hysteresis) so short
        # segments are not cut off at the boundaries.
        runs = [self._extend_run(matches, run) for run in raw_runs]
        runs = self._merge_close_runs(matches, runs)

        regions = []
        for run in runs:
            run_matches = [matches[i] for i in run]
            scores = [m["score"] for m in run_matches]
            duration = run_matches[-1]["t"] - run_matches[0]["t"]
            if (
                duration < self.min_run_seconds
                and len(run) < 2
                and max(scores) < self.min_confident_score
            ):
                continue
            xs = np.array([m["x"] for m in run_matches])
            ys = np.array([m["y"] for m in run_matches])
            x = int(np.median(xs))
            y = int(np.median(ys))
            x = _clamp(x - self.pad, 0, max(frame_w - 1, 0))
            y = _clamp(y - self.pad, 0, max(frame_h - 1, 0))
            w = min(tw + 2 * self.pad, frame_w - x)
            h = min(th + 2 * self.pad, frame_h - y)
            corner = self._corner_name(x, y, w, h, frame_w, frame_h)
            regions.append(
                TemporalRegion(
                    start_sec=run_matches[0]["t"],
                    end_sec=run_matches[-1]["t"],
                    x=x,
                    y=y,
                    w=max(w, 1),
                    h=max(h, 1),
                    corner=corner,
                )
            )
        regions.sort(key=lambda r: r.start_sec)
        return regions

    def _extend_run(self, matches: list[dict], run: list[int]) -> list[int]:
        """Grow a run into neighbouring frames whose match is weaker but still
        at the same position (watermark appearing/disappearing transitions)."""
        xs = np.array([matches[i]["x"] for i in run])
        ys = np.array([matches[i]["y"] for i in run])
        med_x, med_y = int(np.median(xs)), int(np.median(ys))
        low_score = self.match_threshold * self.extend_ratio

        start = run[0]
        while start - 1 >= 0:
            m = matches[start - 1]
            if (
                m["score"] >= low_score
                and abs(m["x"] - med_x) <= self.position_tolerance
                and abs(m["y"] - med_y) <= self.position_tolerance
            ):
                start -= 1
            else:
                break

        end = run[-1]
        while end + 1 < len(matches):
            m = matches[end + 1]
            if (
                m["score"] >= low_score
                and abs(m["x"] - med_x) <= self.position_tolerance
                and abs(m["y"] - med_y) <= self.position_tolerance
            ):
                end += 1
            else:
                break
        return list(range(start, end + 1))

    def _merge_close_runs(self, matches: list[dict], runs: list[list[int]]) -> list[list[int]]:
        """Merge runs at the same position that are separated by a tiny gap."""
        if not runs:
            return []
        merged: list[list[int]] = [runs[0]]
        for run in runs[1:]:
            last = merged[-1]
            gap = matches[run[0]]["t"] - matches[last[-1]]["t"]
            if gap <= self.merge_gap_seconds:
                lx = int(np.median([matches[i]["x"] for i in last]))
                ly = int(np.median([matches[i]["y"] for i in last]))
                rx = int(np.median([matches[i]["x"] for i in run]))
                ry = int(np.median([matches[i]["y"] for i in run]))
                if (
                    abs(lx - rx) <= self.position_tolerance
                    and abs(ly - ry) <= self.position_tolerance
                ):
                    merged[-1] = last + run
                    continue
            merged.append(run)
        return merged

    @staticmethod
    def _corner_name(x, y, w, h, frame_w, frame_h) -> str:
        cx = x + w / 2
        cy = y + h / 2
        horizontal = "r" if cx >= frame_w / 2 else "l"
        vertical = "b" if cy >= frame_h / 2 else "t"
        return TemporalWatermarkTracker.CORNER_LABELS[f"{vertical}{horizontal}"]

    def _consolidate(self, regions: list[TemporalRegion]) -> list[TemporalRegion]:
        if not regions:
            return []
        merged = [regions[0]]
        for r in regions[1:]:
            last = merged[-1]
            if (
                r.corner == last.corner
                and r.start_sec - last.end_sec <= self.sample_interval + 0.1
                and abs(r.x - last.x) <= self.position_tolerance
                and abs(r.y - last.y) <= self.position_tolerance
            ):
                last.end_sec = r.end_sec
                last.x = min(last.x, r.x)
                last.y = min(last.y, r.y)
                last.w = max(last.w, r.w + max(0, r.x - last.x))
                last.h = max(last.h, r.h + max(0, r.y - last.y))
            else:
                merged.append(r)
        return merged
