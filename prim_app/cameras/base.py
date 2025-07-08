from abc import ABC, abstractmethod

class CameraBase(ABC):
    """Abstract camera interface for all camera backends."""

    @abstractmethod
    def connect(self):
        """Open the camera connection."""
        pass

    @abstractmethod
    def disconnect(self):
        """Close and cleanup the camera."""
        pass

    @abstractmethod
    def start_stream(self):
        """Begin streaming images if supported."""
        pass

    @abstractmethod
    def stop_stream(self):
        """Stop streaming images."""
        pass

    @abstractmethod
    def get_frame(self):
        """Return the newest frame as a numpy array or None."""
        pass

    @abstractmethod
    def set_property(self, prop_name: str, value):
        """Generic property setter for camera parameters."""
        pass
