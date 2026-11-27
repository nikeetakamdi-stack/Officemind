"""Phone detection for Secure mode, using a YOLOv8n object-detection model.

The model (models/yolov8n.onnx) recognises 80 everyday objects (the COCO set);
number 67 is "cell phone". It runs on this computer with onnxruntime: webcam
frames are checked in memory and never saved or sent anywhere.
"""

import numpy as np
from PIL import Image

from core.config import PHONE_MIN_CONFIDENCE, YOLO_MODEL_PATH

PHONE_CLASS = 67
INPUT_SIZE = 640
_session = None


def model_available() -> bool:
    return YOLO_MODEL_PATH.exists()


def _get_session():
    global _session
    if _session is None:
        import onnxruntime as ort
        _session = ort.InferenceSession(str(YOLO_MODEL_PATH), providers=["CPUExecutionProvider"])
    return _session


def _prepare(image: Image.Image) -> np.ndarray:
    """Resize to fit 640x640 without stretching (grey padding), as YOLO expects."""
    image = image.convert("RGB")
    scale = INPUT_SIZE / max(image.size)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.BILINEAR)
    canvas = Image.new("RGB", (INPUT_SIZE, INPUT_SIZE), (114, 114, 114))
    canvas.paste(resized, ((INPUT_SIZE - resized.width) // 2, (INPUT_SIZE - resized.height) // 2))
    array = np.asarray(canvas, dtype=np.float32) / 255.0
    return array.transpose(2, 0, 1)[np.newaxis]  # (1, 3, 640, 640)


def class_scores(image: Image.Image) -> np.ndarray:
    """The best score of each of the 80 object types anywhere in the image (0..1)."""
    output = _get_session().run(None, {_get_session().get_inputs()[0].name: _prepare(image)})[0]
    # output: (1, 84, 8400) = 4 box numbers + 80 class scores, for 8400 candidate boxes
    return output[0, 4:, :].max(axis=1)


def phone_confidence(image: Image.Image) -> float:
    """How sure the model is that a mobile phone is in the picture (0..1)."""
    return float(class_scores(image)[PHONE_CLASS])


def phone_detected(image: Image.Image) -> tuple[bool, float]:
    confidence = phone_confidence(image)
    return confidence >= PHONE_MIN_CONFIDENCE, confidence
