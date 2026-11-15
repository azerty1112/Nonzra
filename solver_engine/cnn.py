"""نموذج CNN بسيط للتعرف على نصوص الكبتشا (اختياري، يتطلب torch)."""

from dataclasses import dataclass
from typing import Any, Optional
import time

try:
    import torch
    import torch.nn as nn
    from PIL import Image

    _TORCH_AVAILABLE = True
except Exception:  # noqa: BLE001
    _TORCH_AVAILABLE = False


@dataclass
class CNNConfig:
    model_path: Optional[str] = None
    img_size: int = 64
    num_classes: int = 62  # a-z, 0-9


class CNNSolver:
    """مُصنف CNN لحروف الكبتشا. يمكن تدريبه وتخزين الأوزان."""

    def __init__(self, config: Optional[CNNConfig] = None) -> None:
        self.config = config or CNNConfig()
        self.model: Any = None
        self.ready = False
        if not _TORCH_AVAILABLE:
            return
        self._build_model()
        if config and config.model_path:
            self.load(config.model_path)

    def _build_model(self) -> None:
        import torch.nn as nn

        class CaptchaCNN(nn.Module):
            def __init__(self, num_classes: int) -> None:
                super().__init__()
                self.net = nn.Sequential(
                    nn.Conv2d(1, 32, 3, padding=1),
                    nn.ReLU(),
                    nn.MaxPool2d(2),
                    nn.Conv2d(32, 64, 3, padding=1),
                    nn.ReLU(),
                    nn.MaxPool2d(2),
                    nn.Conv2d(64, 128, 3, padding=1),
                    nn.ReLU(),
                    nn.MaxPool2d(2),
                    nn.Flatten(),
                )
                self.classifier = nn.Linear(128 * 8 * 8, num_classes)

            def forward(self, x: Any) -> Any:
                x = self.net(x)
                return self.classifier(x)

        self.model = CaptchaCNN(self.config.num_classes)
        self.ready = True

    def load(self, path: str) -> None:
        if not _TORCH_AVAILABLE:
            return
        import torch

        state = torch.load(path, map_location="cpu")
        self.model.load_state_dict(state)
        self.model.eval()

    def save(self, path: str) -> None:
        if not _TORCH_AVAILABLE or self.model is None:
            return
        import torch

        torch.save(self.model.state_dict(), path)

    def predict(self, image) -> Optional[str]:
        if not self.ready or self.model is None:
            return None
        import torch
        import torch.nn.functional as F
        from torchvision import transforms

        transform = transforms.Compose(
            [
                transforms.Grayscale(),
                transforms.Resize((self.config.img_size, self.config.img_size)),
                transforms.ToTensor(),
                transforms.Normalize((0.5,), (0.5,)),
            ]
        )
        img = transform(image).unsqueeze(0)
        self.model.eval()
        with torch.no_grad():
            logits = self.model(img)
            prob = F.softmax(logits, dim=1)
            idx = int(prob.argmax(1))
            conf = float(prob[0, idx])
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        if idx < len(chars):
            return chars[idx]
        return None
