# prim_app/threads/serial_thread.py

import csv
import math
import time
import serial
import os
import logging
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
import queue

log = logging.getLogger(__name__)

# How many seconds of silence on the serial port we interpret
# as “Arduino has stopped streaming.” You can tune this if needed.
IDLE_TIMEOUT_S = 2.0


class SerialThread(QThread):
    data_ready = pyqtSignal(int, float, float)  # (frameIndex, timestamp_s, pressure)
    error_occurred = pyqtSignal(str)  # For reporting errors back to the GUI
    status_changed = pyqtSignal(str)  # For general status updates

    def __init__(self, port=None, baud=115200, test_csv=None, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self.ser = None

        # Control flags
        self.running = False
        self._got_first_packet = False  # Have we seen at least one valid line?
        self._last_data_time = None  # Timestamp (time.time()) of last valid packet
        self._stop_requested = False


        # For sending commands (not used here, but kept for future)
        self.command_queue = queue.Queue()
        self.mutex = QMutex()
        self.wait_condition = QWaitCondition()

    def run(self):
        """Main loop for reading from the PRIM device.

        If a serial ``port`` is provided, the thread opens it and emits
        ``data_ready`` for each valid packet. Lack of new data for
        ``IDLE_TIMEOUT_S`` seconds after the first packet triggers
        shutdown.  When no ``port`` is given the thread immediately
        reports an error and exits.
        """
        self.running = True
        self._got_first_packet = False
        self._last_data_time = None

        if not self.port:
            self.error_occurred.emit("No serial port specified")
            self.running = False
            return

        # 1) Attempt to open the real serial port
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
            log.info(f"Opened serial port {self.port} @ {self.baud} baud")
            self.status_changed.emit(f"Connected to {self.port}")
        except Exception as e:
            log.warning(f"Failed to open serial port {self.port}: {e}")
            self.error_occurred.emit(f"Error opening serial: {e}")
            self.ser = None

        # 2) Main loop
        while self.running and not self._stop_requested:
            # 2a) Process any outgoing commands
            try:
                cmd = self.command_queue.get_nowait()
                if self.ser and cmd:
                    self.ser.write(cmd)
                    log.debug(f"Sent command over serial: {cmd}")
            except queue.Empty:
                pass
            except Exception as e:
                log.error(f"Error sending serial command: {e}")
                self.error_occurred.emit(f"Serial send error: {e}")

            # 2b) If we have a real port configured, handle live reading+reconnect
            if self.port:
                # 2b-i) If `ser` is None, attempt to reopen once per loop iteration
                if self.ser is None:
                    try:
                        self.ser = serial.Serial(self.port, self.baud, timeout=1)
                        log.info(f"[SerialThread] Reconnected to {self.port}")
                        self.status_changed.emit(f"Reconnected to {self.port}")
                    except Exception as e_op:
                        # Still cannot open; sleep a bit before retrying
                        log.debug(
                            f"[SerialThread] Reopen failed: {e_op} → retrying in 0.1 s"
                        )
                        self.msleep(100)
                    continue

                # 2b-ii) Now `self.ser` is not None → attempt to read lines
                try:
                    if self.ser.in_waiting > 0:
                        raw = self.ser.readline()
                        if raw:
                            line = raw.decode("utf-8", errors="replace").strip()
                            log.debug(f"Raw serial data: {line}")

                            parts = [fld.strip() for fld in line.split(",")]
                            if len(parts) < 3:
                                log.warning(
                                    f"Malformed data line (expected 3 fields): {line}"
                                )
                            else:
                                try:
                                    frame_idx_device = int(parts[0])
                                    t_device = float(parts[1])
                                    p = float(parts[2])
                                except ValueError as ve:
                                    log.error(f"Parse error for line '{line}': {ve}")
                                else:
                                    # Valid packet → emit signal
                                    self.data_ready.emit(frame_idx_device, t_device, p)

                                    # Mark that we've seen at least one packet
                                    if not self._got_first_packet:
                                        self._got_first_packet = True
                                    # Update last-data timestamp
                                    self._last_data_time = time.time()
                        else:
                            # readline timed out without data; will check idle below
                            pass
                    else:
                        # No bytes waiting; sleep briefly
                        self.msleep(10)

                except serial.SerialException as se:
                    # Port dropped unexpectedly → attempt to reconnect
                    log.error(
                        f"[SerialThread] SerialException: {se} → will attempt reconnect"
                    )
                    self.status_changed.emit("Serial disconnected, retrying…")
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                    self.ser = None
                    # Wait a short moment before retrying
                    t0 = time.time()
                    while (
                        self.running
                        and not self._stop_requested
                        and (time.time() - t0) < 1.0
                    ):
                        # Sleep in small increments so we remain responsive
                        self.msleep(50)
                    continue

                except Exception as e:
                    log.exception(f"[SerialThread] Unexpected error in read loop: {e}")
                    self.msleep(100)


        # 3) Clean up on exit
        if self.ser:
            try:
                self.ser.close()
                log.info(f"Closed serial port {self.port}")
            except Exception as e:
                log.exception(f"Error closing serial port {self.port}: {e}")

        self.status_changed.emit("Disconnected")
        self.running = False
        log.info("SerialThread finished.")

    def send_command(self, command_str):
        """
        Queue a command (ASCII + newline) for the Arduino. GUI can call this safely.
        """
        if self.running:
            final_command = command_str.encode("utf-8") + b"\n"
            self.command_queue.put(final_command)
            log.info(f"Queued command: {command_str}")
        else:
            log.warning("Serial thread not running → cannot send command.")
            self.error_occurred.emit("Cannot send: Serial disconnected.")

    def stop(self):
        """
        Ask the thread to exit cleanly. If it doesn't within 2 seconds, force‐terminate.
        """
        log.info("Stopping SerialThread…")
        self._stop_requested = True
        self.running = False
        self.wait_condition.wakeAll()
        self.quit()
        self.wait(2000)
        if self.isRunning():
            log.warning("SerialThread did not stop gracefully → terminating.")
            self.terminate()
            self.wait(1000)
