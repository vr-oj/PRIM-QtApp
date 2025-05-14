

a) Integrate volume
In your SerialThread or in MainWindow._update_plot, keep a running sum:
# in MainWindow.__init__:
self.volume = 0.0  # µL

# whenever you send a pump‑rate command, record the rate:
self.current_rate = 0.0  # µL/s

def _send_pump_rate(self, rate_ul_s):
    self.current_rate = rate_ul_s
    self._send_serial_cmd(f"PUMP_RATE {rate_ul_s}\n".encode())

# in your QTimer (or inside _update_plot):
dt = t - self.last_t  # time since last sample
self.volume += self.current_rate * dt


b) Compute radius, stress, stretch, and plot
Extend your _update_plot(frame, t, p):

# 1) store pressure & timestamp
self.times.append(t); self.pressures.append(p)

# 2) update volume
dt = t - getattr(self, "last_t", t)
self.last_t = t
self.volume += self.current_rate * dt  # µL

# 3) compute geometry
V_m3 = self.volume * 1e-9  # convert µL → m³
r = (3*V_m3 / (4*math.pi))**(1/3)       # meters
if not hasattr(self, "r0"):
    self.r0 = r                         # store initial radius
tw = 0.0005  # 0.5 mm wall thickness, for instance

# 4) compute stress & stretch
stress = (p * 133.322) * r / (2*tw)     # p in mmHg → Pa (×133.322)
stretch = r / self.r0

# 5) plot on a second axes
if not hasattr(self, "stress_ax"):
    self.stress_ax = self.fig.add_subplot(212)  # below the first
    self.stress_line, = self.stress_ax.plot([], [], '-', label="Stress (Pa)")
    self.stress_ax.set_ylabel("Stress (Pa)")
    self.stress_ax.legend()
self.stress_line.set_data(self.times, [self.stress_line.get_data()[1] + [stress]][0])
self.stress_ax.relim(); self.stress_ax.autoscale_view()

# 6) redraw entire canvas
self.canvas.draw()
