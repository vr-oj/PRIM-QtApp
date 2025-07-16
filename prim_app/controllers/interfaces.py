from abc import ABC, abstractmethod

class IArduinoController(ABC):
    """Abstract interface for an Arduino-based data acquisition device."""

    @abstractmethod
    def open(self):
        """Open the hardware connection."""
        raise NotImplementedError

    @abstractmethod
    def close(self):
        """Close the connection."""
        raise NotImplementedError

    @abstractmethod
    def send_sync(self) -> int:
        """Send a SYNC command and return the device timer in microseconds."""
        raise NotImplementedError

    @abstractmethod
    def send_trigger(self):
        """Send a trigger pulse or command."""
        raise NotImplementedError

    @abstractmethod
    def read_packet(self):
        """Read a single data packet from the device."""
        raise NotImplementedError

class ICameraController(ABC):
    """Abstract interface for camera control."""

    @abstractmethod
    def initialize(self):
        raise NotImplementedError

    @abstractmethod
    def close(self):
        raise NotImplementedError

    @abstractmethod
    def arm_trigger(self):
        """Configure the camera for triggered acquisition."""
        raise NotImplementedError

    @abstractmethod
    def grab_frame(self):
        """Acquire a single frame and return (QImage, raw_buffer)."""
        raise NotImplementedError
