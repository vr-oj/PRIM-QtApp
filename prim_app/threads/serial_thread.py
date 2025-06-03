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
    error_occurred = pyqtSignal(str)  # For reporting errors to the GUI
    status_changed = pyqtSignal(str)  # For general status updates

    def __init__(self, port=None, baud=115200, test_csv=None, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self.ser = None

        # Control flags
        self.running = False
        self._got_first_packet = False  # Have we seen at least one line?
        self._last_data_time = None  # Timestamp of last valid data
        self._stop_requested = False

        # Simulation helpers (if port is None)
        self.fake_t_idx = 0
        self.start_time = 0.0

        # For sending commands (unused here, but retained)
        self.command_queue = queue.Queue()
        self.mutex = QMutex()
        self.wait_condition = QWaitCondition()

    def run(self):
        """
        Open serial port (if provided). Then loop:
          - If port is open, read lines, parse them, emit data_ready(...)
          - Track last_data_time; once we’ve seen the first packet, if
            no new data arrives for IDLE_TIMEOUT_S seconds, break → thread finishes.
          - In simulation mode (port is None), emit a fake sine‐wave at ~10 Hz.
        When loop exits, close port if needed, and exit → QThread.finished() fires.
        """
        self.running = True
        self.start_time = time.time()
        self._got_first_packet = False
        self._last_data_time = None

        # 1) Try opening the real serial port if one was given
        if self.port:
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=1)
                log.info(f"Opened serial port {self.port} @ {self.baud} baud")
                self.status_changed.emit(f"Connected to {self.port}")
            except Exception as e:
                log.warning(f"Failed to open serial port {self.port}: {e}")
                self.error_occurred.emit(f"Error opening serial: {e}")
                self.ser = None
        else:
            # Simulation mode: no real port; we’ll generate fake data
            log.info("No serial port specified → running simulation mode")
            self.status_changed.emit("Running in simulation mode")

        # 2) Main loop
        while self.running and not self._stop_requested:
            # 2a) Process outgoing commands (if any)
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

            # 2b) If real port is open, read lines
            if self.ser:
                try:
                    if self.ser.in_waiting > 0:
                        raw = self.ser.readline()
                        if not raw:
                            # readline timed out with no data;
                            # we’ll loop back and check for IDLE_TIMEOUT below
                            pass
                        else:
                            line = raw.decode("utf-8", errors="replace").strip()
                            log.debug(f"Raw serial data: {line}")

                            parts = [fld.strip() for fld in line.split(",")]
                            if len(parts) < 3:
                                log.warning(
                                    f"Malformed data line (expected 3 parts): {line}"
                                )
                            else:
                                try:
                                    t_device = float(parts[0])
                                    frame_idx_device = int(parts[1])
                                    p = float(parts[2])
                                except ValueError as ve:
                                    log.error(f"Parse error for data '{line}': {ve}")
                                    # Skip this line entirely
                                else:
                                    # We have a valid packet → emit data_ready
                                    self.data_ready.emit(frame_idx_device, t_device, p)

                                    # Mark that we’ve seen our first packet
                                    if not self._got_first_packet:
                                        self._got_first_packet = True
                                    # Record last‐data timestamp
                                    self._last_data_time = time.time()
                    else:
                        # No bytes waiting. Sleep briefly to avoid a tight loop
                        self.msleep(10)

                    # 2c) Check idle timeout (only after we’ve seen at least one packet)
                    if self._got_first_packet and self._last_data_time is not None:
                        if (time.time() - self._last_data_time) > IDLE_TIMEOUT_S:
                            # It’s been IDLE_TIMEOUT_S seconds since the last packet.
                            # We interpret this as “Arduino stopped streaming.”
                            log.info(
                                "No serial data for idle timeout → finishing SerialThread."
                            )
                            break

                except serial.SerialException as se:
                    log.error(f"Serial communication error: {se}")
                    self.error_occurred.emit(f"Serial error: {se}. Disconnecting.")
                    break
                except Exception as e:
                    log.exception(f"Unexpected error in serial read loop: {e}")
                    self.msleep(100)

            else:
                # 2d) Simulation mode: emit fake sine‐wave ~10 Hz
                t_elapsed = time.time() - self.start_time
                p_sim = (
                    50
                    + 40 * math.sin(t_elapsed * math.pi * 0.2)
                    + 10 * math.sin(t_elapsed * math.pi * 0.7)
                )
                self.data_ready.emit(self.fake_t_idx, t_elapsed, p_sim)
                self.fake_t_idx += 1
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
        External callers can queue ASCII commands (terminated with newline) to the Arduino.
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
        Ask the thread to exit cleanly (politely).  If it does not within 2 seconds, force terminate.
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


# For standalone testing if you run this module directly:
if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    class DummyApp:
        def __init__(self):
            self.thread = SerialThread(port=None)
            self.thread.data_ready.connect(self.on_data)
            self.thread.status_changed.connect(lambda s: log.info(f"Status: {s}"))
            self.thread.error_occurred.connect(lambda e: log.error(f"Error: {e}"))
            self.thread.start()

        def on_data(self, idx, t, p):
            log.info(f"Data: Idx={idx}, Time={t:.2f}, Pressure={p:.2f}")

        def stop_thread(self):
            self.thread.stop()

    app = QApplication(sys.argv)
    da = DummyApp()
    # Let it run for a few seconds in simulation
    QTimer = QTimer()
    QTimer.singleShot(5000, da.stop_thread)
    sys.exit(app.exec_())
