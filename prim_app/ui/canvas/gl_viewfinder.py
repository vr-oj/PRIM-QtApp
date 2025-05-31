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
    QSurfaceFormat,
    QOpenGLVertexArrayObject,
)
from OpenGL import GL
import logging

log = logging.getLogger(__name__)


class GLViewfinder(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        self.setFormat(fmt)

        self.program = None
        self.texture = None
        self.vbo_quad = None
        self.vao = None  # Initialize VAO member

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 240)
        self.current_frame_width = 0
        self.current_frame_height = 0
        self.frame_aspect_ratio = 1.0

    def initializeGL(self):
        actual_fmt = self.context().format()
        log.info(
            f"GLViewfinder.initializeGL: Actual Context Version: {actual_fmt.majorVersion()}.{actual_fmt.minorVersion()}, Profile: {'Core' if actual_fmt.profile() == QSurfaceFormat.CoreProfile else 'Compatibility' if actual_fmt.profile() == QSurfaceFormat.CompatibilityProfile else 'NoProfile'}"
        )
        glsl_version_str = GL.glGetString(GL.GL_SHADING_LANGUAGE_VERSION)
        if glsl_version_str:
            log.info(f"GLSL Version reported by context: {glsl_version_str.decode()}")
        else:
            log.warning("Could not retrieve GLSL version string.")

        self.texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        self.program = QOpenGLShaderProgram(self.context())

        vert_src = b"""#version 330 core
layout (location = 0) in vec2 position;
layout (location = 1) in vec2 texcoord;
out vec2 v_texcoord;
void main() {
    gl_Position = vec4(position, 0.0, 1.0);
    v_texcoord = texcoord;
}"""
        frag_src_mono = b"""#version 330 core
uniform sampler2D tex_sampler;
in vec2 v_texcoord;
out vec4 fragColor;
void main() {
    float intensity = texture(tex_sampler, v_texcoord).r; 
    fragColor = vec4(intensity, intensity, intensity, 1.0);
}"""

        if not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, vert_src):
            log.error(f"Vertex shader compilation error: {self.program.log()}")
            self.program = None
            return
        if not self.program.addShaderFromSourceCode(
            QOpenGLShader.Fragment, frag_src_mono
        ):
            log.error(f"Fragment shader compilation error: {self.program.log()}")
            self.program = None
            return
        if not self.program.link():
            log.error(f"Shader link error: {self.program.log()}")
            self.program = None
            return
        log.info("GLSL 3.30 shaders compiled and linked successfully.")

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

        self.makeCurrent()  # Ensure context is current

        # --- VAO Setup ---
        self.vao = QOpenGLVertexArrayObject()
        self.vao.create()
        self.vao.bind()  # Bind the VAO before configuring VBO and attribute pointers

        self.vbo_quad = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)
        GL.glBufferData(
            GL.GL_ARRAY_BUFFER, quad_verts.nbytes, quad_verts, GL.GL_STATIC_DRAW
        )

        # Attribute pointers (state is stored in the bound VAO)
        pos_loc = 0  # From shader: layout (location = 0)
        tex_loc = 1  # From shader: layout (location = 1)
        stride = 4 * np.dtype(np.float32).itemsize

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

        # Unbind VBO (optional here as VAO remembers it, but good practice)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self.vao.release()  # Unbind the VAO
        # --- End VAO Setup ---

        self.doneCurrent()

    def resizeGL(self, w: int, h: int):
        super().resizeGL(w, h)

    @pyqtSlot(object)
    def update_frame(self, frame):
        if (
            frame is None
            or not self.isValid()
            or self.program is None
            or self.texture is None
            or self.vao is None
        ):  # Added vao check
            if self.program is None or self.texture is None or self.vao is None:
                log.debug(
                    "GLViewfinder: update_frame called but GL resources not fully initialized."
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
            self.texture.setFormat(QOpenGLTexture.R8_UNorm)
            self.texture.allocateStorage()
            self.current_frame_width = w
            self.current_frame_height = h
            log.debug(
                f"GLViewfinder: Texture re(allocated) for {w}x{h}, aspect: {self.frame_aspect_ratio:.2f}"
            )
        data_for_texture = (
            frame.copy()
            if frame.ndim == 2
            else frame[:, :, 0].copy() if (frame.ndim == 3 and channels == 1) else None
        )
        if data_for_texture is None:
            log.warning(
                f"Unsupported frame format/channels for texture: shape{frame.shape}"
            )
            self.doneCurrent()
            return
        self.texture.bind()
        self.texture.setData(
            QOpenGLTexture.Red, QOpenGLTexture.UInt8, data_for_texture.data
        )
        self.texture.release()
        self.update()
        self.doneCurrent()

    def paintGL(self):
        if (
            not self.isValid()
            or self.program is None
            or self.texture is None
            or not self.texture.isCreated()
            or self.vbo_quad is None
            or self.vao is None  # Added vao check
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

        self.vao.bind()  # Bind VAO before drawing
        GL.glActiveTexture(GL.GL_TEXTURE0)
        self.texture.bind()
        self.program.setUniformValue("tex_sampler", 0)
        # VBO is already associated with VAO's attribute pointers, no need to bind VBO explicitly here usually
        # GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad) # This line is not strictly necessary if VAO is setup correctly

        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

        self.vao.release()  # Unbind VAO
        self.texture.release()
        self.program.release()
        self.doneCurrent()
