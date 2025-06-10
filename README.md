
# PRIMAcquisition

**PRIMAcquisition** (PRIM) is a Python‑based application for synchronized acquisition of pressure data (from an Arduino‑controlled pressure transducer) and live camera imaging. Designed for vascular physiology experiments, PRIMAcquisition displays live pressure traces, controls and previews a high‑speed camera feed, and saves synchronized recordings (as a CSV and TIFF stack) for offline analysis.

---

## Features

- **Real‑Time Pressure Plotting**  
  - Receives pressure readings from an Arduino (PRIM device) over serial (115200 baud).  
  - Displays live pressure vs. time trace in a PyQt5 plot widget.  
  - Numeric readouts (frame index, device time, pressure) in the TopControlPanel.

- **High‑Speed Camera Preview & Control**  
  - Integrates with The Imaging Source DMK cameras (e.g., DMK 33UP5000, DMK 33UX250) via IC Imaging Control 4 (IC4).  
  - Lists all connected USB3 Vision cameras and enumerates supported resolutions (width×height with PixelFormat).  
  - Live preview in an OpenGL-backed QtCameraWidget, with camera control sliders (exposure, gain, brightness) in CameraControlPanel.

- **Synchronized Recording**  
  - Hardware‑triggered camera acquisition: Arduino pulses `CamTrig` pin for each sample.  
  - RecordingManager captures exactly one camera frame per Arduino trigger, pulls the corresponding serial line (`frame_idx, elapsed_time_s, pressure`) and writes:
    - **experiment_data.csv** (`frame_index, elapsed_time_s, pressure_value`)
    - **experiment_video.ome.tif** (uncompressed grayscale OME‑TIFF with per‑frame timestamp and pressure metadata)

  - Output folder structure:  
    ```
    PRIM_ROOT/YYYY-MM-DD/FillN/
      ├ experiment_data.csv
      └ experiment_video.ome.tif
    ```

- **Simple UI Layout**  
  - **Top row**: Camera Info/Controls tabs, Arduino status/controls (TopControlPanel), Plot controls (PlotControlPanel).  
  - **Bottom row**: Live camera viewfinder (OpenGL QtCameraWidget) | Live pressure plot (PressurePlotWidget).
  - Menu actions for connecting to PRIM device, arming/stopping recording, exporting plot data/image.

---

## Requirements

- **Operating System**: Windows 10/11 (with IC4 SDK installed), or macOS with GenTL drivers.  
- **Python**: 3.8 – 3.10 (tested); use a virtual environment.  
- **Hardware**:  
  - DMK 33UP5000 or DMK 33UX250 camera with USB 3.0.  
  - Arduino (or compatible) running PRIM firmware (PRIM_v3_01.ino).  
  - Pressure transducer wired to an ADS ADC (e.g., ADS1115), connected to Arduino.

- **Python Packages**:  
  - PyQt5  
  - imagingcontrol4 (IC4 Python wrapper for camera)  
  - pyserial  
  - numpy  
  - tifffile  

---

## Installation

1. **Clone the Repository**  
   ```bash
   git clone https://github.com/your‑repo/PRIMAcquisition.git
   cd PRIMAcquisition/prim_app
   ```

2. **Create a Virtual Environment**  
   ```bash
   python3 -m venv primenv
   source primenv/bin/activate    # macOS/Linux
   primenv\Scripts\activate.bat   # Windows
   ```

3. **Install Dependencies**  
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```  
   - If `requirements.txt` is not provided, install manually:  
     ```bash
     pip install pyqt5 imagingcontrol4 pyserial numpy tifffile
     ```

4. **Install IC Imaging Control 4 SDK**  
   - Download and install the TIS IC4 SDK for your camera. Ensure that the GenTL Producer is configured for your DMK camera.  
   - On Windows, verify that `imagingcontrol4` Python module can import successfully.

---

## Running the App

1. **Launch PRIMAcquisition**  
   ```bash
   cd prim_app
   python prim_app.py
   ```

2. **Connect PRIM Device (Arduino)**  
   - In the main toolbar, choose your serial port from the drop‑down (e.g. COM3) or select “🔌 Simulated Data” for testing.  
   - Click **Connect PRIM Device**.  
   - TopControlPanel will display “PRIM Connected.” Live pressure data will start streaming when the Arduino is running.

3. **Select Camera & Resolution**  
   - In the **Camera** → **Info** tab, choose your camera from the **Device** drop‑down.  
   - Wait for “Connecting…” to change to “Connected.”  
   - The **Resolution** drop‑down populates with available `Width×Height (PixelFormat)` entries.  
   - Select a resolution, then click **Start Camera**. Live preview appears in the left pane.

4. **Preview & Adjust**  
   - Switch to the **Controls** tab to adjust Exposure, Gain, Brightness, etc.  
   - Confirm live feed is smooth and properly exposed.

5. **Start Recording**  
   - In the menu bar, go to **Acquisition → Start Recording** (or press **Ctrl+R**).  
   - A new folder (`PRIM_ROOT/YYYY-MM-DD/FillN/`) will be created automatically.  
   - RecordingManager launches in the background: Camera frames and serial data are synced and saved.  
   - The status bar shows “Recording to ‘…’ …”.

6. **Stop Recording**  
   - Click **Acquisition → Stop Recording** (or press **Ctrl+T**).  
   - RecordingManager finalizes `experiment_data.csv` and `experiment_video.ome.tif`.
   - Status bar reads “Recording stopped and saved.”

7. **Review Output**  
   - Navigate to the folder created in step 5.  
   - **experiment_data.csv**:  
     ```
     frame_index, elapsed_time_s, pressure_value
     1, 0.1000, 15.32
     2, 0.2000, 15.47
     3, 0.3000, 15.45
     …  
     ```  

   - **experiment_video.ome.tif**: Uncompressed grayscale OME‑TIFF. Per‑frame timestamps and pressure values are stored in the `<Plane/>` elements.

   - Use ImageJ/Fiji or Python (`tifffile`) to inspect frames and metadata.

---

## Folder Structure

```
PRIMAcquisition/
├─ prim_app/
│  ├─ main_window.py
│  ├─ prim_app.py
│  ├─ recording_manager.py    ← Recording logic lives here
│  ├─ threads/
│  │  ├─ serial_thread.py
│  │  ├─ sdk_camera_thread.py
│  │  └─ …
│  ├─ ui/
│  │  ├─ canvas/
│  │  │  ├─ qtcamera_widget.py
│  │  │  └─ pressure_plot_widget.py
│  │  └─ control_panels/
│  │     ├─ camera_control_panel.py
│  │     ├─ top_control_panel.py
│  │     └─ plot_control_panel.py
│  ├─ utils/
│  │  ├─ app_settings.py
│  │  ├─ config.py
│  │  ├─ path_helpers.py          ← Folder creation logic
│  │  └─ utils.py
│  ├─ ui/… (icons, etc)
│  └─ requirements.txt
└─ README.md  ← This file
```

- **`main_window.py`** contains most of the UI setup, thread management, and menu actions.  
- **`recording_manager.py`** implements the `RecordingManager` that handles synchronized CSV+TIFF writing.  
- **`path_helpers.py`** provides `get_next_fill_folder()` that creates date/FillN folders under `PRIM_ROOT`.

---

## Arduino Firmware (PRIM_v3_01)

- The Arduino sketch (PRIM_v3_01.ino) reads a pressure transducer via an ADS ADC, averages samples, and prints lines over serial at 115200 baud in the format:  
  ```
  <frame_index>, <elapsed_time_s>, <pressure_value>
  ```  
- Every `startup.timeDelay` milliseconds, the Arduino pulses its `CamTrig` pin to trigger exactly one camera frame (hardware trigger).  
- It also toggles `PumpTrig` HIGH/LOW to control an external pump via a relay or transistor.

---

## Troubleshooting

1. **Camera Not Listed**  
   - Ensure the GenTL Producer for your DMK camera is installed.  
   - Verify that `import imagingcontrol4` in Python works without errors.

2. **No Serial Data**  
   - Check Arduino COM port in Device Manager (Windows) or `/dev/tty.*` (macOS).  
   - Confirm baud rate is set to 115200 in both Arduino code and `SerialThread`.

3. **Slow or Dropped Frames**  
   - Make sure USB 3.0 port is used for the DMK camera.  
   - Lower resolution or frame rate if bandwidth is insufficient.

4. **TIFF Cannot Open**  
   - Ensure you have `tifffile` installed in Python.  
   - Open the TIFF in ImageJ or Python to diagnostics page metadata.

---

## License

> **MIT License**  
> 
> Permission is hereby granted, free of charge, to any person obtaining a copy  
> of this software and associated documentation files (the “Software”), to deal  
> in the Software without restriction, including without limitation the rights  
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell  
> copies of the Software, and to permit persons to whom the Software is  
> furnished to do so, subject to the following conditions:  
> 
> The above copyright notice and this permission notice shall be included in all  
> copies or substantial portions of the Software.  
> 
> THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR  
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,  
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE  
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER  
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,  
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE  
> SOFTWARE.

