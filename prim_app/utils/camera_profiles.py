# prim_app/utils/camera_profiles.py

DMK_33UX250 = {
    "model": "DMK 33UX250",
    "max_resolution": (2448, 2048),
    "pixel_formats": ["Mono8", "Mono16"],
    "auto_exposure_modes": ["Off", "Continuous"],
    "supports_trigger": True,
    "default_fps": 10,
    "safe_fallback_resolution": (1920, 1080),
}

DMK_33UP5000 = {
    "model": "DMK 33UP5000",
    "max_resolution": (2592, 2048),
    "pixel_formats": ["Mono8", "Mono10p"],
    "auto_exposure_modes": ["Off", "Continuous"],
    "supports_trigger": True,
    "default_fps": 10,
    "safe_fallback_resolution": (1920, 1080),
}

# Mapping by model name string
CAMERA_PROFILES = {"DMK 33UX250": DMK_33UX250, "DMK 33UP5000": DMK_33UP5000}
