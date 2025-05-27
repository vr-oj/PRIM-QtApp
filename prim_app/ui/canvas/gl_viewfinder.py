# prim_app/ui/canvas/gl_viewfinder.py
import numpy as np
from PyQt5.QtWidgets import (
    QOpenGLWidget,
    QSizePolicy,
)
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtGui import (
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QImage,
    QSurfaceFormat,  # Keep for logging context
)
from OpenGL import GL
import logging

log = logging.getLogger(__name__)


class GLViewfinder(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Comment out per-widget format setting to see what global default (or system fallback) provides
        # fmt = QSurfaceFormat()
        # fmt.setDepthBufferSize(24)
        # fmt.setStencilBufferSize(8)
        # fmt.setVersion(3, 3)
        # fmt.setProfile(QSurfaceFormat.CoreProfile)
        # self.setFormat(fmt)

        self.program = None
        self.texture = None
        self.vbo_quad = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 240)
        self.current_frame_width = 0
        self.current_frame_height = 0
        self.frame_aspect_ratio = 1.0

    def initializeGL(self):
        # Log the actual context information provided to this widget
        actual_fmt = self.context().format()
        log.info(
            f"GLViewfinder.initializeGL: Actual Context Version: {actual_fmt.majorVersion()}.{actual_fmt.minorVersion()}, Profile: {'Core' if actual_fmt.profile() == QSurfaceFormat.CoreProfile else 'Compatibility' if actual_fmt.profile() == QSurfaceFormat.CompatibilityProfile else 'NoProfile'}"
        )
        log.info(
            f"GLSL Version reported by context: {GL.glGetString(GL.GL_SHADING_LANGUAGE_VERSION).decode()}"
        )

        self.texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        self.program = QOpenGLShaderProgram(self.context())

        # GLSL 1.20 Compatible Shaders
        vert_src_compat = b"""
#version 120
attribute vec2 position_attr; // Renamed to avoid conflict with built-ins if any
attribute vec2 texcoord_attr; // Renamed
varying vec2 v_texcoord;
void main() {
    gl_Position = vec4(position_attr, 0.0, 1.0);
    v_texcoord = texcoord_attr;
}
"""
        frag_src_compat_mono = b"""
#version 120
uniform sampler2D tex_sampler; // Renamed uniform
varying vec2 v_texcoord;
void main() {
    float intensity = texture2D(tex_sampler, v_texcoord).r;
    gl_FragColor = vec4(intensity, intensity, intensity, 1.0);
}
"""

        if not self.program.addShaderFromSourceCode(
            QOpenGLShader.Vertex, vert_src_compat
        ):
            log.error(
                f"GLViewfinder: Compat Vertex shader compilation error: {self.program.log()}"
            )
            self.program = None
            return
        if not self.program.addShaderFromSourceCode(
            QOpenGLShader.Fragment, frag_src_compat_mono
        ):
            log.error(
                f"GLViewfinder: Compat Fragment shader compilation error: {self.program.log()}"
            )
            self.program = None
            return

        # IMPORTANT: Bind attribute locations BEFORE linking for older GLSL
        self.program.bindAttributeLocation(
            "position_attr", 0
        )  # "position_attr" must match name in shader
        self.program.bindAttributeLocation(
            "texcoord_attr", 1
        )  # "texcoord_attr" must match name in shader
        log.info("Bound attribute locations for compatibility shaders.")

        if not self.program.link():
            log.error(f"GLViewfinder: Shader link error: {self.program.log()}")
            self.program = None
            return

        log.info(
            "GLViewfinder: Compatibility shaders compiled and linked successfully."
        )

        self.texture.setMinificationFilter(QOpenGLTexture.Linear)
        self.texture.setMagnificationFilter(QOpenGLTexture.Linear)
        self.texture.setWrapMode(QOpenGLTexture.ClampToEdge)

        quad_verts = np.array(
            [
                -1.0,
                -1.0,
                0.0,
                1.0,
                1.0,
                -1.0,
                1.0,
                1.0,
                -1.0,
                1.0,
                0.0,
                0.0,
                1.0,
                1.0,
                1.0,
                0.0,
            ],
            dtype=np.float32,
        )

        self.makeCurrent()
        self.vbo_quad = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)
        GL.glBufferData(
            GL.GL_ARRAY_BUFFER, quad_verts.nbytes, quad_verts, GL.GL_STATIC_DRAW
        )
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self.doneCurrent()

    def resizeGL(self, w: int, h: int):
        super().resizeGL(w, h)

    @pyqtSlot(QImage, object)
    def update_frame(self, qimage_unused: QImage, frame: np.ndarray):
        if (
            frame is None
            or not self.isValid()
            or self.program is None
            or self.texture is None
        ):
            if self.program is None or self.texture is None:
                log.debug(
                    "GLViewfinder: update_frame called but shaders or texture not initialized properly."
                )
            return
        self.makeCurrent()
        h, w = frame.shape[:2]
        channels = frame.shape[2] if frame.ndim == 3 else 1
        current_aspect_ratio = w / h if h > 0 else 1.0
        if abs(self.frame_aspect_ratio - current_aspect_ratio) > 1e-5:
            self.frame_aspect_ratio = current_aspect_ratio
        if (
            not self.texture.isCreated()
            or self.current_frame_width != w
            or self.current_frame_height != h
        ):
            if self.texture.isCreated():
                self.texture.destroy()
            self.texture.create()
            self.texture.setSize(w, h)
            internal_texture_format = QOpenGLTexture.R8_UNorm
            self.texture.setFormat(internal_texture_format)
            self.texture.allocateStorage()
            self.current_frame_width = w
            self.current_frame_height = h
            log.debug(
                f"GLViewfinder: Texture re(allocated) for {w}x{h}, aspect: {self.frame_aspect_ratio:.2f}, format: {internal_texture_format}"
            )
        data_for_texture = frame
        source_pixel_format = QOpenGLTexture.Red
        if channels == 1:
            if frame.ndim == 3 and frame.shape[2] == 1:
                data_for_texture = frame[:, :, 0].copy()
            elif frame.ndim == 2:
                data_for_texture = frame.copy()
            else:
                log.error(
                    f"GLViewfinder: Frame has 1 channel but unexpected dimensions: {frame.shape}"
                )
                self.doneCurrent()
                return
        else:
            log.warning(
                f"GLViewfinder: Unsupported channels ({channels}) for current setup (expected 1)."
            )
            self.doneCurrent()
            return
        if data_for_texture is not None:
            self.texture.bind()
            self.texture.setData(
                source_pixel_format, QOpenGLTexture.UInt8, data_for_texture.data
            )
            self.texture.release()
            self.update()
        else:
            log.warning("GLViewfinder: data_for_texture became None unexpectedly.")
        self.doneCurrent()

    def paintGL(self):
        if (
            not self.isValid()
            or self.program is None
            or self.texture is None
            or not self.texture.isCreated()
            or self.vbo_quad is None
            or self.current_frame_width == 0
            or self.current_frame_height == 0
        ):
            if self.program is None and self.isValid():
                self.makeCurrent()
                GL.glClearColor(0.3, 0.0, 0.0, 1.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT)
                self.doneCurrent()
            return
        self.makeCurrent()
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        widget_w = self.width()
        widget_h = self.height()
        if widget_w == 0 or widget_h == 0:
            self.doneCurrent()
            return
        widget_aspect = widget_w / widget_h
        vp_x, vp_y, vp_w, vp_h = 0, 0, widget_w, widget_h
        if self.frame_aspect_ratio > widget_aspect:
            vp_h = int(widget_w / self.frame_aspect_ratio)
            vp_y = int((widget_h - vp_h) / 2)
        elif self.frame_aspect_ratio < widget_aspect:
            vp_w = int(widget_h * self.frame_aspect_ratio)
            vp_x = int((widget_w - vp_w) / 2)
        GL.glViewport(vp_x, vp_y, vp_w, vp_h)
        if not self.program.bind():
            log.error("paintGL: Failed to bind shader program.")
            GL.glViewport(0, 0, widget_w, widget_h)
            self.doneCurrent()
            return
        GL.glActiveTexture(GL.GL_TEXTURE0)
        self.texture.bind()
        self.program.setUniformValue(
            "tex_sampler", 0
        )  # Use new uniform name: "tex_sampler"
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)
        stride = 4 * np.dtype(np.float32).itemsize

        # Use the bound locations (0 and 1) directly
        pos_loc = 0  # Bound to "position_attr"
        tex_loc = 1  # Bound to "texcoord_attr"

        GL.glEnableVertexAttribArray(pos_loc)
        GL.glVertexAttribPointer(
            pos_loc, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, GL.ctypes.c_void_p(0)
        )
        GL.glEnableVertexAttribArray(tex_loc)
        GL.glVertexAttribPointer(
            tex_loc,
            2,
            GL.GL_FLOAT,
            GL.GL_FALSE,
            stride,
            GL.ctypes.c_void_p(2 * np.dtype(np.float32).itemsize),
        )
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glDisableVertexAttribArray(pos_loc)
        GL.glDisableVertexAttribArray(tex_loc)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self.texture.release()
        self.program.release()
        self.doneCurrent()
