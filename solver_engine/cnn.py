"""نموذج CNN للتعلم الذاتي وتحسين دقة حل الكبتشا.

هذا النموذج يتعلّم من الصور المحلولة والمؤكدة لتحسين دقة التعرف على الحروف والأرقام
في الكبتشا النصية. يستخدم PyTorch إذا كان متاحاً، وإلا يستخدم نسخة مبسطة.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import io
import os
import time

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from PIL import Image
    import torchvision.transforms as transforms

    _TORCH_AVAILABLE = True
except Exception:  # noqa: BLE001
    _TORCH_AVAILABLE = False
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    optim = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    transforms = None  # type: ignore[assignment]


@dataclass
class CaptchaCharPrediction:
    """توقع حرف واحد من الكبتشا."""
    character: str
    confidence: float
    position: int


@dataclass
class CNNModelConfig:
    """إعدادات نموذج CNN."""
    input_height: int = 64
    input_width: int = 200
    input_channels: int = 1
    num_classes: int = 62  # 26 letters + 26 uppercase + 10 digits
    learning_rate: float = 0.001
    batch_size: int = 32
    epochs: int = 10
    model_path: str = "cnn_captcha_model.pt"


class CaptchaCNN(nn.Module if _TORCH_AVAILABLE and nn is not None else object):  # type: ignore[misc, valid-type]
    """نموذج CNN للتعرف على حروف الكبتشا."""

    def __init__(self, config: Optional[CNNModelConfig] = None) -> None:
        if _TORCH_AVAILABLE and nn is not None:
            super().__init__()
        self.config = config or CNNModelConfig()
        self.characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        self.char_to_idx = {c: i for i, c in enumerate(self.characters)}
        self.idx_to_char = {i: c for i, c in enumerate(self.characters)}

        if _TORCH_AVAILABLE and nn is not None:
            self.conv_layers = nn.Sequential(
                # الطبقة الأولى
                nn.Conv2d(self.config.input_channels, 32, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.MaxPool2d(kernel_size=2, stride=2),
                # الطبقة الثانية
                nn.Conv2d(32, 64, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.MaxPool2d(kernel_size=2, stride=2),
                # الطبقة الثالثة
                nn.Conv2d(64, 128, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.MaxPool2d(kernel_size=2, stride=2),
            )

            # حساب حجم المخرجات بعد الطبقات التلافيفية
            conv_output_size = self.config.input_height // 8 * self.config.input_width // 8 * 128

            self.fc_layers = nn.Sequential(
                nn.Linear(conv_output_size, 512),
                nn.ReLU(),
                nn.Dropout(0.5),
                nn.Linear(512, self.config.num_classes),
            )

    def forward(self, x: Any) -> Any:  # type: ignore[override]
        """تمرير أمامي عبر النموذج."""
        if not _TORCH_AVAILABLE:
            return x
        x = self.conv_layers(x)
        x = x.view(x.size(0), -1)
        x = self.fc_layers(x)
        return x

    def predict(self, image: Any) -> List[CaptchaCharPrediction]:
        """توقع الحروف في الصورة."""
        if not _TORCH_AVAILABLE or not torch:
            return []

        self.eval()
        with torch.no_grad():
            # معالجة الصورة
            transform = transforms.Compose([
                transforms.Resize((self.config.input_height, self.config.input_width)),
                transforms.ToTensor(),
                transforms.Normalize((0.5,), (0.5,)),
            ])
            input_tensor = transform(image).unsqueeze(0)
            output = self(input_tensor)
            probabilities = torch.nn.functional.softmax(output, dim=1)

            # الحصول على أفضل توقعات
            top_probs, top_indices = torch.topk(probabilities, 1, dim=1)

            predictions = []
            for i in range(top_indices.size(1)):
                char_idx = top_indices[0, i].item()
                char_prob = top_probs[0, i].item()
                char = self.idx_to_char.get(char_idx, "?")
                predictions.append(
                    CaptchaCharPrediction(
                        character=char,
                        confidence=char_prob,
                        position=i,
                    )
                )
            return predictions

    def save(self, path: Optional[str] = None) -> None:
        """حفظ النموذج."""
        if not _TORCH_AVAILABLE:
            return
        path = path or self.config.model_path
        torch.save(self.state_dict(), path)

    def load(self, path: Optional[str] = None) -> bool:
        """تحميل النموذج."""
        if not _TORCH_AVAILABLE:
            return False
        path = path or self.config.model_path
        if not os.path.exists(path):
            return False
        try:
            self.load_state_dict(torch.load(path))
            return True
        except Exception:  # noqa: BLE001
            return False


class CNNTrainer:
    """مدرب نموذج CNN."""

    def __init__(self, model: CaptchaCNN, config: Optional[CNNModelConfig] = None) -> None:
        self.model = model
        self.config = config or CNNModelConfig()
        self.optimizer = None
        if _TORCH_AVAILABLE and torch and optim is not None:
            self.optimizer = optim.Adam(self.model.parameters(), lr=self.config.learning_rate)
            self.criterion = nn.CrossEntropyLoss()

    def train_on_samples(
        self,
        images: List[Any],
        texts: List[str],
        epochs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """تدريب النموذج على مجموعة من العينات."""
        if not _TORCH_AVAILABLE or not self.optimizer:
            return {"status": "skipped", "reason": "torch غير متاح"}

        epochs = epochs or self.config.epochs
        self.model.train()

        transform = transforms.Compose([
            transforms.Resize((self.config.input_height, self.config.input_width)),
            transforms.ToTensor(),
            transforms.Normalize((0.5,), (0.5,)),
        ])

        # إعداد البيانات
        dataset = []
        for img, text in zip(images, texts):
            tensor = transform(img)
            # أخذ الحرف الأول فقط للتبسيط (يمكن تحسينه لاحقاً)
            if text:
                char = text[0]
                if char in self.model.char_to_idx:
                    label = self.model.char_to_idx[char]
                    dataset.append((tensor, label))

        if not dataset:
            return {"status": "no_data", "reason": "لا توجد بيانات صالحة للتدريب"}

        # التدريب
        total_loss = 0.0
        num_batches = 0

        for epoch in range(epochs):
            epoch_loss = 0.0
            for img_tensor, label in dataset:
                self.optimizer.zero_grad()
                output = self.model(img_tensor.unsqueeze(0))
                loss = self.criterion(output, torch.tensor([label]))
                loss.backward()
                self.optimizer.step()
                epoch_loss += loss.item()
                num_batches += 1

            total_loss = epoch_loss / max(1, len(dataset))

        return {
            "status": "completed",
            "epochs": epochs,
            "samples": len(dataset),
            "final_loss": total_loss,
        }


from solver_engine.base import BaseSolver, CaptchaType, SolverResult


class CNNSolver(BaseSolver):
    """حلّال كبتشا باستخدام نموذج CNN."""

    captcha_type = CaptchaType.IMAGE

    def __init__(self, config: Optional[CNNModelConfig] = None) -> None:
        super().__init__()
        self.config = config or CNNModelConfig()
        self.model = CaptchaCNN(config)
        self.trainer = CNNTrainer(self.model, config)
        self.is_trained = False

    def solve(self, image: Any) -> SolverResult:
        """حل الكبتشا باستخدام النموذج."""
        if not _TORCH_AVAILABLE:
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error="torch غير متاح",
            )
        if not self.is_trained and not self.model.load():
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error="النموذج غير متاح أو غير مدرّب",
            )

        predictions = self.model.predict(image)
        if predictions:
            text = "".join(p.character for p in predictions)
            confidence = min(p.confidence for p in predictions)
            return SolverResult(
                success=True,
                captcha_type=self.captcha_type,
                text=text,
                confidence=confidence,
            )
        return SolverResult(
            success=False,
            captcha_type=self.captcha_type,
            error="فشل في التنبؤ",
        )

    async def solve_async(self, *args: Any, **kwargs: Any) -> SolverResult:
        """حل غير متزامن."""
        import asyncio

        return await asyncio.to_thread(self.solve, *args, **kwargs)

    def train(
        self,
        images: List[Any],
        texts: List[str],
        epochs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """تدريب النموذج على العينات."""
        result = self.trainer.train_on_samples(images, texts, epochs)
        if result.get("status") == "completed":
            self.is_trained = True
            self.model.save()
        return result

    def is_model_available(self) -> bool:
        """التحقق من توفر النموذج المدرب."""
        return self.is_trained or self.model.load()


__all__ = [
    "CaptchaCharPrediction",
    "CNNModelConfig",
    "CaptchaCNN",
    "CNNTrainer",
    "CNNSolver",
    "_TORCH_AVAILABLE",
]
