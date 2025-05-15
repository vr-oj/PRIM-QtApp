import csv
import math
import time
import serial
import os
import logging
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition # Added QMutex, QWaitCondition
import queue # Added for command queue

# Assuming config.py is in the parent directory relative to this file
# If this file is in project_root/threads/ and config.py is in project_root/
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..')) # Add parent dir to path
from config import DEFAULT_SERIAL_BAUD_RATE, SERIAL_COMMAND_TERMINATOR

log = logging.getLogger(__name__)

class SerialThread(QThread):
    data_ready = pyqtSignal(int, float, float)  # (frameCount, time_s, pressure)
    error_occurred = pyqtSignal(str) # For reporting errors to GUI
    status_changed = pyqtSignal(str) # For general status updates

    def __init__(self, port=None, baud=DEFAULT_SERIAL_BAUD_RATE, test_csv=None, parent=None): # Added parent
        super().__init__(parent) # Modified
        self.port = port
        self.baud = baud
        self.ser = None
        self.running = False
        self.fake_t_idx = 0 # Renamed from fake_t for clarity (it's an index/frame count)
        self.test_csv = test_csv # test_csv functionality not fully implemented here, but retained
        self.start_time = 0

        # For asynchronous command sending
        self.command_queue = queue.Queue()
        self.mutex = QMutex()
        self.wait_condition = QWaitCondition()


    def run(self):
        self.running = True
        self.start_time = time.time() # Initialize start_time here

        if self.port:
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=1)
                log.info(f"Opened serial port {self.port} @ {self.baud} baud")
                self.status_changed.emit(f"Connected to {self.port}")
            except Exception as e:
                log.warning(f"Failed to open serial port {self.port}: {e}")
                self.error_occurred.emit(f"Error opening serial: {e}")
                self.ser = None # Ensure ser is None if connection failed
        else:
            log.info("No serial port specified. Running in simulation mode.")
            self.status_changed.emit("Running in simulation mode")

        while self.running:
            # Process commands from the queue
            try:
                command = self.command_queue.get_nowait()
                if self.ser and command:
                    self.ser.write(command) # Command should be bytes already
                    log.debug(f"Sent command: {command}")
            except queue.Empty:
                pass # No command to send
            except Exception as e:
                log.error(f"Error sending serial command: {e}")
                self.error_occurred.emit(f"Serial send error: {e}")


            if self.ser:
                try:
                    if self.ser.in_waiting > 0:
                        raw = self.ser.readline()
                        if not raw:
                            continue
                        line = raw.decode('utf-8', errors='replace').strip() # Use replace for robustness
                        log.debug(f"Raw serial data: {line}")

                        parts = [fld.strip() for fld in line.split(',')]
                        if len(parts) < 3: # Expecting at least 3 parts: time, frame_idx, pressure
                            log.warning(f"Malformed data line: {line}. Expected 3 parts, got {len(parts)}")
                            continue

                        try:
                            # Assuming first part is time from device, or relative time
                            # second is a frame index from device
                            # third is pressure
                            t_device = float(parts[0]) # This could be device's own timestamp or uptime
                            frame_idx_device = int(parts[1])
                            p = float(parts[2])
                            
                            # For consistency, we can also use PC time elapsed if t_device is not absolute
                            # t_pc_elapsed = time.time() - self.start_time
                            # For now, assume t_device is the primary time to use
                            self.data_ready.emit(frame_idx_device, t_device, p)
                        except ValueError as ve:
                            log.error(f"Parse error for data '{line}': {ve}")
                        except Exception as e:
                            log.error(f"Unexpected error parsing data '{line}': {e}")
                            continue
                    else:
                        self.msleep(10) # Sleep briefly if no data to avoid busy-waiting

                except serial.SerialException as se:
                    log.error(f"Serial communication error: {se}")
                    self.error_occurred.emit(f"Serial error: {se}. Disconnecting.")
                    self.ser.close()
                    self.ser = None
                    self.running = False # Stop thread on major serial error
                except Exception as e:
                    log.exception(f"Unexpected error in serial read loop: {e}")
                    # self.error_occurred.emit(f"Runtime error: {e}") # Avoid flooding with errors
                    self.msleep(100)

            else: # Simulation mode
                t_elapsed = time.time() - self.start_time
                p_sim = 50 + 40 * math.sin(t_elapsed * math.pi * 0.2) + 10 * math.sin(t_elapsed * math.pi * 0.7) # More complex wave
                self.data_ready.emit(self.fake_t_idx, t_elapsed, p_sim)
                self.fake_t_idx += 1
                self.msleep(100) # Simulate data at ~10 Hz

        if self.ser:
            try:
                self.ser.close()
                log.info(f"Closed serial port {self.port}")
            except Exception as e:
                log.exception(f"Error closing serial port {self.port}: {e}")
        log.info("SerialThread finished.")
        self.status_changed.emit("Disconnected")


    def send_command(self, command_str):
        """Adds a command string to the queue to be sent by the thread."""
        if self.running:
            # Ensure command is bytes and has the correct terminator
            final_command = command_str.encode('utf-8') + SERIAL_COMMAND_TERMINATOR
            self.command_queue.put(final_command)
            log.info(f"Queued command: {command_str}")
        else:
            log.warning("Serial thread not running. Cannot send command.")
            self.error_occurred.emit("Cannot send: Serial disconnected.")

    def stop(self):
        log.info("Stopping SerialThread...")
        self.running = False
        self.wait_condition.wakeAll() # Wake if sleeping on wait condition (not used currently but good practice)
        self.quit() # Ask event loop to quit
        self.wait(2000) # Wait for thread to finish, with timeout
        if self.isRunning():
            log.warning("SerialThread did not stop gracefully, terminating.")
            self.terminate() # Force terminate if not stopped


# --- Setup basic logging if this module is run directly (for testing) ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    
    # Example Usage (requires a QApplication for signals if run standalone with GUI interaction)
    class DummyApp: # Minimal non-GUI app for testing signals
        def __init__(self):
            self.thread = SerialThread(port=None) # Simulate
            self.thread.data_ready.connect(self.on_data)
            self.thread.status_changed.connect(lambda s: log.info(f"Status: {s}"))
            self.thread.error_occurred.connect(lambda e: log.error(f"Error: {e}"))
            self.thread.start()

        def on_data(self, idx, t, p):
            log.info(f"Data: Idx={idx}, Time={t:.2f}, Pressure={p:.2f}")

        def stop_thread(self):
            self.thread.stop()

    app = DummyApp()
    try:
        count = 0
        while count < 50: # Run for ~5 seconds
            if count == 10:
                app.thread.send_command("TEST COMMAND 1")
            if count == 20:
                app.thread.send_command("MOTOR_SPEED=100")
            time.sleep(0.1)
            count += 1
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received.")
    finally:
        app.stop_thread()
        log.info("Test finished.")