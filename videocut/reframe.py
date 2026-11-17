"""Reenquadramento 16:9 -> 9:16 seguindo o rosto principal.

Amostra alguns frames por segundo, detecta rostos (YuNet do OpenCV, modelo de
~230 KB baixado no primeiro uso), escolhe o maior e suaviza o movimento da
"câmera virtual" com zona morta, para não ficar tremendo.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import httpx
import numpy as np

from .config import ROOT

YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
YUNET_PATH = ROOT / "models" / "face_detection_yunet_2023mar.onnx"


def _face_detector(width: int, height: int):
    if not YUNET_PATH.exists():
        YUNET_PATH.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get(YUNET_URL, follow_redirects=True, timeout=60)
        r.raise_for_status()
        YUNET_PATH.write_bytes(r.content)
    return cv2.FaceDetectorYN.create(str(YUNET_PATH), "", (width, height), score_threshold=0.7)


def compute_crop_track(video: Path, start: float, end: float, sample_fps: float = 3.0) -> list[dict]:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    if not w or not h or w / h <= 9 / 16 + 0.01:
        cap.release()
        return [{"t": 0.0, "x": 0.5}]

    scale = 640 / w
    small_size = (640, int(round(h * scale)))
    try:
        detector = _face_detector(*small_size)
    except Exception as e:  # sem rede/modelo: mantém centralizado
        print(f"[reframe] detector de rosto indisponível ({e}); usando centro.")
        cap.release()
        return [{"t": 0.0, "x": 0.5}]
    step = max(1, int(round(fps / sample_fps)))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    frame_idx = int(start * fps)
    last_frame = int(end * fps)

    times, xs = [], []
    i = 0
    while frame_idx <= last_frame:
        if i % step == 0:
            ok, frame = cap.read()
            if not ok:
                break
            small = cv2.resize(frame, small_size)
            _, faces = detector.detect(small)
            times.append(frame_idx / fps - start)
            if faces is not None and len(faces):
                x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])[:4]
                xs.append(float(x + fw / 2) / small_size[0])
            else:
                xs.append(np.nan)
        else:
            if not cap.grab():
                break
        frame_idx += 1
        i += 1
    cap.release()

    if not xs or np.all(np.isnan(xs)):
        return [{"t": 0.0, "x": 0.5}]
    return _smooth(np.array(times), np.array(xs), crop_ratio=(h * 9 / 16) / w)


def _smooth(times: np.ndarray, xs: np.ndarray, crop_ratio: float) -> list[dict]:
    # Preenche lacunas (frames sem rosto) com o último valor conhecido.
    valid = ~np.isnan(xs)
    first = xs[valid][0]
    filled, last = [], first
    for v in xs:
        last = last if np.isnan(v) else v
        filled.append(last)
    arr = np.array(filled)

    # Mediana móvel remove detecções falsas isoladas.
    k = 5
    pad = np.pad(arr, (k // 2, k // 2), mode="edge")
    med = np.array([np.median(pad[i:i + k]) for i in range(len(arr))])

    # Câmera com zona morta: só se move quando o rosto sai da faixa central.
    dead = crop_ratio * 0.18
    cam, out = med[0], []
    for t, target in zip(times, med):
        if abs(target - cam) > dead:
            cam += (target - cam) * 0.35
        half = crop_ratio / 2
        cam = float(min(max(cam, half), 1 - half))
        out.append({"t": round(float(t), 3), "x": round(cam, 4)})

    # Remove pontos redundantes (mantém a sequência estritamente crescente em t).
    # Ao mudar de posição, inclui o ponto anterior para "segurar" a câmera parada até ali.
    compact = [out[0]]
    for prev, p in zip(out, out[1:]):
        if abs(p["x"] - compact[-1]["x"]) > 0.002:
            if prev["t"] > compact[-1]["t"]:
                compact.append(prev)
            compact.append(p)
    if out[-1]["t"] > compact[-1]["t"]:
        compact.append(out[-1])
    return compact
