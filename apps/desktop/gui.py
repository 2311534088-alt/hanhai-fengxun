"""Tk desktop prototype for the V1.0 product workflow."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from apps.desktop.product_model import (
    CONTROL_DISABLED, ENGINEERING_ESTIMATE, HISTORICAL_REPLAY, PUBLIC_GEOSPATIAL,
    REAL_ENVIRONMENT, SIMULATED_GEOMETRY, SIMULATED_TURBINES, SIMULATED_VESSEL,
    UNAVAILABLE, ProductReplay, ProductSnapshot,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPLAY = ROOT / "data/replay/v1.0b_synchronized_historical_mission.json"

NAVY = "#071A2B"
PANEL = "#0D2A3D"
PANEL_2 = "#12384E"
CYAN = "#38D8E8"
TEXT = "#E8F4F8"
MUTED = "#93AFBC"
GREEN = "#43D18B"
AMBER = "#F4B942"
RED = "#F25F5C"


class HanhaiDesktop(tk.Tk):
    def __init__(self, replay_path: Path = DEFAULT_REPLAY) -> None:
        super().__init__()
        self.replay = ProductReplay(replay_path)
        self.playing = False
        self.title("寒海风巡 · Hanhai Fengxun V1.0")
        self.geometry("1440x900")
        self.minsize(1180, 720)
        self.configure(bg=NAVY)
        self._configure_style()
        self._build_header()
        self._build_body()
        self._build_timeline()
        self.render(self.replay.snapshot())

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=NAVY)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Title.TLabel", background=NAVY, foreground=TEXT, font=("Microsoft YaHei UI", 19, "bold"))
        style.configure("Sub.TLabel", background=NAVY, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("PanelTitle.TLabel", background=PANEL, foreground=CYAN, font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Value.TLabel", background=PANEL, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 8))
        style.configure("Action.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=(12, 7))

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(18, 12))
        header.pack(fill="x")
        left = ttk.Frame(header)
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="寒海风巡", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="庄河寒海风电运维 · 冻结确定性决策核心 V0.9 · V1.0 产品原型", style="Sub.TLabel").pack(anchor="w")
        tags = ttk.Frame(header)
        tags.pack(side="right")
        for text, color in ((REAL_ENVIRONMENT, GREEN), (SIMULATED_VESSEL, AMBER), (CONTROL_DISABLED, RED)):
            tk.Label(tags, text=text, bg=color, fg=NAVY, font=("Microsoft YaHei UI", 8, "bold"), padx=8, pady=5).pack(side="left", padx=4)

    def _build_body(self) -> None:
        body = ttk.Frame(self, padding=(14, 0, 14, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=5)
        body.columnconfigure(2, weight=3)
        body.rowconfigure(0, weight=1)
        self.left = ttk.Frame(body, style="Panel.TFrame", padding=14)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.center = ttk.Frame(body, style="Panel.TFrame", padding=10)
        self.center.grid(row=0, column=1, sticky="nsew", padx=4)
        self.right = ttk.Frame(body, style="Panel.TFrame", padding=14)
        self.right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        self._build_environment()
        self._build_map()
        self._build_decision()

    def _section(self, parent, title: str) -> None:
        ttk.Label(parent, text=title, style="PanelTitle.TLabel").pack(anchor="w", pady=(0, 8))

    def _metric(self, parent, label: str) -> tk.StringVar:
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, style="Muted.TLabel").pack(side="left")
        value = tk.StringVar(value="—")
        ttk.Label(row, textvariable=value, style="Value.TLabel").pack(side="right")
        return value

    def _build_environment(self) -> None:
        self._section(self.left, "环境信息 / ENVIRONMENT")
        self.env_source = tk.StringVar(value=HISTORICAL_REPLAY)
        tk.Label(self.left, textvariable=self.env_source, wraplength=240, justify="left",
                 bg=PANEL_2, fg=AMBER, padx=8, pady=7, font=("Microsoft YaHei UI", 8, "bold")).pack(fill="x", pady=(0, 10))
        self.env = {name: self._metric(self.left, label) for name, label in (
            ("Hs", "有效波高 Hs"), ("Tp", "峰值周期 Tp"), ("wave", "波向"),
            ("wind", "风速 / 风向"), ("current", "表层流 / 流向"), ("depth", "水深"),
        )}
        ttk.Separator(self.left).pack(fill="x", pady=12)
        self._section(self.left, "预留能力")
        tk.Label(self.left, text="SEA ICE / ICE RISK\nUNAVAILABLE / FUTURE EXTENSION",
                 bg=PANEL_2, fg=MUTED, justify="left", anchor="w", padx=9, pady=9,
                 font=("Microsoft YaHei UI", 9)).pack(fill="x")
        ttk.Separator(self.left).pack(fill="x", pady=12)
        self._section(self.left, "来源标签")
        for text in (
            REAL_ENVIRONMENT, PUBLIC_GEOSPATIAL, SIMULATED_GEOMETRY,
            SIMULATED_TURBINES, SIMULATED_VESSEL, ENGINEERING_ESTIMATE, UNAVAILABLE,
        ):
            ttk.Label(self.left, text="• " + text, style="Muted.TLabel", wraplength=240).pack(anchor="w", pady=2)

    def _build_map(self) -> None:
        top = ttk.Frame(self.center, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="任务态势 / SIMULATED VESSEL TRACK", style="PanelTitle.TLabel").pack(side="left")
        self.time_label = tk.StringVar()
        ttk.Label(top, textvariable=self.time_label, style="Muted.TLabel").pack(side="right")
        self.canvas = tk.Canvas(self.center, bg="#082435", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(10, 0))
        self.canvas.bind("<Configure>", lambda _event: self._draw_map())

    def _build_decision(self) -> None:
        self._section(self.right, "WHAT HAPPENED / 当前状态")
        self.risk_score = tk.StringVar()
        self.risk_level = tk.StringVar()
        score = tk.Label(self.right, textvariable=self.risk_score, bg=PANEL, fg=CYAN,
                         font=("Segoe UI", 30, "bold"))
        score.pack(anchor="w")
        tk.Label(self.right, textvariable=self.risk_level, bg=PANEL, fg=TEXT,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", pady=(0, 10))
        self.decision = {name: self._metric(self.right, label) for name, label in (
            ("primary", "WHY / 主要风险"), ("resonance", "共振接近度"),
            ("q90", "Current GRID_Q90 proxy"), ("robust", "Current robust status"),
        )}
        ttk.Separator(self.right).pack(fill="x", pady=12)
        self.action = tk.StringVar()
        self.action_label = tk.Label(self.right, textvariable=self.action, bg=GREEN, fg=NAVY,
                                     font=("Microsoft YaHei UI", 15, "bold"), padx=10, pady=8)
        self.action_label.pack(fill="x")
        self.reason = tk.StringVar()
        tk.Label(self.right, textvariable=self.reason, bg=PANEL, fg=TEXT, wraplength=330,
                 justify="left", anchor="nw", font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=10)
        ttk.Separator(self.right).pack(fill="x", pady=5)
        self._section(self.right, "WHAT TO DO / 稳健主建议")
        self.candidates = {}
        for key, label in (
            ("current", "当前 SOG / HDG"), ("constrained", "约束建议 SOG / HDG"),
            ("unrestricted", "仿真敏感性最优"), ("change", "WHAT CHANGES"),
            ("maneuver", "调整 / 边界"), ("parameters", "参数来源 / 状态"),
        ):
            row = ttk.Frame(self.right, style="Panel.TFrame")
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, style="Muted.TLabel").pack(side="left")
            value = tk.StringVar(value="—")
            ttk.Label(row, textvariable=value, style="Value.TLabel").pack(side="right")
            self.candidates[key] = value
        ttk.Label(
            self.right,
            text="0.5–3.0 m/s = SIMULATION_SEARCH_BOUND\n±20% = PRELIMINARY / NEEDS REAL VESSEL VALIDATION",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(8, 0))

    def _build_timeline(self) -> None:
        bottom = ttk.Frame(self, style="Panel.TFrame", padding=(16, 10))
        bottom.pack(fill="x", padx=14, pady=(0, 14))
        controls = ttk.Frame(bottom, style="Panel.TFrame")
        controls.pack(side="left")
        ttk.Button(controls, text="◀", command=self.previous, style="Action.TButton").pack(side="left", padx=3)
        self.play_text = tk.StringVar(value="播放历史回放")
        ttk.Button(controls, textvariable=self.play_text, command=self.toggle_play, style="Action.TButton").pack(side="left", padx=3)
        ttk.Button(controls, text="▶", command=self.next, style="Action.TButton").pack(side="left", padx=3)
        self.progress = tk.StringVar()
        ttk.Label(bottom, textvariable=self.progress, style="PanelTitle.TLabel").pack(side="left", padx=18)
        self.timeline_canvas = tk.Canvas(bottom, height=68, bg=PANEL, highlightthickness=0)
        self.timeline_canvas.pack(side="left", fill="x", expand=True)

    def previous(self) -> None:
        self.playing = False
        self.play_text.set("播放历史回放")
        self.render(self.replay.previous())

    def next(self) -> None:
        self.render(self.replay.next())

    def toggle_play(self) -> None:
        self.playing = not self.playing
        self.play_text.set("暂停" if self.playing else "播放历史回放")
        if self.playing:
            self._tick()

    def _tick(self) -> None:
        if not self.playing:
            return
        if self.replay.index >= len(self.replay.records) - 1:
            self.playing = False
            self.play_text.set("重新播放")
            return
        self.render(self.replay.next())
        self.after(850, self._tick)

    @staticmethod
    def _fmt(value, unit="", digits=1) -> str:
        return "UNAVAILABLE" if value is None else f"{value:.{digits}f}{unit}"

    def render(self, s: ProductSnapshot) -> None:
        self.time_label.set(f"MISSION {s.timestamp}  ·  {s.mission_state}")
        self.env_source.set(f"{HISTORICAL_REPLAY}\nCLOCK {s.timestamp}\nSAMPLE {s.latitude:.3f}°N, {s.longitude:.3f}°E")
        self.env["Hs"].set(self._fmt(s.Hs, " m", 2))
        self.env["Tp"].set(self._fmt(s.Tp, " s", 2))
        self.env["wave"].set(self._fmt(s.wave_direction, "°"))
        self.env["wind"].set(f"{self._fmt(s.wind_speed, ' m/s')} / {self._fmt(s.wind_direction, '°')}")
        self.env["current"].set(f"{self._fmt(s.current_speed, ' m/s', 2)} / {self._fmt(s.current_direction, '°')}")
        self.env["depth"].set(self._fmt(s.water_depth, " m", 1))
        self.risk_score.set(f"{s.risk_score:.1f} / 10")
        self.risk_level.set(f"单船风险 · {s.risk_level}")
        self.decision["primary"].set(s.primary_risk)
        self.decision["resonance"].set(s.resonance_status)
        self.decision["q90"].set(self._fmt(s.current_grid_q90, "° eq.", 2))
        self.decision["robust"].set(s.current_robust_status)
        self.action.set(s.decision_action)
        color = RED if "RETURN ASSESSMENT" in s.decision_action else AMBER if "REVIEW" in s.decision_action or "ADJUSTMENT" in s.decision_action else GREEN
        self.action_label.configure(bg=color)
        self.reason.set(
            f"MISSION / {s.decision_reason}\nSOURCE: {s.decision_source}\n\n"
            f"OPERATOR ADVICE: {s.operator_advice}\n"
            f"ROBUST SOURCE: {s.robust_advice_source}\n\n"
            "DECISION ADVICE ONLY · OPERATOR RETAINS AUTHORITY"
        )
        self.candidates["current"].set(f"{self._fmt(s.SOG, ' m/s')} / {self._fmt(s.HDG, '°')}")
        self.candidates["constrained"].set(
            f"{self._fmt(s.recommended_SOG, ' m/s')} / {self._fmt(s.recommended_HDG, '°')}"
        )
        self.candidates["unrestricted"].set(
            f"{self._fmt(s.unrestricted_SOG, ' m/s')} / {self._fmt(s.unrestricted_HDG, '°')}"
        )
        self.candidates["change"].set(
            f"Q90 {self._fmt(s.current_grid_q90, '', 1)} → {self._fmt(s.recommended_grid_q90, '', 1)} · {s.recommended_robust_status}"
        )
        self.candidates["maneuver"].set(
            f"Δv {self._fmt(s.speed_change_percent, '%')} · Δψ {self._fmt(s.heading_change_deg, '°')} · boundary {s.boundary_hit}"
        )
        self.candidates["parameters"].set(f"{s.parameter_source} / {s.parameter_status}")
        self.progress.set(f"{s.index + 1:02d}/{s.total:02d}  {s.mission_state}")
        self._draw_map()
        self._draw_timeline()

    def _map_point(self, lat: float, lon: float) -> tuple[float, float]:
        width, height = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
        track = self.replay.track
        lats, lons = [p[0] for p in track], [p[1] for p in track]
        lat_span = max(max(lats) - min(lats), 1e-6)
        lon_span = max(max(lons) - min(lons), 1e-6)
        x = 55 + (lon - min(lons)) / lon_span * (width - 110)
        y = height - 55 - (lat - min(lats)) / lat_span * (height - 110)
        return x, y

    def _draw_map(self) -> None:
        if not hasattr(self, "canvas"):
            return
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        for i in range(1, 8):
            x = i * w / 8
            c.create_line(x, 0, x, h, fill="#104158")
        for i in range(1, 6):
            y = i * h / 6
            c.create_line(0, y, w, y, fill="#104158")
        points = [self._map_point(lat, lon) for lat, lon in self.replay.track]
        flat = [value for point in points for value in point]
        c.create_line(*flat, fill="#246B83", width=4, smooth=True)
        completed = points[: self.replay.index + 1]
        if len(completed) > 1:
            c.create_line(*[v for p in completed for v in p], fill=CYAN, width=5, smooth=True)
        # Public context is a coarse reference area only. Turbine points are simulated.
        c.create_rectangle(w * 0.52, h * 0.08, w * 0.94, h * 0.56, outline="#31677C", dash=(7, 5), width=2)
        c.create_text(w * 0.73, h * 0.11, text="WINDFARM REFERENCE AREA · SIMULATED EXTENT", fill=MUTED, font=("Segoe UI", 8))
        for idx in (3, 6, 8):
            if idx < len(points):
                x, y = points[idx]
                c.create_oval(x-7, y-7, x+7, y+7, outline=AMBER, width=2)
                c.create_line(x, y-7, x, y-24, fill=AMBER, width=2)
                label = f"WT-{idx:02d}" + (" · TARGET" if idx == 6 else "")
                c.create_text(x, y-34, text=label, fill=TEXT, font=("Segoe UI", 8, "bold"))
        sx, sy = points[0]
        c.create_rectangle(sx-8, sy-8, sx+8, sy+8, fill=GREEN, outline="")
        c.create_text(sx+28, sy, text="BASE", fill=GREEN, font=("Segoe UI", 8, "bold"))
        x, y = points[self.replay.index]
        c.create_polygon(x, y-13, x-9, y+10, x+9, y+10, fill=RED, outline=TEXT)
        c.create_oval(x-42, y-42, x+42, y+42, outline=RED, dash=(4, 4))
        if self.replay.snapshot().recommended_HDG is not None:
            import math
            angle = math.radians(self.replay.snapshot().recommended_HDG - 90)
            c.create_line(x, y, x + 65 * math.cos(angle), y + 65 * math.sin(angle), fill=AMBER, width=3, arrow="last")
        c.create_text(
            16, h-18, anchor="w",
            text="PUBLIC GEOSPATIAL REFERENCE NOT LOADED · SIMULATED TURBINE LAYOUT / TRACK · NOT A NAVIGATION CHART",
            fill=MUTED, font=("Segoe UI", 8),
        )

    def _draw_timeline(self) -> None:
        c = self.timeline_canvas
        c.delete("all")
        w = max(c.winfo_width(), 400)
        count = len(self.replay.timeline)
        y = 33
        c.create_line(28, y, w-28, y, fill="#31586A", width=3)
        for idx, (phase, action) in enumerate(zip(self.replay.timeline, self.replay.action_timeline)):
            x = 28 + idx * (w - 56) / max(count - 1, 1)
            active = idx <= self.replay.index
            color = CYAN if active else "#31586A"
            c.create_oval(x-6, y-6, x+6, y+6, fill=color, outline="")
            if idx in (0, 1, 6, 8, count-1):
                c.create_text(x, 54 if idx % 2 else 12, text=phase, fill=TEXT if active else MUTED, font=("Segoe UI", 7))
            if idx == self.replay.index:
                c.create_text(x, 66, text=action, fill=AMBER, font=("Segoe UI", 7, "bold"))


def run_gui(replay_path: Path = DEFAULT_REPLAY) -> None:
    HanhaiDesktop(replay_path).mainloop()


if __name__ == "__main__":
    run_gui()
