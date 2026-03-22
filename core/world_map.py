"""세계 지도 생성 모듈 (Skia 기반).
map_generator.py에서 분리된 세계 지도 관련 코드."""

import json
import os
import math
import skia
from PIL import Image

from core.skia_utils import skia_rgba, skia_paint, pil_to_skia_image


def _switch_sd_model(model_name):
    """SD WebUI 모델 전환 + 로딩 완료 대기"""
    try:
        import requests
        import time
        from core.sd_generator import SD_API_URL
        SD_API = SD_API_URL

        # 현재 모델 확인 — 이미 같으면 스킵
        try:
            current = requests.get(f"{SD_API}/sdapi/v1/options", timeout=10).json()
            if model_name in current.get("sd_model_checkpoint", ""):
                return True
        except Exception:
            pass

        # 모델 전환 요청
        requests.post(
            f"{SD_API}/sdapi/v1/options",
            json={"sd_model_checkpoint": model_name},
            timeout=180,
        )

        # 로딩 완료 대기 (최대 120초)
        for _ in range(60):
            time.sleep(2)
            try:
                opts = requests.get(f"{SD_API}/sdapi/v1/options", timeout=10).json()
                if model_name in opts.get("sd_model_checkpoint", ""):
                    return True
            except Exception:
                continue

        return False
    except Exception:
        return False


def _draw_parchment_bg(canvas, W, H, _rng):
    """양피지 배경 텍스처 — 판타지 지도 스타일 (다층 그라디언트 + 섬유 + 접힌 자국) [Skia]"""
    PI2 = 2 * math.pi
    _rng.seed(42)

    # ── 1) 기본 세피아톤 베이스 ──
    canvas.drawRect(skia.Rect(0, 0, W, H), skia_paint(0.89, 0.83, 0.69))

    # ── 2) 여러 겹의 radial gradient로 자연스러운 색상 변화 ──
    for _ in range(12):
        cx = _rng.random() * W
        cy = _rng.random() * H
        r_inner = 20 + _rng.random() * 80
        r_outer = r_inner + 80 + _rng.random() * 200
        r_col = 0.78 + _rng.random() * 0.12
        g_col = 0.68 + _rng.random() * 0.12
        b_col = 0.50 + _rng.random() * 0.12
        alpha = 0.06 + _rng.random() * 0.10
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeRadial(
            center=(cx, cy), radius=r_outer,
            colors=[skia_rgba(r_col, g_col, b_col, alpha), skia_rgba(r_col, g_col, b_col, 0)],
            positions=[r_inner / r_outer, 1.0],
        ))
        canvas.drawRect(skia.Rect(0, 0, W, H), p)

    # ── 3) linear gradient 얼룩 (방향성 있는 색 변화) ──
    for _ in range(6):
        x0 = _rng.random() * W
        y0 = _rng.random() * H
        angle = _rng.random() * PI2
        dist = 100 + _rng.random() * 250
        x1 = x0 + math.cos(angle) * dist
        y1 = y0 + math.sin(angle) * dist
        r_col = 0.72 + _rng.random() * 0.15
        g_col = 0.62 + _rng.random() * 0.12
        b_col = 0.42 + _rng.random() * 0.15
        alpha = 0.04 + _rng.random() * 0.08
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(x0, y0), (x1, y1)],
            colors=[skia_rgba(r_col, g_col, b_col, alpha),
                    skia_rgba(r_col, g_col, b_col, alpha * 0.3),
                    skia_rgba(r_col, g_col, b_col, 0)],
            positions=[0, 0.5, 1.0],
        ))
        canvas.drawRect(skia.Rect(0, 0, W, H), p)

    # ── 4) 미세 노이즈 (종이 질감 — 작은 반투명 점들) ──
    noise_count = max(5000, W * H // 120)
    for _ in range(noise_count):
        x = _rng.random() * W
        y = _rng.random() * H
        shade = 0.50 + _rng.random() * 0.20
        canvas.drawCircle(x, y, 0.5 + _rng.random() * 1.8,
                          skia_paint(shade, shade * 0.85, shade * 0.65, _rng.random() * 0.12))

    # ── 5) 종이 섬유 방향 텍스처 (얇은 수평/대각선 라인) ──
    # 수평 섬유
    for _ in range(300):
        fx = _rng.random() * W
        fy = _rng.random() * H
        flen = 8 + _rng.random() * 25
        angle = _rng.uniform(-0.15, 0.15)
        p = skia_paint(0.65, 0.55, 0.40, 0.04 + _rng.random() * 0.06,
                        style=skia.Paint.kStroke_Style, stroke_width=0.3)
        canvas.drawLine(fx, fy, fx + flen * math.cos(angle), fy + flen * math.sin(angle), p)
    # 대각선 섬유
    for _ in range(150):
        fx = _rng.random() * W
        fy = _rng.random() * H
        flen = 5 + _rng.random() * 18
        angle = math.pi / 4 + _rng.uniform(-0.3, 0.3)
        p = skia_paint(0.60, 0.50, 0.35, 0.03 + _rng.random() * 0.05,
                        style=skia.Paint.kStroke_Style, stroke_width=0.3)
        canvas.drawLine(fx, fy, fx + flen * math.cos(angle), fy + flen * math.sin(angle), p)

    # ── 6) 커피/물 얼룩 (불규칙 원 클러스터) ──
    for _ in range(10):
        sx = _rng.random() * W
        sy = _rng.random() * H
        sr = 25 + _rng.random() * 70
        canvas.drawCircle(sx, sy, sr, skia_paint(0.55, 0.42, 0.28, _rng.random() * 0.07))
        for _s in range(3 + int(_rng.random() * 5)):
            ox = sx + _rng.uniform(-sr, sr) * 0.8
            oy = sy + _rng.uniform(-sr, sr) * 0.8
            osr = sr * (0.2 + _rng.random() * 0.4)
            canvas.drawCircle(ox, oy, osr, skia_paint(0.52, 0.40, 0.25, _rng.random() * 0.05))

    # ── 7) 접힌 자국 (수평/수직 어두운 라인) ──
    for fold_y_ratio in [0.33 + _rng.uniform(-0.03, 0.03), 0.66 + _rng.uniform(-0.03, 0.03)]:
        fy = H * fold_y_ratio
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(0, fy - 4), (0, fy + 4)],
            colors=[skia_rgba(0.50, 0.40, 0.28, 0),
                    skia_rgba(0.45, 0.35, 0.22, 0.12),
                    skia_rgba(0.40, 0.30, 0.18, 0.18),
                    skia_rgba(0.45, 0.35, 0.22, 0.12),
                    skia_rgba(0.50, 0.40, 0.28, 0)],
            positions=[0, 0.4, 0.5, 0.6, 1.0],
        ))
        canvas.drawRect(skia.Rect(0, fy - 4, W, fy + 4), p)
    for fold_x_ratio in [0.5 + _rng.uniform(-0.05, 0.05)]:
        fx = W * fold_x_ratio
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(fx - 4, 0), (fx + 4, 0)],
            colors=[skia_rgba(0.50, 0.40, 0.28, 0),
                    skia_rgba(0.45, 0.35, 0.22, 0.10),
                    skia_rgba(0.40, 0.30, 0.18, 0.15),
                    skia_rgba(0.45, 0.35, 0.22, 0.10),
                    skia_rgba(0.50, 0.40, 0.28, 0)],
            positions=[0, 0.4, 0.5, 0.6, 1.0],
        ))
        canvas.drawRect(skia.Rect(fx - 4, 0, fx + 4, H), p)

    # ── 8) 가장자리 burn 효과 (강한 비네팅) ──
    p = skia.Paint()
    p.setAntiAlias(True)
    p.setShader(skia.GradientShader.MakeRadial(
        center=(W / 2, H / 2), radius=max(W, H) * 0.72,
        colors=[skia_rgba(0, 0, 0, 0), skia_rgba(0.25, 0.18, 0.08, 0.08), skia_rgba(0.20, 0.12, 0.05, 0.35)],
        positions=[min(W, H) * 0.25 / (max(W, H) * 0.72), 0.7, 1.0],
    ))
    canvas.drawRect(skia.Rect(0, 0, W, H), p)

    # 각 모서리 추가 burn
    corners = [(0, 0), (W, 0), (0, H), (W, H)]
    for corner_x, corner_y in corners:
        cr = 120 + _rng.random() * 80
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeRadial(
            center=(corner_x, corner_y), radius=cr,
            colors=[skia_rgba(0.25, 0.15, 0.05, 0.25), skia_rgba(0.30, 0.18, 0.08, 0.10), skia_rgba(0, 0, 0, 0)],
            positions=[0, 0.6, 1.0],
        ))
        canvas.drawRect(skia.Rect(0, 0, W, H), p)

    # 상하좌우 가장자리 추가 burn (선형)
    for (pts, rect) in [
        ([(0, 0), (0, 60)], skia.Rect(0, 0, W, 60)),
        ([(0, H - 60), (0, H)], skia.Rect(0, H - 60, W, H)),
        ([(0, 0), (60, 0)], skia.Rect(0, 0, 60, H)),
        ([(W - 60, 0), (W, 0)], skia.Rect(W - 60, 0, W, H)),
    ]:
        p = skia.Paint()
        p.setAntiAlias(True)
        if pts[0] == (0, 0) and pts[1] == (0, 60):
            colors = [skia_rgba(0.30, 0.20, 0.10, 0.25), skia_rgba(0, 0, 0, 0)]
        elif pts[0] == (0, H - 60):
            colors = [skia_rgba(0, 0, 0, 0), skia_rgba(0.30, 0.20, 0.10, 0.25)]
        elif pts[0] == (0, 0) and pts[1] == (60, 0):
            colors = [skia_rgba(0.30, 0.20, 0.10, 0.20), skia_rgba(0, 0, 0, 0)]
        else:
            colors = [skia_rgba(0, 0, 0, 0), skia_rgba(0.30, 0.20, 0.10, 0.20)]
        p.setShader(skia.GradientShader.MakeLinear(points=pts, colors=colors))
        canvas.drawRect(rect, p)


def _compute_convex_hull(points):
    """Graham scan으로 convex hull 계산. 점 리스트 -> hull 꼭짓점 리스트 (반시계 방향)"""
    points = sorted(set((p[0], p[1]) for p in points))
    if len(points) <= 1:
        return list(points)

    def cross(O, A, B):
        return (A[0] - O[0]) * (B[1] - O[1]) - (A[1] - O[1]) * (B[0] - O[0])

    lower = []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _draw_terrain_pattern(canvas, coords, terrain_type, to_pixel_fn, tw, th, _rng,
                          fill_only=False, icons_only=False):
    """지형별 판타지 스타일 패턴 — 유기적 경계 + 아이콘 렌더링 [Skia]

    fill_only=True: 배경색/블롭만 채우기 (아이콘 제외)
    icons_only=True: 아이콘만 그리기 (배경색 제외)
    둘 다 False: 기존 동작 (배경+아이콘 모두)
    """
    if not coords:
        return
    PI2 = 2 * math.pi

    # 영역 bounding box (픽셀 기준)
    pixels = [to_pixel_fn(c[0], c[1]) for c in coords]
    min_px = min(p[0] for p in pixels) - tw
    max_px = max(p[0] for p in pixels) + tw
    min_py = min(p[1] for p in pixels) - th
    max_py = max(p[1] for p in pixels) + th
    area_w = max_px - min_px
    area_h = max_py - min_py

    # ── 공통 헬퍼: convex hull 기반 지형 영역 채우기 ──
    def _fill_terrain_hull(base_r, base_g, base_b, base_a):
        """coords의 convex hull로 폴리곤을 만들어 빈틈 없이 채움"""
        hull = _compute_convex_hull(pixels)
        if len(hull) >= 3:
            cx_avg = sum(p[0] for p in hull) / len(hull)
            cy_avg = sum(p[1] for p in hull) / len(hull)
            expand = tw * 0.8
            expanded = []
            for px_h, py_h in hull:
                dx = px_h - cx_avg
                dy = py_h - cy_avg
                dist = math.sqrt(dx * dx + dy * dy)
                if dist > 0:
                    expanded.append((px_h + dx / dist * expand, py_h + dy / dist * expand))
                else:
                    expanded.append((px_h, py_h))

            # 부드러운 곡선 경로로 채우기 (skia.Path)
            path = skia.Path()
            path.moveTo(expanded[0][0], expanded[0][1])
            n = len(expanded)
            for i in range(1, n):
                prev = expanded[i - 1]
                curr = expanded[i]
                mid_x = (prev[0] + curr[0]) / 2
                mid_y = (prev[1] + curr[1]) / 2
                path.quadTo(prev[0], prev[1], mid_x, mid_y)
            last = expanded[-1]
            first = expanded[0]
            mid_x = (last[0] + first[0]) / 2
            mid_y = (last[1] + first[1]) / 2
            path.quadTo(last[0], last[1], mid_x, mid_y)
            path.close()
            canvas.drawPath(path, skia_paint(base_r, base_g, base_b, base_a))
        else:
            blob_r = tw * 1.1
            paint = skia_paint(base_r, base_g, base_b, base_a)
            for px_c, py_c in pixels:
                canvas.drawCircle(px_c, py_c, blob_r, paint)

        # 가장자리 노이즈
        noise_paint = skia_paint(base_r, base_g, base_b, base_a * 0.55)
        noise_points = hull if len(hull) >= 3 else pixels
        for px_c, py_c in noise_points:
            for _ in range(10):
                angle = _rng.random() * PI2
                dist = tw * (0.55 + _rng.random() * 0.65)
                nr = tw * (0.18 + _rng.random() * 0.32)
                nx = px_c + math.cos(angle) * dist
                ny = py_c + math.sin(angle) * dist
                canvas.drawCircle(nx, ny, nr, noise_paint)

    # ── 공통 헬퍼: 유기적 블롭 (sea 등 기존 방식 유지용) ──
    def _fill_organic_blob(base_r, base_g, base_b, base_a):
        """각 coord 중심에 원을 그려 자연스럽게 합쳐지는 블롭 형태"""
        blob_r = tw * 1.1
        for px_c, py_c in pixels:
            p = skia.Paint()
            p.setAntiAlias(True)
            p.setShader(skia.GradientShader.MakeRadial(
                center=(px_c, py_c), radius=blob_r,
                colors=[skia_rgba(base_r, base_g, base_b, base_a),
                        skia_rgba(base_r, base_g, base_b, base_a * 0.85),
                        skia_rgba(base_r, base_g, base_b, base_a * 0.35)],
                positions=[0, 0.65, 1.0],
            ))
            canvas.drawCircle(px_c, py_c, blob_r, p)
        noise_paint = skia_paint(base_r, base_g, base_b, base_a * 0.55)
        for px_c, py_c in pixels:
            for _ in range(10):
                angle = _rng.random() * PI2
                dist = blob_r * (0.55 + _rng.random() * 0.65)
                nr = blob_r * (0.18 + _rng.random() * 0.32)
                nx = px_c + math.cos(angle) * dist
                ny = py_c + math.sin(angle) * dist
                canvas.drawCircle(nx, ny, nr, noise_paint)

    def _in_region(x, y):
        """점이 영역 내에 있는지 확인"""
        return any(abs(x - p[0]) < tw and abs(y - p[1]) < th for p in pixels)

    if terrain_type == "forest":
        if not icons_only:
            _fill_terrain_hull(0.15, 0.40, 0.12, 0.80)
            for px_c, py_c in pixels:
                p = skia.Paint()
                p.setAntiAlias(True)
                p.setShader(skia.GradientShader.MakeRadial(
                    center=(px_c, py_c), radius=tw * 0.9,
                    colors=[skia_rgba(0.12, 0.35, 0.08, 0.35),
                            skia_rgba(0.18, 0.38, 0.10, 0.20),
                            skia_rgba(0.22, 0.40, 0.15, 0.05)],
                    positions=[0, 0.6, 1.0],
                ))
                canvas.drawCircle(px_c, py_c, tw * 0.9, p)

        if fill_only:
            return
        tree_count = max(30, int(area_w * area_h / 150))
        for _ in range(tree_count):
            tx = min_px + _rng.random() * area_w
            ty = min_py + _rng.random() * area_h
            if not _in_region(tx, ty):
                continue
            s = 12 + _rng.random() * 14

            # 그림자
            canvas.drawCircle(tx + 2, ty + s * 0.15, s * 0.35,
                              skia_paint(0.06, 0.15, 0.04, 0.25))
            # 줄기
            trunk_r = 0.30 + _rng.random() * 0.12
            trunk_g = 0.20 + _rng.random() * 0.08
            trunk_b = 0.08 + _rng.random() * 0.06
            p = skia_paint(trunk_r, trunk_g, trunk_b, 0.7,
                            style=skia.Paint.kStroke_Style,
                            stroke_width=max(1.5, s * 0.08))
            p.setStrokeCap(skia.Paint.kRound_Cap)
            canvas.drawLine(tx, ty + s * 0.05, tx, ty + s * 0.30, p)

            # 수관
            crown_g = 0.28 + _rng.random() * 0.18
            crown_r = 0.06 + _rng.random() * 0.10
            crown_b = 0.03 + _rng.random() * 0.06
            num_crowns = 2 + int(_rng.random() * 2)
            for ci in range(num_crowns):
                ox = _rng.uniform(-s * 0.18, s * 0.18)
                oy = _rng.uniform(-s * 0.15, s * 0.08)
                cr = s * (0.22 + _rng.random() * 0.12)
                canvas.drawCircle(tx + ox, ty - s * 0.15 + oy, cr + 1,
                                  skia_paint(crown_r * 0.5, crown_g * 0.5, crown_b * 0.5, 0.30))
                canvas.drawCircle(tx + ox, ty - s * 0.15 + oy, cr,
                                  skia_paint(crown_r, crown_g, crown_b, 0.85))
            canvas.drawCircle(tx - s * 0.06, ty - s * 0.25, s * 0.10,
                              skia_paint(crown_r + 0.15, crown_g + 0.15, crown_b + 0.05, 0.35))

    elif terrain_type == "mountain":
        if not icons_only:
            _fill_terrain_hull(0.45, 0.36, 0.26, 0.75)
            for px_c, py_c in pixels:
                p = skia.Paint()
                p.setAntiAlias(True)
                p.setShader(skia.GradientShader.MakeRadial(
                    center=(px_c, py_c), radius=tw * 0.8,
                    colors=[skia_rgba(0.52, 0.45, 0.38, 0.30),
                            skia_rgba(0.48, 0.40, 0.30, 0.18),
                            skia_rgba(0.42, 0.35, 0.25, 0.05)],
                    positions=[0, 0.6, 1.0],
                ))
                canvas.drawCircle(px_c, py_c, tw * 0.8, p)

        if fill_only:
            return
        peak_count = max(16, int(area_w * area_h / 300))
        for _ in range(peak_count):
            tx = min_px + _rng.random() * area_w
            ty = min_py + _rng.random() * area_h
            if not _in_region(tx, ty):
                continue
            s = 22 + _rng.random() * 18

            num_peaks = 2 + int(_rng.random() * 2)
            for pi in range(num_peaks):
                depth = (num_peaks - pi) / num_peaks
                ps = s * (0.5 + 0.5 * (1 - depth))
                px_off = (pi - num_peaks / 2) * s * 0.35
                py_off = -depth * s * 0.15
                alpha = 0.55 + 0.35 * (1 - depth)
                bx = tx + px_off
                by = ty + py_off

                # 산기슭
                if pi == num_peaks - 1:
                    path = skia.Path()
                    path.moveTo(bx - ps * 0.9, by + ps * 0.3)
                    path.lineTo(bx + ps * 0.9, by + ps * 0.3)
                    path.lineTo(bx + ps * 0.7, by + ps * 0.45)
                    path.lineTo(bx - ps * 0.7, by + ps * 0.45)
                    path.close()
                    canvas.drawPath(path, skia_paint(0.25, 0.38, 0.18, 0.30))

                # 오른쪽 면
                r_col = 0.52 + _rng.random() * 0.10
                g_col = 0.44 + _rng.random() * 0.08
                b_col = 0.34 + _rng.random() * 0.06
                path = skia.Path()
                path.moveTo(bx, by - ps)
                path.lineTo(bx + ps * 0.85, by + ps * 0.3)
                path.lineTo(bx, by + ps * 0.3)
                path.close()
                canvas.drawPath(path, skia_paint(r_col, g_col, b_col, alpha))

                # 왼쪽 면 그림자
                path = skia.Path()
                path.moveTo(bx, by - ps)
                path.lineTo(bx - ps * 0.85, by + ps * 0.3)
                path.lineTo(bx, by + ps * 0.3)
                path.close()
                canvas.drawPath(path, skia_paint(r_col * 0.55, g_col * 0.55, b_col * 0.55, alpha * 0.85))

                # 눈
                snow_alpha = 0.60 + _rng.random() * 0.20
                path = skia.Path()
                path.moveTo(bx, by - ps)
                path.lineTo(bx - ps * 0.22, by - ps * 0.52)
                path.lineTo(bx + ps * 0.22, by - ps * 0.52)
                path.close()
                canvas.drawPath(path, skia_paint(0.95, 0.95, 0.97, snow_alpha * (1 - depth * 0.3)))

    elif terrain_type == "sea":
        if icons_only:
            return
        _fill_organic_blob(0.22, 0.48, 0.62, 0.80)

        if len(pixels) > 1:
            for px_c, py_c in pixels:
                dx_edge = min(abs(px_c - min_px), abs(px_c - max_px))
                dy_edge = min(abs(py_c - min_py), abs(py_c - max_py))
                edge_dist = min(dx_edge, dy_edge)
                max_dist = min(area_w, area_h) * 0.5
                depth_ratio = min(1.0, edge_dist / max(1, max_dist))
                r = 0.22 - depth_ratio * 0.12
                g = 0.48 - depth_ratio * 0.18
                b = 0.62 - depth_ratio * 0.05
                canvas.drawCircle(px_c, py_c, tw * 0.55, skia_paint(r, g, b, 0.45))

        # 파도 라인
        wave_count = max(20, int(area_h / 3))
        for wi in range(wave_count):
            wy = min_py + wi * (area_h / wave_count)
            phase1 = _rng.random() * 20
            phase2 = _rng.random() * 40
            phase3 = _rng.random() * 10
            amp1 = 3 + _rng.random() * 3
            amp2 = 1.5 + _rng.random() * 2
            amp3 = 0.5 + _rng.random() * 1
            alpha = 0.15 + _rng.random() * 0.15
            wave_path = skia.Path()
            wave_path.moveTo(min_px, wy)
            for wx in range(int(min_px), int(max_px), 8):
                dy = (math.sin((wx + phase1) * 0.12) * amp1
                      + math.sin((wx + phase2) * 0.25) * amp2
                      + math.sin((wx + phase3) * 0.06) * amp3)
                wave_path.lineTo(wx, wy + dy)
            p = skia_paint(0.35, 0.55, 0.78, alpha,
                            style=skia.Paint.kStroke_Style,
                            stroke_width=1.0 + _rng.random() * 1.2)
            canvas.drawPath(wave_path, p)

        # 파도 하이라이트
        for wi in range(0, wave_count, 3):
            wy = min_py + wi * (area_h / wave_count) + 2
            phase = _rng.random() * 15
            wave_path = skia.Path()
            wave_path.moveTo(min_px, wy)
            for wx in range(int(min_px), int(max_px), 10):
                dy = math.sin((wx + phase) * 0.10) * 4
                wave_path.lineTo(wx, wy + dy)
            p = skia_paint(0.50, 0.65, 0.85, 0.10 + _rng.random() * 0.08,
                            style=skia.Paint.kStroke_Style, stroke_width=0.6)
            canvas.drawPath(wave_path, p)

    elif terrain_type == "plains":
        if not icons_only:
            _fill_terrain_hull(0.55, 0.62, 0.30, 0.65)
            for i, (px_c, py_c) in enumerate(pixels):
                ratio = i / max(1, len(pixels) - 1)
                r = 0.50 + ratio * 0.18
                g = 0.58 + ratio * 0.08
                b = 0.22 + ratio * 0.08
                p = skia.Paint()
                p.setAntiAlias(True)
                p.setShader(skia.GradientShader.MakeRadial(
                    center=(px_c, py_c), radius=tw * 0.8,
                    colors=[skia_rgba(r, g, b, 0.28),
                            skia_rgba(r, g, b, 0.15),
                            skia_rgba(r, g, b, 0)],
                    positions=[0, 0.6, 1.0],
                ))
                canvas.drawCircle(px_c, py_c, tw * 0.8, p)

        if fill_only:
            return
        grass_count = max(80, int(area_w * area_h / 80))
        for _ in range(grass_count):
            gx = min_px + _rng.random() * area_w
            gy = min_py + _rng.random() * area_h
            if not _in_region(gx, gy):
                continue
            num_blades = 2 + int(_rng.random() * 2)
            for _b in range(num_blades):
                blade_len = 2 + _rng.random() * 4
                angle = math.pi * (-0.8 + _rng.random() * 0.6)
                g_green = 0.42 + _rng.random() * 0.20
                g_red = 0.35 + _rng.random() * 0.20
                p = skia_paint(g_red, g_green, 0.15, 0.35 + _rng.random() * 0.20,
                                style=skia.Paint.kStroke_Style,
                                stroke_width=0.6 + _rng.random() * 0.6)
                bx = gx + _rng.uniform(-1.5, 1.5)
                by = gy + _rng.uniform(-0.5, 0.5)
                canvas.drawLine(bx, by,
                                bx + math.cos(angle) * blade_len,
                                by + math.sin(angle) * blade_len, p)

    elif terrain_type == "swamp":
        if not icons_only:
            _fill_terrain_hull(0.48, 0.43, 0.28, 0.70)
            for px_c, py_c in pixels:
                p = skia.Paint()
                p.setAntiAlias(True)
                p.setShader(skia.GradientShader.MakeRadial(
                    center=(px_c, py_c), radius=tw * 0.8,
                    colors=[skia_rgba(0.34, 0.36, 0.18, 0.25),
                            skia_rgba(0.38, 0.40, 0.22, 0.12),
                            skia_rgba(0.38, 0.40, 0.22, 0)],
                    positions=[0, 0.6, 1.0],
                ))
                canvas.drawCircle(px_c, py_c, tw * 0.8, p)

        if fill_only:
            return
        puddle_count = max(8, int(area_w * area_h / 600))
        for _ in range(puddle_count):
            px_p = min_px + _rng.random() * area_w
            py_p = min_py + _rng.random() * area_h
            if not _in_region(px_p, py_p):
                continue
            pr = 3 + _rng.random() * 8
            canvas.drawCircle(px_p, py_p, pr,
                              skia_paint(0.25, 0.32, 0.22, 0.35 + _rng.random() * 0.20))
            canvas.drawCircle(px_p - pr * 0.2, py_p - pr * 0.2, pr * 0.4,
                              skia_paint(0.35, 0.42, 0.30, 0.15))

        hatch_count = max(20, int(area_w * area_h / 200))
        for _ in range(hatch_count):
            hx = min_px + _rng.random() * area_w
            hy = min_py + _rng.random() * area_h
            if not _in_region(hx, hy):
                continue
            hlen = 4 + _rng.random() * 8
            angle = math.pi * (-0.7 + _rng.random() * 0.4)
            p = skia_paint(0.32, 0.30, 0.15, 0.18 + _rng.random() * 0.12,
                            style=skia.Paint.kStroke_Style, stroke_width=0.6)
            canvas.drawLine(hx, hy, hx + math.cos(angle) * hlen, hy + math.sin(angle) * hlen, p)

    elif terrain_type == "coastline":
        if icons_only:
            return
        _fill_terrain_hull(0.68, 0.60, 0.40, 0.60)
        for px_c, py_c in pixels:
            p = skia.Paint()
            p.setAntiAlias(True)
            p.setShader(skia.GradientShader.MakeRadial(
                center=(px_c, py_c), radius=tw * 0.5,
                colors=[skia_rgba(0.76, 0.68, 0.48, 0.15), skia_rgba(0.65, 0.55, 0.35, 0.05)],
            ))
            canvas.drawCircle(px_c, py_c, tw * 0.5, p)
        sand_count = max(30, int(area_w * area_h / 250))
        for _ in range(sand_count):
            sx = min_px + _rng.random() * area_w
            sy = min_py + _rng.random() * area_h
            if not _in_region(sx, sy):
                continue
            canvas.drawCircle(sx, sy, 0.5 + _rng.random() * 1.2,
                              skia_paint(0.60 + _rng.random() * 0.15, 0.50 + _rng.random() * 0.12,
                                          0.30 + _rng.random() * 0.10, 0.12 + _rng.random() * 0.10))


def _draw_coastline_hatching(canvas, path, to_pixel_fn, tw, _math):
    """해안선 전통 지도 스타일 빗금 (해안선 안쪽으로 짧은 빗금) [Skia]"""
    p = skia_paint(0.35, 0.28, 0.18, 0.45,
                    style=skia.Paint.kStroke_Style, stroke_width=0.5)
    for i in range(len(path) - 1):
        x1, y1 = to_pixel_fn(path[i][0], path[i][1])
        x2, y2 = to_pixel_fn(path[i+1][0], path[i+1][1])
        dx = x2 - x1
        dy = y2 - y1
        length = _math.sqrt(dx*dx + dy*dy)
        if length < 1:
            continue
        nx = -dy / length
        ny = dx / length
        num_hatches = max(1, int(length / 5))
        for j in range(num_hatches):
            t = j / max(1, num_hatches - 1)
            hx = x1 + dx * t
            hy = y1 + dy * t
            canvas.drawLine(hx, hy, hx + nx * tw * 0.12, hy + ny * tw * 0.12, p)


def generate_world_map():
    """worldbuilding.json 기반 판타지 스타일 세계 지도 생성.
    Skia로 고퀄리티 판타지 백지도를 생성. SD img2img는 선택적."""
    import random as _rng

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wb_path = os.path.join(BASE_DIR, "data", "worldbuilding.json")
    if not os.path.exists(wb_path):
        return None

    with open(wb_path, "r", encoding="utf-8") as f:
        wb = json.load(f)

    locations = wb.get("locations", {})
    terrain = wb.get("terrain", {})
    if not locations:
        return None

    # world_pos가 있는 지역만
    placed = {}
    for loc_id, loc_data in locations.items():
        wp = loc_data.get("world_pos")
        if wp:
            placed[loc_id] = {
                "name": loc_data.get("name", loc_id),
                "type": loc_data.get("type", ""),
                "x": wp[0], "y": wp[1],
                "connections": loc_data.get("connections", {}),
            }
    if not placed:
        return None

    # 좌표 범위 (지형 포함)
    all_xs, all_ys = [], []
    for v in placed.values():
        all_xs.append(v["x"]); all_ys.append(v["y"])
    for feat in terrain.get("features", []):
        for c in feat.get("coords", []) + feat.get("path", []):
            all_xs.append(c[0]); all_ys.append(c[1])

    # 좌표 범위에 비례하는 패딩 (10x 확장 좌표 대응)
    raw_range = max(max(all_xs) - min(all_xs), max(all_ys) - min(all_ys), 1)
    padding = max(2, round(raw_range * 0.15))
    min_x, max_x = min(all_xs) - padding, max(all_xs) + padding
    min_y, max_y = min(all_ys) - padding, max(all_ys) + padding

    W, H = 1024, 1024
    cols = max_x - min_x + 1
    rows = max_y - min_y + 1
    tw = W / cols
    th = H / rows

    def to_pixel(wx, wy):
        return (wx - min_x + 0.5) * tw, (wy - min_y + 0.5) * th

    _rng.seed(42)

    # 세계관 ID 기반 캐시 파일명 (Skia/SD 분리)
    world_name = wb.get("world_info", {}).get("name", "default")
    safe_world_name = world_name.replace(" ", "_")
    world_map_dir = os.path.join(BASE_DIR, "static", "maps", "world", safe_world_name)
    os.makedirs(world_map_dir, exist_ok=True)
    skia_bg_cache_path = os.path.join(world_map_dir, "background_skia.webp")
    sd_cache_path = os.path.join(world_map_dir, "background_sd.webp")

    # SD 설정 확인
    try:
        _session_path = os.path.join(BASE_DIR, "data", "current_session.json")
        with open(_session_path, "r", encoding="utf-8") as f:
            _session = json.load(f)
        _sd_enabled = _session.get("sd_illustration", True)
    except Exception:
        _sd_enabled = False

    # 배경 우선순위: custom > SD 캐시(SD ON일 때만) > Skia 캐시 > 새로 생성
    custom_bg_dir = os.path.join(world_map_dir, "custom")
    custom_bg_path = None
    if os.path.isdir(custom_bg_dir):
        for ext in ["webp", "png", "jpg", "jpeg"]:
            _p = os.path.join(custom_bg_dir, f"background.{ext}")
            if os.path.exists(_p):
                custom_bg_path = _p
                break

    cached_bg = None
    _has_sd_bg = False
    _has_custom_bg = False
    if custom_bg_path:
        cached_bg = Image.open(custom_bg_path).convert("RGB").resize((W, H), Image.LANCZOS).convert("RGBA")
        _has_custom_bg = True
        _has_sd_bg = True  # custom도 SD와 같은 취급 (Skia 렌더링 스킵)
    elif _sd_enabled and os.path.exists(sd_cache_path):
        # RGB로 로드 후 불투명 RGBA로 변환 (알파 255) — 반투명 방지
        _sd_img = Image.open(sd_cache_path).convert("RGB").resize((W, H), Image.LANCZOS)
        cached_bg = _sd_img.convert("RGBA")  # RGB→RGBA: 알파가 자동으로 255(불투명)
        _has_sd_bg = True
    elif os.path.exists(skia_bg_cache_path):
        cached_bg = Image.open(skia_bg_cache_path).convert("RGBA").resize((W, H), Image.LANCZOS)

    # ─── 1단계: Skia 판타지 스타일 배경 ───
    final_surface = skia.Surface(W, H)
    canvas = final_surface.getCanvas()

    # 양피지 배경
    _draw_parchment_bg(canvas, W, H, _rng)
    _rng.seed(42)  # 시드 재설정 (일관성)

    # ─── 2단계: 지형 패턴 렌더링 ───

    # ── 2단계-A: 해안선 폴리곤으로 바다 영역 채우기 ──
    # SD 배경이 있으면 SD가 바다를 포함하므로 Skia 바다 채우기 스킵
    _all_sea_pixels = []
    _has_coastline_path = False
    if not _has_sd_bg:
        # sea 타입 좌표 수집 (바다 방향 판단용)
        for _sf in terrain.get("features", []):
            if _sf.get("type") == "sea" and "coords" in _sf:
                for _sc in _sf["coords"]:
                    _all_sea_pixels.append(to_pixel(_sc[0], _sc[1]))

        for feat in terrain.get("features", []):
            if feat.get("type") == "coastline" and "path" in feat and len(feat["path"]) >= 2:
                _has_coastline_path = True
                coast_pts = feat["path"]
                coast_pixels = [to_pixel(c[0], c[1]) for c in coast_pts]

                first_px, first_py = coast_pixels[0]
                last_px, last_py = coast_pixels[-1]

                # 바다 폴리곤 구성
                sea_path = skia.Path()
                sea_path.moveTo(first_px, first_py)
                for i in range(1, len(coast_pixels)):
                    px, py = coast_pixels[i]
                    prev_x, prev_y = coast_pixels[i-1]
                    cpx = (prev_x + px) / 2 + (py - prev_y) * 0.1
                    cpy = (prev_y + py) / 2 - (px - prev_x) * 0.1
                    sea_path.quadTo(cpx, cpy, px, py)

                # sea coords 평균 vs 해안선 평균으로 바다 방향 판단
                coast_avg_x = sum(p[0] for p in coast_pixels) / len(coast_pixels)

                if _all_sea_pixels:
                    sea_avg_x = sum(p[0] for p in _all_sea_pixels) / len(_all_sea_pixels)
                else:
                    sea_avg_x = W  # 기본: 오른쪽에 바다

                sea_is_right = sea_avg_x > coast_avg_x

                if sea_is_right:
                    # 해안선 끝 → 우측 하단 → 우측 상단 → 해안선 시작
                    sea_path.lineTo(W + 10, last_py)
                    sea_path.lineTo(W + 10, H + 10)
                    sea_path.lineTo(W + 10, -10)
                    sea_path.lineTo(first_px, -10)
                else:
                    # 해안선 끝 → 좌측 하단 → 좌측 상단 → 해안선 시작
                    sea_path.lineTo(-10, last_py)
                    sea_path.lineTo(-10, H + 10)
                    sea_path.lineTo(-10, -10)
                    sea_path.lineTo(first_px, -10)
                sea_path.close()

                # 바다 영역을 진한 남색으로 채우기
                canvas.drawPath(sea_path, skia_paint(0.10, 0.30, 0.57, 0.85))

                # 해안 근처 밝은 청록 그라디언트 오버레이 (clip)
                canvas.save()
                canvas.clipPath(sea_path)
                for i in range(len(coast_pixels)):
                    cpx_c, cpy_c = coast_pixels[i]
                    p = skia.Paint()
                    p.setAntiAlias(True)
                    p.setShader(skia.GradientShader.MakeRadial(
                        center=(cpx_c, cpy_c), radius=tw * 3.0,
                        colors=[skia_rgba(0.28, 0.58, 0.72, 0.55),
                                skia_rgba(0.18, 0.42, 0.62, 0.25),
                                skia_rgba(0, 0, 0, 0)],
                        positions=[0, 0.4, 1.0],
                    ))
                    canvas.drawRect(skia.Rect(cpx_c - tw * 3, cpy_c - tw * 3,
                                               cpx_c + tw * 3, cpy_c + tw * 3), p)

                # 파도 텍스처 (바다 영역 내, clip 안에서)
                # 바다 방향에 따라 파도 영역 범위 결정
                _coast_min_x = min(p[0] for p in coast_pixels)
                _coast_max_x = max(p[0] for p in coast_pixels)
                _coast_min_y = min(p[1] for p in coast_pixels)
                _coast_max_y = max(p[1] for p in coast_pixels)
                if not sea_is_right:
                    sea_min_x = -10
                    sea_max_x = _coast_max_x
                else:
                    sea_min_x = _coast_min_x
                    sea_max_x = W + 10
                sea_min_y = min(-10, _coast_min_y - tw)
                sea_max_y = max(H + 10, _coast_max_y + tw)
                sea_area_h = sea_max_y - sea_min_y
                wave_count = max(20, int(sea_area_h / 3))
                for wi in range(wave_count):
                    wy = sea_min_y + wi * (sea_area_h / wave_count)
                    phase1 = _rng.random() * 20
                    phase2 = _rng.random() * 40
                    phase3 = _rng.random() * 10
                    amp1 = 3 + _rng.random() * 3
                    amp2 = 1.5 + _rng.random() * 2
                    amp3 = 0.5 + _rng.random() * 1
                    alpha = 0.15 + _rng.random() * 0.15
                    wave_path = skia.Path()
                    wave_path.moveTo(sea_min_x, wy)
                    for wx in range(int(sea_min_x), int(sea_max_x), 8):
                        dy = (math.sin((wx + phase1) * 0.12) * amp1
                              + math.sin((wx + phase2) * 0.25) * amp2
                              + math.sin((wx + phase3) * 0.06) * amp3)
                        wave_path.lineTo(wx, wy + dy)
                    p = skia_paint(0.35, 0.55, 0.78, alpha,
                                    style=skia.Paint.kStroke_Style,
                                    stroke_width=1.0 + _rng.random() * 1.2)
                    canvas.drawPath(wave_path, p)
                # 파도 하이라이트
                for wi in range(0, wave_count, 3):
                    wy = sea_min_y + wi * (sea_area_h / wave_count) + 2
                    phase = _rng.random() * 15
                    wave_path = skia.Path()
                    wave_path.moveTo(sea_min_x, wy)
                    for wx in range(int(sea_min_x), int(sea_max_x), 10):
                        dy = math.sin((wx + phase) * 0.10) * 4
                        wave_path.lineTo(wx, wy + dy)
                    p = skia_paint(0.50, 0.65, 0.85, 0.10 + _rng.random() * 0.08,
                                    style=skia.Paint.kStroke_Style, stroke_width=0.6)
                    canvas.drawPath(wave_path, p)

                canvas.restore()

    # ── 2단계-B: 대륙 지형색 채우기 (blob, 아이콘 제외) ──
    # SD 배경이 있으면 Skia 지형 렌더링 전체 스킵 (SD가 배경을 완전히 대체)
    if _has_sd_bg:
        # SD 배경을 양피지 위에 바로 올리고 마커 단계로 점프
        canvas.drawImage(pil_to_skia_image(cached_bg), 0, 0)
        # 마커 단계(3단계)로 바로 이동하기 위해 아래 지형 렌더링 건너뛰기
        _skip_terrain_rendering = True
    else:
        _skip_terrain_rendering = False

    if not _skip_terrain_rendering:
        render_order = ["plains", "coastline", "swamp", "forest", "mountain"]
        if not _has_coastline_path:
            render_order = ["sea"] + render_order
        for target_type in render_order:
            for feat in terrain.get("features", []):
                ftype = feat.get("type", "")
                if ftype != target_type:
                    continue
                if "coords" in feat:
                    _draw_terrain_pattern(canvas, feat["coords"], ftype, to_pixel, tw, th, _rng,
                                          fill_only=True)

        # 지형 경계 부드럽게 — 가우시안 블러 (Skia 네이티브)
        image_snap = final_surface.makeImageSnapshot()
        blur_surface = skia.Surface(W, H)
        blur_canvas = blur_surface.getCanvas()
        blur_paint = skia.Paint()
        blur_paint.setImageFilter(skia.ImageFilters.Blur(1.2, 1.2))
        blur_canvas.drawImage(image_snap, 0, 0, skia.SamplingOptions(), blur_paint)
        # 블러 결과를 새 surface로 교체
        final_surface = skia.Surface(W, H)
        canvas = final_surface.getCanvas()
        canvas.drawImage(blur_surface.makeImageSnapshot(), 0, 0)

        # ── 2단계-C: 지형 아이콘 그리기 (블러 후 선명하게) ──
        icon_types = ["forest", "mountain", "plains", "swamp"]
        for target_type in icon_types:
            for feat in terrain.get("features", []):
                ftype = feat.get("type", "")
                if ftype != target_type:
                    continue
                if "coords" in feat:
                    _draw_terrain_pattern(canvas, feat["coords"], ftype, to_pixel, tw, th, _rng,
                                          icons_only=True)

        # 해안선 곡선 + 빗금 (블러 후 선명하게)
        for feat in terrain.get("features", []):
            if feat.get("type") == "coastline" and "path" in feat:
                pts = feat["path"]
                if len(pts) >= 2:
                    # 굵은 해안선
                    coast_path = skia.Path()
                    x0, y0 = to_pixel(pts[0][0], pts[0][1])
                    coast_path.moveTo(x0, y0)
                    for i in range(1, len(pts)):
                        px, py = to_pixel(pts[i][0], pts[i][1])
                        prev_x, prev_y = to_pixel(pts[i-1][0], pts[i-1][1])
                        cpx = (prev_x + px) / 2 + (py - prev_y) * 0.1
                        cpy = (prev_y + py) / 2 - (px - prev_x) * 0.1
                        coast_path.quadTo(cpx, cpy, px, py)
                    p = skia_paint(0.40, 0.32, 0.20, 0.7,
                                    style=skia.Paint.kStroke_Style, stroke_width=tw * 0.25)
                    p.setStrokeCap(skia.Paint.kRound_Cap)
                    canvas.drawPath(coast_path, p)
                    # 빗금
                    _draw_coastline_hatching(canvas, pts, to_pixel, tw, math)

        # 강: 파란 곡선, 하류로 갈수록 굵어짐
        for feat in terrain.get("features", []):
            if feat.get("type") == "river" and "path" in feat:
                path_pts = [to_pixel(c[0], c[1]) for c in feat["path"]]
                if len(path_pts) >= 2:
                    base_width = max(2, tw * 0.08)
                    max_width = max(5, tw * 0.22)
                    for i in range(1, len(path_pts)):
                        progress = i / max(1, len(path_pts) - 1)
                        line_w = base_width + (max_width - base_width) * progress
                        prev = path_pts[i-1]; curr = path_pts[i]
                        dx = curr[0]-prev[0]; dy = curr[1]-prev[1]
                        cpx = (prev[0]+curr[0])/2 - dy*0.2 + _rng.uniform(-6,6)
                        cpy = (prev[1]+curr[1])/2 + dx*0.2 + _rng.uniform(-3,3)
                        # 어두운 외곽
                        rp = skia.Path()
                        rp.moveTo(*prev); rp.quadTo(cpx, cpy, *curr)
                        p = skia_paint(0.12, 0.25, 0.50, 0.6,
                                        style=skia.Paint.kStroke_Style, stroke_width=line_w + 1.5)
                        p.setStrokeCap(skia.Paint.kRound_Cap)
                        canvas.drawPath(rp, p)
                        # 메인 강
                        rp2 = skia.Path()
                        rp2.moveTo(*prev); rp2.quadTo(cpx, cpy, *curr)
                        p2 = skia_paint(0.20, 0.40, 0.65, 0.8,
                                         style=skia.Paint.kStroke_Style, stroke_width=line_w)
                        p2.setStrokeCap(skia.Paint.kRound_Cap)
                        canvas.drawPath(rp2, p2)
                        # 하이라이트
                        rp3 = skia.Path()
                        rp3.moveTo(prev[0]+1, prev[1]-1); rp3.quadTo(cpx+1, cpy-1, curr[0]+1, curr[1]-1)
                        p3 = skia_paint(0.35, 0.55, 0.80, 0.3,
                                         style=skia.Paint.kStroke_Style, stroke_width=max(1, line_w * 0.4))
                        p3.setStrokeCap(skia.Paint.kRound_Cap)
                        canvas.drawPath(rp3, p3)

        # Skia 배경을 webp로 캐시 저장
        try:
            _cache_tmp = os.path.join(world_map_dir, "world_map_temp_cache.tmp.png")
            final_surface.makeImageSnapshot().save(_cache_tmp, skia.kPNG)
            _cache_img = Image.open(_cache_tmp).convert("RGBA")
            _cache_img.save(skia_bg_cache_path, "WEBP", quality=90)
            try:
                os.remove(_cache_tmp)
            except Exception:
                pass
        except Exception:
            pass

    # ─── SD 새 생성 (캐시 없고 SD ON일 때) ───
    # _has_sd_bg=True → 이미 895행에서 SD 캐시를 그렸으므로 패스
    # _has_sd_bg=False, _sd_enabled=True → SD 새 생성 시도
    # _has_sd_bg=False, _sd_enabled=False → 패스
    if not _has_sd_bg and _sd_enabled:
        try:
            from core.sd_generator import is_sd_enabled
            if is_sd_enabled():
                import requests
                import base64
                import io
                from core.sd_generator import SD_API_URL

                _sd_input = Image.open(skia_bg_cache_path).convert("RGB")
                buffered = io.BytesIO()
                _sd_input.save(buffered, format="PNG")
                img_b64 = base64.b64encode(buffered.getvalue()).decode()

                prompt = (
                    "fantasy map, <lora:AZovyaRPGArtistToolsLORAV2art:0.6>, "
                    "medieval cartography style, parchment texture, hand painted, "
                    "watercolor terrain, top down birds eye view, aged paper"
                )
                negative_prompt = (
                    "animals, birds, people, characters, faces, 3d render, "
                    "realistic photo, modern, text, labels, blurry, low quality, close up"
                )

                payload = {
                    "init_images": [img_b64],
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "steps": 25,
                    "sampler_name": "DPM++ 2M Karras",
                    "width": 768,
                    "height": 768,
                    "cfg_scale": 8,
                    "denoising_strength": 0.45,
                }

                resp = requests.post(f"{SD_API_URL}/sdapi/v1/img2img", json=payload, timeout=300)
                resp.raise_for_status()

                result = resp.json()
                if result.get("images"):
                    img_data = base64.b64decode(result["images"][0])
                    sd_bg = Image.open(io.BytesIO(img_data)).convert("RGBA").resize((W, H), Image.LANCZOS)
                    sd_bg.save(sd_cache_path, "WEBP", quality=90)
                    canvas.drawImage(pil_to_skia_image(sd_bg), 0, 0)
        except Exception:
            pass

    # ─── 3단계: 공통 오버레이 (도로/마커/라벨) ───

    # 폰트 준비
    typeface = skia.Typeface('Malgun Gothic')
    typeface_bold = skia.Typeface.MakeFromName('Malgun Gothic', skia.FontStyle.Bold())
    font_14 = skia.Font(typeface_bold, 14)
    font_14_italic = skia.Font(typeface, 14)
    font_13_italic = skia.Font(typeface, 13)
    font_22 = skia.Font(typeface_bold, 22)
    font_12 = skia.Font(typeface, 12)
    font_11 = skia.Font(typeface_bold, 11)

    # 지형 이름 (river 포함)
    name_colors = {
        "forest": (0.15, 0.30, 0.10), "mountain": (0.35, 0.25, 0.15),
        "sea": (0.10, 0.20, 0.50), "plains": (0.40, 0.42, 0.25),
        "swamp": (0.25, 0.32, 0.18), "river": (0.10, 0.22, 0.48),
    }
    for feat in terrain.get("features", []):
        feat_name = feat.get("name", "")
        if not feat_name:
            continue
        feat_type = feat.get("type", "")

        if feat_type == "river" and "path" in feat and len(feat["path"]) >= 2:
            path_pts = [to_pixel(c[0], c[1]) for c in feat["path"]]
            mid = path_pts[len(path_pts) // 2]
            tx, ty = mid
            nc = name_colors.get(feat_type, (0.4, 0.4, 0.4))
            text_w = font_13_italic.measureText(feat_name)
            canvas.drawRect(skia.Rect(tx - text_w/2 - 4, ty - 8, tx + text_w/2 + 4, ty + 10),
                            skia_paint(0.82, 0.75, 0.60, 0.7))
            canvas.drawString(feat_name, tx - text_w/2, ty + 5, font_13_italic,
                              skia_paint(*nc, 0.9))
        elif feat.get("coords"):
            avg_x = sum(c[0] for c in feat["coords"]) / len(feat["coords"])
            avg_y = sum(c[1] for c in feat["coords"]) / len(feat["coords"])
            tx, ty = to_pixel(avg_x, avg_y)
            nc = name_colors.get(feat_type, (0.4, 0.4, 0.4))
            text_w = font_14_italic.measureText(feat_name)
            canvas.drawRect(skia.Rect(tx - text_w/2 - 4, ty - 8, tx + text_w/2 + 4, ty + 10),
                            skia_paint(0.82, 0.75, 0.60, 0.7))
            canvas.drawString(feat_name, tx - text_w/2, ty + 5, font_14_italic,
                              skia_paint(*nc, 0.9))

    # 도로 (메인길/샛길)
    main_types = {"village", "trade_city", "port_village"}
    drawn_connections = set()
    for loc_id, loc in placed.items():
        for target_name, conn in loc["connections"].items():
            target_id = None
            for tid, tdata in placed.items():
                if tdata["name"] == target_name:
                    target_id = tid
                    break
            if not target_id:
                continue
            pair = tuple(sorted([loc_id, target_id]))
            if pair in drawn_connections:
                continue
            drawn_connections.add(pair)

            x1, y1 = to_pixel(loc["x"], loc["y"])
            x2, y2 = to_pixel(placed[target_id]["x"], placed[target_id]["y"])
            is_main = (loc["type"] in main_types and placed[target_id]["type"] in main_types) or \
                      loc["type"] == "trade_city" or placed[target_id]["type"] == "trade_city"

            mid_x = (x1+x2)/2; mid_y = (y1+y2)/2
            dx = x2-x1; dy = y2-y1
            offset = _rng.uniform(-10, 10)
            cpx = mid_x - dy*0.08 + offset
            cpy = mid_y + dx*0.08

            road_path = skia.Path()
            road_path.moveTo(x1, y1)
            road_path.quadTo(cpx, cpy, x2, y2)

            if is_main:
                p1 = skia_paint(0.22, 0.16, 0.08, 0.5,
                                 style=skia.Paint.kStroke_Style, stroke_width=6)
                p1.setStrokeCap(skia.Paint.kRound_Cap)
                canvas.drawPath(road_path, p1)
                p2 = skia_paint(0.55, 0.45, 0.30, 0.85,
                                 style=skia.Paint.kStroke_Style, stroke_width=3.5)
                p2.setStrokeCap(skia.Paint.kRound_Cap)
                canvas.drawPath(road_path, p2)
            else:
                p = skia_paint(0.55, 0.48, 0.35, 0.7,
                                style=skia.Paint.kStroke_Style, stroke_width=2.5)
                p.setStrokeCap(skia.Paint.kRound_Cap)
                p.setPathEffect(skia.DashPathEffect.Make([8, 5], 0))
                canvas.drawPath(road_path, p)

    # 지역 마커 + 라벨
    label_rects = []
    def find_label_pos(cx, cy, tw_l, th_l):
        offsets = [(cx-tw_l/2, cy+26), (cx-tw_l/2, cy-th_l-26),
                   (cx+28, cy-th_l/2), (cx-tw_l-28, cy-th_l/2),
                   (cx-tw_l/2, cy+42), (cx-tw_l/2, cy-th_l-42)]
        for lx, ly in offsets:
            rect = (lx-2, ly-2, lx+tw_l+4, ly+th_l+4)
            if not any(not(rect[2]<r[0] or rect[0]>r[2] or rect[3]<r[1] or rect[1]>r[3]) for r in label_rects):
                label_rects.append(rect)
                return lx, ly
        label_rects.append((offsets[0][0]-2, offsets[0][1]-2, offsets[0][0]+tw_l+4, offsets[0][1]+th_l+4))
        return offsets[0]

    type_colors = {
        "village": (0.63, 0.47, 0.24), "trade_city": (0.72, 0.55, 0.18),
        "road": (0.55, 0.47, 0.32), "dungeon": (0.47, 0.32, 0.40),
        "rest_area": (0.52, 0.56, 0.36), "port_village": (0.32, 0.47, 0.60),
    }

    for loc_id, loc in placed.items():
        cx, cy = to_pixel(loc["x"], loc["y"])
        color = type_colors.get(loc["type"], (0.6, 0.5, 0.4))
        if loc["type"] == "trade_city":
            r = 16
            canvas.drawRect(skia.Rect(cx-r, cy-r, cx+r, cy+r), skia_paint(*color))
            canvas.drawRect(skia.Rect(cx-r, cy-r, cx+r, cy+r),
                            skia_paint(0.32, 0.24, 0.12, style=skia.Paint.kStroke_Style, stroke_width=2))
            for tx_off in [-r, r-5]:
                canvas.drawRect(skia.Rect(cx+tx_off, cy-r-8, cx+tx_off+5, cy-r),
                                skia_paint(0.32, 0.24, 0.12))
        elif loc["type"] in ("village", "port_village"):
            r = 11
            canvas.drawRect(skia.Rect(cx-r, cy-3, cx+r, cy+r), skia_paint(*color))
            roof = skia.Path()
            roof.moveTo(cx-r-2, cy-3); roof.lineTo(cx, cy-r-5); roof.lineTo(cx+r+2, cy-3)
            roof.close()
            canvas.drawPath(roof, skia_paint(0.63, 0.40, 0.20))
            canvas.drawRect(skia.Rect(cx-r, cy-3, cx+r, cy+r),
                            skia_paint(0.32, 0.24, 0.12, style=skia.Paint.kStroke_Style, stroke_width=1.5))
        elif loc["type"] == "dungeon":
            r = 13
            canvas.drawCircle(cx, cy, r, skia_paint(0.24, 0.20, 0.24, 0.9))
            canvas.drawCircle(cx, cy, r, skia_paint(0.40, 0.32, 0.32,
                                                       style=skia.Paint.kStroke_Style, stroke_width=2))
        elif loc["type"] == "rest_area":
            r = 9
            tri = skia.Path()
            tri.moveTo(cx, cy-r-4); tri.lineTo(cx-r-4, cy+r); tri.lineTo(cx+r+4, cy+r)
            tri.close()
            canvas.drawPath(tri, skia_paint(*color))
            canvas.drawPath(tri, skia_paint(0.32, 0.24, 0.12,
                                              style=skia.Paint.kStroke_Style, stroke_width=1.5))
        else:
            r = 11
            canvas.drawCircle(cx, cy, r, skia_paint(*color))
            canvas.drawCircle(cx, cy, r, skia_paint(0.32, 0.24, 0.12,
                                                       style=skia.Paint.kStroke_Style, stroke_width=1.5))

        # 라벨
        name = loc["name"]
        text_w = font_14.measureText(name)
        tw_l = text_w + 8
        th_l = 18
        lx, ly = find_label_pos(cx, cy, tw_l, th_l)
        canvas.drawRect(skia.Rect(lx, ly, lx+tw_l, ly+th_l),
                        skia_paint(0.92, 0.88, 0.78, 0.85))
        canvas.drawRect(skia.Rect(lx, ly, lx+tw_l, ly+th_l),
                        skia_paint(0.45, 0.38, 0.25, 0.7, style=skia.Paint.kStroke_Style, stroke_width=1))
        canvas.drawString(name, lx+4, ly+14, font_14, skia_paint(0.18, 0.10, 0.04))

    # 현재 위치
    try:
        gs_path = os.path.join(BASE_DIR, "data", "game_state.json")
        if os.path.exists(gs_path):
            with open(gs_path, "r", encoding="utf-8") as f:
                gs = json.load(f)
            cur_loc = gs.get("current_location", "")
            if cur_loc in placed:
                px, py = to_pixel(placed[cur_loc]["x"], placed[cur_loc]["y"])
                # 깃대
                p = skia_paint(0.72, 0.15, 0.15, style=skia.Paint.kStroke_Style, stroke_width=2.5)
                canvas.drawLine(px+18, py-2, px+18, py-26, p)
                # 깃발
                flag = skia.Path()
                flag.moveTo(px+18, py-26); flag.lineTo(px+32, py-20); flag.lineTo(px+18, py-14)
                flag.close()
                canvas.drawPath(flag, skia_paint(0.82, 0.20, 0.20, 0.9))
                # 텍스트
                font_12_bold = skia.Font(typeface_bold, 12)
                canvas.drawString("현재 위치", px+34, py-16, font_12_bold,
                                  skia_paint(0.72, 0.15, 0.15))
    except Exception:
        pass

    # ── 장식 테두리: 4중선 + 코너 장식 ──
    bc = (0.35, 0.28, 0.18)
    for width, margin in [(5, 3), (1.5, 10), (2.5, 14), (0.8, 19)]:
        canvas.drawRect(skia.Rect(margin, margin, W - margin, H - margin),
                        skia_paint(*bc, style=skia.Paint.kStroke_Style, stroke_width=width))

    # 코너 장식
    corner_len = 40
    corner_positions = [
        (22, 22, 1, 1), (W - 22, 22, -1, 1),
        (22, H - 22, 1, -1), (W - 22, H - 22, -1, -1),
    ]
    for cx_c, cy_c, dx_dir, dy_dir in corner_positions:
        cp = skia.Path()
        cp.moveTo(cx_c + dx_dir * corner_len, cy_c)
        cp.lineTo(cx_c, cy_c)
        cp.lineTo(cx_c, cy_c + dy_dir * corner_len)
        canvas.drawPath(cp, skia_paint(*bc, style=skia.Paint.kStroke_Style, stroke_width=3))
        canvas.drawCircle(cx_c + dx_dir * corner_len, cy_c, 2.5, skia_paint(*bc))
        canvas.drawCircle(cx_c, cy_c + dy_dir * corner_len, 2.5, skia_paint(*bc))
        canvas.drawCircle(cx_c, cy_c, 3.5, skia_paint(*bc))

    # 변 중앙 마름모
    mid_deco_size = 4
    for mx, my in [(W / 2, 8), (W / 2, H - 8), (8, H / 2), (W - 8, H / 2)]:
        dp = skia.Path()
        dp.moveTo(mx, my - mid_deco_size)
        dp.lineTo(mx + mid_deco_size, my)
        dp.lineTo(mx, my + mid_deco_size)
        dp.lineTo(mx - mid_deco_size, my)
        dp.close()
        canvas.drawPath(dp, skia_paint(*bc))

    # ── 제목 카르투슈: 장식 프레임 ──
    world_name = wb.get("world_info", {}).get("name", "세계 지도")
    title_text = f"{world_name} 세계 지도"
    text_w = font_22.measureText(title_text)
    cart_w = text_w + 50
    cart_h = 42
    cart_x = 24
    cart_y = 18
    cart_r = 10

    # 둥근 직사각형
    rrect = skia.RRect.MakeRectXY(skia.Rect(cart_x, cart_y, cart_x + cart_w, cart_y + cart_h), cart_r, cart_r)
    canvas.drawRRect(rrect, skia_paint(0.90, 0.84, 0.72, 0.92))
    canvas.drawRRect(rrect, skia_paint(0.35, 0.28, 0.18,
                                          style=skia.Paint.kStroke_Style, stroke_width=2.0))

    # 이중 테두리
    inner_margin = 3
    rrect2 = skia.RRect.MakeRectXY(
        skia.Rect(cart_x + inner_margin, cart_y + inner_margin,
                  cart_x + cart_w - inner_margin, cart_y + cart_h - inner_margin),
        cart_r - 2, cart_r - 2)
    canvas.drawRRect(rrect2, skia_paint(0.45, 0.35, 0.22, 0.5,
                                           style=skia.Paint.kStroke_Style, stroke_width=0.8))

    # 스크롤 장식
    for scroll_x, scroll_dir in [(cart_x - 2, 1), (cart_x + cart_w + 2, -1)]:
        scroll_cy = cart_y + cart_h / 2
        sp = skia.Path()
        for t_step in range(20):
            t = t_step / 19.0
            angle = t * 1.5 * math.pi
            r_spiral = 3 + t * 5
            sx = scroll_x + scroll_dir * r_spiral * math.cos(angle)
            sy = scroll_cy + r_spiral * math.sin(angle)
            if t_step == 0:
                sp.moveTo(sx, sy)
            else:
                sp.lineTo(sx, sy)
        canvas.drawPath(sp, skia_paint(0.40, 0.32, 0.20, 0.6,
                                          style=skia.Paint.kStroke_Style, stroke_width=1.5))

    # 제목 텍스트
    canvas.drawString(title_text, cart_x + 25, cart_y + cart_h - 12, font_22,
                      skia_paint(0.18, 0.10, 0.04))

    # ── 나침반: 8방향 별 모양 + 외곽 원 + 방위 텍스트 ──
    ncx, ncy = W - 55, H - 55
    nr = 30

    canvas.drawCircle(ncx, ncy, nr + 4, skia_paint(0.90, 0.84, 0.72, 0.88))
    canvas.drawCircle(ncx, ncy, nr + 4, skia_paint(0.35, 0.28, 0.18,
                                                       style=skia.Paint.kStroke_Style, stroke_width=2.0))
    canvas.drawCircle(ncx, ncy, nr + 1, skia_paint(0.35, 0.28, 0.18,
                                                       style=skia.Paint.kStroke_Style, stroke_width=0.8))

    for i in range(8):
        angle = i * math.pi / 4 - math.pi / 2
        is_cardinal = (i % 2 == 0)
        tip_r = nr * (0.85 if is_cardinal else 0.55)
        half_w = math.pi / (20 if is_cardinal else 28)
        tip_x = ncx + math.cos(angle) * tip_r
        tip_y = ncy + math.sin(angle) * tip_r
        left_x = ncx + math.cos(angle - half_w) * nr * 0.18
        left_y = ncy + math.sin(angle - half_w) * nr * 0.18
        right_x = ncx + math.cos(angle + half_w) * nr * 0.18
        right_y = ncy + math.sin(angle + half_w) * nr * 0.18

        if i == 0:
            fill_r = skia_paint(0.72, 0.15, 0.15, 0.9)
            fill_l = skia_paint(0.55, 0.10, 0.10, 0.9)
        else:
            fill_r = skia_paint(0.35, 0.28, 0.18, 0.85 if is_cardinal else 0.60)
            fill_l = skia_paint(0.25, 0.18, 0.10, 0.85 if is_cardinal else 0.60)

        pr = skia.Path()
        pr.moveTo(tip_x, tip_y); pr.lineTo(ncx, ncy); pr.lineTo(right_x, right_y); pr.close()
        canvas.drawPath(pr, fill_r)

        pl = skia.Path()
        pl.moveTo(tip_x, tip_y); pl.lineTo(ncx, ncy); pl.lineTo(left_x, left_y); pl.close()
        canvas.drawPath(pl, fill_l)

    canvas.drawCircle(ncx, ncy, 3, skia_paint(0.35, 0.28, 0.18))

    # 방위 텍스트
    dir_labels = [("N", 0), ("NE", 1), ("E", 2), ("SE", 3),
                  ("S", 4), ("SW", 5), ("W", 6), ("NW", 7)]
    for label, idx in dir_labels:
        angle = idx * math.pi / 4 - math.pi / 2
        is_cardinal = (idx % 2 == 0)
        text_r = nr + (14 if is_cardinal else 12)
        tx_d = ncx + math.cos(angle) * text_r
        ty_d = ncy + math.sin(angle) * text_r

        if label == "N":
            font_s = skia.Font(typeface_bold, 13)
            paint = skia_paint(0.72, 0.15, 0.15)
        else:
            font_s = skia.Font(typeface_bold, 9 if not is_cardinal else 11)
            paint = skia_paint(0.25, 0.18, 0.10)

        tw_t = font_s.measureText(label)
        canvas.drawString(label, tx_d - tw_t / 2, ty_d + 4, font_s, paint)

    # === 월드맵 범례 ===
    legend_h = 30
    legend_surface = skia.Surface(W, H + legend_h)
    legend_canvas = legend_surface.getCanvas()
    legend_canvas.drawImage(final_surface.makeImageSnapshot(), 0, 0)

    # 범례 배경
    legend_canvas.drawRect(skia.Rect(0, H, W, H + legend_h), skia_paint(0, 0, 0, 0.8))

    legend_text_items = [
        ("#2d5a1e", "숲"), ("#8B7355", "산맥"), ("#2a6fa0", "바다"),
        ("#6a9a30", "평원"), ("#d2b48c", "해안"), ("#e63946", "현재 위치"),
        ("#c8a82a", "마을/도시"),
    ]

    lx = 10
    for color_hex, label in legend_text_items:
        r = int(color_hex[1:3], 16) / 255
        g = int(color_hex[3:5], 16) / 255
        b = int(color_hex[5:7], 16) / 255
        legend_canvas.drawCircle(lx + 6, H + 15, 5, skia_paint(r, g, b))
        legend_canvas.drawString(label, lx + 15, H + 20, font_12, skia_paint(0.8, 0.8, 0.8))
        tw_t = font_12.measureText(label)
        lx += tw_t + 30

    # 저장
    output_path = os.path.join(world_map_dir, "world_map.png")
    legend_surface.makeImageSnapshot().save(output_path, skia.kPNG)
    return output_path


# ═══════════════════════════════════════════════════════════════════
# 세계 지도 4단계 파이프라인
# ═══════════════════════════════════════════════════════════════════

# 색 가이드용 지형 색상 매핑 (0~255 RGB)
GUIDE_COLORS = {
    "forest": (30, 90, 25),
    "mountain": (110, 85, 60),
    "sea": (35, 75, 145),
    "plains": (140, 150, 70),
    "swamp": (120, 105, 60),
}

# 양피지 배경색 (RGB)
_PARCHMENT_BG = (225, 210, 175)


def _load_worldbuilding():
    """worldbuilding.json 로드 헬퍼."""
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wb_path = os.path.join(BASE_DIR, "data", "worldbuilding.json")
    if not os.path.exists(wb_path):
        return None
    with open(wb_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_sd_enabled():
    """SD 일러스트 활성 여부 확인."""
    try:
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _session_path = os.path.join(BASE_DIR, "data", "current_session.json")
        with open(_session_path, "r", encoding="utf-8") as f:
            _session = json.load(f)
        if not _session.get("sd_illustration", True):
            return False
        from core.sd_generator import is_sd_enabled
        return is_sd_enabled()
    except Exception:
        return False


def generate_color_guide(wb, output_dir):
    """[파이프라인 1단계] 색 블롭 가이드 생성 (Skia + PIL 블러).

    terrain coords를 부드러운 색 필드로 변환하여 color_guide.png 저장.
    SD img2img의 입력 이미지로 사용됨.

    Args:
        wb: worldbuilding.json 딕셔너리
        output_dir: 출력 디렉토리 경로

    Returns:
        저장된 color_guide.png 경로
    """
    from PIL import ImageFilter
    import random as _rng

    terrain = wb.get("terrain", {})
    locations = wb.get("locations", {})

    # 좌표 범위 계산
    all_xs, all_ys = [], []
    for loc_data in locations.values():
        wp = loc_data.get("world_pos")
        if wp:
            all_xs.append(wp[0])
            all_ys.append(wp[1])
    for feat in terrain.get("features", []):
        for c in feat.get("coords", []) + feat.get("path", []):
            all_xs.append(c[0])
            all_ys.append(c[1])

    if not all_xs or not all_ys:
        return None

    raw_range = max(max(all_xs) - min(all_xs), max(all_ys) - min(all_ys), 1)
    padding = max(2, round(raw_range * 0.15))
    min_x, max_x = min(all_xs) - padding, max(all_xs) + padding
    min_y, max_y = min(all_ys) - padding, max(all_ys) + padding

    W, H = 1024, 1024
    cols = max_x - min_x + 1
    rows = max_y - min_y + 1
    tw = W / cols
    th = H / rows

    def to_pixel(wx, wy):
        return (wx - min_x + 0.5) * tw, (wy - min_y + 0.5) * th

    _rng.seed(42)

    # Skia surface로 색 블롭 생성
    surface = skia.Surface(W, H)
    canvas = surface.getCanvas()

    # 양피지 배경
    bg_r, bg_g, bg_b = _PARCHMENT_BG
    canvas.drawRect(skia.Rect(0, 0, W, H),
                    skia_paint(bg_r / 255, bg_g / 255, bg_b / 255))

    # 3겹 블러 레이어 설정
    blur_layers = [
        {"blur_mult": 4.0, "radius_mult": 5.0, "alpha": 120},
        {"blur_mult": 2.5, "radius_mult": 3.5, "alpha": 100},
        {"blur_mult": 1.5, "radius_mult": 2.0, "alpha": 80},
    ]

    for layer_cfg in blur_layers:
        blur_mult = layer_cfg["blur_mult"]
        radius_mult = layer_cfg["radius_mult"]
        alpha_val = layer_cfg["alpha"]

        for feat in terrain.get("features", []):
            ftype = feat.get("type", "")
            color = GUIDE_COLORS.get(ftype)
            if not color:
                continue

            coords = feat.get("coords", [])
            for coord in coords:
                px, py = to_pixel(coord[0], coord[1])
                radius = tw * radius_mult
                cr, cg, cb = color
                p = skia.Paint()
                p.setAntiAlias(True)
                p.setImageFilter(skia.ImageFilters.Blur(
                    tw * blur_mult, tw * blur_mult))
                p.setColor(skia.Color(cr, cg, cb, alpha_val))
                canvas.drawCircle(px, py, radius, p)

    # 강: 굵은 블러 선
    for feat in terrain.get("features", []):
        if feat.get("type") == "river" and "path" in feat:
            path_pts = [to_pixel(c[0], c[1]) for c in feat["path"]]
            if len(path_pts) >= 2:
                river_path = skia.Path()
                river_path.moveTo(*path_pts[0])
                for i in range(1, len(path_pts)):
                    prev = path_pts[i - 1]
                    curr = path_pts[i]
                    cpx = (prev[0] + curr[0]) / 2
                    cpy = (prev[1] + curr[1]) / 2
                    river_path.quadTo(cpx, cpy, *curr)

                sea_color = GUIDE_COLORS.get("sea", (35, 75, 145))
                p = skia.Paint()
                p.setAntiAlias(True)
                p.setStyle(skia.Paint.kStroke_Style)
                p.setStrokeWidth(tw * 1.5)
                p.setStrokeCap(skia.Paint.kRound_Cap)
                p.setImageFilter(skia.ImageFilters.Blur(tw * 2.0, tw * 2.0))
                p.setColor(skia.Color(sea_color[0], sea_color[1], sea_color[2], 100))
                canvas.drawPath(river_path, p)

    # Skia → PIL 변환 후 추가 GaussianBlur(15) 적용
    os.makedirs(output_dir, exist_ok=True)
    tmp_path = os.path.join(output_dir, "color_guide_raw.tmp.png")
    surface.makeImageSnapshot().save(tmp_path, skia.kPNG)

    pil_img = Image.open(tmp_path).convert("RGB")
    pil_img = pil_img.filter(ImageFilter.GaussianBlur(15))

    guide_path = os.path.join(output_dir, "color_guide.png")
    pil_img.save(guide_path, "PNG")

    # 임시 파일 삭제
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    return guide_path


def generate_sd_background(guide_path, output_path):
    """[파이프라인 2단계] SD img2img로 색 가이드를 판타지 텍스처로 변환.

    Args:
        guide_path: color_guide.png 경로
        output_path: 출력 background_sd.webp 경로

    Returns:
        성공 시 output_path, 실패/SD OFF 시 None
    """
    if not _is_sd_enabled():
        return None

    try:
        import requests
        import base64
        import io
        from core.sd_generator import SD_API_URL

        # 색 가이드 이미지 로드 + base64 인코딩
        sd_input = Image.open(guide_path).convert("RGB")
        buffered = io.BytesIO()
        sd_input.save(buffered, format="PNG")
        img_b64 = base64.b64encode(buffered.getvalue()).decode()

        prompt = (
            "fantasy map, <lora:AZovyaRPGArtistToolsLORAV2art:0.6>, "
            "medieval cartography, parchment texture, hand painted, "
            "watercolor terrain, top down view, aged paper"
        )
        negative_prompt = (
            "animals, birds, people, characters, faces, 3d render, "
            "realistic photo, modern, text, labels, blurry, low quality, "
            "close up, anime"
        )

        payload = {
            "init_images": [img_b64],
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "steps": 25,
            "sampler_name": "DPM++ 2M Karras",
            "width": 1024,
            "height": 1024,
            "cfg_scale": 8,
            "denoising_strength": 0.55,
        }

        resp = requests.post(
            f"{SD_API_URL}/sdapi/v1/img2img", json=payload, timeout=300
        )
        resp.raise_for_status()

        result = resp.json()
        if result.get("images"):
            img_data = base64.b64decode(result["images"][0])
            sd_bg = Image.open(io.BytesIO(img_data)).convert("RGB")
            sd_bg = sd_bg.resize((1024, 1024), Image.LANCZOS)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            sd_bg.save(output_path, "WEBP", quality=90)
            return output_path

        return None
    except Exception:
        return None


def generate_world_map_pipeline(force_regenerate=False):
    """세계 지도 4단계 파이프라인 오케스트레이터.

    [1] 색 블롭 가이드 생성 (Skia, 즉시)
    [2] SD img2img 변환 (백그라운드, 30초~)
    [3] Skia 정식 백지도 생성 (즉시)
    [4] 배경 + 마커 합성 → world_map.png

    Args:
        force_regenerate: True면 모든 캐시 무시하고 재생성

    Returns:
        world_map.png 경로 (generate_world_map 결과)
    """
    import threading

    wb = _load_worldbuilding()
    if not wb:
        return None

    world_name = wb.get("world_info", {}).get("name", "default")
    safe_world_name = world_name.replace(" ", "_")
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(BASE_DIR, "static", "maps", "world", safe_world_name)
    os.makedirs(output_dir, exist_ok=True)

    guide_path = os.path.join(output_dir, "color_guide.png")
    sd_path = os.path.join(output_dir, "background_sd.webp")

    # custom 배경 체크 — 있으면 색 가이드/SD 생성 스킵
    custom_bg_dir = os.path.join(output_dir, "custom")
    _has_custom = False
    if os.path.isdir(custom_bg_dir):
        for ext in ["webp", "png", "jpg", "jpeg"]:
            if os.path.exists(os.path.join(custom_bg_dir, f"background.{ext}")):
                _has_custom = True
                break

    if _has_custom and not force_regenerate:
        # custom 배경 사용 — 마커만 합성
        return generate_world_map()

    # ── 1단계: 색 가이드 (캐시 없거나 force면 재생성) ──
    if force_regenerate or not os.path.exists(guide_path):
        generate_color_guide(wb, output_dir)

    # ── 2단계: SD 변환 (백그라운드) ──
    if force_regenerate or not os.path.exists(sd_path):
        if os.path.exists(guide_path) and _is_sd_enabled():
            def _sd_worker():
                try:
                    result = generate_sd_background(guide_path, sd_path)
                    if result:
                        # SD 완료 후 최종 지도 재합성 (4단계 재실행)
                        generate_world_map()
                except Exception:
                    pass

            threading.Thread(target=_sd_worker, daemon=True).start()

    # ── 3단계: Skia 백지도 (즉시) ──
    # generate_world_map() 내부에서 자동 생성됨

    # ── 4단계: 배경 + 마커 합성 ──
    return generate_world_map()
