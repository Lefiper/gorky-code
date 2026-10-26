"""ASR-движки. Все реализуют один интерфейс: transcribe(path, duration) -> str.

Основной движок — GigaAM-v3. Whisper (faster-whisper) подключается опционально
как запасной или для сравнения: ENGINES=gigaam,whisper
"""
import abc
import os

GIGAAM_SHORT_LIMIT_SEC = 25  # .transcribe() работает только до ~25 секунд


class Engine(abc.ABC):
    name: str

    @abc.abstractmethod
    def transcribe(self, path: str, duration: float | None = None) -> str: ...


class GigaAMEngine(Engine):
    def __init__(self):
        import gigaam

        # v3_e2e_rnnt / v3_e2e_ctc — сразу текст с пунктуацией и нормализацией;
        # v3_rnnt / v3_ctc — без пунктуации. Свой дообученный чекпоинт: GIGAAM_CHECKPOINT=/path/model.ckpt
        model_name = os.getenv("GIGAAM_MODEL", "v3_e2e_rnnt")
        self.name = f"gigaam-{model_name}"
        self.model = gigaam.load_model(os.getenv("GIGAAM_CHECKPOINT") or model_name)

    def transcribe(self, path: str, duration: float | None = None) -> str:
        if duration is None or duration <= GIGAAM_SHORT_LIMIT_SEC:
            res = self.model.transcribe(path)
            return (getattr(res, "text", res) or "").strip()
        # Длинное аудио: нужны extras [longform], HF_TOKEN и принятые условия
        # pyannote/segmentation-3.0 на Hugging Face.
        res = self.model.transcribe_longform(path)
        segments = getattr(res, "segments", res)
        return " ".join(s.text.strip() for s in segments).strip()


class WhisperEngine(Engine):
    def __init__(self):
        from faster_whisper import WhisperModel

        model_name = os.getenv("WHISPER_MODEL", "large-v3")  # или large-v3-turbo, medium, small
        device = os.getenv("WHISPER_DEVICE", "auto")  # auto | cuda | cpu
        compute_type = os.getenv("WHISPER_COMPUTE", "")  # float16 на GPU, int8 на CPU
        if not compute_type:
            compute_type = "int8" if device == "cpu" else "default"

        self.name = f"whisper-{model_name}"
        self.language = os.getenv("WHISPER_LANG", "ru")
        self.prompt = os.getenv(
            "WHISPER_PROMPT",
            "Создай встречу с Ивановым завтра в 15:00. Напомни в пятницу. "
            "Найди все визиты к врачу.",
        )
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)

    def transcribe(self, path: str, duration: float | None = None) -> str:
        segments, _info = self.model.transcribe(
            path,
            language=self.language,
            beam_size=5,
            vad_filter=True,  # отсекает тишину, меньше галлюцинаций
            condition_on_previous_text=False,
            initial_prompt=self.prompt or None,
        )
        return " ".join(s.text.strip() for s in segments).strip()


REGISTRY = {"gigaam": GigaAMEngine, "whisper": WhisperEngine}


def build_engines() -> dict[str, Engine]:
    names = [n.strip() for n in os.getenv("ENGINES", "gigaam").split(",") if n.strip()]
    return {n: REGISTRY[n]() for n in names}
