import httpx
import ollama


class SharedModelClient:
    """A lifecycle-managed proxy around the synchronous Ollama client."""

    def __init__(self) -> None:
        self._client: ollama.Client | None = None

    def start(self) -> None:
        if self._client is None:
            self._client = ollama.Client(
                timeout=httpx.Timeout(120.0, connect=5.0),
            )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __getattr__(self, name):
        self.start()
        return getattr(self._client, name)


model_client = SharedModelClient()


def model_ready() -> bool:
    from app.core.config import get_settings

    response = model_client.list()
    installed = {
        name
        for item in response.models
        if item.model
        for name in (item.model, item.model.removesuffix(":latest"))
    }
    settings = get_settings()
    return {
        settings.embedding_model,
        settings.generation_model,
    }.issubset(installed)
