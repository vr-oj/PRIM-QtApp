# setup_wizard.py
from PyQt5.QtWidgets import QFileDialog


def prompt_for_camera_profile(parent=None):
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Select GenTL Producer (.cti)",
        "",
        "GenTL Producer Files (*.cti);;All Files (*)",
    )
    return file_path if file_path else None
