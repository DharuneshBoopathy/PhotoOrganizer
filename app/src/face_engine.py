"""
Local face detection, embedding extraction, and clustering.
Uses InsightFace (buffalo_l ONNX model) — fully offline.
Falls back to OpenCV Haar cascade if InsightFace unavailable.
DBSCAN clustering groups same-person faces without a predefined count.
"""
import os
import io
import pickle
from typing import List, Optional, Tuple, Dict, Any

import numpy as np

try:
    import insightface
    from insightface.app import FaceAnalysis
    HAS_INSIGHTFACE = True
except ImportError:
    HAS_INSIGHTFACE = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    from sklearn.cluster import DBSCAN
    from sklearn.preprocessing import normalize
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


# Face represents one detected face in an image
class FaceDetection:
    __slots__ = ("bbox", "embedding", "confidence", "landmarks")

    def __init__(self, bbox: Tuple[int, int, int, int], embedding: np.ndarray,
                 confidence: float, landmarks: Optional[np.ndarray] = None):
        self.bbox = bbox  # (x1, y1, x2, y2)
        self.embedding = embedding
        self.confidence = confidence
        self.landmarks = landmarks  # 5x2 keypoints from InsightFace, or None


class FaceEngine:
    """
    Lazy-initialized face engine. Initialization downloads/loads model once.
    The InsightFace buffalo_l model lives in ~/.insightface by default.
    Pass model_dir to override the cache directory (e.g., to a USB drive).
    """

    def __init__(self, model_dir: Optional[str] = None, use_gpu: bool = False):
        self.model_dir = model_dir
        self.use_gpu = use_gpu
        self._app = None
        self._cascade = None
        self._backend = "none"

    def _init(self):
        if self._backend != "none":
            return

        if HAS_INSIGHTFACE:
            try:
                ctx_id = 0 if self.use_gpu else -1
                app = FaceAnalysis(
                    name="buffalo_l",
                    root=self.model_dir or os.path.expanduser("~/.insightface"),
                    providers=["CPUExecutionProvider"],
                )
                app.prepare(ctx_id=ctx_id, det_size=(640, 640))
                self._app = app
                self._backend = "insightface"
                return
            except Exception as e:
                print(f"[face_engine] InsightFace init failed: {e}")

        if HAS_CV2:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            if os.path.exists(cascade_path):
                self._cascade = cv2.CascadeClassifier(cascade_path)
                self._backend = "opencv_haar"
                print("[face_engine] Falling back to OpenCV Haar cascade (no embeddings).")
                return

        print("[face_engine] No face detection backend available. Skipping face analysis.")
        self._backend = "unavailable"

    def detect(self, image_path: str) -> List[FaceDetection]:
        """
        Detect faces in an image. Returns list of FaceDetection objects.
        Read-only — image file is never modified.
        """
        self._init()

        if self._backend == "insightface":
            return self._detect_insightface(image_path)
        elif self._backend == "opencv_haar":
            return self._detect_opencv(image_path)
        return []

    def _detect_insightface(self, image_path: str) -> List[FaceDetection]:
        if not HAS_CV2:
            return []
        try:
            img = cv2.imread(image_path)
            if img is None:
                return []
            faces = self._app.get(img)
            result = []
            for face in faces:
                bbox = face.bbox.astype(int)
                x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                x1, y1 = max(0, x1), max(0, y1)
                emb = face.normed_embedding if hasattr(face, "normed_embedding") else face.embedding
                det_score = float(face.det_score) if hasattr(face, "det_score") else 1.0
                lmk = None
                if hasattr(face, "kps") and face.kps is not None:
                    lmk = np.asarray(face.kps, dtype=np.float32)
                elif hasattr(face, "landmark_2d_106") and face.landmark_2d_106 is not None:
                    lmk = np.asarray(face.landmark_2d_106, dtype=np.float32)
                result.append(FaceDetection(
                    bbox=(x1, y1, x2, y2),
                    embedding=emb.astype(np.float32),
                    confidence=det_score,
                    landmarks=lmk,
                ))
            return result
        except Exception as e:
            print(f"[face_engine] Detection error on {image_path}: {e}")
            return []

    def _detect_opencv(self, image_path: str) -> List[FaceDetection]:
        """Haar cascade — detects faces but produces no embeddings."""
        if not HAS_CV2:
            return []
        try:
            img = cv2.imread(image_path)
            if img is None:
                return []
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
            result = []
            for (x, y, w, h) in faces:
                dummy_emb = np.zeros(128, dtype=np.float32)
                result.append(FaceDetection(
                    bbox=(int(x), int(y), int(x + w), int(y + h)),
                    embedding=dummy_emb,
                    confidence=0.9,
                ))
            return result
        except Exception:
            return []

    @property
    def can_cluster(self) -> bool:
        """True only when we have real embeddings (InsightFace backend)."""
        self._init()
        return self._backend == "insightface" and HAS_SKLEARN


def embedding_to_bytes(emb: np.ndarray) -> bytes:
    return emb.astype(np.float32).tobytes()


def bytes_to_embedding(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def cluster_embeddings(
    detection_ids: List[int],
    embeddings: List[np.ndarray],
    eps: float = 0.4,
    min_samples: int = 2,
) -> Dict[int, str]:
    """
    Cluster face embeddings using DBSCAN with cosine distance.
    Returns {detection_id: cluster_key}.
    Noise points (label=-1) get cluster_key "unknown_<detection_id>".
    """
    if not HAS_SKLEARN or len(embeddings) == 0:
        return {}

    matrix = np.vstack(embeddings)
    matrix = normalize(matrix, norm="l2")

    db = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine", n_jobs=-1)
    labels = db.fit_predict(matrix)

    result = {}
    for det_id, label in zip(detection_ids, labels):
        if label == -1:
            result[det_id] = f"unknown_{det_id}"
        else:
            result[det_id] = f"person_{label:04d}"

    return result
