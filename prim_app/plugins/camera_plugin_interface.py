from abc import ABC, abstractmethod
from typing import Any
import numpy as np

class CameraPluginInterface(ABC):
    """Base interface that all camera plugins must implement."""

    @abstractmethod
    def initialize(self) -> None:
        """Setup and initialize the camera."""
        raise NotImplementedError

    @abstractmethod
    def start_acquisition(self) -> None:
        """Start live acquisition if supported."""
        raise NotImplementedError

    @abstractmethod
    def stop_acquisition(self) -> None:
        """Stop acquisition."""
        raise NotImplementedError

    @abstractmethod
    def get_frame(self) -> Any:
        """Return the most recent frame as a numpy array."""
        raise NotImplementedError

    @abstractmethod
    def set_exposure(self, value: float) -> None:
        """Set camera exposure time in microseconds or milliseconds."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release resources and cleanup."""
        raise NotImplementedError
