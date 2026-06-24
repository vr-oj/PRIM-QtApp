# Windows Installer

Build the installer on the Windows acquisition machine or another Windows machine with the same Python and camera dependencies available.

## Prerequisites

- Python 3.11 64-bit
- Inno Setup 6
- IC Imaging Control / camera driver installed on the target machine

Install Inno Setup from a terminal:

```bat
winget install -e --id JRSoftware.InnoSetup
```

## Build

From the repository root:

```bat
installer\build_installer.bat
```

The script builds the PyInstaller app first, then creates:

```text
installer\output\PRIMA-Setup-3.0.0.exe
```

## Manual Build

If you prefer to run each step manually:

```bat
python -m PyInstaller PRIMAcquisition.spec --clean --noconfirm
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer\PRIMA.iss
```

The PyInstaller output is:

```text
dist\PRIMA\PRIMA.exe
```

## Code Signing

The installer is usable without signing, but Windows SmartScreen may warn users. For a more official release, sign `installer\output\PRIMA-Setup-3.0.0.exe` with a Windows code-signing certificate.
