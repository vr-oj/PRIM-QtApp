# prim_app/ui/canvas/gl_viewfinder.py
import numpy as np
from PyQt5.QtWidgets import (
    QOpenGLWidget,
    QSizePolicy,
)  # Make sure QSizePolicy is imported
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtGui import (
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QImage,
)
from OpenGL import GL
import logging

log = logging.getLogger(__name__)


class GLViewfinder(QOpenGLWidget):
    """
    High-performance OpenGL viewfinder widget.
    Receives raw numpy frames and renders them via GPU texture, maintaining aspect ratio.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.program = None  # Will be initialized in initializeGL
        self.texture = None  # Will be initialized in initializeGL
        self.vbo_quad = None

        # Encourage the widget to expand and fill available space
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 240)  # Maintain a reasonable minimum size

        self.current_frame_width = 0
        self.current_frame_height = 0
        self.frame_aspect_ratio = 1.0  # Default aspect ratio (width / height)

    def initializeGL(self):
        # Initialize critical members first to avoid NoneType errors if shader compilation/linking fails
        self.texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        self.program = QOpenGLShaderProgram(self.context())

        # Vertex shader source - NO #version directive here
        vert_src = b"""
        layout (location = 0) in vec2 position;
        layout (location = 1) in vec2 texcoord;
        out vec2 v_texcoord;
        void main() {
            gl_Position = vec4(position, 0.0, 1.0);
            v_texcoord = texcoord;
        }
        """
        # Fragment shader source for single channel (Mono8) - NO #version directive here
        frag_src_mono = b"""
        uniform sampler2D tex;
        in vec2 v_texcoord;
        out vec4 fragColor;
        void main() {
            float intensity = texture(tex, v_texcoord).r; // Sample red channel (for R8_UNorm)
            fragColor = vec4(intensity, intensity, intensity, 1.0); // Display as grayscale
        }
        """

        if not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, vert_src):
            log.error(
                f"GLViewfinder: Vertex shader compilation error: {self.program.log()}"
            )
            self.program = None  # Mark as failed
            return
        if not self.program.addShaderFromSourceCode(
            QOpenGLShader.Fragment, frag_src_mono
        ):
            log.error(
                f"GLViewfinder: Fragment shader compilation error: {self.program.log()}"
            )
            self.program = None  # Mark as failed
            return
        if not self.program.link():
            log.error(f"GLViewfinder: Shader link error: {self.program.log()}")
            self.program = None  # Mark as failed
            return

        # Configure texture (it's already instantiated)
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

        self.makeCurrent()
        self.vbo_quad = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)
        GL.glBufferData(
            GL.GL_ARRAY_BUFFER, quad_verts.nbytes, quad_verts, GL.GL_STATIC_DRAW
        )
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self.doneCurrent()

    def resizeGL(self, w: int, h: int):
        # The actual viewport adjustment for aspect ratio is done in paintGL.
        super().resizeGL(w, h)  # Call base implementation

    @pyqtSlot(QImage, object)
    def update_frame(self, qimage_unused: QImage, frame: np.ndarray):
        # Add check for program and texture initialization
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

        # Calculate and store frame aspect ratio
        current_aspect_ratio = w / h if h > 0 else 1.0
        if (
            abs(self.frame_aspect_ratio - current_aspect_ratio) > 1e-5
        ):  # Update if changed significantly
            self.frame_aspect_ratio = current_aspect_ratio

        # Texture reallocation if size or format changes
        if (
            not self.texture.isCreated()  # This should now be safe as self.texture is an object
            or self.current_frame_width != w
            or self.current_frame_height != h
            # TODO: Add a check if texture internal_format needs to change if supporting color later
        ):
            if self.texture.isCreated():
                self.texture.destroy()

            self.texture.create()  # Create the OpenGL texture resource
            self.texture.setSize(w, h)

            # Optimized for Mono8 (single channel) data from your camera
            internal_texture_format = (
                QOpenGLTexture.R8_UNorm
            )  # For single channel 8-bit data

            self.texture.setFormat(internal_texture_format)
            self.texture.allocateStorage()  # Allocate GPU memory for the texture
            self.current_frame_width = w
            self.current_frame_height = h
            log.debug(
                f"GLViewfinder: Texture re(allocated) for {w}x{h}, aspect: {self.frame_aspect_ratio:.2f}, format: {internal_texture_format}"
            )

        data_for_texture = frame
        # For R8_UNorm internal format, the source data should be single channel,
        # and QOpenGLTexture.Red indicates the source data provides the red channel values.
        source_pixel_format = QOpenGLTexture.Red

        if channels == 1:
            if frame.ndim == 3 and frame.shape[2] == 1:  # If HxWx1
                data_for_texture = frame[
                    :, :, 0
                ].copy()  # Make it 2D HxW, ensure it's contiguous
            elif frame.ndim == 2:  # Already HxW
                data_for_texture = (
                    frame.copy()
                )  # Ensure it's contiguous for safety with .data pointer
            else:
                log.error(
                    f"GLViewfinder: Frame has 1 channel but unexpected dimensions: {frame.shape}"
                )
                self.doneCurrent()
                return
        # elif channels == 3: # Example if you add BGR support later
        # internal_texture_format would need to be QOpenGLTexture.BGR8_UNorm or similar
        # source_pixel_format = QOpenGLTexture.BGR
        # data_for_texture = frame.copy()
        else:
            log.warning(
                f"GLViewfinder: Unsupported number of channels ({channels}) for current setup (expected 1 for Mono8)."
            )
            self.doneCurrent()
            return

        if data_for_texture is not None:
            self.texture.bind()
            # Upload data: source format is Red, source type is UInt8 (for numpy uint8 array)
            self.texture.setData(
                source_pixel_format, QOpenGLTexture.UInt8, data_for_texture.data
            )
            self.texture.release()
            self.update()  # Request a repaint (calls paintGL)
        else:
            log.warning("GLViewfinder: data_for_texture became None unexpectedly.")

        self.doneCurrent()

    def paintGL(self):
        if (
            not self.isValid()
            or self.program is None  # Check if program was successfully compiled/linked
            # or not self.program.isLinked() # Redundant if self.program is None on link failure
            or self.texture is None  # Check if texture object was instantiated
            or not self.texture.isCreated()  # Check if OpenGL texture resource is created
            or self.vbo_quad is None
            or self.current_frame_width == 0  # Ensure we have valid frame dimensions
            or self.current_frame_height == 0
        ):
            # If shaders didn't compile or texture not ready, clear to a debug color or just return
            if (
                self.program is None and self.isValid()
            ):  # Check isValid to ensure context is available
                self.makeCurrent()
                GL.glClearColor(
                    0.3, 0.0, 0.0, 1.0
                )  # Dark red indicates shader init problem
                GL.glClear(GL.GL_COLOR_BUFFER_BIT)
                self.doneCurrent()
            return

        self.makeCurrent()

        GL.glClearColor(0.0, 0.0, 0.0, 1.0)  # Black for letterbox/pillarbox bars
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        widget_w = self.width()
        widget_h = self.height()

        if (
            widget_w == 0 or widget_h == 0
        ):  # Avoid division by zero if widget not yet sized
            self.doneCurrent()
            return

        widget_aspect = widget_w / widget_h

        # Calculate viewport to maintain frame's aspect ratio
        vp_x, vp_y, vp_w, vp_h = 0, 0, widget_w, widget_h

        if self.frame_aspect_ratio > widget_aspect:
            # Frame is wider than widget display area (needs letterboxing)
            vp_h = int(widget_w / self.frame_aspect_ratio)
            vp_y = int((widget_h - vp_h) / 2)  # Center vertically
        elif self.frame_aspect_ratio < widget_aspect:
            # Frame is taller than widget display area (needs pillarboxing)
            vp_w = int(widget_h * self.frame_aspect_ratio)
            vp_x = int((widget_w - vp_w) / 2)  # Center horizontally
        # Else: aspect ratios are close enough, use full widget_w, widget_h for viewport

        GL.glViewport(vp_x, vp_y, vp_w, vp_h)  # Apply the calculated viewport

        if not self.program.bind():  # Check if bind is successful
            log.error("paintGL: Failed to bind shader program.")
            GL.glViewport(0, 0, widget_w, widget_h)  # Reset viewport if bind fails
            self.doneCurrent()
            return

        GL.glActiveTexture(GL.GL_TEXTURE0)
        self.texture.bind()
        self.program.setUniformValue("tex", 0)  # Tell shader to use texture unit 0

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)
        stride = (
            4 * np.dtype(np.float32).itemsize
        )  # (2 pos floats + 2 tex floats) * size_of_float
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
            )

        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)  # Draw the quad

        # Cleanup
        if pos_loc != -1:
            GL.glDisableVertexAttribArray(pos_loc)
        if tex_loc != -1:
            GL.glDisableVertexAttribArray(tex_loc)

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)  # Unbind VBO
        self.texture.release()  # Unbind texture
        self.program.release()  # Unbind program

        self.doneCurrent()
