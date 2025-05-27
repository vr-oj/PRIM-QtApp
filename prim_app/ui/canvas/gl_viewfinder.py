# prim_app/ui/canvas/gl_viewfinder.py
import numpy as np
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtGui import (
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QImage,
)
from OpenGL import GL
import logging  # Added logging

log = logging.getLogger(__name__)  # Added logger


class GLViewfinder(QOpenGLWidget):
    """
    High-performance OpenGL viewfinder widget.
    Receives raw numpy frames and renders them via GPU texture.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.program = None
        self.texture = None
        self.vbo_quad = None
        self._frame_data = None  # Not currently used, but could be for caching
        self.setMinimumSize(320, 240)
        self.current_frame_width = 0
        self.current_frame_height = 0

    def initializeGL(self):
        vert_src = b"""
        #version 330 core
        layout (location = 0) in vec2 position;
        layout (location = 1) in vec2 texcoord;
        out vec2 v_texcoord;
        void main() {
            gl_Position = vec4(position, 0.0, 1.0);
            v_texcoord = texcoord;
        }
        """
        frag_src = b"""
        #version 330 core
        uniform sampler2D tex;
        in vec2 v_texcoord;
        out vec4 fragColor;
        void main() {
            fragColor = texture(tex, v_texcoord);
        }
        """

        self.program = QOpenGLShaderProgram(self.context())
        if not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, vert_src):
            log.error(
                f"GLViewfinder: Vertex shader compilation error: {self.program.log()}"
            )
            return
        if not self.program.addShaderFromSourceCode(QOpenGLShader.Fragment, frag_src):
            log.error(
                f"GLViewfinder: Fragment shader compilation error: {self.program.log()}"
            )
            return
        if not self.program.link():
            log.error(f"GLViewfinder: Shader link error: {self.program.log()}")
            return
        # Binding is done before drawing, not necessarily at init.

        self.texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        self.texture.setMinificationFilter(QOpenGLTexture.Linear)
        self.texture.setMagnificationFilter(QOpenGLTexture.Linear)
        self.texture.setWrapMode(QOpenGLTexture.ClampToEdge)

        quad_verts = np.array(
            [
                -1.0,
                -1.0,
                0.0,
                1.0,  # Bottom-left Pos, Tex
                1.0,
                -1.0,
                1.0,
                1.0,  # Bottom-right Pos, Tex
                -1.0,
                1.0,
                0.0,
                0.0,  # Top-left Pos, Tex
                1.0,
                1.0,
                1.0,
                0.0,  # Top-right Pos, Tex
            ],
            dtype=np.float32,
        )

        self.makeCurrent()  # Ensure GL context is current for glGenBuffers etc.
        self.vbo_quad = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)
        GL.glBufferData(
            GL.GL_ARRAY_BUFFER, quad_verts.nbytes, quad_verts, GL.GL_STATIC_DRAW
        )
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self.doneCurrent()

    def resizeGL(self, w: int, h: int):
        self.makeCurrent()
        GL.glViewport(0, 0, w, h)
        self.doneCurrent()

    @pyqtSlot(
        QImage, object
    )  # QImage from SDK thread (already converted), object is numpy array
    def update_frame(self, qimage_unused: QImage, frame: np.ndarray):
        if frame is None or not self.isValid():  # Check if widget is valid
            # log.debug("GLViewfinder: update_frame called with None frame or invalid widget.")
            return

        self.makeCurrent()  # Ensure OpenGL context is current for texture operations

        h, w = frame.shape[:2]
        channels = frame.shape[2] if frame.ndim == 3 else 1

        # Texture reallocation if size or format changes
        if (
            not self.texture.isCreated()
            or self.current_frame_width != w
            or self.current_frame_height != h
        ):
            if self.texture.isCreated():
                self.texture.destroy()

            self.texture.create()
            self.texture.setSize(w, h)  # Set dimensions
            # Set format based on incoming data. Assuming 8-bit for now.
            # For QOpenGLTexture.setData, sourceFormat and sourceType are important.
            # Internal format is often inferred or can be set explicitly.
            self.texture.setFormat(
                QOpenGLTexture.RGBA8_UNorm
            )  # A common internal format for 8-bit/channel
            self.texture.allocateStorage()  # Allocate based on setSize and setFormat
            self.current_frame_width = w
            self.current_frame_height = h
            log.debug(f"GLViewfinder: Texture re(allocated) for {w}x{h}")

        # Prepare data for texture upload (must be RGBA for RGBA8_UNorm internal format)
        # Or, use a different internal format if source is grayscale (e.g., R8_UNorm)
        # and adjust shader if needed. For simplicity, converting to RGBA on CPU.

        data_for_texture = None
        source_format_gl = GL.GL_LUMINANCE  # Default for grayscale
        pixel_type_gl = GL.GL_UNSIGNED_BYTE

        if channels == 1:  # Grayscale
            source_format_gl = GL.GL_LUMINANCE  # or GL_RED if shader expects R channel
            if frame.ndim == 3 and frame.shape[2] == 1:
                data_for_texture = frame[:, :, 0].copy()  # Make it 2D HxW
            else:  # Already HxW
                data_for_texture = frame.copy()
            # If texture internal format is RGBA8, we might need to replicate mono to RGB channels
            # Or, use a GL_R8 internal format and GL_RED source format.
            # For now, let's assume QOpenGLTexture handles LUMINANCE to RGBA expansion if internal is RGBA.
            # Alternatively, create an RGBA buffer:
            # temp_rgba = np.empty((h,w,4), dtype=np.uint8)
            # temp_rgba[..., 0] = data_for_texture
            # temp_rgba[..., 1] = data_for_texture
            # temp_rgba[..., 2] = data_for_texture
            # temp_rgba[..., 3] = 255
            # data_for_texture = temp_rgba
            # source_format_gl = GL.GL_RGBA

        elif channels == 3:  # Assuming BGR from OpenCV or similar
            source_format_gl = GL.GL_BGR  # If QOpenGLTexture can take BGR directly
            data_for_texture = frame.copy()
            # If texture internal format is RGBA8, and source is BGR:
            # temp_rgba = np.empty((h,w,4), dtype=np.uint8)
            # temp_rgba[..., 0] = frame[..., 2] # R
            # temp_rgba[..., 1] = frame[..., 1] # G
            # temp_rgba[..., 2] = frame[..., 0] # B
            # temp_rgba[..., 3] = 255          # A
            # data_for_texture = temp_rgba
            # source_format_gl = GL.GL_RGBA

        elif channels == 4:  # Assuming BGRA or RGBA
            source_format_gl = GL.GL_BGRA  # Or GL_RGBA depending on source
            data_for_texture = frame.copy()
        else:
            log.warning(
                f"GLViewfinder: Unsupported number of channels ({channels}) in update_frame."
            )
            self.doneCurrent()
            return

        if data_for_texture is not None:
            self.texture.bind()
            # Use QOpenGLTexture.setData with appropriate QOpenGLTexture.PixelFormat and QOpenGLTexture.PixelType
            # Mapping GL constants to QOpenGLTexture enums:
            q_source_format = QOpenGLTexture.Luminance  # Default
            if source_format_gl == GL.GL_BGR:
                q_source_format = QOpenGLTexture.BGR
            elif source_format_gl == GL.GL_RGB:
                q_source_format = QOpenGLTexture.RGB
            elif source_format_gl == GL.GL_RGBA:
                q_source_format = QOpenGLTexture.RGBA
            elif source_format_gl == GL.GL_BGRA:
                q_source_format = QOpenGLTexture.BGRA
            # Add more mappings if needed (e.g. GL_RED -> QOpenGLTexture.Red)

            q_pixel_type = QOpenGLTexture.UInt8  # Assuming GL_UNSIGNED_BYTE

            self.texture.setData(q_source_format, q_pixel_type, data_for_texture.data)
            self.texture.release()
            self.update()  # Request a repaint (calls paintGL)

        self.doneCurrent()

    def paintGL(self):
        if (
            not self.isValid()
            or not self.program
            or not self.program.isLinked()
            or not self.texture
            or not self.texture.isCreated()
            or self.vbo_quad is None
        ):
            # log.debug("paintGL: Not ready to paint.")
            return

        self.makeCurrent()
        GL.glClearColor(0.1, 0.1, 0.1, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        if not self.program.bind():
            log.error("paintGL: Failed to bind shader program.")
            self.doneCurrent()
            return

        GL.glActiveTexture(GL.GL_TEXTURE0)
        self.texture.bind()
        self.program.setUniformValue("tex", 0)

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)
        stride = (
            4 * np.dtype(np.float32).itemsize
        )  # 2 pos (vec2) + 2 tex (vec2) = 4 floats

        pos_loc = self.program.attributeLocation("position")
        tex_loc = self.program.attributeLocation("texcoord")

        if pos_loc != -1:
            GL.glEnableVertexAttribArray(pos_loc)
            GL.glVertexAttribPointer(
                pos_loc, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, GL.ctypes.c_void_p(0)
            )

        if tex_loc != -1:
            GL.glEnableVertexAttribArray(tex_loc)
            GL.glVertexAttribPointer(
                tex_loc,
                2,
                GL.GL_FLOAT,
                GL.GL_FALSE,
                stride,
                GL.ctypes.c_void_p(2 * np.dtype(np.float32).itemsize),
            )  # Offset by 2 floats

        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

        if pos_loc != -1:
            GL.glDisableVertexAttribArray(pos_loc)
        if tex_loc != -1:
            GL.glDisableVertexAttribArray(tex_loc)

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self.texture.release()  # Unbind texture
        self.program.release()  # Unbind program
        self.doneCurrent()
